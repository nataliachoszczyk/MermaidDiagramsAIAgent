from dataclasses import astuple

import pytest

from mermaiddiagramsaiagent.eval.flowchart import parse_flowchart
from mermaiddiagramsaiagent.eval.metrics import (
    PRF,
    match_nodes,
    pair_nodes,
    normalize_label,
    prf,
    score_example,
)
from mermaiddiagramsaiagent.eval.output import NormalizedOutput

REFERENCE = """flowchart TD
    A[Złóż wniosek] --> B{Czy kompletny?}
    B -->|Tak| C[Rozpatrz]
    B -->|Nie| D[Odrzuć]
"""


def bare(code: str) -> NormalizedOutput:
    return NormalizedOutput(code, fenced=False, extra_text=False)


# --- building blocks ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Złóż wniosek", "złóż wniosek"),
        ("Czy kwota > 1000?", "czy kwota 1000"),
        ("  Wyślij   e-mail.  ", "wyślij e mail"),
        ("ZAPISZ DANE", "zapisz dane"),
    ],
)
def test_normalize_label(label: str, expected: str) -> None:
    assert normalize_label(label) == expected


def test_prf() -> None:
    assert prf(2, 2, 3) == PRF(1.0, 2 / 3, 0.8)
    assert prf(0, 3, 4) == PRF(0.0, 0.0, 0.0)
    assert prf(0, 0, 4) == PRF(0.0, 0.0, 0.0)
    assert prf(0, 0, 0) == PRF(1.0, 1.0, 1.0)


def test_match_nodes_ignores_ids_and_label_formatting() -> None:
    predicted = parse_flowchart('flowchart TD\n    x["złóż wniosek"] --> y{Czy kompletny}')
    assert match_nodes(predicted, parse_flowchart(REFERENCE)) == {"x": "A", "y": "B"}


def test_match_nodes_is_one_to_one_for_duplicate_labels() -> None:
    reference = parse_flowchart("flowchart TD\n    A[Sprawdź] --> B[Sprawdź]")
    predicted = parse_flowchart("flowchart TD\n    x[Sprawdź] --> y[Sprawdź] --> z[Sprawdź]")
    assert match_nodes(predicted, reference) == {"x": "A", "y": "B"}


# --- score_example --------------------------------------------------------------------------------


def test_perfect_prediction_with_different_ids() -> None:
    predicted = """flowchart TD
    start[Złóż wniosek] --> check{Czy kompletny?}
    check -->|Tak| ok[Rozpatrz]
    check -->|Nie| no[Odrzuć]
    """
    score = score_example(bare(predicted), renders=True, reference_code=REFERENCE)
    assert score.node == PRF(1.0, 1.0, 1.0)
    assert score.edge == PRF(1.0, 1.0, 1.0)
    assert score.mermaid_only and score.type_ok and score.parsed


def test_partial_prediction() -> None:
    # The example from the explanation: one label differs, one branch is missing.
    predicted = """flowchart TD
    start[Złóż wniosek] --> check{Czy kompletny?}
    check --> ok[Rozpatrz wniosek]
    """
    # Exact matching: "Rozpatrz wniosek" != "Rozpatrz", so the check -> ok edge does not count either.
    score = score_example(bare(predicted), renders=True, reference_code=REFERENCE)
    assert astuple(score.node) == pytest.approx((2 / 3, 2 / 4, 4 / 7))
    assert astuple(score.edge) == pytest.approx((1 / 2, 1 / 3, 0.4))


def test_reversed_edge_does_not_count() -> None:
    predicted = "flowchart TD\n    B{Czy kompletny?} --> A[Złóż wniosek]"
    score = score_example(bare(predicted), renders=True, reference_code=REFERENCE)
    assert score.edge.precision == 0.0


def test_not_rendering_output_gets_zero_f1() -> None:
    score = score_example(bare(REFERENCE), renders=False, reference_code=REFERENCE)
    assert score.node.f1 == 0.0 and score.edge.f1 == 0.0
    assert not score.parsed


def test_wrong_diagram_type_gets_zero_f1() -> None:
    score = score_example(bare("sequenceDiagram\n    A->>B: hej"), renders=True, reference_code=REFERENCE)
    assert score.predicted_type == "sequenceDiagram"
    assert not score.type_ok
    assert score.node.f1 == 0.0


def test_graph_keyword_counts_as_flowchart() -> None:
    score = score_example(bare(REFERENCE.replace("flowchart", "graph")), renders=True, reference_code=REFERENCE)
    assert score.type_ok and score.node.f1 == 1.0


def test_fenced_output_is_not_mermaid_only_but_still_scored() -> None:
    output = NormalizedOutput(REFERENCE, fenced=True, extra_text=False)
    score = score_example(output, renders=True, reference_code=REFERENCE)
    assert not score.mermaid_only
    assert score.node.f1 == 1.0


def test_sequence_reference_is_not_supported_yet() -> None:
    with pytest.raises(NotImplementedError):
        score_example(bare(REFERENCE), renders=True, reference_code="sequenceDiagram\n    A->>B: hej")


# --- embedding matching ---------------------------------------------------------------------------

VECTORS = {
    "Sklonuj repozytorium": [1.0, 0.0, 0.0],
    "Klonujemy repozytorium": [0.95, 0.3, 0.0],
    "Uruchom testy": [0.0, 1.0, 0.0],
    "Uruchamiamy testy": [0.3, 0.95, 0.0],
    "Zamów pizzę": [0.0, 0.0, 1.0],
}


def fake_embed(texts: list[str]) -> list[list[float]]:
    return [VECTORS[text] for text in texts]


def test_embedding_matches_paraphrased_labels() -> None:
    reference = parse_flowchart("flowchart TD\n    A[Sklonuj repozytorium] --> B[Uruchom testy]")
    predicted = parse_flowchart("flowchart TD\n    x[Klonujemy repozytorium] --> y[Uruchamiamy testy]")
    assert match_nodes(predicted, reference) == {}
    assert match_nodes(predicted, reference, fake_embed) == {"x": "A", "y": "B"}


def test_embedding_pair_below_threshold_is_kept_but_not_matched() -> None:
    reference = parse_flowchart("flowchart TD\n    A[Sklonuj repozytorium]")
    predicted = parse_flowchart("flowchart TD\n    x[Zamów pizzę]")
    (pair,) = pair_nodes(predicted, reference, fake_embed)
    assert (pair.method, pair.similarity, pair.matched) == ("embedding", 0.0, False)


def test_embedding_assignment_is_one_to_one_and_optimal() -> None:
    # Greedy would give x -> A (0.95) and leave y unmatched; the best total assignment is y -> A, x -> B.
    vectors = {"a": [1.0, 0.0], "b": [0.8, 0.6], "x": [0.95, 0.3122], "y": [1.0, 0.02]}
    reference = parse_flowchart("flowchart TD\n    A[a] --> B[b]")
    predicted = parse_flowchart("flowchart TD\n    x[x] --> y[y]")
    matches = match_nodes(predicted, reference, lambda texts: [vectors[t] for t in texts], threshold=0.8)
    assert matches == {"x": "B", "y": "A"}


def test_exact_match_comes_before_embeddings() -> None:
    calls: list[list[str]] = []

    def recording_embed(texts: list[str]) -> list[list[float]]:
        calls.append(texts)
        return fake_embed(texts)

    reference = parse_flowchart("flowchart TD\n    A[Uruchom testy] --> B[Sklonuj repozytorium]")
    predicted = parse_flowchart("flowchart TD\n    x[Uruchom testy] --> y[Klonujemy repozytorium]")
    assert match_nodes(predicted, reference, recording_embed) == {"x": "A", "y": "B"}
    assert calls == [["Klonujemy repozytorium", "Sklonuj repozytorium"]]


def test_score_example_with_embeddings() -> None:
    reference = "flowchart TD\n    A[Sklonuj repozytorium] --> B[Uruchom testy]"
    output = bare("flowchart TD\n    x[Klonujemy repozytorium] --> y[Uruchamiamy testy]")
    assert score_example(output, True, reference).node.f1 == 0.0
    score = score_example(output, True, reference, fake_embed)
    assert (score.node.f1, score.edge.f1) == (1.0, 1.0)
    assert [pair.method for pair in score.node_pairs] == ["embedding", "embedding"]


# --- shape accuracy -------------------------------------------------------------------------------


def test_shape_acc_counts_matched_nodes_with_the_reference_shape() -> None:
    output = bare("flowchart TD\n    A[Złóż wniosek] --> B[Czy kompletny?]\n    B --> C[Rozpatrz]\n    B --> D[Odrzuć]")
    assert score_example(output, True, REFERENCE).shape_acc == 0.75


def test_shape_acc_is_none_without_matched_nodes() -> None:
    assert score_example(bare("flowchart TD\n    A[Zamów pizzę]"), True, REFERENCE).shape_acc is None
