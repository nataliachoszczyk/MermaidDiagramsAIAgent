"""Build the English pilot set from the RonnieAllen test split.

The pilot only exists to run the evaluation pipeline end to end before the Polish golden set is ready.
Its descriptions are the original one-line prompts, so the model has to guess the steps: F1 numbers on the
pilot are a sanity check, not results to report.
"""

from pathlib import Path
from typing import Any

from mermaiddiagramsaiagent.data.jsonl import read_jsonl, write_jsonl
from mermaiddiagramsaiagent.data.sources import RONNIEALLEN
from mermaiddiagramsaiagent.eval.flowchart import Flowchart, parse_flowchart

PILOT_PATH = Path("data/pilot/pilot_en.jsonl")
SOURCE_FILE = RONNIEALLEN.local_dir / "data" / "test.jsonl"


def difficulty(chart: Flowchart) -> str:
    """design.md §2.3: easy = ≤6 nodes and no decision, medium = ≤12 nodes and ≤2 decisions, else hard."""
    nodes = len(chart.nodes)
    decisions = sum(node.shape == "rhombus" for node in chart.nodes.values())
    if nodes <= 6 and decisions == 0:
        return "easy"
    if nodes <= 12 and decisions <= 2:
        return "medium"
    return "hard"


def build_record(line_number: int, source: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"pilot-flow-{line_number:04d}",
        "split": "pilot",
        "source": "ronnieallen",
        "source_ref": f"{RONNIEALLEN.repo_id}@{RONNIEALLEN.revision[:8]}:data/test.jsonl:{line_number}",
        "license": "CC-BY-4.0",
        "diagram_type": "flowchart",
        "difficulty": difficulty(parse_flowchart(source["mermaid"])),
        "description": source["prompt"],
        "expected_mermaid": source["mermaid"],
        "notes": "English pilot; description is the original one-line prompt, not a step-by-step description",
    }


def main() -> None:
    if not SOURCE_FILE.exists():
        raise SystemExit(f"{SOURCE_FILE} not found; run `uv run download-raw` first")
    records = [build_record(line, source) for line, source in enumerate(read_jsonl(SOURCE_FILE), start=1)]
    write_jsonl(PILOT_PATH, records)
    print(f"Wrote {len(records)} records to {PILOT_PATH}")


if __name__ == "__main__":
    main()
