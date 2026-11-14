# Polish process description → Mermaid diagram (LoRA fine-tuning)

Semester project for the LLM engineering course. We fine-tune a small open model (~4B, optionally 9B) with LoRA
so that it turns a Polish description of a process into valid Mermaid code (`flowchart`, `sequenceDiagram`).
Improvement is measured against the same base model with zero-shot and few-shot prompting.

Specification (data formats, metrics, training setup, open decisions): `docs/design.md`. Read it before
changing data, evaluation or training code, and update it when a decision changes.

## Repository layout
Package: `src/mermaiddiagramsaiagent/`. Items marked *(planned)* do not exist yet.
- `data/raw/` – public source datasets, downloaded at pinned revisions (gitignored)
- `data/pilot/` – English smoke-test set from the RonnieAllen `test` split. Descriptions are one-line prompts, so
  node/edge F1 on it is meaningless (only `mermaid_only`, `render_rate`, `type_acc` are); not for reported numbers
- `data/golden/` – test set, JSONL in the `docs/design.md` §2.2 format *(planned)*
- `data/synthetic/` – generated training and validation data *(planned)*
- `prompts/system.txt` – system prompt shared by every model and stage
- `prompts/describe.txt` – prompt for generating descriptions from diagrams (`uv run describe`)
- `prompts/golden.txt` – prompt for translating a source diagram and describing it (`uv run build-golden`)
- `src/mermaiddiagramsaiagent/data/` – dataset definitions (`sources.py`), download, raw-data report, pilot builder,
  golden builder, JSONL I/O
- `src/mermaiddiagramsaiagent/eval/` – output normalization, rendering (`mmdc`), flowchart parser, metrics, evaluation runner
- `src/mermaiddiagramsaiagent/synth/` – data synthesis: topics → diagram → filters → description → coverage check *(planned)*
- `src/mermaiddiagramsaiagent/train/` – LoRA training and export *(planned)*
- `tests/` – pytest; tests that need `data/raw/` are skipped when it has not been downloaded
- `results/` – one file per evaluation run, including the full config

## Setup (once)
- `uv sync`
- Mermaid CLI (`mmdc`) on `PATH`. If it fails with "Could not find chrome-headless-shell", install the browser
  with the Puppeteer bundled in mermaid-cli: run `node install.mjs` in
  `<mermaid-cli install dir>/node_modules/puppeteer`. `report-raw` and `evaluate` check `mmdc` before running.
- Copy `.env.example` to `.env` (inference server URL; the API key is a dummy for Ollama).
- Base model: `ollama pull qwen3:4b-instruct-2507-q8_0`
- Embedding model for node matching in `evaluate`: `ollama pull bge-m3`

## Commands
- Run anything: `uv run <command>` (entry points defined in `pyproject.toml`)
- `uv run download-raw` – download the raw datasets into `data/raw/`
- `uv run report-raw` – record counts, fields, diagram types and `mmdc` render check → `data/raw/report.json`
- `uv run build-pilot` – build `data/pilot/pilot_en.jsonl`
- `uv run describe --data <jsonl> --model <name> --language <lang> [--no-think]` – replace descriptions with
  step-by-step ones generated from `expected_mermaid` → `<stem>_described.jsonl`; read every one afterwards
- `uv run build-golden --model <name> [--kaggle-proxy] [--flowcharts N] [--sequences N] [--out <jsonl>]` – generated
  part of the golden set: Polish texts and a description for chosen source diagrams, structure and `mmdc` checked;
  keeps records already in the output file; read every record afterwards. `--kaggle-proxy`: see `KAGGLE.md` §9
- `uv run evaluate --model <name> --data <jsonl> [--limit N] [--matching exact]` – evaluate a model, save the run
  to `results/`; nodes are matched by label embeddings unless `--matching exact`
- `uv run pytest` – tests
- Render a single diagram: `mmdc -i diagram.mmd -o out.svg`

## Rules
- **The golden set never goes into training or validation data.** Synthetic data is deduplicated against it.
- **Never change expected outputs in the golden set to match model output.** Fix an entry only if the reference
  itself is wrong, and explain why in the commit message.
- Evaluation always runs at temperature 0; every result is saved with model name/version, prompt and date.
- Change one thing at a time when comparing runs; all stages use the same golden set.
- Every diagram (reference or training example) must render with `mmdc`.
- Training data is generated with a local open model whose license allows training on its outputs.
- No personal data anywhere in the data.

## Code conventions
- Python, managed with `uv`. Type hints, small functions, tests for the metric code.
- **Platform-agnostic:** must run on macOS, Linux and Windows. Use `pathlib`, no shell-specific scripts
  (entry points via `pyproject.toml` instead of Makefiles or bash), no hard-coded paths.
- Inference goes through the OpenAI-compatible API (Ollama locally, `base_url` from `.env`), never a vendor-specific SDK in core code.
- Training backend is selectable in config: MLX (`mlx-lm`) on Apple Silicon, PEFT/Unsloth on NVIDIA GPUs (e.g. Colab).
  Shared code (data loading, formatting, evaluation) must not depend on either backend.
- Code, comments and docs in English; data content (descriptions, diagram labels) in Polish. The only exception
  is the English pilot in `data/pilot/`.

## Mermaid conventions
- Model output must be bare Mermaid code. If it arrives wrapped in ```mermaid fences, strip them and record it
  in the "Mermaid only" metric.
- Keywords are lowercase (`flowchart`, `class`); labels with special characters go in double quotes;
  never use `end` as a node id.
