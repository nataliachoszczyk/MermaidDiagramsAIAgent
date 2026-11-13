"""Check the sequence parser against the real MermaidSeqBench diagrams (skipped if `uv run download-raw` was not run)."""

import csv

import pytest

from mermaiddiagramsaiagent.data.sources import MERMAIDSEQBENCH
from mermaiddiagramsaiagent.eval.sequence import parse_sequence

DATA_CSV = MERMAIDSEQBENCH.local_dir / "data.csv"

pytestmark = pytest.mark.skipif(not DATA_CSV.exists(), reason="raw data not downloaded (uv run download-raw)")


def test_all_diagrams_parse_without_warnings() -> None:
    with DATA_CSV.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    failures = {}
    for index, row in enumerate(rows):
        diagram = parse_sequence(row["expected_output"])
        if diagram.warnings or len(diagram.participants) < 2 or not diagram.messages:
            failures[index] = diagram.warnings
    assert len(rows) == 132
    assert failures == {}
