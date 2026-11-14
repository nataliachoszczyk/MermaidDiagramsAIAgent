"""Run `evaluate` inside a Kaggle kernel: install Node + `mmdc` and Ollama, pull the models, evaluate, copy the result.

    uv run kaggle-eval --model qwen3:4b-instruct-2507-q8_0 --data data/golden/golden.jsonl --out /kaggle/working/x -- --sample 15

Arguments after `--` go to `evaluate` unchanged. Run it from the repository root. It is written for the Kaggle
image (Linux, root, apt); on a normal machine set up Ollama and `mmdc` by hand and call `evaluate` directly.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

NODE_VERSION = "26.13.1"
MERMAID_CLI = "@mermaid-js/mermaid-cli@12.2.0"  # the version the golden references were checked with
DEFAULT_EMBEDDING_MODEL = "bge-m3:latest"
TOOLS = Path("/tmp/tools")
OLLAMA_URL = "http://127.0.0.1:11434"
RESULTS_DIR = Path("results")
# Shared libraries that headless Chromium needs; on newer Ubuntu some packages carry the suffix `t64`.
CHROMIUM_LIBS = (
    "libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 "
    "libxfixes3 libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2 libatspi2.0-0 libdbus-1-3 libglib2.0-0"
).split()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True, help="Ollama model to evaluate")
    parser.add_argument("--data", type=Path, required=True, help="evaluation JSONL")
    parser.add_argument("--out", type=Path, required=True, help="folder for the result file, under /kaggle/working")
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--allow-cpu", action="store_true", help="do not stop when the session has no GPU")
    parser.add_argument("evaluate_args", nargs="*", help="after `--`: extra arguments for `evaluate`")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    started = time.perf_counter()
    gpu = gpu_names()
    print("GPU:", gpu or "none", flush=True)
    if not gpu and not args.allow_cpu:
        raise SystemExit("no GPU: check the phone verification of the account and `enable_gpu` in the metadata")

    install_mmdc()
    server = start_ollama()
    try:
        for model in (args.model, args.embedding_model):
            run(["ollama", "pull", model])
        before = set(RESULTS_DIR.glob("*.json"))
        run(
            [sys.executable, "-m", "mermaiddiagramsaiagent.eval.run", "--model", args.model, "--data", str(args.data)]
            + ["--embedding-model", args.embedding_model, *args.evaluate_args]
        )
        args.out.mkdir(parents=True, exist_ok=True)
        for path in sorted(set(RESULTS_DIR.glob("*.json")) - before):
            shutil.copy(path, args.out / path.name)
        loaded = subprocess.run(["ollama", "ps"], capture_output=True, text=True).stdout
        print(loaded, flush=True)  # the PROCESSOR column shows whether the models ran on the GPU
        environment = {"gpu": gpu, "ollama_ps": loaded, "ollama": output(["ollama", "--version"])}
        environment["total_seconds"] = round(time.perf_counter() - started)
        (args.out / "environment.json").write_text(json.dumps(environment, indent=2), encoding="utf-8")
    finally:
        server.terminate()


def gpu_names() -> list[str]:
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], capture_output=True, text=True
        )
    except OSError:
        return []
    return proc.stdout.split("\n")[:-1] if proc.returncode == 0 else []


def install_mmdc() -> None:
    """Node from nodejs.org, mermaid-cli with its bundled Chromium, and a Puppeteer config without the sandbox."""
    name = f"node-v{NODE_VERSION}-linux-x64"
    TOOLS.mkdir(parents=True, exist_ok=True)
    archive = TOOLS / f"{name}.tar.xz"
    urllib.request.urlretrieve(f"https://nodejs.org/dist/v{NODE_VERSION}/{name}.tar.xz", archive)
    with tarfile.open(archive) as tar:
        tar.extractall(TOOLS)
    os.environ["PATH"] = f"{TOOLS / name / 'bin'}{os.pathsep}{os.environ['PATH']}"
    run(["npm", "install", "-g", "--no-fund", "--no-audit", MERMAID_CLI])
    apt_install(CHROMIUM_LIBS)
    # Chromium refuses to start as root with its sandbox, and a Kaggle kernel runs as root.
    config = TOOLS / "puppeteer.json"
    config.write_text(json.dumps({"args": ["--no-sandbox"]}), encoding="utf-8")
    os.environ["MMDC_PUPPETEER_CONFIG"] = str(config)
    print("mmdc", output(["mmdc", "--version"]), flush=True)


def apt_install(packages: list[str]) -> None:
    """Install each package that exists under its name or with the suffix `t64`; a missing one is only reported,
    because `evaluate` checks that `mmdc` renders before it starts."""
    subprocess.run(["apt-get", "update", "-qq"], capture_output=True)
    for package in packages:
        for name in (package, f"{package}t64"):
            command = ["apt-get", "install", "-y", "-qq", "--no-install-recommends", name]
            if subprocess.run(command, capture_output=True).returncode == 0:
                break
        else:
            print(f"apt: could not install {package}", flush=True)


def start_ollama() -> subprocess.Popen:
    apt_install(["zstd"])  # the Ollama installer unpacks a .tar.zst archive
    run(["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"])
    os.environ["OPENAI_BASE_URL"] = f"{OLLAMA_URL}/v1"
    os.environ["OPENAI_API_KEY"] = "ollama"
    log = (TOOLS / "ollama.log").open("w")
    server = subprocess.Popen(["ollama", "serve"], stdout=log, stderr=subprocess.STDOUT)
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"{OLLAMA_URL}/api/version", timeout=2) as response:
                print("ollama", json.load(response)["version"], flush=True)
            return server
        except OSError:
            time.sleep(1)
    server.terminate()
    raise SystemExit(f"Ollama did not start:\n{(TOOLS / 'ollama.log').read_text()[-2000:]}")


def run(command: list[str]) -> None:
    print("$", " ".join(command), flush=True)
    subprocess.run(command, check=True)


def output(command: list[str]) -> str:
    return subprocess.run(command, capture_output=True, text=True).stdout.strip()


if __name__ == "__main__":
    main()
