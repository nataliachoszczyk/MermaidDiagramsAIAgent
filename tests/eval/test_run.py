from dataclasses import asdict
from typing import Any

import pytest

from mermaiddiagramsaiagent.eval.metrics import score_example
from mermaiddiagramsaiagent.eval.output import REFUSAL, normalize_output
from mermaiddiagramsaiagent.eval.run import aggregate, summarize

REFERENCE = "flowchart TD\n    A[Złóż wniosek] --> B[Rozpatrz]"


def example(raw_output: str, reference: str, renders: bool = True, **fields: Any) -> dict[str, Any]:
    """An example as `evaluate_record` builds it, without calling a model or mmdc."""
    score = score_example(normalize_output(raw_output), renders, reference)
    return {"diagram_type": "flowchart", "difficulty": "easy", "finish_reason": "stop", "score": asdict(score)} | fields


def test_aggregate_keeps_refusal_examples_out_of_diagram_metrics() -> None:
    examples = [
        example(REFERENCE, REFERENCE),
        example("flowchart TD\n    A[Zamów pizzę]", REFERENCE),
        example(REFUSAL, REFUSAL, renders=False, diagram_type="none"),
        example(REFERENCE, REFUSAL, renders=False, diagram_type="none"),
    ]
    result = aggregate(examples)
    assert (result["n"], result["n_refusal"]) == (4, 2)
    assert result["refusal_acc"] == 0.5
    assert result["render_rate"] == 1.0  # the two refusal examples do not count as render failures
    assert result["node_f1"] == 0.5


def test_aggregate_of_refusal_examples_only_has_no_diagram_metrics() -> None:
    result = aggregate([example(REFUSAL, REFUSAL, renders=False, diagram_type="none")])
    assert result["refusal_acc"] == 1.0
    assert result["render_rate"] is None and result["node_f1"] is None and result["shape_acc"] is None


def test_aggregate_without_refusal_examples_has_no_refusal_acc() -> None:
    result = aggregate([example(REFERENCE, REFERENCE)])
    assert result["refusal_acc"] is None and result["n_refusal"] == 0


def test_refusal_for_a_process_description_gets_zero_f1() -> None:
    result = aggregate([example(REFUSAL, REFERENCE, renders=False)])
    assert (result["render_rate"], result["node_f1"], result["refusal_acc"]) == (0.0, 0.0, None)


def test_summarize_groups_by_description_style() -> None:
    examples = [
        example(REFERENCE, REFERENCE, description_style="structured"),
        example(REFERENCE, REFERENCE, description_style="natural"),
        example("flowchart TD\n    A[Zamów pizzę]", REFERENCE, description_style="natural"),
        example(REFUSAL, REFUSAL, renders=False, diagram_type="none", difficulty=None, description_style=None),
    ]
    summary = summarize(examples)
    styles = summary["by_description_style"]
    assert list(styles) == ["natural", "structured"]
    assert (styles["natural"]["n"], styles["natural"]["node_f1"]) == (2, 0.5)
    assert styles["structured"]["node_f1"] == 1.0
    assert summary["by_diagram_type"]["none"]["refusal_acc"] == 1.0
    assert list(summary["by_difficulty"]) == ["easy"]


def test_summarize_without_styles_has_an_empty_style_group() -> None:
    assert summarize([example(REFERENCE, REFERENCE)])["by_description_style"] == {}


@pytest.mark.parametrize(
    ("raw_output", "expected"),
    [
        (REFUSAL, True),
        (f"  {REFUSAL}\n", True),
        (f"```\n{REFUSAL}\n```", False),
        (f"{REFUSAL}. Tekst nie opisuje procesu.", False),
        ("brak_procesu", False),
        (REFERENCE, False),
        ("", False),
    ],
)
def test_refusal_ok_needs_the_bare_refusal_string(raw_output: str, expected: bool) -> None:
    score = score_example(normalize_output(raw_output), renders=False, reference_code=REFUSAL)
    assert score.refusal_ok is expected
    assert score.node.f1 == 0.0 and not score.renders
