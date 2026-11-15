"""Build the generated part of the golden test set from the public source datasets (design.md §2.3).

    uv run build-golden --model anthropic/claude-sonnet-5@default --kaggle-proxy --flowcharts 3 --sequences 3

For every selected source diagram a model translates the texts to Polish and writes a Polish description in one
of the three styles (design.md §2.2.1). The translated diagram must keep the structure of the source and render
with `mmdc`; a record that fails these checks is retried with the problems named, then skipped. Records already
in the output file are kept, so an interrupted run continues where it stopped. Hand-written records are not
made here. Every record still needs a human read.
"""

import argparse
import csv
import hashlib
import re
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import BadRequestError, OpenAI

from mermaiddiagramsaiagent.data.jsonl import read_jsonl, write_jsonl
from mermaiddiagramsaiagent.data.pilot import difficulty as flowchart_difficulty
from mermaiddiagramsaiagent.data.sources import MERMAIDSEQBENCH, RONNIEALLEN, Source
from mermaiddiagramsaiagent.eval.flowchart import Flowchart, ParseError, parse_flowchart
from mermaiddiagramsaiagent.eval.render import check_mmdc_works, render
from mermaiddiagramsaiagent.eval.sequence import SequenceDiagram, parse_sequence
from mermaiddiagramsaiagent.llm import make_client, make_kaggle_proxy_client

GOLDEN_PATH = Path("data/golden/golden.jsonl")
PROMPT_PATH = Path("prompts/golden.txt")
STYLES = ("structured", "natural", "brief")
FLOWCHART_SPLITS = ("train", "validation")  # the `test` split is the pilot
PILOT_SPLIT = "test"
TEMPERATURE = 0.0
MAX_TOKENS = 4096
ATTEMPTS = 3
MAX_UNTRANSLATED = 0.5  # more than this share of texts left as in the source: the diagram was not translated

PROMPT_PREFIX_RE = re.compile(
    r"^(Create a flowchart for: |Design a flowchart showing |Draw the complete process flow for |"
    r"Map out all the steps and decisions for |Show the full decision flow when handling )"
)
TITLE_RE = re.compile(r"^.* (?P<scenario>\d+)/(?P<variant>[IVXL]+)$")
BLOCK_RE = re.compile(r"^\s*(?:alt|loop|opt|par|critical|break)\b", re.MULTILINE)
RESPONSE_RE = re.compile(r"<mermaid>\s*(.*?)\s*</mermaid>\s*<description>\s*(.*?)\s*</description>", re.DOTALL)


@dataclass(frozen=True)
class Candidate:
    """A source diagram chosen for the golden set."""

    diagram_type: str  # "flowchart" or "sequenceDiagram"
    source: str  # value of the `source` field
    source_ref: str
    license: str
    mermaid: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True, help="generator model as the server knows it")
    parser.add_argument("--kaggle-proxy", action="store_true", help="use the Kaggle Model Proxy (see KAGGLE.md)")
    parser.add_argument("--flowcharts", type=int, default=100, help="number of flowcharts (fewer if not available)")
    parser.add_argument("--sequences", type=int, default=30, help="number of sequence diagrams")
    parser.add_argument("--out", type=Path, default=GOLDEN_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = make_kaggle_proxy_client() if args.kaggle_proxy else make_client()
    check_mmdc_works()
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    prompt_hash = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()[:12]
    plan = plan_records(select_flowcharts()[: args.flowcharts], select_sequences()[: args.sequences])
    records = {record["id"]: record for record in read_jsonl(args.out)} if args.out.exists() else {}
    failed, cost = [], 0.0
    sampling = {"temperature": TEMPERATURE}  # emptied if the model rejects the parameter

    with tempfile.TemporaryDirectory() as tmp:
        for i, (record_id, style, candidate) in enumerate(plan, start=1):
            if record_id in records:
                print(f"[{i:>3}/{len(plan)}] {record_id:<18} kept from an earlier run")
                continue
            generated, problems, spent = generate_checked(
                client, args.model, system_prompt, candidate, style, Path(tmp), sampling
            )
            cost += spent
            if generated is None:
                failed.append(record_id)
                print(f"[{i:>3}/{len(plan)}] {record_id:<18} FAILED: {'; '.join(problems)}")
                continue
            note = f"texts translated and description written by {args.model} (prompt {prompt_hash})"
            records[record_id] = build_record(record_id, candidate, style, *generated, note)
            write_jsonl(args.out, [records[key] for key in sorted(records)])  # after every record: keeps progress
            print(f"[{i:>3}/{len(plan)}] {record_id:<18} {style:<10} {generated[1][:60]}...")

    print(f"\n{len(records)} records in {args.out}; read every one before using the set")
    print(f"Cost reported by the server for this run: ${cost:.2f}")
    if failed:
        print(f"Failed after {ATTEMPTS} attempts (run again to retry): {', '.join(failed)}")


# --- choosing the source diagrams -------------------------------------------------------------------


def topic(prompt: str) -> str:
    """The process a RonnieAllen prompt asks for: 'Create a flowchart for: X' -> 'x'."""
    return PROMPT_PREFIX_RE.sub("", prompt).strip().lower()


def reference_problems(chart: Flowchart) -> list[str]:
    """Reasons why a source flowchart is not a good reference (many are generated with broken logic)."""
    outgoing = Counter(edge.src for edge in chart.edges)
    nodes = list(chart.nodes.values())
    problems = []
    if chart.warnings or any(node.label.startswith("{") for node in nodes):
        problems.append("syntax the parser or mmdc does not accept")
    if any(node.shape == "rhombus" and outgoing[node.id] < 2 for node in nodes):
        problems.append("decision with fewer than two branches")
    if any(edge.label and edge.src in chart.nodes and chart.nodes[edge.src].shape != "rhombus" for edge in chart.edges):
        problems.append("labelled branch that does not leave a decision")
    if any(node.shape != "stadium" and outgoing[node.id] == 0 for node in nodes):
        problems.append("step that leads nowhere")
    if sum(node.shape == "stadium" for node in nodes) != 2:
        problems.append("not exactly one start and one end")
    return problems


def select_flowcharts() -> list[Candidate]:
    """Usable RonnieAllen flowcharts, ordered so that any prefix of the list has as many topics as possible.

    The dataset has several diagrams per topic. First come the topics that are not in the pilot, one diagram
    each, then one diagram for each pilot topic, then the second diagram of every topic, and so on.
    """
    data_dir = RONNIEALLEN.local_dir / "data"
    pilot_topics = {topic(row["prompt"]) for row in read_jsonl(data_dir / f"{PILOT_SPLIT}.jsonl")}
    seen_per_topic: Counter[str] = Counter()
    seen_diagrams: set[str] = set()
    ranked = []
    for split in FLOWCHART_SPLITS:
        for line, row in enumerate(read_jsonl(data_dir / f"{split}.jsonl"), start=1):
            code = row["mermaid"].strip()
            if code in seen_diagrams or reference_problems(parse_flowchart(code)):
                continue
            seen_diagrams.add(code)
            name = topic(row["prompt"])
            rank = (seen_per_topic[name], name in pilot_topics, len(ranked))
            seen_per_topic[name] += 1
            ref = source_ref(RONNIEALLEN, f"data/{split}.jsonl:{line}")
            ranked.append((rank, Candidate("flowchart", "ronnieallen", ref, "CC-BY-4.0", code)))
    return [candidate for _, candidate in sorted(ranked, key=lambda item: item[0])]


def select_sequences() -> list[Candidate]:
    """One MermaidSeqBench diagram per scenario: the first variant in which every participant takes part."""
    with (MERMAIDSEQBENCH.local_dir / "data.csv").open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    chosen: dict[str, tuple[bool, Candidate]] = {}
    for line, row in enumerate(rows, start=1):
        title = TITLE_RE.match(row["nl_task_title"])
        if title is None:
            raise ValueError(f"unexpected MermaidSeqBench title: {row['nl_task_title']!r}")
        code = row["expected_output"].strip()
        complete = not idle_participants(parse_sequence(code))
        scenario = title.group("scenario")
        if scenario not in chosen or (complete and not chosen[scenario][0]):
            ref = source_ref(MERMAIDSEQBENCH, f"data.csv:{line} ({row['nl_task_title']})")
            chosen[scenario] = (complete, Candidate("sequenceDiagram", "mermaidseqbench", ref, "Apache-2.0", code))
    return [candidate for _, candidate in chosen.values()]


def idle_participants(diagram: SequenceDiagram) -> set[str]:
    """Participants that send and receive nothing (e.g. created by a note that uses the alias as an id)."""
    active = {message.src for message in diagram.messages} | {message.dst for message in diagram.messages}
    return set(diagram.participants) - active


def source_ref(source: Source, location: str) -> str:
    return f"{source.repo_id}@{source.revision[:8]}:{location}"


def plan_records(flowcharts: list[Candidate], sequences: list[Candidate]) -> list[tuple[str, str, Candidate]]:
    """(record id, description style, candidate); the styles alternate within each diagram type."""
    plan = []
    for prefix, candidates in (("golden-flow", flowcharts), ("golden-seq", sequences)):
        for index, candidate in enumerate(candidates):
            plan.append((f"{prefix}-{index + 1:04d}", STYLES[index % len(STYLES)], candidate))
    return plan


# --- generating and checking one record -------------------------------------------------------------


def generate_checked(
    client: OpenAI,
    model: str,
    system_prompt: str,
    candidate: Candidate,
    style: str,
    work_dir: Path,
    sampling: dict[str, float],
) -> tuple[tuple[str, str] | None, list[str], float]:
    """((translated diagram, description) or None, problems of the last attempt, cost in dollars)."""
    problems: list[str] = []
    cost = 0.0
    for _ in range(ATTEMPTS):
        text, spent = ask(client, model, system_prompt, user_message(candidate, style, problems), sampling)
        cost += spent
        parsed = parse_response(text)
        if parsed is None:
            problems = ["the answer did not have the <mermaid> and <description> blocks"]
            continue
        problems = translation_problems(candidate.mermaid, parsed[0]) + description_problems(parsed[1])
        if not problems and not render(parsed[0], work_dir, "golden").ok:
            problems = ["the translated diagram does not render with mmdc"]
        if not problems:
            return parsed, [], cost
    return None, problems, cost


def user_message(candidate: Candidate, style: str, problems: list[str]) -> str:
    message = f"Style: {style}\n\n{candidate.mermaid}"
    if problems:
        message += "\n\nYour previous answer was rejected: " + "; ".join(problems) + ". Fix this."
    return message


def ask(
    client: OpenAI, model: str, system_prompt: str, message: str, sampling: dict[str, float]
) -> tuple[str, float]:
    """(answer text, cost in dollars if the server reports it, else 0).

    Some hosted models reject `temperature`; then `sampling` is emptied and the request is sent without it.
    """
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": message}]
    try:
        response = client.chat.completions.create(model=model, messages=messages, max_tokens=MAX_TOKENS, **sampling)
    except BadRequestError as error:
        if not sampling or "temperature" not in str(error):
            raise
        print("The model does not accept `temperature`; generating with its default sampling.")
        sampling.clear()
        response = client.chat.completions.create(model=model, messages=messages, max_tokens=MAX_TOKENS)
    cost = getattr(response.usage, "cost", None) or {}  # the Kaggle Model Proxy adds the cost in nanodollars
    return response.choices[0].message.content or "", sum(cost.values()) / 1e9


def parse_response(text: str) -> tuple[str, str] | None:
    match = RESPONSE_RE.search(text)
    return (match.group(1), match.group(2)) if match else None


def translation_problems(source_code: str, translated_code: str) -> list[str]:
    """Differences in structure between the source diagram and its translation, and missing translation."""
    try:
        if source_code.lstrip().startswith("sequenceDiagram"):
            return sequence_problems(parse_sequence(source_code), parse_sequence(translated_code))
        return flowchart_problems(parse_flowchart(source_code), parse_flowchart(translated_code))
    except ParseError as error:
        return [f"the translated diagram does not parse: {error}"]


def flowchart_problems(source: Flowchart, translated: Flowchart) -> list[str]:
    problems = [f"parser warning: {warning}" for warning in translated.warnings]
    if {n.id: n.shape for n in source.nodes.values()} != {n.id: n.shape for n in translated.nodes.values()}:
        problems.append("node ids or shapes differ from the source")
    if [(e.src, e.dst, bool(e.label)) for e in source.edges] != [(e.src, e.dst, bool(e.label)) for e in translated.edges]:
        problems.append("edges differ from the source")
    texts = [(a.label, translated.nodes[a.id].label) for a in source.nodes.values() if a.id in translated.nodes]
    return problems + untranslated_problem([pair for pair in texts if pair[0] != "Start"])


def sequence_problems(source: SequenceDiagram, translated: SequenceDiagram) -> list[str]:
    problems = [f"parser warning: {warning}" for warning in translated.warnings]
    if participant_outline(source) != participant_outline(translated):
        problems.append("participant ids or aliases differ from the source")
    if [(m.src, m.dst, m.arrow) for m in source.messages] != [(m.src, m.dst, m.arrow) for m in translated.messages]:
        problems.append("messages (sender, receiver, arrow) differ from the source")
    texts = [(a.text, b.text) for a, b in zip(source.messages, translated.messages)]
    labels = [(a.label, b.label) for a, b in zip(source.participants.values(), translated.participants.values())]
    if any(after.startswith('"') and not before.startswith('"') for before, after in texts + labels):
        problems.append("quotation marks added around a message text or an alias (Mermaid would draw them)")
    return problems + untranslated_problem(texts)


def participant_outline(diagram: SequenceDiagram) -> list[tuple[str, bool]]:
    """(id, has an alias) for every participant, in order."""
    return [(p.id, p.label != p.id) for p in diagram.participants.values()]


def untranslated_problem(texts: list[tuple[str, str]]) -> list[str]:
    same = sum(before == after for before, after in texts)
    if texts and same / len(texts) > MAX_UNTRANSLATED:
        return [f"{same} of {len(texts)} texts are the same as in the source: translate them into Polish"]
    return []


def description_problems(description: str) -> list[str]:
    problems = []
    if not description.strip():
        problems.append("the description is empty")
    if re.search(r"mermaid|flowchart|sequenceDiagram", description, re.IGNORECASE):
        problems.append("the description mentions Mermaid")
    if re.search(r"^\s*(?:[-*•]|\d+[.)])\s", description, re.MULTILINE):
        problems.append("the description contains a list")
    return problems


# --- the record -------------------------------------------------------------------------------------


def sequence_difficulty(code: str) -> str:
    """Proposed rule (design.md §2.3): easy = ≤8 messages and no block, medium = ≤14 messages and ≤1 block."""
    messages = len(parse_sequence(code).messages)
    blocks = len(BLOCK_RE.findall(code))
    if messages <= 8 and blocks == 0:
        return "easy"
    if messages <= 14 and blocks <= 1:
        return "medium"
    return "hard"


def build_record(
    record_id: str, candidate: Candidate, style: str, mermaid: str, description: str, note: str
) -> dict[str, Any]:
    if candidate.diagram_type == "flowchart":
        level = flowchart_difficulty(parse_flowchart(mermaid))
    else:
        level = sequence_difficulty(mermaid)
    return {
        "id": record_id,
        "split": "golden",
        "source": candidate.source,
        "source_ref": candidate.source_ref,
        "license": candidate.license,
        "diagram_type": candidate.diagram_type,
        "difficulty": level,
        "description": description,
        "description_style": style,
        "expected_mermaid": mermaid,
        "notes": f"{note}; structure equal to the source and mmdc render checked; not verified by a human",
    }


if __name__ == "__main__":
    main()
