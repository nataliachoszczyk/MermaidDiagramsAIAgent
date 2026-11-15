"""Smoke test on the CPU of a hosted reference model, gemini-3-flash-preview through the Kaggle Model Proxy:
zero-shot, on 5 golden records (2 flowcharts, 2 sequence diagrams, 1 refusal) that the
Qwen3 smoke jobs also ran. The model runs at Google; the kernel only renders with mmdc and embeds labels with
bge-m3."""

import subprocess
import sys

REPO = "https://github.com/nataliachoszczyk/MermaidDiagramsAIAgent.git"
BRANCH = "eval-gemini"
CLONE = "/tmp/repo"
CODENAME = "eval-smoke-gemini-zs"
MODEL = "google/gemini-3-flash-preview"
DATA = "data/golden/golden.jsonl"
KAGGLE_EVAL_ARGS = ["--allow-cpu", "--kaggle-proxy"]
IDS = ["golden-flow-0006", "golden-flow-0050", "golden-seq-0020", "golden-seq-0026", "golden-none-0003"]
# Thinking off as for every model (design.md §4.1); with it on, it eats most of the 1024 max tokens.
EVALUATE_ARGS = ["--ids", ",".join(IDS), "--no-think"]

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
