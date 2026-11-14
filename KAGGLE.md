# Experiments on Kaggle

How to run heavy jobs (LoRA training, large evaluations) on Kaggle from this repository. The local machine has
the code and the records, Kaggle does the computation, git connects the two.

**Status:** `jobs/` exists; the jobs and their results are listed in `jobs/JOBS.md`.

## 1. Setup

| Item | What to do |
|---|---|
| Kaggle account | Do the phone verification (Settings). Without it a kernel gets no GPU and no internet. |
| Kaggle CLI | No install: `uvx --with six kaggle <arguments>` (version 2.2.5; `six` is missing from its dependencies). |
| Credentials | kaggle.com → Settings → API. Either `~/.kaggle/kaggle.json` (legacy key) or `~/.kaggle/access_token` (new token, one line). |
| Git remote | The repository is public, so kernels can clone it. Push the branch before you push a kernel. |

Check the connection and the account:

```
uvx --with six kaggle config view
uvx --with six kaggle kernels list --mine
```

Never commit credentials. They give full access to the account. Keep them in the home folder, not in the project.

All jobs of this project run on one account. The `<user>` in a kernel id must be the account from
`config view`, otherwise the push fails with "Permission denied".

## 2. Platform facts

| Item | Value |
|---|---|
| GPU machine | `"machine_shape": "NvidiaTeslaT4"` gives 2x Tesla T4, 15 GB each. |
| GPU sessions at the same time | 2 per account. A third push fails with "Maximum batch GPU session count of 2 reached". |
| GPU time | Weekly quota, about 30 hours. A session counts its hours, not its GPUs. |
| CPU sessions | 4 cores, about 30 GB of RAM. They do not use the GPU quota. |
| Session limit | 12 hours. |
| Output | `/kaggle/working/`, about 20 GB. Only this folder is kept. |
| Temporary | `/kaggle/temp/`, deleted after the session. |
| Input | `/kaggle/input/<slug>/...`, read-only. The path can change: find files with `Path("/kaggle/input").rglob(...)`. |

Behavior to remember:

- If a kernel fails (status ERROR), Kaggle deletes its complete output.
- The CLI cannot stop a kernel. Cancel it on the web page.
- The CLI does not give the version ID of a run, so use one kernel per job, not many versions of one kernel.
- Without phone verification a GPU kernel runs on the CPU and no error occurs.

## 3. Repository structure

```
jobs/
  JOBS.md                 list of all jobs and their status
  runs/
    YYYY-MM-DD_NN_<job>/  one folder per job; NN is the job number in the project and never restarts
      run.py              the script that Kaggle runs
      kernel-metadata.json
      <codename>.yaml     one config per experiment of the job
      output/             small results only, same paths as /kaggle/working/
        <codename>/
```

Names:

- **Job folder** `2026-11-20_03_lora-v1ab` identifies a job. One job folder = one Kaggle kernel = one row in `JOBS.md`.
- **Job name** is the last part (`lora-v1ab`). The kernel id is `<user>/mermaid-<job name>`.
- **Codename** (`lora-v1a`) names one experiment: its config file and its output folder. Variants of one idea
  get letters; a job that runs `lora-v1a` and `lora-v1b` is called `lora-v1ab`.
- Lowercase letters, digits and hyphens only. Every name is unique in the project.

Rules:

- All logic stays in `src/mermaiddiagramsaiagent/`. `run.py` only clones the repository and calls it.
- A job folder does not change after the start. A new variant gets a new folder.
- `output/` keeps only small files (JSON, CSV, PNG). Model weights, data and caches stay on Kaggle;
  add the patterns to `.gitignore` when the first job is created.
- Evaluation run files still go to `results/`, in the usual format (`docs/design.md` §4.4).
- Helper scripts (for example one that follows a kernel and updates `JOBS.md`) are Python entry points in
  `pyproject.toml`, not shell scripts.

## 4. Code and data on Kaggle

The kernel clones the branch from GitHub, so every run uses code from git, and it prints the commit hash.
Clone into `/tmp`, not into `/kaggle/working`, otherwise the clone becomes part of the output.

`kernel-metadata.json`:

```json
{
  "id": "<user>/mermaid-<job name>",
  "title": "mermaid-<job name>",
  "code_file": "run.py",
  "language": "python",
  "kernel_type": "script",
  "is_private": true,
  "enable_gpu": true,
  "enable_internet": true,
  "machine_shape": "NvidiaTeslaT4",
  "dataset_sources": [],
  "competition_sources": [],
  "kernel_sources": []
}
```

For a CPU job use `"enable_gpu": false` and remove `machine_shape`.

`run.py` (one experiment):

```python
"""<What the job does, in one or two sentences.>"""
import subprocess
import sys

REPO = "https://github.com/<owner>/MermaidDiagramsAIAgent.git"
BRANCH = "<branch>"
CLONE = "/tmp/repo"
CODENAMES = ["<codename>"]

import torch

# A long job on the CPU wastes hours, so stop immediately without a GPU.
assert torch.cuda.is_available(), "no GPU: check the phone verification of the account"

subprocess.run(["git", "clone", "--depth", "1", "--branch", BRANCH, REPO, CLONE], check=True)
print("commit", subprocess.run(["git", "-C", CLONE, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip())
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-e", CLONE], check=True)

# Then call the project code for each codename, for example the training entry point (planned).
```

Data:

- Training and validation files are small and live in git, so the clone brings them. The golden set is never
  used by a training job.
- The output of one kernel can be the input of another: `"kernel_sources": ["<user>/mermaid-<job name>"]`.
  Use this to pass a trained adapter to an evaluation job without a download.

### Evaluation jobs

The Kaggle image has an older Python than the project needs and neither Ollama nor `mmdc`. An evaluation
`run.py` therefore installs `uv`, runs `uv sync` in the clone and calls `uv run kaggle-eval`
(`src/mermaiddiagramsaiagent/kaggle_eval.py`): it installs Node, mermaid-cli (same version as on the local
machine) and Ollama, starts the server, pulls the models, runs `evaluate` and copies the run file and
`environment.json` (GPU names, `ollama ps`, total time) to `/kaggle/working/<codename>/`. Copy the run file
from the job's `output/` to `results/` if its numbers are reported.

## 5. Two GPUs

A T4 x2 session has two GPUs and the quota counts the session, so a job that uses one GPU wastes half of its
cost. Run one process per GPU, each with its own experiment (for example two LoRA configs):

- Use the `spawn` multiprocessing context; CUDA does not work in a forked process.
- Put the main code under `if __name__ == "__main__":`, because each new process imports `run.py` again.
- Each process gets its device as an argument and writes to its own folder `/kaggle/working/<codename>/`.
- The main process must not hold GPU memory before the pool starts.
- If one process fails, the job fails and the output of both experiments is deleted. Do a smoke test first.
- The processes share the RAM of the session.

## 6. Start, follow, collect

1. Commit and push the code.
2. Add a row to `jobs/JOBS.md` with the status `to run`.
3. Push the kernel:

   ```
   uvx --with six kaggle kernels push -p jobs/runs/YYYY-MM-DD_NN_<job name>
   ```

   The first push creates the kernel and starts it. If two GPU sessions are active, the push fails; try again later.
4. Follow it:

   ```
   uvx --with six kaggle kernels status <user>/mermaid-<job name>
   ```

   States: QUEUED, RUNNING, COMPLETE, ERROR, CANCEL. Write each change into `JOBS.md`.
5. When it is complete, list the files and download only the small ones:

   ```
   uvx --with six kaggle kernels files <user>/mermaid-<job name>
   uvx --with six kaggle kernels output <user>/mermaid-<job name> -p jobs/runs/YYYY-MM-DD_NN_<job name>/output --file-pattern "(json|csv|png)$"
   ```

   The pattern is a regular expression for the complete path. Do not start it with `^`.
6. Commit the small results and write the main numbers into the comment of the `JOBS.md` row.

`jobs/JOBS.md`:

```markdown
Status values: to run, queued, running, complete, failed, cancelled. Results go into the comment.

| Date | Job | Folder | Link | Comment | Status |
|---|---|---|---|---|---|
| YYYY-MM-DD | <job name> | `YYYY-MM-DD_NN_<job name>` | [mermaid-<job name>](https://www.kaggle.com/code/<user>/mermaid-<job name>) | <what the job does; main results> | complete |
```

One job folder has one row. A new version after an error uses the same row and gets a note in the comment.

## 7. Protect long runs

- **Smoke test.** Before a run of many hours, run the same code path on a few examples, including the final
  steps (checkpoint selection, export, writing results). An error at the end of a long run loses everything.
- **Early checks.** Put cheap checks at the start (GPU present, data files found, one training step, one
  generated diagram) and stop the job if one fails.
- **Deadline.** A long loop gets a deadline (for example 9 hours). After it no new work starts and the job
  writes its results before the 12-hour limit.

## 8. Experiment method

These extend the rules in `CLAUDE.md`:

- **One change per variant.** Variants of one group share a base and each changes one thing.
- **Checkpoints.** Keep several checkpoints and pick the best by `node_f1` on `val`, not by the loss
  (`docs/design.md` §5). The golden set is only for the final numbers.
- **Noise.** Two runs with the same settings and a different seed show the random difference. A smaller
  difference between variants is not a result.

## 9. Hosted models (Model Proxy)

Besides GPU time, a Kaggle account has an "AI Quota" for calling hosted models: $10 per day and $100 per month,
free. It needs no kernel: the models are called from the local machine through an OpenAI-compatible API.

Get a key (valid for two hours, so repeat it at the start of a session) and see the spend:

```
uvx --with six kaggle benchmarks auth -y --env-file .env.kaggle
uvx --with six kaggle benchmarks quota
```

`.env.kaggle` is gitignored. Commands that support the proxy take `--kaggle-proxy` (today: `build-golden`) and
read the key from that file. `uvx --with six kaggle benchmarks init --env-file <file>` also lists the models of
the account in `LLMS_AVAILABLE`; the proxy has no model list endpoint.

Checked on 2026-11-13:

- `anthropic/claude-sonnet-5@default` works; about $2 / $10 per million input / output tokens. It rejects the
  `temperature` parameter, so its output is not reproducible.
- `google/gemini-3-flash-preview` and `openai/gpt-oss-120b` answer. `qwen/qwen3-next-80b-a3b-instruct` is listed
  but returns 404.
- Every response reports its cost (`usage.cost`, in nanodollars).

The quota exists for Kaggle Benchmarks. Whether the Kaggle terms allow other uses was not checked.
Training data must not come from here: it has to be generated with a local open model (`CLAUDE.md`).
