"""Check the evaluation setup in a Kaggle kernel (Node, mmdc, Ollama) on 3 golden records, on the CPU: no GPU quota."""

import subprocess
import sys

REPO = "https://github.com/nataliachoszczyk/MermaidDiagramsAIAgent.git"
BRANCH = "e1-baseline"
CLONE = "/tmp/repo"
CODENAME = "eval-setup"
MODEL = "qwen3:4b-instruct-2507-q8_0"
DATA = "data/golden/golden.jsonl"
KAGGLE_EVAL_ARGS = ["--allow-cpu"]
EVALUATE_ARGS = ["--sample", "3"]

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
