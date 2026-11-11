"""Per-example metrics from design.md §4.3: mermaid_only, render, type_acc, node_f1, edge_f1.

Nodes are matched one-to-one by exact label after normalization. Embedding-based matching of the remaining
labels (design.md §4.2 step 4) is not implemented yet.
"""

import re
from dataclasses import dataclass, field

from mermaiddiagramsaiagent.eval.flowchart import Flowchart, ParseError, parse_flowchart
from mermaiddiagramsaiagent.eval.output import NormalizedOutput, diagram_type

PUNCTUATION_RE = re.compile(r"[^\w\s]")


@dataclass(frozen=True)
class PRF:
    precision: float
    recall: float
    f1: float


ZERO = PRF(0.0, 0.0, 0.0)


@dataclass
class ExampleScore:
    mermaid_only: bool
    fenced: bool
    extra_text: bool
    renders: bool
    predicted_type: str
    type_ok: bool
    parsed: bool = False
    parse_warnings: list[str] = field(default_factory=list)
    node: PRF = ZERO
    edge: PRF = ZERO


def normalize_label(label: str) -> str:
    """Lowercase, punctuation removed, whitespace collapsed: 'Czy kwota > 1000?' -> 'czy kwota 1000'."""
    return " ".join(PUNCTUATION_RE.sub(" ", label.lower()).split())


def prf(matched: int, predicted: int, reference: int) -> PRF:
    if predicted == 0 and reference == 0:
        return PRF(1.0, 1.0, 1.0)
    precision = matched / predicted if predicted else 0.0
    recall = matched / reference if reference else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return PRF(precision, recall, f1)


def match_nodes(predicted: Flowchart, reference: Flowchart) -> dict[str, str]:
    """One-to-one map predicted node id -> reference node id with the same normalized label."""
    unmatched: dict[str, list[str]] = {}
    for node in reference.nodes.values():
        unmatched.setdefault(normalize_label(node.label), []).append(node.id)
    matches = {}
    for node in predicted.nodes.values():
        candidates = unmatched.get(normalize_label(node.label))
        if candidates:
            matches[node.id] = candidates.pop(0)
    return matches


def node_prf(predicted: Flowchart, reference: Flowchart, matches: dict[str, str]) -> PRF:
    return prf(len(matches), len(predicted.nodes), len(reference.nodes))


def edge_prf(predicted: Flowchart, reference: Flowchart, matches: dict[str, str]) -> PRF:
    """A predicted edge counts if its matched endpoints form a reference edge. Labels and duplicates ignored."""
    reference_edges = {(e.src, e.dst) for e in reference.edges}
    predicted_edges = {(e.src, e.dst) for e in predicted.edges}
    hits = sum((matches.get(src), matches.get(dst)) in reference_edges for src, dst in predicted_edges)
    return prf(hits, len(predicted_edges), len(reference_edges))


def score_example(output: NormalizedOutput, renders: bool, reference_code: str) -> ExampleScore:
    """Score one model output. Output that does not render, has the wrong type or does not parse gets F1 = 0."""
    reference_type = diagram_type(reference_code)
    if reference_type != "flowchart":
        raise NotImplementedError(f"scoring {reference_type} is not implemented yet")
    predicted_type = diagram_type(output.code)
    score = ExampleScore(
        mermaid_only=not output.fenced and not output.extra_text,
        fenced=output.fenced,
        extra_text=output.extra_text,
        renders=renders,
        predicted_type=predicted_type,
        type_ok=predicted_type == reference_type,
    )
    if not (renders and score.type_ok):
        return score
    try:
        predicted = parse_flowchart(output.code)
    except ParseError:
        return score
    reference = parse_flowchart(reference_code)
    matches = match_nodes(predicted, reference)
    score.parsed = True
    score.parse_warnings = predicted.warnings
    score.node = node_prf(predicted, reference, matches)
    score.edge = edge_prf(predicted, reference, matches)
    return score
