# Design: Polish process description → Mermaid

Technical specification for the project. Items marked **[OPEN]** are not decided yet; the value given is the
proposed default. When a decision is made, update this file and the decision log at the end.

## 1. Task

- **Input:** a Polish description of a process (typically 2–15 sentences).
- **Output:** bare Mermaid code, nothing else.
- **In scope:** `flowchart` (any direction) and `sequenceDiagram`.
- **Out of scope inputs** (text that does not describe a process): the model must answer with the exact
  refusal string `BRAK_PROCESU`. **[OPEN]** exact string.
- **Model under test:** a small open model (~4B, optionally 9B) served through an OpenAI-compatible API (Ollama).
  Base model: `Qwen3-4B-Instruct-2507` (Ollama `qwen3:4b-instruct-2507-q8_0`, HF `Qwen/Qwen3-4B-Instruct-2507`).

## 2. Data

### 2.1 Splits

| Split | Size | Source | Use |
|---|---|---|---|
| train | 1,000–3,000 | local synthesis (§3) | training |
| val | 100–200 | held-out part of synthesis | checkpoint and hyperparameter selection, few-shot examples |
| golden | ~150 | public datasets + hand-written, all human-verified (§2.3) | final before/after numbers only |
| pilot | 22 | RonnieAllen `test` split, English, unverified (`uv run build-pilot`) | smoke test of the evaluation pipeline only; numbers are not reported (see below) |

The pilot descriptions are the original one-line prompts ("Create a flowchart for: password reset via email
link"). The model has to guess the steps and their names, so `node_f1` / `edge_f1` on the pilot measure guessing,
not description → diagram conversion. Only `mermaid_only`, `render_rate` and `type_acc` are meaningful on it.
Fix: see the status in §2.3.

The golden set never feeds training, validation or few-shot prompts. Train/val are deduplicated against it
(embedding cosine similarity of descriptions ≥ 0.9 → drop). **[OPEN]** threshold.

### 2.2 Record format (JSONL, all splits)

```json
{
  "id": "golden-flow-0001",
  "split": "golden",
  "source": "ronnieallen | mermaidseqbench | handwritten | synthetic",
  "source_ref": "original id or URL, null for handwritten",
  "license": "CC-BY-4.0 | Apache-2.0 | own",
  "diagram_type": "flowchart | sequenceDiagram | none",
  "difficulty": "easy | medium | hard",
  "description": "Polish description",
  "expected_mermaid": "flowchart TD\n    A[...] --> B[...]",
  "notes": "free text, e.g. what was fixed during verification"
}
```

Out-of-scope examples use `diagram_type: "none"` and `expected_mermaid: "BRAK_PROCESU"`.

### 2.3 Golden set sources

| Part | Source | Count | Processing |
|---|---|---|---|
| flowchart | `RonnieAllen/mermaid-flowchart-dataset` (CC-BY-4.0) | ~100 | prompts there are underspecified, so regenerate a step-by-step description from the diagram; translate description and labels to Polish; human check |
| sequenceDiagram | `ibm-research/MermaidSeqBench` (Apache-2.0) | ~30 | one variant per scenario (the set is ~30 scenarios augmented ~4×); translate; human check |
| handwritten | team | 20–30 | written "in user words", includes ~5 out-of-scope texts |

**Status: not built yet — open task.** Needs a script that generates the step-by-step Polish descriptions and
translated labels with a local model, an `mmdc` check of every diagram, and a human pass over every record.
Until then the evaluation pipeline runs on the English pilot (§2.1).

Description generator: `uv run describe` (`data/describe.py`, prompt `prompts/describe.txt`), output language
as a parameter, temperature 0. For each record it prints the share of node labels found verbatim in the
description, as a hint for which descriptions to read first. Plan: run it in English on the pilot first,
replacing its one-line prompts, so that F1 on the pilot becomes meaningful; then use it for the Polish golden
descriptions. Label translation for golden is not implemented yet. **[OPEN]** generator model (default
`qwen3:30b-a3b` without thinking).

Difficulty (flowchart, as implemented in `data/pilot.py`): `easy` ≤ 6 nodes and no decision; `medium`
≤ 12 nodes and ≤ 2 decisions; `hard` otherwise. **[OPEN]** thresholds; whether loops, parallel paths and
subgraphs also make a diagram `hard` (not implemented); the rule for sequence diagrams.

Rejected: `Celiadraw/text-to-mermaid` (LLM-generated, contains diagrams that do not render).

## 3. Synthesis pipeline (train/val)

Generator: a local open model (~30B) whose license allows training on its outputs. **[OPEN]** model choice.

1. **Topics:** grid of domain × scenario × complexity parameters (node count range, decisions, loop yes/no,
   parallel paths yes/no, diagram type).
2. **Diagram:** generator writes Mermaid with Polish labels matching the parameters.
3. **Filters (all must pass):** renders with `mmdc`; parser succeeds (§4.2); node and decision counts within the
   requested range; no empty labels; every node connected; not a duplicate.
4. **Description:** generator writes a Polish description of the finished diagram in a randomly chosen style
   (formal, casual, chaotic, bullet points, short, long).
5. **Coverage check:** each node label must have a description sentence with embedding cosine similarity ≥ τ_cov,
   otherwise drop. **[OPEN]** τ_cov = 0.6.

Every generated record keeps the generator model name and the generation parameters in `notes`.

## 4. Evaluation

### 4.1 Prompting

- Same system prompt for every model and stage (stored in `prompts/system.txt`).
- `zero-shot`: system prompt + description.
- `few-shot`: system prompt + k = 3 fixed examples taken from `val` (never golden) + description.
- Temperature 0, seed 0, fixed max tokens. **[OPEN]** max tokens = 1024.

### 4.2 Per-example pipeline

1. **Normalize output:** trim whitespace; if wrapped in ```` ``` ```` / ```` ```mermaid ```` fences, strip them and set
   `fenced = true`; text around the fences or before the diagram header sets `extra_text = true`. Text after an
   unfenced diagram is not detected here; it makes rendering fail instead.
2. **Render:** `mmdc` on the normalized code → `renders: bool`.
3. **Parse** to a graph:
   - flowchart: nodes = (id, label, shape), edges = (src, dst, label).
   - sequenceDiagram: nodes = participants (id, display name); edges = messages (from, to, text), in order.
   - Parser: own Python parser for the supported subset (`src/<package>/eval/`). Unknown lines are skipped and
     reported as warnings instead of failing the parse; parsing fails only when the header is missing or wrong.
     Validity is still decided by `mmdc` (step 2).
   - **Status:** flowchart parser implemented; checked once against what Mermaid itself draws, on the
     flowchart examples from the Mermaid docs. sequenceDiagram parser not implemented yet.
4. **Match nodes** between prediction and reference:
   - exact match after normalization (lowercase, strip punctuation and whitespace) first;
   - remaining labels: embedding cosine similarity matrix (bge-m3), one-to-one assignment with the Hungarian
     algorithm (`scipy.optimize.linear_sum_assignment`), keep pairs with similarity ≥ τ. **[OPEN]** τ = 0.7
     (preliminary, see status); to be calibrated on ~20 manually judged examples in E1.
   - **Status:** implemented (`--matching embedding`, the default; `--matching exact` skips the embedding step).
     Embeddings come from the same OpenAI-compatible server (`bge-m3:latest` in Ollama). Every assigned pair is
     saved with its similarity in the run file (`score.node_pairs`), also below τ, so τ can be calibrated
     without rerunning the model.
   - **τ = 0.7, preliminary** (2026-11-13, base model on the two pilots, pairs read by hand). Polish: all pairs
     ≥ 0.8 were correct, about 45 correct pairs fell in 0.70–0.80 (`Zapisujemy miniatury` / `Zapisz miniatury`
     0.797, `Kończymy` / `Koniec` 0.751), wrong pairs started at 0.677 (`End` / `Start`); two correct pairs were
     below 0.70. Node / edge F1 at τ = 0.8, 0.75, 0.7, 0.65: PL 0.64 / 0.44, 0.76 / 0.60, 0.87 / 0.75, 0.89 / 0.77;
     EN 0.90 / 0.84, 0.91 / 0.84, 0.91 / 0.85, 0.92 / 0.85. Chosen on the same 22 records it was judged on, with
     descriptions not written by users: repeat on the golden set.
5. **Score.**

### 4.3 Metrics

| Metric | Definition |
|---|---|
| `render_rate` | share of outputs with `renders = true` |
| `mermaid_only` | share of outputs with `fenced = false` and `extra_text = false` |
| `type_acc` | predicted diagram type equals reference type |
| `node_f1` | P = matched / predicted nodes, R = matched / reference nodes, F1 = 2PR / (P + R) |
| `edge_f1` | a predicted edge counts if (match(src), match(dst)) is a reference edge; P, R, F1 as above; edge labels ignored |
| `shape_acc` | share of matched nodes whose shape equals the reference shape (e.g. decision drawn as a rhombus); examples with no matched node are left out of the average |
| `refusal_acc` | out-of-scope examples only: output equals the refusal string |
| `judge_score` | optional: LLM judge, rubric 1–5 for logic, completeness, extra elements |

- Output that does not render or does not parse gets `node_f1 = edge_f1 = 0`. Also report F1 averaged over
  rendering outputs only.
- Aggregation: macro average over examples, reported overall and per `diagram_type` and `difficulty`.
- **[OPEN]** sequence diagrams: whether message order and `alt`/`loop` blocks count in v1 (default: no).
- **Status:** implemented for flowcharts: `render_rate`, `mermaid_only`, `type_acc`, `node_f1`, `edge_f1`, `shape_acc`.
  Not yet: scoring sequence diagrams, `refusal_acc`, `judge_score`.

### 4.4 Run record

Each run (`uv run evaluate --model <name> --data <jsonl>`) writes
`results/<date>_<time>_<model>_<setting>_<data>_<matching>.json` with: model name and Ollama digest, setting
(zero-shot / few-shot / fine-tuned checkpoint), system prompt text and hash, temperature, seed, max tokens,
data file hash, matching method, embedding model and digest, τ, mmdc version, git commit, per-example results (raw output, render error,
scores) and aggregated metrics. Few-shot is not implemented until `val` exists.

## 5. Training

- Format: chat JSONL, `{"messages": [{"role": "system"}, {"role": "user"}, {"role": "assistant"}]}`,
  assistant content = `expected_mermaid`.
- Loss on assistant tokens only.
- LoRA defaults: rank 16, alpha 32, dropout 0.05, target attention and MLP projections, lr 2e-4,
  1–3 epochs, max length 2048. **[OPEN]** all values.
- Backends: MLX (`mlx-lm`) on Apple Silicon, PEFT/Unsloth on NVIDIA. Same data files and config for both.
- Checkpoint selection: best `node_f1` on `val`, not lowest val loss.
- Export: merge adapter, convert to GGUF, register in Ollama, evaluate with the same script as the base model.

## 6. Planned experiments

- E1: base model zero-shot and few-shot; large model as upper bound.
- E2: fine-tuned model; data size 500 / 1,000 / 3,000; data source ablations.
- E3: self-repair loop — on render failure the model gets the `mmdc` error and retries (max 3); compare with E2.

## 7. Decision log

| Date | Decision | Reason |
|---|---|---|
| 2026-11-10 | Synthesis is the main training source; GitHub mining optional | GitHub diagrams are mostly architecture, heavy filtering needed |
| 2026-11-10 | Golden set from RonnieAllen + MermaidSeqBench + handwritten | Different source than training data, permissive licenses |
| 2026-11-10 | Celiadraw dataset rejected | Contains non-rendering diagrams |
| 2026-11-11 | Base model Qwen3-4B-Instruct-2507, q8_0 in Ollama | Apache-2.0; instruct (non-thinking) variant outputs code directly — plain `qwen3:4b` in Ollama is the thinking variant; same weights on HF for MLX/PEFT; q8_0 is close to the weights we fine-tune, and the fine-tuned model is exported with the same quantization |
| 2026-11-11 | English pilot from RonnieAllen `test` before the Polish golden set | Run the pipeline end to end now; Polish descriptions are an open task |
| 2026-11-11 | Own Python parser for flowchart / sequenceDiagram instead of Mermaid's JS parser | Small subset, no Node dependency in eval, easy to test; existing Python wrappers (`mermaid-parser-py`) are immature and rely on a deprecated Mermaid API |
| 2026-11-13 | Node matching with embeddings is the default in `evaluate` | On the Polish pilot exact matching gave node F1 0.10 for structurally correct diagrams: Polish inflection changes almost every label |
| 2026-11-13 | τ = 0.7 for embedding matching (preliminary) | At 0.8 about 45 correct Polish pairs were rejected; wrong pairs start at 0.677 |
| 2026-11-13 | Added `shape_acc` | Embedding matching forgives a decision drawn as a rectangle, a frequent base-model error that F1 does not see |
