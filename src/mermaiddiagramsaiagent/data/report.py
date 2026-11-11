"""Summarize the raw datasets in data/raw/: record counts, fields, diagram types, mmdc render rate.

Prints a human-readable summary and writes the details (including render errors) to data/raw/report.json.
"""

import csv
import json
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from mermaiddiagramsaiagent.data.sources import MERMAIDSEQBENCH, RAW_DIR, RONNIEALLEN

REPORT_PATH = RAW_DIR / "report.json"
RENDER_TIMEOUT_S = 60
RENDER_WORKERS = 6
FENCE_RE = re.compile(r"^\s*```(?:mermaid)?\s*\n(.*?)\n\s*```\s*$", re.DOTALL)


@dataclass
class Dataset:
    name: str
    files: dict[str, list[dict[str, Any]]]  # file name -> records
    unique_records: list[dict[str, Any]]  # records used for type/render stats
    id_field: str
    diagram_field: str


@dataclass
class RenderResult:
    record_id: str
    ok: bool
    error: str


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_ronnieallen() -> Dataset:
    data_dir = RONNIEALLEN.local_dir / "data"
    files = {p.name: read_jsonl(p) for p in sorted(data_dir.glob("*.jsonl"))}
    # full.jsonl is the union of train/validation/test; use it for per-diagram statistics.
    return Dataset(RONNIEALLEN.repo_id, files, files["full.jsonl"], "prompt", "mermaid")


def load_mermaidseqbench() -> Dataset:
    records = read_csv(MERMAIDSEQBENCH.local_dir / "data.csv")
    return Dataset(MERMAIDSEQBENCH.repo_id, {"data.csv": records}, records, "nl_task_title", "expected_output")


def strip_fences(code: str) -> tuple[str, bool]:
    match = FENCE_RE.match(code)
    return (match.group(1), True) if match else (code.strip(), False)


def diagram_type(code: str) -> str:
    """First keyword of the diagram, skipping blank lines, %% comments and YAML front matter."""
    lines = iter(code.strip().splitlines())
    for line in lines:
        stripped = line.strip()
        if stripped == "---":
            for inner in lines:
                if inner.strip() == "---":
                    break
            continue
        if not stripped or stripped.startswith("%%"):
            continue
        return stripped.split()[0]
    return "<empty>"


def describe_fields(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    presence: Counter[str] = Counter()
    types: dict[str, Counter[str]] = {}
    for record in records:
        for key, value in record.items():
            presence[key] += 1
            types.setdefault(key, Counter())[type(value).__name__] += 1
    return {key: {"present": presence[key], "types": dict(types[key])} for key in presence}


def mmdc_command() -> str:
    path = shutil.which("mmdc")
    if path is None:
        raise SystemExit("mmdc not found on PATH (npm install -g @mermaid-js/mermaid-cli)")
    return path


def render(mmdc: str, record_id: str, code: str, work_dir: Path, index: int) -> RenderResult:
    src = work_dir / f"{index}.mmd"
    out = work_dir / f"{index}.svg"
    src.write_text(code, encoding="utf-8")
    try:
        proc = subprocess.run(
            [mmdc, "-q", "-i", str(src), "-o", str(out)],
            capture_output=True,
            text=True,
            timeout=RENDER_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return RenderResult(record_id, False, "timeout")
    ok = proc.returncode == 0 and out.exists() and out.stat().st_size > 0
    error = "" if ok else (proc.stderr or proc.stdout).strip()[:2000]
    return RenderResult(record_id, ok, error)


def render_with_retry(mmdc: str, record_id: str, code: str, work_dir: Path, index: int) -> RenderResult:
    """Retry once: headless Chromium occasionally crashes under parallel load; real syntax errors fail twice."""
    result = render(mmdc, record_id, code, work_dir, index)
    return result if result.ok else render(mmdc, record_id, code, work_dir, index)


def check_mmdc_works(mmdc: str, work_dir: Path) -> None:
    """Fail loudly if mmdc cannot render a trivial diagram, so a broken setup is not reported as bad data."""
    result = render(mmdc, "smoke-test", "flowchart TD\n    A --> B", work_dir, -1)
    if not result.ok:
        raise SystemExit(f"mmdc cannot render a trivial diagram; fix the setup first:\n{result.error}")


def render_all(diagrams: list[tuple[str, str]]) -> list[RenderResult]:
    mmdc = mmdc_command()
    with tempfile.TemporaryDirectory() as tmp, ThreadPoolExecutor(RENDER_WORKERS) as pool:
        work_dir = Path(tmp)
        check_mmdc_works(mmdc, work_dir)
        futures = [
            pool.submit(render_with_retry, mmdc, record_id, code, work_dir, i)
            for i, (record_id, code) in enumerate(diagrams)
        ]
        return [f.result() for f in futures]


def summarize(dataset: Dataset) -> dict[str, Any]:
    stripped = [strip_fences(r[dataset.diagram_field]) for r in dataset.unique_records]
    ids = [str(r[dataset.id_field]) for r in dataset.unique_records]
    results = render_all([(rid, code) for rid, (code, _) in zip(ids, stripped)])
    return {
        "dataset": dataset.name,
        "records_per_file": {name: len(records) for name, records in dataset.files.items()},
        "unique_diagrams": len(dataset.unique_records),
        "unique_ids": len(set(ids)),
        "fields": describe_fields(dataset.unique_records),
        "diagram_types": dict(Counter(diagram_type(code) for code, _ in stripped)),
        "fenced_references": sum(fenced for _, fenced in stripped),
        "renders": sum(r.ok for r in results),
        "render_failures": [{"id": r.record_id, "error": r.error} for r in results if not r.ok],
    }


def print_summary(summary: dict[str, Any]) -> None:
    print(f"\n=== {summary['dataset']}")
    for name, count in summary["records_per_file"].items():
        print(f"  {name:<20} {count:>5} records")
    print(f"  unique diagrams      {summary['unique_diagrams']:>5} (unique ids: {summary['unique_ids']})")
    print("  fields:")
    for key, info in summary["fields"].items():
        types = ", ".join(f"{t}×{n}" for t, n in info["types"].items())
        print(f"    {key:<18} present {info['present']:>4}  ({types})")
    print(f"  diagram types:       {summary['diagram_types']}")
    print(f"  fenced references:   {summary['fenced_references']}")
    total = summary["unique_diagrams"]
    print(f"  render with mmdc:    {summary['renders']}/{total} ({summary['renders'] / total:.1%})")
    for failure in summary["render_failures"][:10]:
        lines = failure["error"].splitlines() or ["<no output>"]
        print(f"    FAIL {failure['id']!r}")
        for line in lines[:4]:
            print(f"      {line[:120]}")


def main() -> None:
    summaries = [summarize(load()) for load in (load_ronnieallen, load_mermaidseqbench)]
    for summary in summaries:
        print_summary(summary)
    report = {"date": date.today().isoformat(), "mmdc": mmdc_version(), "datasets": summaries}
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDetails written to {REPORT_PATH}")


def mmdc_version() -> str:
    proc = subprocess.run([mmdc_command(), "--version"], capture_output=True, text=True)
    return proc.stdout.strip()


if __name__ == "__main__":
    main()
