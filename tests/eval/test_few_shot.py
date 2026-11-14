"""Few-shot prompt construction and the guard against shots that overlap the evaluation data or the golden set."""

from pathlib import Path
from typing import Any

import pytest

from mermaiddiagramsaiagent.data.jsonl import read_jsonl, write_jsonl
from mermaiddiagramsaiagent.eval.run import GOLDEN_PATH, build_messages, load_shots

SHOTS_PATH = Path("data/shots/shots_pl.jsonl")


def shot(i: int, **fields: Any) -> dict[str, Any]:
    return {
        "id": f"s{i}",
        "source_ref": f"src:{i}",
        "description": f"opis {i}",
        "expected_mermaid": f"flowchart TD\n A --> B{i}",
    } | fields


def write(tmp_path: Path, shots: list[dict[str, Any]]) -> Path:
    path = tmp_path / "shots.jsonl"
    write_jsonl(path, shots)
    return path


def test_zero_shot_messages() -> None:
    assert build_messages("sys", [], "opis") == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "opis"},
    ]


def test_few_shot_messages_alternate_user_and_assistant() -> None:
    messages = build_messages("sys", [shot(1), shot(2)], "opis")
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user", "assistant", "user"]
    assert messages[2]["content"] == "flowchart TD\n A --> B1"
    assert messages[-1]["content"] == "opis"


def test_load_shots_takes_first_k(tmp_path: Path) -> None:
    path = write(tmp_path, [shot(1), shot(2), shot(3)])
    assert [s["id"] for s in load_shots(path, 2, [])] == ["s1", "s2"]


def test_load_shots_rejects_too_few(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        load_shots(write(tmp_path, [shot(1)]), 3, [])


@pytest.mark.parametrize(
    "forbidden",
    [
        shot(9, expected_mermaid="flowchart TD\n A --> B2\n"),  # same diagram
        shot(9, description=" opis 2"),  # same description
        shot(9, source_ref="src:2"),  # same source record, e.g. a golden record made from it
    ],
)
def test_load_shots_rejects_overlap(tmp_path: Path, forbidden: dict[str, Any]) -> None:
    with pytest.raises(SystemExit):
        load_shots(write(tmp_path, [shot(1), shot(2)]), 2, [forbidden])


def test_load_shots_ignores_missing_source_refs(tmp_path: Path) -> None:
    path = write(tmp_path, [shot(1, source_ref=None)])
    assert len(load_shots(path, 1, [shot(9, source_ref=None)])) == 1


@pytest.mark.skipif(not GOLDEN_PATH.exists(), reason="no golden set")
def test_committed_shots_do_not_overlap_golden() -> None:
    shots = load_shots(SHOTS_PATH, 3, read_jsonl(GOLDEN_PATH))
    assert {s["diagram_type"] for s in shots} == {"flowchart", "sequenceDiagram"}
