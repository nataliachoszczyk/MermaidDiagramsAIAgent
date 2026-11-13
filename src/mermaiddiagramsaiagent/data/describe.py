"""Generate step-by-step process descriptions from the reference diagrams (design.md §2.3).

    uv run describe --data data/pilot/pilot_en.jsonl --model qwen3:30b-a3b --language English --no-think

Writes a copy of the input with `description` replaced, by default to `<input stem>_described.jsonl` next to
the input. The generator model and prompt hash go into `notes`. Every description still needs a human read.
"""

import argparse
import hashlib
import re
from pathlib import Path
from statistics import mean
from typing import Any

from openai import OpenAI

from mermaiddiagramsaiagent.data.jsonl import read_jsonl, write_jsonl
from mermaiddiagramsaiagent.eval.flowchart import parse_flowchart
from mermaiddiagramsaiagent.eval.metrics import normalize_label
from mermaiddiagramsaiagent.llm import check_model_available, make_client

PROMPT_PATH = Path("prompts/describe.txt")
THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
TEMPERATURE = 0.0
SEED = 0
DEFAULT_MAX_TOKENS = 4096


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, required=True, help="JSONL in the design.md §2.2 format")
    parser.add_argument("--model", required=True, help="generator model as the server knows it")
    parser.add_argument("--language", required=True, help="language of the descriptions, e.g. English, Polish")
    parser.add_argument("--out", type=Path, help="output JSONL (default: <input stem>_described.jsonl)")
    parser.add_argument("--no-think", action="store_true", help="append /no_think (Qwen3 hybrid models)")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--limit", type=int, help="only the first N records (for quick checks)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = make_client()
    check_model_available(client, args.model)
    template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt_hash = hashlib.sha256(template.encode("utf-8")).hexdigest()[:12]
    system_prompt = template.replace("{language}", args.language)
    records = read_jsonl(args.data)[: args.limit]
    out = args.out or args.data.with_name(f"{args.data.stem}_described.jsonl")

    described, coverages, truncated = [], [], []
    for i, record in enumerate(records, start=1):
        diagram = record["expected_mermaid"]
        description = describe(client, args.model, system_prompt, diagram, args.max_tokens, args.no_think)
        if description is None:
            truncated.append(record["id"])
            print(f"[{i:>3}/{len(records)}] {record['id']:<18} TRUNCATED at {args.max_tokens} tokens, skipped")
            continue
        coverage = label_coverage(diagram, description)
        coverages.append(coverage)
        notes = f"description generated from expected_mermaid by {args.model} (prompt {prompt_hash}); not verified"
        described.append({**record, "description": description, "notes": notes})
        write_jsonl(out, described)  # after every record, so an interrupted run keeps its progress
        print(f"[{i:>3}/{len(records)}] {record['id']:<18} labels_verbatim={coverage:.2f}  {description[:70]}...")

    if coverages:
        print(f"\nMean share of labels found verbatim: {mean(coverages):.2f}")
    print(f"Wrote {len(described)} of {len(records)} records to {out}; read every description before using it")
    if truncated:
        print(f"Skipped (truncated output): {', '.join(truncated)}")


def describe(
    client: OpenAI, model: str, system_prompt: str, diagram: str, max_tokens: int, no_think: bool
) -> str | None:
    """The description, or None if the model ran out of tokens before finishing it."""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": diagram + ("\n/no_think" if no_think else "")},
        ],
        temperature=TEMPERATURE,
        seed=SEED,
        max_tokens=max_tokens,
    )
    choice = response.choices[0]
    if choice.finish_reason == "length":
        return None
    return strip_thinking(choice.message.content or "")


def strip_thinking(text: str) -> str:
    """Drop `<think>...</think>` blocks that some servers leave in the content of reasoning models."""
    return THINK_RE.sub("", text).strip()


def label_coverage(diagram: str, description: str) -> float:
    """Share of node labels whose normalized text appears in the normalized description.

    A rough check only: paraphrased labels count as missing. Low values point to descriptions worth reading first.
    """
    labels = {normalize_label(node.label) for node in parse_flowchart(diagram).nodes.values()}
    labels.discard("")
    if not labels:
        return 1.0
    text = f" {normalize_label(description)} "
    return sum(f" {label} " in text for label in labels) / len(labels)


if __name__ == "__main__":
    main()
