"""Few-shot prompt construction and the guard against shots that overlap the evaluation data or the golden set."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from openai import BadRequestError

from mermaiddiagramsaiagent.data.jsonl import read_jsonl, write_jsonl
from mermaiddiagramsaiagent.eval.run import GOLDEN_PATH, build_messages, complete, load_shots

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


def reply(text: str | None) -> SimpleNamespace:
    """A chat completion as the client returns it; None = no message, as the Kaggle proxy sometimes sends."""
    message = None if text is None else SimpleNamespace(content=text)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])


class FakeCompletions:
    """Rejects `temperature` like some hosted models, then gives the replies in order (the last one repeats)."""

    def __init__(self, *replies: str | None) -> None:
        self.replies = list(replies) or ["ok"]
        self.calls: list[dict[str, Any]] = []

    def create(self, **request: Any) -> SimpleNamespace:
        self.calls.append(request)
        if "temperature" in request:
            error = BadRequestError.__new__(BadRequestError)  # skips the HTTP response the real one carries
            Exception.__init__(error, "temperature is not supported")
            raise error
        return reply(self.replies.pop(0) if len(self.replies) > 1 else self.replies[0])


def fake_client(completions: FakeCompletions) -> SimpleNamespace:
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


def test_complete_drops_rejected_sampling_for_the_rest_of_the_run() -> None:
    completions = FakeCompletions()
    sampling = {"temperature": 0.0, "seed": 0}
    assert complete(fake_client(completions), sampling, model="m").choices[0].message.content == "ok"
    assert sampling == {}
    complete(fake_client(completions), sampling, model="m")
    assert [("temperature" in c) for c in completions.calls] == [True, False, False]


def test_complete_asks_again_after_an_empty_response() -> None:
    completions = FakeCompletions(None, "flowchart TD")
    response = complete(fake_client(completions), {}, model="m")
    assert response.choices[0].message.content == "flowchart TD"
    assert len(completions.calls) == 2


def test_complete_gives_up_after_the_retries() -> None:
    completions = FakeCompletions(None)
    response = complete(fake_client(completions), {}, model="m")
    assert response.choices[0].message is None
    assert len(completions.calls) == 3
