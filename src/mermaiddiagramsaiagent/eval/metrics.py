"""Per-example metrics from design.md §4.3: mermaid_only, render, type_acc, node_f1, edge_f1, shape_acc, refusal.

Nodes are matched one-to-one (design.md §4.2 step 4): first by exact label after normalization, then, if an
embedder is given, the remaining labels by embedding cosine similarity with the Hungarian algorithm.
In a sequence diagram the nodes are the participants and the edges are the messages; a predicted message counts
if its sender and receiver are matched and its text matches a reference message between the same two
participants (same matching as for labels). Message order and blocks (`alt`, `loop`) are not scored.
This module does not talk to any server; the caller passes the function that turns texts into vectors.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
from scipy.optimize import linear_sum_assignment

from mermaiddiagramsaiagent.eval.flowchart import Flowchart, ParseError, parse_flowchart
from mermaiddiagramsaiagent.eval.output import NormalizedOutput, diagram_type, is_refusal
from mermaiddiagramsaiagent.eval.sequence import Message, SequenceDiagram, parse_sequence

PUNCTUATION_RE = re.compile(r"[^\w\s]")
DEFAULT_THRESHOLD = 0.7  # preliminary, see design.md §4.2

Embedder = Callable[[list[str]], list[list[float]]]


class Labelled(Protocol):
    """Anything matched by its label: a flowchart node, a participant, a message text."""

    @property
    def id(self) -> str: ...

    @property
    def label(self) -> str: ...


@dataclass(frozen=True)
class Item:
    id: str
    label: str


@dataclass(frozen=True)
class PRF:
    precision: float
    recall: float
    f1: float


ZERO = PRF(0.0, 0.0, 0.0)


@dataclass(frozen=True)
class NodePair:
    """A predicted node paired with a reference node. Pairs below the threshold are kept for calibration.

    Also used for messages of a sequence diagram: the ids are then the positions of the messages (from 0).
    """

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
    shape_acc: float | None = None  # None when no node was matched, and for sequence diagrams
    node_pairs: list[NodePair] = field(default_factory=list)
    message_pairs: list[NodePair] = field(default_factory=list)  # sequence diagrams only
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
    return pair_items(list(predicted.nodes.values()), list(reference.nodes.values()), embed, threshold)


def pair_items(
    predicted: Sequence[Labelled],
    reference: Sequence[Labelled],
    embed: Embedder | None = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> list[NodePair]:
    """One-to-one pairs by label: exact matches first, then the rest by embeddings (empty labels are left out)."""
    pairs = exact_pairs(predicted, reference)
    if embed is not None:
        used_predicted = {pair.predicted_id for pair in pairs}
        used_reference = {pair.reference_id for pair in pairs}
        rest_predicted = [item for item in predicted if item.id not in used_predicted and item.label]
        rest_reference = [item for item in reference if item.id not in used_reference and item.label]
        pairs += embedding_pairs(rest_predicted, rest_reference, embed, threshold)
    return pairs


def exact_pairs(predicted: Sequence[Labelled], reference: Sequence[Labelled]) -> list[NodePair]:
    unmatched: dict[str, list[Labelled]] = {}
    for node in reference:
        unmatched.setdefault(normalize_label(node.label), []).append(node)
    pairs = []
    for node in predicted:
        candidates = unmatched.get(normalize_label(node.label))
        if candidates:
            target = candidates.pop(0)
            pairs.append(NodePair(node.id, target.id, node.label, target.label, "exact", 1.0, True))
    return pairs


def embedding_pairs(
    predicted: Sequence[Labelled], reference: Sequence[Labelled], embed: Embedder, threshold: float
) -> list[NodePair]:
    """Best one-to-one assignment by cosine similarity; a pair counts as matched if similarity >= threshold."""
    if not predicted or not reference:
        return []
    vectors = np.asarray(embed([node.label for node in [*predicted, *reference]]), dtype=float)
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


def pair_messages(
    predicted: SequenceDiagram,
    reference: SequenceDiagram,
    matches: dict[str, str],
    embed: Embedder | None = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> list[NodePair]:
    """Pair message texts, separately for each (sender, receiver) pair of matched participants.

    `matches` maps predicted participant ids to reference ones. A predicted message with an unmatched sender or
    receiver, or between two participants that exchange nothing in that direction in the reference, has no pair.
    """
    reference_groups = group_messages(reference.messages, {p: p for p in reference.participants})
    predicted_groups = group_messages(predicted.messages, matches)
    pairs = []
    for ends, items in predicted_groups.items():
        if ends in reference_groups:
            pairs += pair_items(items, reference_groups[ends], embed, threshold)
    return pairs


def group_messages(messages: list[Message], ids: dict[str, str]) -> dict[tuple[str, str], list[Item]]:
    """Message texts by (sender, receiver) after translating the ids; the item id is the message position."""
    groups: dict[tuple[str, str], list[Item]] = {}
    for index, message in enumerate(messages):
        if message.src in ids and message.dst in ids:
            groups.setdefault((ids[message.src], ids[message.dst]), []).append(Item(str(index), message.text))
    return groups


PARSERS: dict[str, Callable[[str], Flowchart | SequenceDiagram]] = {
    "flowchart": parse_flowchart,
    "sequenceDiagram": parse_sequence,
}


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
    if reference_type not in PARSERS:
        raise ValueError(f"reference is not a supported diagram or the refusal string: {reference_type!r}")
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
    parse = PARSERS[reference_type]
    try:
        predicted = parse(output.code)
    except ParseError:
        return score
    reference = parse(reference_code)
    score.parsed = True
    score.parse_warnings = predicted.warnings
    if isinstance(predicted, Flowchart) and isinstance(reference, Flowchart):
        score_flowchart(score, predicted, reference, embed, threshold)
    elif isinstance(predicted, SequenceDiagram) and isinstance(reference, SequenceDiagram):
        score_sequence(score, predicted, reference, embed, threshold)
    return score


def score_flowchart(
    score: ExampleScore, predicted: Flowchart, reference: Flowchart, embed: Embedder | None, threshold: float
) -> None:
    score.node_pairs = pair_nodes(predicted, reference, embed, threshold)
    matches = {pair.predicted_id: pair.reference_id for pair in score.node_pairs if pair.matched}
    score.node = node_prf(predicted, reference, matches)
    score.edge = edge_prf(predicted, reference, matches)
    score.shape_acc = shape_accuracy(predicted, reference, matches)


def score_sequence(
    score: ExampleScore, predicted: SequenceDiagram, reference: SequenceDiagram, embed: Embedder | None, threshold: float
) -> None:
    """Nodes are participants, edges are messages; every message counts once, also a repeated one."""
    participants = list(predicted.participants.values()), list(reference.participants.values())
    score.node_pairs = pair_items(*participants, embed, threshold)
    matches = {pair.predicted_id: pair.reference_id for pair in score.node_pairs if pair.matched}
    score.message_pairs = pair_messages(predicted, reference, matches, embed, threshold)
    hits = sum(pair.matched for pair in score.message_pairs)
    score.node = prf(len(matches), len(predicted.participants), len(reference.participants))
    score.edge = prf(hits, len(predicted.messages), len(reference.messages))


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
