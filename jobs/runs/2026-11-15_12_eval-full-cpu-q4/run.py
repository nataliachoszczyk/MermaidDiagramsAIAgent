"""E1 baseline on the CPU: Qwen3 4B, zero-shot and few-shot, all 130 golden records. Same system prompt,
options and examples as the smoke jobs 05-10. Replaces the GPU job eval-full-q4-q17, which stayed queued."""


import subprocess
import sys

REPO = "https://github.com/nataliachoszczyk/MermaidDiagramsAIAgent.git"
BRANCH = "few-shot-prompting"
CLONE = "/tmp/repo"
DATA = "data/golden/golden.jsonl"
FEW_SHOT = ["--setting", "few-shot", "--shots", "data/shots/shots_pl.jsonl"]
RUNS = [
    ("full-q4-zero", "qwen3:4b-instruct-2507-q8_0", []),
    ("full-q4-few", "qwen3:4b-instruct-2507-q8_0", FEW_SHOT),
]

subprocess.run(["git", "clone", "--depth", "1", "--branch", BRANCH, REPO, CLONE], check=True)
print("commit", subprocess.run(["git", "-C", CLONE, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip())
# The project needs a newer Python than the Kaggle image has; uv installs it together with the locked packages.
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "uv"], check=True)
subprocess.run(["uv", "sync", "--no-dev"], cwd=CLONE, check=True)
# A failed kernel loses all its output, so a failed run is reported and the next one still starts.
failed = []
for codename, model, evaluate_args in RUNS:
    proc = subprocess.run(
        ["uv", "run", "--no-dev", "kaggle-eval", "--model", model, "--data", DATA]
        + ["--out", f"/kaggle/working/{codename}", "--allow-cpu", "--", *evaluate_args],
        cwd=CLONE,
    )
    if proc.returncode != 0:
        failed.append(codename)
print("failed runs:", failed or "none")
