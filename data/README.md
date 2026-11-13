# Data

## Public source datasets (`data/raw/`, gitignored)

Downloaded with `uv run download-raw` at the revisions pinned in `src/mermaiddiagramsaiagent/data/sources.py`.
`uv run report-raw` writes counts, fields and an `mmdc` render check to `data/raw/report.json`.

| Dataset | Revision | License | Content | Renders with `mmdc` 12.2.0 |
|---|---|---|---|---|
| [`RonnieAllen/mermaid-flowchart-dataset`](https://huggingface.co/datasets/RonnieAllen/mermaid-flowchart-dataset) | `d28ea0de` | CC-BY-4.0 | 196 English flowcharts (train 157 / validation 17 / test 22), LLM-generated, one-line prompts | 194 / 196 |
| [`ibm-research/MermaidSeqBench`](https://huggingface.co/datasets/ibm-research/MermaidSeqBench) | `c1547591` | Apache-2.0 | 132 English sequence diagrams (~30 scenarios, each augmented ~4×) | 132 / 132 |

The two RonnieAllen diagrams that do not render use `X[{...}]`; see `tests/eval/test_flowchart_raw_data.py`.

### Attribution

Both licenses require attribution in anything we publish that contains data derived from these sets.

```bibtex
@dataset{mermaid-flowchart-dataset,
  title={Mermaid Flowchart Dataset},
  author={Dataset Curator},
  year={2026},
  publisher={Hugging Face},
  url={https://huggingface.co/datasets/RonnieAllen/mermaid-flowchart-dataset}
}

@misc{shbita2025mermaidseqbenchevaluationbenchmarkllmtomermaid,
  title={MermaidSeqBench: An Evaluation Benchmark for NL-to-Mermaid Sequence Diagram Generation},
  author={Basel Shbita and Farhan Ahmed and Chad DeLuca},
  year={2025},
  eprint={2511.14967},
  archivePrefix={arXiv},
  primaryClass={cs.SE},
  url={https://arxiv.org/abs/2511.14967}
}
```

## Pilot (`data/pilot/`, committed)

Built from the 22 diagrams of the RonnieAllen `test` split (CC-BY-4.0). For checking the evaluation pipeline
only; numbers on it are not reported. Not human-verified.

| File | Diagrams | Descriptions | How it was made |
|---|---|---|---|
| `pilot_en.jsonl` | original | original one-line prompts | `uv run build-pilot` |
| `pilot_en_described.jsonl` | original | English, step by step, close to the label wording | written by Claude from the diagrams |
| `pilot_pl.jsonl` | labels translated to Polish, structure unchanged | Polish, in own words | written by Claude; every diagram checked with `mmdc` |

The last two files are the source of truth: the one-off script that produced them is not in the repository.
Each record says in `notes` how its description was made.

## Planned

- `data/golden/` – test set (`docs/design.md` §2.3)
- `data/synthetic/` – training and validation data (`docs/design.md` §3)
