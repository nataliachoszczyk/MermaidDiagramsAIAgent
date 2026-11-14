"""Smoke test on the CPU of the fourth system prompt: the 4B base model, zero-shot, the 10 golden records of
eval-smoke-cpu and 5 more sequence diagrams."""

import subprocess
import sys

REPO = "https://github.com/nataliachoszczyk/MermaidDiagramsAIAgent.git"
BRANCH = "e1-baseline"
CLONE = "/tmp/repo"
CODENAME = "eval-smoke-prompt4"
MODEL = "qwen3:4b-instruct-2507-q8_0"
DATA = "data/golden/golden.jsonl"
KAGGLE_EVAL_ARGS = ["--allow-cpu"]
IDS = [
    *("golden-flow-0006", "golden-flow-0034", "golden-flow-0050", "golden-flow-0054", "golden-flow-0063"),
    *("golden-flow-0066", "golden-seq-0020", "golden-seq-0026", "golden-seq-0031", "golden-none-0003"),
    *("golden-seq-0003", "golden-seq-0011", "golden-seq-0019", "golden-seq-0021", "golden-seq-0034"),
]
EVALUATE_ARGS = ["--ids", ",".join(IDS)]

subprocess.run(["git", "clone", "--depth", "1", "--branch", BRANCH, REPO, CLONE], check=True)
print("commit", subprocess.run(["git", "-C", CLONE, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip())
# The project needs a newer Python than the Kaggle image has; uv installs it together with the locked packages.
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "uv"], check=True)
subprocess.run(["uv", "sync", "--no-dev"], cwd=CLONE, check=True)
subprocess.run(
    ["uv", "run", "--no-dev", "kaggle-eval", "--model", MODEL, "--data", DATA]
    + ["--out", f"/kaggle/working/{CODENAME}", *KAGGLE_EVAL_ARGS, "--", *EVALUATE_ARGS],
    cwd=CLONE,
    check=True,
)
