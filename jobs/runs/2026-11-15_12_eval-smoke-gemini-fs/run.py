"""Smoke test on the CPU of a hosted reference model, gemini-3-flash-preview, few-shot (three examples from data/shots/shots_pl.jsonl):
5 golden records (2 flowcharts, 2 sequence diagrams, 1 refusal) that the Qwen3 smoke jobs also ran.

A kernel cannot reach the Kaggle Model Proxy, so the answers were fetched on the local machine with
`evaluate --kaggle-proxy` (thinking off, the arguments below) and are committed in answers/. The kernel only
renders them with mmdc and scores them with bge-m3 embeddings (`evaluate --replay`)."""

import subprocess
import sys

REPO = "https://github.com/nataliachoszczyk/MermaidDiagramsAIAgent.git"
BRANCH = "eval-gemini"
CLONE = "/tmp/repo"
CODENAME = "eval-smoke-gemini-fs"
MODEL = "google/gemini-3-flash-preview"
DATA = "data/golden/golden.jsonl"
SHOTS = "data/shots/shots_pl.jsonl"
ANSWERS = "jobs/runs/2026-11-15_12_eval-smoke-gemini-fs/answers/2026-11-15_1325_google-gemini-3-flash-preview_few-shot_golden_exact.json"
KAGGLE_EVAL_ARGS = ["--allow-cpu", "--replay", ANSWERS]
IDS = ["golden-flow-0006", "golden-flow-0050", "golden-seq-0020", "golden-seq-0026", "golden-none-0003"]
EVALUATE_ARGS = ["--ids", ",".join(IDS), "--no-think", "--setting", "few-shot", "--shots", SHOTS]

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
