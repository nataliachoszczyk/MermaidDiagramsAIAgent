"""Summarize the raw datasets in data/raw/: record counts, fields, diagram types, mmdc render rate.

Prints a human-readable summary and writes the details (including render errors) to data/raw/report.json.
"""

import csv
import json
import tempfile
from collections import Counter
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from mermaiddiagramsaiagent.data.jsonl import read_jsonl
from mermaiddiagramsaiagent.data.sources import MERMAIDSEQBENCH, RAW_DIR, RONNIEALLEN
from mermaiddiagramsaiagent.eval.output import diagram_type, normalize_output
from mermaiddiagramsaiagent.eval.render import RenderResult, check_mmdc_works, mmdc_version, render

REPORT_PATH = RAW_DIR / "report.json"
RENDER_WORKERS = 6


@dataclass
class Dataset:
    name: str
    files: dict[str, list[dict[str, Any]]]  # file name -> records
    unique_records: list[dict[str, Any]]  # records used for type/render stats
    id_field: str
    diagram_field: str


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


def describe_fields(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    presence: Counter[str] = Counter()
    types: dict[str, Counter[str]] = {}
    for record in records:
        for key, value in record.items():
            presence[key] += 1
            types.setdefault(key, Counter())[type(value).__name__] += 1
    return {key: {"present": presence[key], "types": dict(types[key])} for key in presence}


def render_all(codes: list[str]) -> list[RenderResult]:
    check_mmdc_works()
    with tempfile.TemporaryDirectory() as tmp, ThreadPoolExecutor(RENDER_WORKERS) as pool:
        return list(pool.map(lambda item: render(item[1], Path(tmp), str(item[0])), enumerate(codes)))


def summarize(dataset: Dataset) -> dict[str, Any]:
    outputs = [normalize_output(r[dataset.diagram_field]) for r in dataset.unique_records]
    ids = [str(r[dataset.id_field]) for r in dataset.unique_records]
    results = render_all([o.code for o in outputs])
    return {
        "dataset": dataset.name,
        "records_per_file": {name: len(records) for name, records in dataset.files.items()},
        "unique_diagrams": len(dataset.unique_records),
        "unique_ids": len(set(ids)),
        "fields": describe_fields(dataset.unique_records),
        "diagram_types": dict(Counter(diagram_type(o.code) for o in outputs)),
        "fenced_references": sum(o.fenced for o in outputs),
        "renders": sum(r.ok for r in results),
        "render_failures": [{"id": rid, "error": r.error} for rid, r in zip(ids, results) if not r.ok],
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


if __name__ == "__main__":
    main()
