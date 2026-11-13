"""Per-example metrics from design.md §4.3: mermaid_only, render, type_acc, node_f1, edge_f1, shape_acc, refusal.

Nodes are matched one-to-one (design.md §4.2 step 4): first by exact label after normalization, then, if an
embedder is given, the remaining labels by embedding cosine similarity with the Hungarian algorithm.
This module does not talk to any server; the caller passes the function that turns texts into vectors.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

from mermaiddiagramsaiagent.eval.flowchart import Flowchart, Node, ParseError, parse_flowchart
from mermaiddiagramsaiagent.eval.output import NormalizedOutput, diagram_type, is_refusal

PUNCTUATION_RE = re.compile(r"[^\w\s]")
DEFAULT_THRESHOLD = 0.7  # preliminary, see design.md §4.2

Embedder = Callable[[list[str]], list[list[float]]]


@dataclass(frozen=True)
class PRF:
    precision: float
    recall: float
    f1: float


ZERO = PRF(0.0, 0.0, 0.0)


@dataclass(frozen=True)
class NodePair:
    """A predicted node paired with a reference node. Pairs below the threshold are kept for calibration."""

    predicted_id: str
    reference_id: str
    predicted_label: str
    reference_label: str
    method: str  # "exact" or "embedding"
    similarity: float
    matched: bool


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
    shape_acc: float | None = None  # None when no node was matched
    node_pairs: list[NodePair] = field(default_factory=list)
    refusal_ok: bool | None = None  # out-of-scope references only: the output is exactly the refusal string


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


def pair_nodes(
    predicted: Flowchart, reference: Flowchart, embed: Embedder | None = None, threshold: float = DEFAULT_THRESHOLD
) -> list[NodePair]:
    """One-to-one pairs of predicted and reference nodes: exact label matches, then embedding matches."""
    pairs = exact_pairs(predicted, reference)
    if embed is not None:
        used_predicted = {pair.predicted_id for pair in pairs}
        used_reference = {pair.reference_id for pair in pairs}
        rest_predicted = [node for node in predicted.nodes.values() if node.id not in used_predicted]
        rest_reference = [node for node in reference.nodes.values() if node.id not in used_reference]
        pairs += embedding_pairs(rest_predicted, rest_reference, embed, threshold)
    return pairs


def exact_pairs(predicted: Flowchart, reference: Flowchart) -> list[NodePair]:
    unmatched: dict[str, list[Node]] = {}
    for node in reference.nodes.values():
        unmatched.setdefault(normalize_label(node.label), []).append(node)
    pairs = []
    for node in predicted.nodes.values():
        candidates = unmatched.get(normalize_label(node.label))
        if candidates:
            target = candidates.pop(0)
            pairs.append(NodePair(node.id, target.id, node.label, target.label, "exact", 1.0, True))
    return pairs


def embedding_pairs(
    predicted: list[Node], reference: list[Node], embed: Embedder, threshold: float
) -> list[NodePair]:
    """Best one-to-one assignment by cosine similarity; a pair counts as matched if similarity >= threshold."""
    if not predicted or not reference:
        return []
    vectors = np.asarray(embed([node.label for node in predicted + reference]), dtype=float)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    similarity = vectors[: len(predicted)] @ vectors[len(predicted) :].T
    rows, columns = linear_sum_assignment(similarity, maximize=True)
    pairs = []
    for row, column in zip(rows, columns):
        source, target, value = predicted[row], reference[column], float(similarity[row, column])
        pairs.append(
            NodePair(source.id, target.id, source.label, target.label, "embedding", round(value, 4), value >= threshold)
        )
    return pairs


def match_nodes(
    predicted: Flowchart, reference: Flowchart, embed: Embedder | None = None, threshold: float = DEFAULT_THRESHOLD
) -> dict[str, str]:
    """Map predicted node id -> reference node id for the matched pairs."""
    return {p.predicted_id: p.reference_id for p in pair_nodes(predicted, reference, embed, threshold) if p.matched}


def node_prf(predicted: Flowchart, reference: Flowchart, matches: dict[str, str]) -> PRF:
    return prf(len(matches), len(predicted.nodes), len(reference.nodes))


def edge_prf(predicted: Flowchart, reference: Flowchart, matches: dict[str, str]) -> PRF:
    """A predicted edge counts if its matched endpoints form a reference edge. Labels and duplicates ignored."""
    reference_edges = {(e.src, e.dst) for e in reference.edges}
    predicted_edges = {(e.src, e.dst) for e in predicted.edges}
    hits = sum((matches.get(src), matches.get(dst)) in reference_edges for src, dst in predicted_edges)
    return prf(hits, len(predicted_edges), len(reference_edges))


def shape_accuracy(predicted: Flowchart, reference: Flowchart, matches: dict[str, str]) -> float | None:
    """Share of matched nodes drawn with the reference shape (e.g. a decision as a rhombus)."""
    if not matches:
        return None
    same = sum(predicted.nodes[src].shape == reference.nodes[dst].shape for src, dst in matches.items())
    return same / len(matches)


def score_example(
    output: NormalizedOutput,
    renders: bool,
    reference_code: str,
    embed: Embedder | None = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> ExampleScore:
    """Score one model output. Output that does not render, has the wrong type or does not parse gets F1 = 0.

    Without `embed`, nodes are matched by exact normalized label only. For an out-of-scope reference (the
    refusal string) only `refusal_ok` is meaningful; the caller keeps such examples out of the diagram metrics.
    """
    if is_refusal(reference_code):
        return score_refusal(output)
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
    score.node_pairs = pair_nodes(predicted, reference, embed, threshold)
    matches = {pair.predicted_id: pair.reference_id for pair in score.node_pairs if pair.matched}
    score.parsed = True
    score.parse_warnings = predicted.warnings
    score.node = node_prf(predicted, reference, matches)
    score.edge = edge_prf(predicted, reference, matches)
    score.shape_acc = shape_accuracy(predicted, reference, matches)
    return score


def score_refusal(output: NormalizedOutput) -> ExampleScore:
    """Score the answer to an out-of-scope text: correct only if it is the bare refusal string."""
    refused = is_refusal(output.code) and not output.fenced and not output.extra_text
    return ExampleScore(
        mermaid_only=False,
        fenced=output.fenced,
        extra_text=output.extra_text,
        renders=False,
        predicted_type="none" if is_refusal(output.code) else diagram_type(output.code),
        type_ok=refused,
        refusal_ok=refused,
    )
