"""Turn raw model output into bare Mermaid code and record how far it was from "Mermaid only"."""

import re
from dataclasses import dataclass

FENCED_BLOCK_RE = re.compile(r"```[ \t]*(?:mermaid)?[ \t]*\n(.*?)\n?[ \t]*```", re.DOTALL)
DIAGRAM_KEYWORDS = ("flowchart", "graph", "sequenceDiagram")


@dataclass(frozen=True)
class NormalizedOutput:
    code: str
    fenced: bool  # the code was wrapped in ``` fences
    extra_text: bool  # there was other text around the code


def normalize_output(raw: str) -> NormalizedOutput:
    text = raw.strip()
    fenced = FENCED_BLOCK_RE.search(text)
    if fenced is not None:
        outside = (text[: fenced.start()] + text[fenced.end() :]).strip()
        return NormalizedOutput(fenced.group(1).strip(), fenced=True, extra_text=bool(outside))
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if _starts_diagram(line)), None)
    if start is None:  # no diagram at all (e.g. a refusal); keep the text as is
        return NormalizedOutput(text, fenced=False, extra_text=False)
    return NormalizedOutput("\n".join(lines[start:]).strip(), fenced=False, extra_text=start > 0)


def diagram_type(code: str) -> str:
    """Diagram keyword (`graph` counts as `flowchart`), skipping blank lines, %% comments and front matter."""
    lines = iter(code.strip().splitlines())
    for line in lines:
        stripped = line.strip()
        if stripped == "---":
            for inner in lines:
                if inner.strip() == "---":
                    break
            continue
        if not stripped or stripped.startswith("%%"):
            continue
        keyword = stripped.split()[0].rstrip(";")
        return "flowchart" if keyword == "graph" else keyword
    return "<empty>"


def _starts_diagram(line: str) -> bool:
    stripped = line.strip()
    first_word = stripped.split(maxsplit=1)[0].rstrip(";") if stripped else ""
    return stripped.startswith(("---", "%%")) or first_word in DIAGRAM_KEYWORDS
