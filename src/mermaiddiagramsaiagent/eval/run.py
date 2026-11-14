"""Evaluate a model on an evaluation set (JSONL in the design.md §2.2 format) and save one result file.

    uv run evaluate --model qwen3:4b-instruct-2507-q8_0 --data data/pilot/pilot_en.jsonl
    uv run evaluate --model qwen3:4b-instruct-2507-q8_0 --data data/golden/golden.jsonl \
        --setting few-shot --shots data/shots/shots_pl.jsonl

Inference goes through the OpenAI-compatible API; the server is configured in .env (see .env.example).
"""

import argparse
import hashlib
import json
import random
import re
import subprocess
import tempfile
import time
import urllib.request
from collections.abc import Iterable
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from openai import OpenAI

from mermaiddiagramsaiagent.data.jsonl import read_jsonl
from mermaiddiagramsaiagent.eval.metrics import DEFAULT_THRESHOLD, Embedder, score_example
from mermaiddiagramsaiagent.eval.output import is_refusal, normalize_output
from mermaiddiagramsaiagent.eval.render import RenderResult, check_mmdc_works, mmdc_version, render
from mermaiddiagramsaiagent.llm import check_model_available, make_client

SYSTEM_PROMPT_PATH = Path("prompts/system.txt")
GOLDEN_PATH = Path("data/golden/golden.jsonl")
RESULTS_DIR = Path("results")
TEMPERATURE = 0.0
SEED = 0
DEFAULT_MAX_TOKENS = 1024
DEFAULT_EMBEDDING_MODEL = "bge-m3:latest"
NO_THINK_BODY = {"reasoning_effort": "none"}  # Ollama: turns thinking off for models where it is on/off
GROUP_KEYS = ("diagram_type", "difficulty", "description_style")
DEFAULT_K = 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True, help="model name as the server knows it")
    parser.add_argument("--data", type=Path, required=True, help="evaluation JSONL")
    parser.add_argument("--setting", default="zero-shot", choices=["zero-shot", "few-shot"])
    parser.add_argument("--shots", type=Path, help="few-shot examples (JSONL, §2.2 format); never golden records")
    parser.add_argument("--k", type=int, default=DEFAULT_K, help="number of few-shot examples (first k of --shots)")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--matching", default="embedding", choices=["embedding", "exact"], help="node matching")
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL, help="used with --matching embedding")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="min cosine similarity for a match")
    parser.add_argument("--limit", type=int, help="only the first N examples (for quick checks)")
    parser.add_argument("--sample", type=int, help="only N examples, drawn from every diagram type (for quick checks)")
    parser.add_argument("--no-think", action="store_true", help="turn thinking off (hybrid models, e.g. qwen3:1.7b)")
    parser.add_argument("--ids", help="only the records with these ids, comma-separated (to repeat a quick check)")
    args = parser.parse_args()
    if (args.setting == "few-shot") != (args.shots is not None):
        parser.error("--shots is required with --setting few-shot and only allowed with it")
    return args


def select_records(records: list[dict[str, Any]], ids: list[str]) -> list[dict[str, Any]]:
    """The records with the given ids, in file order; an id that is not in the data is an error."""
    unknown = sorted(set(ids) - {record["id"] for record in records})
    if unknown:
        raise SystemExit(f"ids not in the data: {', '.join(unknown)}")
    return [record for record in records if record["id"] in ids]


def sample_records(records: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    """`n` records in file order: every diagram type gets a share in proportion to its size, but at least one
    record, drawn with a fixed seed. The first N records of the golden set are all flowcharts."""
    if n >= len(records):
        return records
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        groups.setdefault(record["diagram_type"], []).append(record)
    quotas = {name: max(1, round(n * len(group) / len(records))) for name, group in groups.items()}
    largest = max(groups, key=lambda name: len(groups[name]))
    quotas[largest] = max(0, quotas[largest] + n - sum(quotas.values()))  # rounding must not change the total
    rng = random.Random(SEED)
    chosen = {record["id"] for name, group in groups.items() for record in rng.sample(group, quotas[name])}
    return [record for record in records if record["id"] in chosen]


def main() -> None:
    args = parse_args()
    client = make_client()
    check_model_available(client, args.model)
    embed = None
    if args.matching == "embedding":
        check_model_available(client, args.embedding_model)
        embed = make_embedder(client, args.embedding_model)
    check_mmdc_works()
    system_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    all_records = read_jsonl(args.data)
    shots = load_shots(args.shots, args.k, all_records + golden_records()) if args.shots else []
    records = all_records[: args.limit]
    if args.sample:
        records = sample_records(records, args.sample)
    if args.ids:
        records = select_records(records, args.ids.split(","))

    examples = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, record in enumerate(records, start=1):
            example = evaluate_record(
                client, args.model, system_prompt, args.max_tokens, record, Path(tmp), embed, args.threshold,
                args.no_think, shots,
            )
            examples.append(example)
            print_progress(i, len(records), example)

    result = {
        "config": run_config(args, client, system_prompt, shots),
        "summary": summarize(examples),
        "examples": examples,
    }
    path = save_result(result, args)
    print_summary(result["summary"])
    print(f"\nSaved to {path}")


def golden_records() -> list[dict[str, Any]]:
    return read_jsonl(GOLDEN_PATH) if GOLDEN_PATH.exists() else []


def load_shots(path: Path, k: int, forbidden: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """First k records of the shots file. Refuses a shot that shares its diagram, description or source record
    with a forbidden record (the evaluation data and the golden set: design.md §2.1)."""
    shots = read_jsonl(path)
    if len(shots) < k:
        raise SystemExit(f"{path} has {len(shots)} examples, --k is {k}")
    shots = shots[:k]
    leaked = [shot["id"] for shot in shots if any(shares_source(shot, record) for record in forbidden)]
    if leaked:
        raise SystemExit(f"few-shot examples overlap the evaluation data or the golden set: {', '.join(leaked)}")
    return shots


def shares_source(shot: dict[str, Any], record: dict[str, Any]) -> bool:
    same_ref = shot.get("source_ref") is not None and shot.get("source_ref") == record.get("source_ref")
    same_text = any(shot[key].strip() == record[key].strip() for key in ("expected_mermaid", "description"))
    return same_ref or same_text


def build_messages(system_prompt: str, shots: list[dict[str, Any]], description: str) -> list[dict[str, str]]:
    """System prompt, each shot as a user/assistant turn (design.md §4.1), then the description."""
    messages = [{"role": "system", "content": system_prompt}]
    for shot in shots:
        messages.append({"role": "user", "content": shot["description"]})
        messages.append({"role": "assistant", "content": shot["expected_mermaid"]})
    messages.append({"role": "user", "content": description})
    return messages


def make_embedder(client: OpenAI, model: str) -> Embedder:
    """Texts -> vectors through the embeddings endpoint; each distinct text is embedded once per run."""
    cache: dict[str, list[float]] = {}

    def embed(texts: list[str]) -> list[list[float]]:
        missing = [text for text in dict.fromkeys(texts) if text not in cache]
        if missing:
            response = client.embeddings.create(model=model, input=missing, encoding_format="float")
            cache.update(zip(missing, (item.embedding for item in response.data)))
        return [cache[text] for text in texts]

    return embed


def evaluate_record(
    client: OpenAI,
    model: str,
    system_prompt: str,
    max_tokens: int,
    record: dict[str, Any],
    work_dir: Path,
    embed: Embedder | None,
    threshold: float,
    no_think: bool = False,
    shots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    response = client.chat.completions.create(
        model=model,
        messages=build_messages(system_prompt, shots or [], record["description"]),
        temperature=TEMPERATURE,
        seed=SEED,
        max_tokens=max_tokens,
        extra_body=NO_THINK_BODY if no_think else None,
    )
    latency_s = time.perf_counter() - started
    choice = response.choices[0]
    raw_output = choice.message.content or ""
    output = normalize_output(raw_output)
    if is_refusal(record["expected_mermaid"]) or is_refusal(output.code):
        rendered = RenderResult(False, "")  # a refusal is not a diagram: nothing to render
    else:
        rendered = render(output.code, work_dir, record["id"])
    score = score_example(output, rendered.ok, record["expected_mermaid"], embed, threshold)
    return {
        "id": record["id"],
        "diagram_type": record["diagram_type"],
        "difficulty": record.get("difficulty"),
        "description_style": record.get("description_style"),
        "description": record["description"],
        "expected_mermaid": record["expected_mermaid"],
        "raw_output": raw_output,
        "reasoning_chars": len(getattr(choice.message, "reasoning", None) or ""),  # 0 when the model did not think
        "code": output.code,
        "finish_reason": choice.finish_reason,
        "completion_tokens": response.usage.completion_tokens if response.usage else None,
        "latency_s": round(latency_s, 2),
        "render_error": rendered.error,
        "score": asdict(score),
    }


def summarize(examples: list[dict[str, Any]]) -> dict[str, Any]:
    """Macro averages overall and per diagram type, difficulty and description style (design.md §4.3).

    An example without a value for a key (e.g. no `description_style` in the pilot) is left out of that grouping.
    """
    summary: dict[str, Any] = {"overall": aggregate(examples)}
    for key in GROUP_KEYS:
        groups: dict[str, list[dict[str, Any]]] = {}
        for example in examples:
            if example.get(key) is not None:
                groups.setdefault(example[key], []).append(example)
        summary[f"by_{key}"] = {name: aggregate(group) for name, group in sorted(groups.items())}
    return summary


def aggregate(examples: list[dict[str, Any]]) -> dict[str, Any]:
    """Diagram metrics are averaged over examples with a diagram reference, `refusal_acc` over the others."""
    scores = [example["score"] for example in examples]
    diagrams = [s for s in scores if s["refusal_ok"] is None]
    refusals = [s["refusal_ok"] for s in scores if s["refusal_ok"] is not None]
    rendering = [s for s in diagrams if s["renders"]]
    return {
        "n": len(scores),
        "n_refusal": len(refusals),
        "mermaid_only": mean_or_none(s["mermaid_only"] for s in diagrams),
        "render_rate": mean_or_none(s["renders"] for s in diagrams),
        "type_acc": mean_or_none(s["type_ok"] for s in diagrams),
        "node_f1": mean_or_none(s["node"]["f1"] for s in diagrams),
        "edge_f1": mean_or_none(s["edge"]["f1"] for s in diagrams),
        "shape_acc": mean_or_none(s["shape_acc"] for s in diagrams if s["shape_acc"] is not None),
        "node_f1_rendering_only": mean_or_none(s["node"]["f1"] for s in rendering),
        "edge_f1_rendering_only": mean_or_none(s["edge"]["f1"] for s in rendering),
        "refusal_acc": mean_or_none(refusals),
        "truncated": sum(example["finish_reason"] == "length" for example in examples),
    }


def mean_or_none(values: Iterable[float]) -> float | None:
    items = list(values)
    return mean(items) if items else None


def run_config(
    args: argparse.Namespace, client: OpenAI, system_prompt: str, shots: list[dict[str, Any]]
) -> dict[str, Any]:
    embedding = args.matching == "embedding"
    return {
        "date": datetime.now().isoformat(timespec="seconds"),
        "model": args.model,
        "model_digest": ollama_digest(str(client.base_url), args.model),
        "setting": args.setting,
        "shots": args.shots.as_posix() if args.shots else None,
        "shots_sha256": sha256(args.shots.read_bytes()) if args.shots else None,
        "shot_ids": [shot["id"] for shot in shots],
        "base_url": str(client.base_url),
        "temperature": TEMPERATURE,
        "seed": SEED,
        "max_tokens": args.max_tokens,
        "no_think": args.no_think,
        "limit": args.limit,
        "sample": args.sample,
        "ids": args.ids,
        "system_prompt": system_prompt,
        "system_prompt_sha256": sha256(system_prompt.encode("utf-8")),
        "data": args.data.as_posix(),
        "data_sha256": sha256(args.data.read_bytes()),
        "matching": args.matching,
        "embedding_model": args.embedding_model if embedding else None,
        "embedding_model_digest": ollama_digest(str(client.base_url), args.embedding_model) if embedding else None,
        "threshold": args.threshold if embedding else None,
        "mmdc": mmdc_version(),
        "git_commit": git_commit(),
    }


def ollama_digest(base_url: str, model: str) -> str | None:
    """Model digest from Ollama's native API, if the server is Ollama; None for other servers."""
    url = base_url.rstrip("/").removesuffix("/v1") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            tags = json.load(response)
        return next((m["digest"] for m in tags.get("models", []) if m["name"] == model), None)
    except (OSError, ValueError, KeyError, AttributeError):
        return None


def git_commit() -> str | None:
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
        return proc.stdout.strip() + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return None


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_result(result: dict[str, Any], args: argparse.Namespace) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    model = re.sub(r"[^\w.-]+", "-", args.model)
    path = RESULTS_DIR / f"{stamp}_{model}_{args.setting}_{args.data.stem}_{args.matching}.json"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def print_progress(i: int, total: int, example: dict[str, Any]) -> None:
    s = example["score"]
    flags = "".join(flag for flag, on in (("F", s["fenced"]), ("T", s["extra_text"])) if on) or "-"
    if s["refusal_ok"] is not None:
        result = f"refusal={'ok ' if s['refusal_ok'] else 'NO '}"
    else:
        result = f"render={'ok ' if s['renders'] else 'ERR'} node_f1={s['node']['f1']:.2f} edge_f1={s['edge']['f1']:.2f}"
    print(f"[{i:>3}/{total}] {example['id']:<18} {result} flags={flags} {example['latency_s']}s")


def print_summary(summary: dict[str, Any]) -> None:
    print("\n" + format_row("group", None))
    print(format_row("overall", summary["overall"]))
    for key in GROUP_KEYS:
        for name, values in summary[f"by_{key}"].items():
            print(format_row(f"  {name}", values))


def format_row(name: str, values: dict[str, Any] | None) -> str:
    columns = ("n", "mermaid_only", "render_rate", "type_acc", "node_f1", "edge_f1", "shape_acc", "refusal_acc")
    if values is None:
        return f"{name:<18}" + "".join(f"{c:>14}" for c in columns)
    return f"{name:<18}" + "".join(format_cell(column, values[column]) for column in columns)


def format_cell(column: str, value: float | None) -> str:
    if value is None:
        return f"{'-':>14}"
    return f"{value:>14}" if column == "n" else f"{value:>14.3f}"


if __name__ == "__main__":
    main()
