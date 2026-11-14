# Kaggle jobs

Status values: to run, queued, running, complete, failed, cancelled. Results go into the comment.

| Date | Job | Folder | Link | Comment | Status |
|---|---|---|---|---|---|
| 2026-11-14 | eval-setup | `2026-11-14_01_eval-setup` | [mermaid-eval-setup](https://www.kaggle.com/code/nataliachoszczyk/mermaid-eval-setup) | CPU session: installs Node, `mmdc`, Ollama and evaluates the 4B base model on 3 golden records, to debug the setup without GPU quota. Passed at the first attempt, 355 s in total; the sequence record was drawn as a flowchart | complete |
| 2026-11-14 | eval-smoke | `2026-11-14_02_eval-smoke` | [mermaid-eval-smoke](https://www.kaggle.com/code/nataliachoszczyk/mermaid-eval-smoke) | GPU session: 4B base model, zero-shot, 10 golden records (`--sample 10`); smoke test before the full baseline. Version 1 had `--sample 15`; version 2 (10 records) replaced it while both waited for a GPU | queued |
| 2026-11-14 | eval-smoke-cpu | `2026-11-14_03_eval-smoke-cpu` | [mermaid-eval-smoke-cpu](https://www.kaggle.com/code/nataliachoszczyk/mermaid-eval-smoke-cpu) | CPU session: the same 10 golden records as eval-smoke (`--sample 10`), started because eval-smoke waited over 30 minutes for a GPU. 1086 s in total, 78 s per record. Flowcharts (6): render 1.00, node F1 0.87, edge F1 0.80, shape 0.70. Sequence diagrams (3): all drawn as flowcharts, F1 0, one does not render. Refusal (1): correct | complete |
| 2026-11-14 | eval-smoke-prompt2 | `2026-11-14_04_eval-smoke-prompt2` | [mermaid-eval-smoke-prompt2](https://www.kaggle.com/code/nataliachoszczyk/mermaid-eval-smoke-prompt2) | CPU session: the same 10 golden records as eval-smoke-cpu, after the system prompt change (rule for choosing the diagram type) | running |
