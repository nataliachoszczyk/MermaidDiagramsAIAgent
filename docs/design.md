# Design: Polish process description → Mermaid

Technical specification for the project. Items marked **[OPEN]** are not decided yet; the value given is the
proposed default. When a decision is made, update this file and the decision log at the end.

## 1. Task

- **Input:** a Polish description of a process (typically 2–15 sentences).
- **Output:** bare Mermaid code, nothing else.
- **In scope:** `flowchart` (any direction) and `sequenceDiagram`.
- **Out of scope inputs** (text that does not describe a process): the model must answer with the exact
  refusal string `BRAK_PROCESU` (confirmed by the team, 2026-11-13).
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
  "source": "ronnieallen | mermaidseqbench | handwritten | claude-drafted | synthetic",
  "source_ref": "original id or URL, null for handwritten and claude-drafted",
  "license": "CC-BY-4.0 | Apache-2.0 | own",
  "diagram_type": "flowchart | sequenceDiagram | none",
  "difficulty": "easy | medium | hard",
  "description": "Polish description",
  "description_style": "structured | natural | brief | null",
  "expected_mermaid": "flowchart TD\n    A[...] --> B[...]",
  "notes": "free text, e.g. what was fixed during verification"
}
```

Out-of-scope examples use `diagram_type: "none"`, `expected_mermaid: "BRAK_PROCESU"` and
`description_style: null`.

### 2.2.1 Description styles (golden)

Every golden record with a diagram has one description, written in one of three styles. The style is stored in
`description_style`, and the styles are spread evenly over the records (about a third each, within every
`diagram_type`).

| Style | What the description looks like |
|---|---|
| `structured` | Step by step, in the order of the diagram, with wording close to the labels. |
| `natural` | The way a user would say it: casual wording, steps in another order, digressions. |
| `brief` | Short, but every step and every branch can still be read from it. |

In every style the description must contain all steps and all branches of the reference diagram. A
description that only names the process ("draw the complaint process") is not allowed, because the model would
have to guess the steps (the problem of the English pilot, §2.1). Hand-written records (§2.3) use `natural`.
Records outside golden (pilot, train, val) may leave the field out; the styles of synthetic descriptions are
defined in §3.

### 2.3 Golden set sources

| Part | Source | Count | Processing |
|---|---|---|---|
| flowchart | `RonnieAllen/mermaid-flowchart-dataset` (CC-BY-4.0) | ~100 | prompts there are underspecified, so regenerate a step-by-step description from the diagram; translate description and labels to Polish; human check |
| sequenceDiagram | `ibm-research/MermaidSeqBench` (Apache-2.0) | ~30 | one variant per scenario (the set is ~30 scenarios augmented ~4×); translate; human check |
| handwritten | team | 20–30 | written "in user words", includes ~5 out-of-scope texts |
| claude-drafted | written by Claude without a source diagram | 16 | 11 easy records (7 flowcharts, 4 sequence diagrams), because the public sources have almost none: styles in turn; parse, difficulty rule and `mmdc` render checked. 5 out-of-scope texts (`golden-none-*`, `difficulty: null`). Human check |

**Status (2026-11-14): `data/golden/golden.jsonl` has 130 records: 114 generated with `uv run build-golden`
(`data/golden.py`, prompt `prompts/golden.txt`) and 16 `claude-drafted` (11 easy diagrams, 5 out-of-scope texts); none read by a human yet.** For each chosen source diagram one model call translates the texts
to Polish and writes the description in the style assigned to the record. The command then checks that the
translation has the structure of the source (same ids, shapes, edges; same participants and messages), that
texts were translated, and that the diagram renders with `mmdc`; a failed record is retried twice with the
problems named, then skipped. Every record still needs a human read. Hand-written records are added by the team.

Which source diagrams are used:

- RonnieAllen (174 diagrams outside the pilot): only **84 are usable** as references. The others have a logic
  defect: a decision with a single branch (71 diagrams), a labelled branch that leaves a plain step, not exactly
  one start and one end, or a shape that does not render. The 84 cover **41 topics** (the dataset has several
  diagrams per topic; some topics also occur in the pilot, with other diagrams). The command orders them so
  that the first 41 are one per topic. None of them is `easy`: 77 `medium`, 7 `hard`.
- MermaidSeqBench: the scenario and variant are the end of `nl_task_title` (`Read water meter 4/II`): 30
  scenarios, 2 to 32 variants each. The command takes the first variant of each scenario in which every
  participant sends or receives a message (3 of the 132 diagrams have an idle participant).

Generator model: a hosted model through the Kaggle Model Proxy (`KAGGLE.md` §9), `anthropic/claude-sonnet-5@default`
in the trial. The rule about a local open model applies to training data, not to the golden set. The model
rejects `temperature`, so a rerun gives different texts; the generated file is the record, not the command.

Description generator: `uv run describe` (`data/describe.py`, prompt `prompts/describe.txt`), output language
as a parameter, temperature 0. For each record it prints the share of node labels found verbatim in the
description, as a hint for which descriptions to read first. Plan: run it in English on the pilot first,
replacing its one-line prompts, so that F1 on the pilot becomes meaningful; then use it for the Polish golden
descriptions. Label translation for golden is not implemented yet. **[OPEN]** generator model (default
`qwen3:30b-a3b` without thinking).

Difficulty (flowchart, as implemented in `data/pilot.py`): `easy` ≤ 6 nodes and no decision; `medium`
≤ 12 nodes and ≤ 2 decisions; `hard` otherwise. Sequence diagram (as implemented in `data/golden.py`, proposed):
`easy` ≤ 8 messages and no block (`alt`, `loop`, `opt`, `par`, ...); `medium` ≤ 14 messages and ≤ 1 block;
`hard` otherwise (the 30 chosen diagrams: 1 easy, 22 medium, 7 hard). **[OPEN]** all thresholds; whether loops,
parallel paths and subgraphs also make a flowchart `hard` (not implemented).

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
     flowchart examples from the Mermaid docs. sequenceDiagram parser implemented (`eval/sequence.py`); checked
     once (2026-11-13, mermaid 12.3.0) against the participant labels and message texts that `mmdc` draws, on the
     38 sequence examples from the Mermaid docs and all 132 MermaidSeqBench diagrams. A participant named only in
     a note counts as a participant, as in Mermaid: `Note over User` after `participant U as User` adds a second
     lifeline. Notes, activations and blocks (`alt`, `loop`, ...) are skipped; messages inside blocks are kept.
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
| `edge_f1` | flowchart: a predicted edge counts if (match(src), match(dst)) is a reference edge; P, R, F1 as above; edge labels ignored. sequenceDiagram: see below |
| `shape_acc` | flowcharts only: share of matched nodes whose shape equals the reference shape (e.g. decision drawn as a rhombus); examples with no matched node are left out of the average |
| `refusal_acc` | out-of-scope examples only: output equals the refusal string (surrounding whitespace ignored; fences or any other text make it wrong) |
| `judge_score` | optional: LLM judge, rubric 1–5 for logic, completeness, extra elements |

- Output that does not render or does not parse gets `node_f1 = edge_f1 = 0`. Also report F1 averaged over
  rendering outputs only.
- Aggregation: macro average over examples, reported overall and per `diagram_type`, `difficulty` and
  `description_style` (§2.2.1). An example without a value for a grouping key is left out of that grouping.
- Out-of-scope examples (reference = refusal string) are not rendered or parsed and count only in `refusal_acc`;
  all other metrics are averaged over the examples with a diagram reference. A refusal given for a process
  description is a normal failure: it does not render, so `node_f1 = edge_f1 = 0`.
- Sequence diagrams: `node_f1` is computed on participants, matched by label as in §4.2 step 4. For `edge_f1`
  a predicted message counts if its sender and receiver are matched participants and its text matches the text
  of a reference message between the same two participants in the same direction (exact after normalization,
  then embeddings with the same τ, one-to-one). Every message counts once, so P = matched / predicted messages
  and R = matched / reference messages. The text is part of the match because (sender, receiver) pairs alone
  barely tell diagrams apart: with 3–4 participants almost every diagram has the same pairs. The arrow type is
  not scored. Message pairs are saved with their similarity in `score.message_pairs`.
- **[OPEN]** sequence diagrams: whether message order and `alt`/`loop` blocks count in v1 (default: no, and
  not implemented).
- **Status:** implemented: `render_rate`, `mermaid_only`, `type_acc`, `node_f1`, `edge_f1` for flowcharts and
  sequence diagrams, `shape_acc`, `refusal_acc`; grouping per `description_style`. Not yet: `judge_score`.
  Sequence scoring is tested with unit tests only; τ = 0.7 was never checked on message texts (no model run yet).

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
| 2026-11-13 | Three description styles in golden (`structured`, `natural`, `brief`), stored in `description_style`, results reported per style | The base model already scores high on step-by-step descriptions (PL pilot node F1 0.87); the harder styles are closer to real use and are where fine-tuning can show a gain |
| 2026-11-13 | System prompt stays unchanged | Team decision; the prompt is shared by all stages, so it is fixed before the first golden run |
| 2026-11-13 | Sequence diagrams: participants are nodes, messages are edges; a message matches by sender, receiver and text | (sender, receiver) pairs alone are nearly the same for any diagram with 3–4 participants; order and blocks stay unscored in v1 |
| 2026-11-14 | System prompt: the rule for choosing the diagram type rewritten (who sends what to whom -> `sequenceDiagram`, with the message syntax); everything else unchanged | In the first smoke test on golden the base model drew 4 of 4 sequence records as `flowchart TD`: the old rule ("flowchart for processes with steps and decisions") fits every description. Changed before the first full golden run, so no reported number used the old prompt |
| 2026-11-14 | System prompt, third version of the type rule: both types described side by side by what the description follows (steps of one procedure / exchange between several participants), no default type, message syntax without backticks | The second version fixed the sequence records (3 of 3) but 2 of 6 flowcharts were drawn as sequence diagrams and 3 came in code fences. In golden, conditions do not tell the types apart (84 of 91 flowchart descriptions and 22 of 34 sequence descriptions have one); who passes what to whom does |
| 2026-11-14 | System prompt, fourth version of the type rule: the type follows from who acts (one person or nobody named / several named participants that pass things to one another, also with conditions) | The third version gave the best flowcharts (6 of 6) but only 1 of 3 sequence records; the two missed ones are long `natural` descriptions, one with a condition, which read like one procedure |
| 2026-11-14 | Golden texts (translation, descriptions) are generated with a hosted model through the Kaggle Model Proxy | No local GPU; a strong model writes better Polish, so fewer manual fixes; the local-open-model rule is about training data |
| 2026-11-14 | Only RonnieAllen diagrams without logic defects go into golden (84 of 174) | 71 source diagrams have a decision with one branch; a broken reference would be unfair to the model |
| 2026-11-14 | A golden record whose source diagram has a logic defect is corrected by hand (diagram and description); `notes` says what and why | The human read found 14 such diagrams among the 84; an illogical reference makes the description unnatural. These records no longer have the structure of the source |
