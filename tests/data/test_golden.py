from datetime import UTC, datetime

import pytest

from mermaiddiagramsaiagent.data.golden import (
    STYLES,
    Candidate,
    build_record,
    description_problems,
    parse_response,
    plan_records,
    reference_problems,
    select_flowcharts,
    select_sequences,
    sequence_difficulty,
    topic,
    translation_problems,
)
from mermaiddiagramsaiagent.data.sources import MERMAIDSEQBENCH, RONNIEALLEN
from mermaiddiagramsaiagent.eval.flowchart import parse_flowchart
from mermaiddiagramsaiagent.llm import proxy_key_expired

FLOW_EN = """flowchart TD
 A([Start]) --> B[Check balance]
 B --> C{Is balance sufficient?}
 C -->|Yes| D[Pay]
 C -->|No| E[Reject]
 D --> Z([End])
 E --> Z([End])"""
FLOW_PL = """flowchart TD
 A([Start]) --> B[Sprawdź saldo]
 B --> C{Czy saldo wystarcza?}
 C -->|Tak| D[Zapłać]
 C -->|Nie| E[Odrzuć]
 D --> Z([Koniec])
 E --> Z([Koniec])"""
SEQ_EN = "sequenceDiagram\nparticipant U as User\nparticipant S as Shop\nU->>S: Place order\nS-->>U: Confirmation"
SEQ_PL = "sequenceDiagram\nparticipant U as Użytkownik\nparticipant S as Sklep\nU->>S: Złóż zamówienie\nS-->>U: Potwierdzenie"

needs_raw_data = pytest.mark.skipif(
    not (RONNIEALLEN.local_dir / "data").exists() or not (MERMAIDSEQBENCH.local_dir / "data.csv").exists(),
    reason="raw data not downloaded (uv run download-raw)",
)


# --- choosing the source diagrams -----------------------------------------------------------------


def test_topic_strips_the_prompt_prefix() -> None:
    assert topic("Create a flowchart for: Password reset via email link") == "password reset via email link"
    assert topic("Show the full decision flow when handling refund request") == "refund request"


@pytest.mark.parametrize(
    ("code", "problem"),
    [
        (FLOW_EN, None),
        (FLOW_EN.replace(" C -->|No| E[Reject]\n", "").replace(" E --> Z([End])", " E[Reject] --> Z"), "decision"),
        (FLOW_EN.replace("\n E --> Z([End])", ""), "leads nowhere"),
        (FLOW_EN.replace("B --> C{", "B -->|Yes| C{"), "labelled branch"),
        (FLOW_EN.replace("D --> Z([End])", "D --> Y([Done])"), "one start and one end"),
        (FLOW_EN.replace("{Is balance sufficient?}", "[{Is balance sufficient?}]"), "syntax"),
    ],
)
def test_reference_problems(code: str, problem: str | None) -> None:
    problems = reference_problems(parse_flowchart(code))
    assert problems == [] if problem is None else any(problem in found for found in problems)


@needs_raw_data
def test_selected_flowcharts_are_usable_distinct_and_start_with_distinct_topics() -> None:
    flowcharts = select_flowcharts()
    assert len(flowcharts) > 50
    assert len({candidate.mermaid for candidate in flowcharts}) == len(flowcharts)
    assert all(not reference_problems(parse_flowchart(candidate.mermaid)) for candidate in flowcharts)
    assert all(":data/test.jsonl" not in candidate.source_ref for candidate in flowcharts)


@needs_raw_data
def test_one_sequence_diagram_per_scenario() -> None:
    sequences = select_sequences()
    assert len(sequences) == 30
    scenarios = [candidate.source_ref.rsplit(" ", 1)[1].split("/")[0] for candidate in sequences]
    assert len(set(scenarios)) == 30


def test_plan_alternates_styles_within_each_type() -> None:
    flow = Candidate("flowchart", "ronnieallen", "ref", "CC-BY-4.0", FLOW_EN)
    seq = Candidate("sequenceDiagram", "mermaidseqbench", "ref", "Apache-2.0", SEQ_EN)
    plan = plan_records([flow] * 4, [seq] * 2)
    assert [(record_id, style) for record_id, style, _ in plan] == [
        ("golden-flow-0001", STYLES[0]),
        ("golden-flow-0002", STYLES[1]),
        ("golden-flow-0003", STYLES[2]),
        ("golden-flow-0004", STYLES[0]),
        ("golden-seq-0001", STYLES[0]),
        ("golden-seq-0002", STYLES[1]),
    ]


# --- checking the generated record ----------------------------------------------------------------


def test_parse_response() -> None:
    text = f"<mermaid>\n{FLOW_PL}\n</mermaid>\n<description>\nNajpierw sprawdzam saldo.\n</description>"
    assert parse_response(text) == (FLOW_PL, "Najpierw sprawdzam saldo.")
    assert parse_response(FLOW_PL) is None


def test_correct_translations_have_no_problems() -> None:
    assert translation_problems(FLOW_EN, FLOW_PL) == []
    assert translation_problems(SEQ_EN, SEQ_PL) == []


@pytest.mark.parametrize(
    ("source", "translated", "problem"),
    [
        (FLOW_EN, FLOW_PL.replace("{Czy saldo wystarcza?}", "[Czy saldo wystarcza?]"), "shapes"),
        (FLOW_EN, FLOW_PL.replace(" E --> Z([Koniec])", ""), "edges"),
        (FLOW_EN, FLOW_PL.replace("-->|Tak|", "-->"), "edges"),
        (FLOW_EN, FLOW_EN, "translate them"),
        (FLOW_EN, SEQ_PL, "does not parse"),
        (SEQ_EN, SEQ_PL.replace("participant S as Sklep\n", ""), "participant ids"),
        (SEQ_EN, SEQ_PL.replace("S-->>U", "S->>U"), "messages"),
        (SEQ_EN, SEQ_EN, "translate them"),
        (SEQ_EN, SEQ_PL.replace("Potwierdzenie", '"Potwierdzenie"'), "quotation marks"),
    ],
)
def test_translation_problems(source: str, translated: str, problem: str) -> None:
    assert any(problem in found for found in translation_problems(source, translated))


@pytest.mark.parametrize(
    ("description", "ok"),
    [
        ("Najpierw sprawdzam saldo, potem płacę.", True),
        ("", False),
        ("Narysuj to w Mermaid.", False),
        ("Kroki:\n- sprawdź saldo\n- zapłać", False),
        ("Kroki:\n1. sprawdź saldo", False),
    ],
)
def test_description_problems(description: str, ok: bool) -> None:
    assert (description_problems(description) == []) is ok


# --- the record -----------------------------------------------------------------------------------


def test_sequence_difficulty() -> None:
    assert sequence_difficulty(SEQ_PL) == "easy"
    assert sequence_difficulty(SEQ_PL + "\nalt błąd\nS-->>U: Błąd\nend") == "medium"
    assert sequence_difficulty(SEQ_PL + "\nU->>S: Ping" * 13) == "hard"


def test_build_record_has_the_design_fields() -> None:
    candidate = Candidate("flowchart", "ronnieallen", "repo@rev:data/train.jsonl:1", "CC-BY-4.0", FLOW_EN)
    record = build_record("golden-flow-0001", candidate, "brief", FLOW_PL, "Opis.", "note")
    assert list(record) == [
        "id", "split", "source", "source_ref", "license", "diagram_type", "difficulty",
        "description", "description_style", "expected_mermaid", "notes",
    ]  # fmt: skip
    assert (record["split"], record["difficulty"], record["expected_mermaid"]) == ("golden", "medium", FLOW_PL)


def test_proxy_key_expiry() -> None:
    now = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    assert proxy_key_expired("2026-11-14T11:59:00.000000Z", now)
    assert not proxy_key_expired("2026-11-14T12:30:00.000000Z", now)
    assert not proxy_key_expired(None, now)
