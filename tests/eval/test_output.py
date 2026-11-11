import pytest

from mermaiddiagramsaiagent.eval.output import NormalizedOutput, diagram_type, normalize_output

CODE = "flowchart TD\n    A --> B"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (CODE, NormalizedOutput(CODE, fenced=False, extra_text=False)),
        (f"\n\n  {CODE}\n\n", NormalizedOutput(CODE, fenced=False, extra_text=False)),
        (f"```mermaid\n{CODE}\n```", NormalizedOutput(CODE, fenced=True, extra_text=False)),
        (f"```\n{CODE}\n```", NormalizedOutput(CODE, fenced=True, extra_text=False)),
        (f"```mermaid\n{CODE}```", NormalizedOutput(CODE, fenced=True, extra_text=False)),
        (f"Oto diagram:\n```mermaid\n{CODE}\n```\nGotowe.", NormalizedOutput(CODE, fenced=True, extra_text=True)),
        (f"Oto diagram:\n{CODE}", NormalizedOutput(CODE, fenced=False, extra_text=True)),
        ("BRAK_PROCESU", NormalizedOutput("BRAK_PROCESU", fenced=False, extra_text=False)),
        ("%% komentarz\n" + CODE, NormalizedOutput("%% komentarz\n" + CODE, fenced=False, extra_text=False)),
        ("graph TD;\n    A-->B", NormalizedOutput("graph TD;\n    A-->B", fenced=False, extra_text=False)),
    ],
)
def test_normalize_output(raw: str, expected: NormalizedOutput) -> None:
    assert normalize_output(raw) == expected


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (CODE, "flowchart"),
        ("graph LR\n A-->B", "flowchart"),
        ("graph TD;\n A-->B", "flowchart"),
        ("sequenceDiagram\n A->>B: hej", "sequenceDiagram"),
        ("---\ntitle: Proces\n---\n%% komentarz\nflowchart LR\n A-->B", "flowchart"),
        ("", "<empty>"),
    ],
)
def test_diagram_type(code: str, expected: str) -> None:
    assert diagram_type(code) == expected
