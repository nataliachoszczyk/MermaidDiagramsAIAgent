"""Check the flowchart parser against the real RonnieAllen diagrams (skipped if `uv run download-raw` was not run)."""

import json

import pytest

from mermaiddiagramsaiagent.data.sources import RONNIEALLEN
from mermaiddiagramsaiagent.eval.flowchart import parse_flowchart

FULL_JSONL = RONNIEALLEN.local_dir / "data" / "full.jsonl"

pytestmark = pytest.mark.skipif(not FULL_JSONL.exists(), reason="raw data not downloaded (uv run download-raw)")

# These two use `X[{...}]`, which mmdc rejects; the dataset counts them as decisions, our parser as rectangles.
DO_NOT_RENDER = {
    "Map out all the steps and decisions for insurance claim submission and review",
    "Map out all the steps and decisions for inventory check before order confirmation",
}


def load_records() -> list[dict]:
    with FULL_JSONL.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_all_diagrams_parse_without_warnings() -> None:
    failures = {}
    for record in load_records():
        chart = parse_flowchart(record["mermaid"])
        if chart.warnings or not chart.edges:
            failures[record["prompt"]] = chart.warnings
    assert failures == {}


def test_node_and_decision_counts_match_dataset_metadata() -> None:
    mismatches = {}
    for record in load_records():
        if record["prompt"] in DO_NOT_RENDER:
            continue
        chart = parse_flowchart(record["mermaid"])
        counts = (len(chart.nodes), sum(n.shape == "rhombus" for n in chart.nodes.values()))
        if counts != (record["num_nodes"], record["num_decisions"]):
            mismatches[record["prompt"]] = {"parsed": counts, "dataset": (record["num_nodes"], record["num_decisions"])}
    assert mismatches == {}
