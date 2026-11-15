"""Render Mermaid code with `mmdc` to check that it is valid."""

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

RENDER_TIMEOUT_S = 60
PUPPETEER_CONFIG_ENV = "MMDC_PUPPETEER_CONFIG"


@dataclass(frozen=True)
class RenderResult:
    ok: bool
    error: str


def mmdc_command() -> str:
    path = shutil.which("mmdc")
    if path is None:
        raise SystemExit("mmdc not found on PATH (npm install -g @mermaid-js/mermaid-cli)")
    return path


def mmdc_version() -> str:
    return subprocess.run([mmdc_command(), "--version"], capture_output=True, text=True).stdout.strip()


def puppeteer_args() -> list[str]:
    """`-p <file>` if MMDC_PUPPETEER_CONFIG names a Puppeteer config (needed in a container: Chromium does not
    start as root with its sandbox, so the config there is `{"args": ["--no-sandbox"]}`)."""
    config = os.environ.get(PUPPETEER_CONFIG_ENV)
    return ["-p", config] if config else []


def render_once(code: str, work_dir: Path, name: str) -> RenderResult:
    src = work_dir / f"{name}.mmd"
    out = work_dir / f"{name}.svg"
    src.write_text(code, encoding="utf-8")
    try:
        proc = subprocess.run(
            [mmdc_command(), "-q", *puppeteer_args(), "-i", str(src), "-o", str(out)],
            capture_output=True,
            text=True,
            timeout=RENDER_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return RenderResult(False, "timeout")
    ok = proc.returncode == 0 and out.exists() and out.stat().st_size > 0
    return RenderResult(ok, "" if ok else (proc.stderr or proc.stdout).strip()[:2000])


def render(code: str, work_dir: Path, name: str) -> RenderResult:
    """Retry once: headless Chromium occasionally crashes under parallel load; real syntax errors fail twice."""
    result = render_once(code, work_dir, name)
    return result if result.ok else render_once(code, work_dir, name)


def check_mmdc_works() -> None:
    """Fail loudly if mmdc cannot render a trivial diagram, so a broken setup is not reported as bad output."""
    with tempfile.TemporaryDirectory() as tmp:
        result = render_once("flowchart TD\n    A --> B", Path(tmp), "smoke-test")
    if not result.ok:
        raise SystemExit(f"mmdc cannot render a trivial diagram; fix the setup first:\n{result.error}")
