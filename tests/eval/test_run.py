from dataclasses import asdict
from types import SimpleNamespace
from typing import Any

import pytest

from mermaiddiagramsaiagent.eval.metrics import score_example
from mermaiddiagramsaiagent.eval.output import REFUSAL, normalize_output
from mermaiddiagramsaiagent.eval.run import (
    aggregate,
    call_cost_usd,
    reasoning_tokens,
    sample_records,
    select_records,
    summarize,
)

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


def records_of(**counts: int) -> list[dict[str, Any]]:
    return [{"id": f"{kind}-{i}", "diagram_type": kind} for kind, count in counts.items() for i in range(count)]


def test_sample_has_the_asked_size_and_every_diagram_type() -> None:
    records = records_of(flowchart=91, sequenceDiagram=34, none=5)
    sample = sample_records(records, 15)
    kinds = [record["diagram_type"] for record in sample]
    assert (kinds.count("flowchart"), kinds.count("sequenceDiagram"), kinds.count("none")) == (10, 4, 1)


def test_sample_keeps_the_file_order_and_is_the_same_every_time() -> None:
    records = records_of(flowchart=20, sequenceDiagram=10)
    sample = sample_records(records, 6)
    assert sample == sample_records(records, 6)
    assert sample == [record for record in records if record in sample]


def test_small_sample_still_has_the_asked_size() -> None:
    assert len(sample_records(records_of(flowchart=91, sequenceDiagram=34, none=5), 3)) == 3


def test_sample_larger_than_the_data_returns_everything() -> None:
    records = records_of(flowchart=2)
    assert sample_records(records, 5) == records


def test_select_records_keeps_the_file_order() -> None:
    records = records_of(flowchart=3)
    assert select_records(records, ["flowchart-2", "flowchart-0"]) == [records[0], records[2]]


def test_select_records_rejects_an_unknown_id() -> None:
    with pytest.raises(SystemExit, match="flowchart-9"):
        select_records(records_of(flowchart=3), ["flowchart-9"])


def test_call_cost_sums_the_proxy_cost_parts_in_dollars() -> None:
    usage = SimpleNamespace(cost={"input_tokens_cost_nanodollars": 624500, "output_tokens_cost_nanodollars": 3054000})
    assert call_cost_usd(usage) == pytest.approx(0.0036785)


def test_call_cost_is_none_for_servers_without_it() -> None:
    assert call_cost_usd(SimpleNamespace()) is None
    assert call_cost_usd(None) is None


def test_reasoning_tokens_from_usage_details() -> None:
    usage = SimpleNamespace(completion_tokens_details=SimpleNamespace(reasoning_tokens=842))
    assert reasoning_tokens(usage) == 842
    assert reasoning_tokens(SimpleNamespace(completion_tokens_details=None)) is None


def test_aggregate_adds_up_the_cost_and_has_none_without_it() -> None:
    priced = [example(REFERENCE, REFERENCE, cost_usd=0.25), example(REFERENCE, REFERENCE, cost_usd=0.5)]
    assert aggregate(priced)["cost_usd"] == 0.75
    assert aggregate([example(REFERENCE, REFERENCE)])["cost_usd"] is None
