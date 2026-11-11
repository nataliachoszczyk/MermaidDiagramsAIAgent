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

## 2. Data

### 2.1 Splits

| Split | Size | Source | Use |
|---|---|---|---|
| train | 1,000–3,000 | local synthesis (§3) | training |
| val | 100–200 | held-out part of synthesis | checkpoint and hyperparameter selection, few-shot examples |
| golden | ~150 | public datasets + hand-written, all human-verified (§2.3) | final before/after numbers only |

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

Difficulty: `easy` ≤ 6 nodes and no decision; `medium` 7–12 nodes or 1–2 decisions; `hard` otherwise
(loops, parallel paths, subgraphs, sequence diagrams with `alt`/`loop`). **[OPEN]** thresholds.

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
- Temperature 0, fixed max tokens. **[OPEN]** max tokens = 1024.

### 4.2 Per-example pipeline

1. **Normalize output:** trim whitespace; if wrapped in ```` ``` ```` / ```` ```mermaid ```` fences, strip them and set
   `fenced = true`; any other non-Mermaid text sets `extra_text = true`.
2. **Render:** `mmdc` on the normalized code → `renders: bool`.
3. **Parse** to a graph:
   - flowchart: nodes = (id, label, shape), edges = (src, dst, label).
   - sequenceDiagram: nodes = participants (id, display name); edges = messages (from, to, text), in order.
   - Parser: own Python parser for the supported subset (`src/<package>/eval/`). Unknown lines are skipped and
     reported as warnings instead of failing the parse; parsing fails only when the header is missing or wrong.
     Validity is still decided by `mmdc` (step 2).
4. **Match nodes** between prediction and reference:
   - exact match after normalization (lowercase, strip punctuation and whitespace) first;
   - remaining labels: embedding cosine similarity matrix (bge-m3), one-to-one assignment with the Hungarian
     algorithm (`scipy.optimize.linear_sum_assignment`), keep pairs with similarity ≥ τ. **[OPEN]** τ = 0.8,
     calibrated on ~20 manually judged examples in E1.
5. **Score.**

### 4.3 Metrics

| Metric | Definition |
|---|---|
| `render_rate` | share of outputs with `renders = true` |
| `mermaid_only` | share of outputs with `fenced = false` and `extra_text = false` |
| `type_acc` | predicted diagram type equals reference type |
| `node_f1` | P = matched / predicted nodes, R = matched / reference nodes, F1 = 2PR / (P + R) |
| `edge_f1` | a predicted edge counts if (match(src), match(dst)) is a reference edge; P, R, F1 as above; edge labels ignored |
| `refusal_acc` | out-of-scope examples only: output equals the refusal string |
| `judge_score` | optional: LLM judge, rubric 1–5 for logic, completeness, extra elements |

- Output that does not render or does not parse gets `node_f1 = edge_f1 = 0`. Also report F1 averaged over
  rendering outputs only.
- Aggregation: macro average over examples, reported overall and per `diagram_type` and `difficulty`.
- **[OPEN]** sequence diagrams: whether message order and `alt`/`loop` blocks count in v1 (default: no).

### 4.4 Run record

Each run writes `results/<date>_<model>_<setting>.json` with: model name and version/hash, setting
(zero-shot / few-shot / fine-tuned checkpoint), system prompt hash, τ, golden set hash, per-example results,
aggregated metrics.

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
| 2026-11-11 | Own Python parser for flowchart / sequenceDiagram instead of Mermaid's JS parser | Small subset, no Node dependency in eval, easy to test; existing Python wrappers (`mermaid-parser-py`) are immature and rely on a deprecated Mermaid API |
