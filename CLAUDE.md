# Polish process description → Mermaid diagram (LoRA fine-tuning)

Semester project for the LLM engineering course. We fine-tune a small open model (~4B, optionally 9B) with LoRA
so that it turns a Polish description of a process into valid Mermaid code (`flowchart`, `sequenceDiagram`).
Improvement is measured against the same base model with zero-shot and few-shot prompting.

Specification (data formats, metrics, training setup, open decisions): `docs/design.md`. Read it before
changing data, evaluation or training code, and update it when a decision changes.

## Repository layout
<!-- TODO: update once the structure exists -->
- `data/golden/` – test set (JSONL: `id`, `source`, `description`, `expected_mermaid`, `diagram_type`, `difficulty`)
- `data/synthetic/` – generated training and validation data
- `src/<package>/eval/` – rendering (`mmdc`), Mermaid → graph parser, metrics (node/edge F1)
- `src/<package>/synth/` – data synthesis: topics → diagram → filters → description → coverage check
- `src/<package>/train/` – LoRA training and export
- `results/` – one file per evaluation run, including the full config

## Commands
<!-- TODO: fill in as entry points are added -->
- Setup: `uv sync`
- Run anything: `uv run <command>` (entry points defined in `pyproject.toml`)
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
- Code, comments and docs in English; data content (descriptions, diagram labels) in Polish.

## Mermaid conventions
- Model output must be bare Mermaid code. If it arrives wrapped in ```mermaid fences, strip them and record it
  in the "Mermaid only" metric.
- Keywords are lowercase (`flowchart`, `class`); labels with special characters go in double quotes;
  never use `end` as a node id.
