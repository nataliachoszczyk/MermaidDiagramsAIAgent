"""`evaluate --replay`: answers taken from an earlier run file are scored like fresh ones, and only when that run
asked the same model the same thing."""

import argparse
from pathlib import Path
from typing import Any

import pytest

from mermaiddiagramsaiagent.eval.output import REFUSAL
from mermaiddiagramsaiagent.eval.run import ANSWER_KEYS, evaluate_record, replay_answers, same_file, sha256

PROMPT = "system prompt"


def answer(raw_output: str = REFUSAL) -> dict[str, Any]:
    return {key: None for key in ANSWER_KEYS} | {"raw_output": raw_output, "finish_reason": "stop", "latency_s": 1.0}


def setup(tmp_path: Path, **config: Any) -> tuple[dict[str, Any], argparse.Namespace]:
    data = tmp_path / "data.jsonl"
    data.write_bytes(b'{"id": "r1"}\r\n')  # as a Windows checkout has it
    args = argparse.Namespace(
        model="m", setting="zero-shot", no_think=True, max_tokens=1024, data=data, shots=None, replay=Path("run.json")
    )
    recorded = {
        "model": "m",
        "setting": "zero-shot",
        "shot_ids": [],
        "system_prompt_sha256": sha256(PROMPT.encode("utf-8")),
        "no_think": True,
        "max_tokens": 1024,
        "data_sha256": sha256(b'{"id": "r1"}\n'),  # as Linux has it
        "shots_sha256": None,
    }
    replay = {"config": recorded | config, "examples": [{"id": "r1", "score": {}} | answer()]}
    return replay, args


def test_replay_returns_the_answer_fields_per_id(tmp_path: Path) -> None:
    replay, args = setup(tmp_path)
    answers = replay_answers(replay, args, PROMPT, [], [{"id": "r1"}])
    assert answers == {"r1": answer()}


@pytest.mark.parametrize("key, value", [("model", "other"), ("setting", "few-shot"), ("no_think", False)])
def test_replay_from_a_different_run_is_refused(tmp_path: Path, key: str, value: Any) -> None:
    replay, args = setup(tmp_path, **{key: value})
    with pytest.raises(SystemExit, match=key):
        replay_answers(replay, args, PROMPT, [], [{"id": "r1"}])


def test_replay_with_other_data_is_refused(tmp_path: Path) -> None:
    replay, args = setup(tmp_path, data_sha256="0" * 64)
    with pytest.raises(SystemExit, match="data_sha256"):
        replay_answers(replay, args, PROMPT, [], [{"id": "r1"}])


def test_replay_without_an_answer_for_a_record_is_refused(tmp_path: Path) -> None:
    replay, args = setup(tmp_path)
    with pytest.raises(SystemExit, match="r2"):
        replay_answers(replay, args, PROMPT, [], [{"id": "r1"}, {"id": "r2"}])


def test_same_file_ignores_the_line_ending(tmp_path: Path) -> None:
    path = tmp_path / "f.txt"
    path.write_bytes(b"a\nb\n")
    assert same_file(path, sha256(b"a\r\nb\r\n")) and same_file(path, sha256(b"a\nb\n"))
    assert not same_file(path, sha256(b"a\nc\n"))
    assert same_file(None, None) and not same_file(None, sha256(b""))


def test_evaluate_record_scores_a_given_answer_and_keeps_its_fields(tmp_path: Path) -> None:
    record = {"id": "r1", "diagram_type": "none", "description": "Dzień dobry.", "expected_mermaid": REFUSAL}
    given = answer() | {"cost_usd": 0.001, "reasoning_tokens": 0}
    example = evaluate_record(record, given, tmp_path, None, 0.7)
    assert example["score"]["refusal_ok"] is True
    assert {key: example[key] for key in ANSWER_KEYS} == given
