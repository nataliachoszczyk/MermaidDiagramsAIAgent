"""The parser against the examples of the Mermaid docs (syntax/sequenceDiagram.md).

The expected participants and messages were compared once with what `mmdc` draws for the same code.
"""

import pytest

from mermaiddiagramsaiagent.eval.flowchart import ParseError
from mermaiddiagramsaiagent.eval.sequence import Message, Participant, parse_sequence


def labels(code: str) -> list[str]:
    return [p.label for p in parse_sequence(code).participants.values()]


def messages(code: str) -> list[tuple[str, str, str]]:
    return [(m.src, m.dst, m.text) for m in parse_sequence(code).messages]


# --- header ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("code", ["", "  \n ", "flowchart TD\n    A --> B", "sequencediagram\n    A->>B: hej", "A->>B: hej"])
def test_invalid_header_raises(code: str) -> None:
    with pytest.raises(ParseError):
        parse_sequence(code)


def test_front_matter_comments_and_semicolons() -> None:
    code = "---\ntitle: Logowanie\n---\n%% komentarz\nsequenceDiagram;\n    A->>B: Dane; B-->>A: Wynik\n    %% koniec"
    assert messages(code) == [("A", "B", "Dane"), ("B", "A", "Wynik")]


# --- participants ---------------------------------------------------------------------------------


def test_implicit_participants_in_order_of_appearance() -> None:
    code = """sequenceDiagram
    Alice->>John: Hello John, how are you?
    John-->>Alice: Great!
    Alice-)John: See you later!
    """
    diagram = parse_sequence(code)
    assert diagram.participants == {
        "Alice": Participant("Alice", "Alice", "participant"),
        "John": Participant("John", "John", "participant"),
    }
    assert diagram.messages == [
        Message("Alice", "John", "Hello John, how are you?", "->>"),
        Message("John", "Alice", "Great!", "-->>"),
        Message("Alice", "John", "See you later!", "-)"),
    ]
    assert diagram.warnings == []


def test_declarations_set_the_order() -> None:
    code = "sequenceDiagram\n    participant Alice\n    participant Bob\n    Bob->>Alice: Hi Alice\n    Alice->>Bob: Hi Bob"
    assert labels(code) == ["Alice", "Bob"]


def test_actor_keyword_sets_the_kind() -> None:
    diagram = parse_sequence("sequenceDiagram\n    actor Alice\n    participant Bob\n    Alice->>Bob: Hi Bob")
    assert [p.kind for p in diagram.participants.values()] == ["actor", "participant"]


def test_alias_is_the_label() -> None:
    code = "sequenceDiagram\n    participant A as Alice\n    participant J as John\n    A->>J: Hello John, how are you?"
    diagram = parse_sequence(code)
    assert diagram.participants["A"] == Participant("A", "Alice", "participant")
    assert messages(code) == [("A", "J", "Hello John, how are you?")]


def test_alias_with_line_break_and_quotes() -> None:
    assert labels('sequenceDiagram\n    participant A as Alice<br/>Johnson\n    participant B as "Baza danych"') == [
        "Alice Johnson",
        "Baza danych",
    ]


def test_json_configuration() -> None:
    code = """sequenceDiagram
    participant API@{ "type": "boundary" } as Public API
    actor DB@{ "type": "database" } as User Database
    participant Svc@{ "type": "control", "alias": "Auth Service" }
    participant Q@{ "type" : "queue" }
    participant X@{ "type": "entity", "alias": "Internal Name" } as External Name
    API->>Svc: Authenticate
    """
    assert list(parse_sequence(code).participants.values()) == [
        Participant("API", "Public API", "boundary"),
        Participant("DB", "User Database", "database"),
        Participant("Svc", "Auth Service", "control"),
        Participant("Q", "Q", "queue"),
        Participant("X", "External Name", "entity"),
    ]


def test_create_and_destroy() -> None:
    code = """sequenceDiagram
    Alice->>Bob: Hello Bob, how are you ?
    create participant Carl
    Alice->>Carl: Hi Carl!
    create actor D as Donald
    Carl->>D: Hi!
    destroy Carl
    Alice-xCarl: We are too many
    """
    diagram = parse_sequence(code)
    assert labels(code) == ["Alice", "Bob", "Carl", "Donald"]
    assert diagram.participants["D"].kind == "actor"
    assert diagram.messages[-1] == Message("Alice", "Carl", "We are too many", "-x")
    assert diagram.warnings == []


def test_participants_in_boxes() -> None:
    code = """sequenceDiagram
    box Purple Alice & John
    participant A
    participant J
    end
    box Another Group
    participant B
    end
    A->>J: Hello John, how are you?
    A->>B: Hello Bob, how is Charley?
    """
    diagram = parse_sequence(code)
    assert list(diagram.participants) == ["A", "J", "B"]
    assert len(diagram.messages) == 2 and diagram.warnings == []


def test_note_creates_an_undeclared_participant() -> None:
    # As Mermaid draws it: `User` is not the alias-declared `U`, so the note adds a second lifeline.
    code = "sequenceDiagram\n    participant U as User\n    Note over User, App: Logowanie\n    U->>App: Dane"
    assert list(parse_sequence(code).participants) == ["U", "User", "App"]


def test_repeated_declaration_without_alias_keeps_the_label() -> None:
    assert labels("sequenceDiagram\n    participant A as Alicja\n    participant A\n    A->>B: hej") == ["Alicja", "B"]


def test_participant_ids_with_spaces_hyphens_and_polish_characters() -> None:
    code = "sequenceDiagram\n    Dział obsługi->>System-CRM: Zgłoszenie\n    System-CRM-->>Dział obsługi: Numer"
    assert messages(code) == [("Dział obsługi", "System-CRM", "Zgłoszenie"), ("System-CRM", "Dział obsługi", "Numer")]


# --- messages -------------------------------------------------------------------------------------

ARROWS = ["->", "-->", "->>", "-->>", "<<->>", "<<-->>", "-x", "--x", "-)", "--)"]
HALF_ARROWS = ["-|\\", "--|\\", "-|/", "--|/", "/|-", "/|--", "\\\\-", "\\\\--", "-\\\\", "--\\\\", "-//", "--//", "//-", "//--"]


@pytest.mark.parametrize("arrow", ARROWS + HALF_ARROWS)
@pytest.mark.parametrize("spacing", ["{}", " {} "])
def test_arrow_types(arrow: str, spacing: str) -> None:
    diagram = parse_sequence(f"sequenceDiagram\n    Alice{spacing.format(arrow)}Bob: Cześć")
    assert diagram.messages == [Message("Alice", "Bob", "Cześć", arrow)]
    assert diagram.warnings == []


def test_activation_suffix() -> None:
    code = "sequenceDiagram\n    Alice->>+John: Hello John, how are you?\n    John-->>-Alice: Great!"
    assert messages(code) == [("Alice", "John", "Hello John, how are you?"), ("John", "Alice", "Great!")]


def test_central_connections() -> None:
    code = "sequenceDiagram\n    Alice->>()John: Hello John\n    Alice()->>John: How are you?\n    John()->>()Alice: Great!"
    assert messages(code) == [
        ("Alice", "John", "Hello John"),
        ("Alice", "John", "How are you?"),
        ("John", "Alice", "Great!"),
    ]


def test_message_to_self() -> None:
    assert messages("sequenceDiagram\n    John->>John: Fight against hypochondria") == [
        ("John", "John", "Fight against hypochondria")
    ]


def test_message_text_is_cleaned() -> None:
    code = "sequenceDiagram\n    A->>B: Hello John,<br/>how are you?\n    B->>A: I #9829; you #infin; times more!\n    A->>B: a #59; b: c"
    assert [m.text for m in parse_sequence(code).messages] == [
        "Hello John, how are you?",
        "I ♥ you ∞ times more!",
        "a ; b: c",
    ]


# --- skipped and unknown lines --------------------------------------------------------------------


def test_messages_inside_blocks_are_kept_and_blocks_are_skipped() -> None:
    code = """sequenceDiagram
    autonumber
    Alice->>Bob: Hello Bob, how are you?
    alt is sick
        Bob->>Alice: Not so good :(
    else is well
        Bob->>Alice: Feeling fresh like a daisy
    end
    opt Extra response
        Bob->>Alice: Thanks for asking
    end
    loop Every minute
        Alice->>Bob: Ping
    end
    par Alice to Bob
        Alice->>Bob: Hello guys!
    and Alice to John
        Alice->>John: Hello guys!
    end
    critical Establish a connection to the DB
        Service-->DB: connect
    option Network timeout
        Service-->Service: Log error
    end
    break when the booking process fails
        API-->Consumer: show failure
    end
    rect rgb(191, 223, 255)
        activate Bob
        Bob-->>Alice: Great!
        deactivate Bob
    end
    """
    diagram = parse_sequence(code)
    assert len(diagram.messages) == 11
    assert list(diagram.participants) == ["Alice", "Bob", "John", "Service", "DB", "API", "Consumer"]
    assert diagram.warnings == []


def test_notes_and_menus_are_not_messages() -> None:
    code = """sequenceDiagram
    participant Alice
    participant John
    link Alice: Dashboard @ https://dashboard.contoso.com/alice
    links John: {"Dashboard": "https://dashboard.contoso.com/john"}
    Note right of John: Text in note
    Note over Alice,John: Alice->>John: not a message
    Alice->>John: Hello John, how are you?
    """
    diagram = parse_sequence(code)
    assert messages(code) == [("Alice", "John", "Hello John, how are you?")]
    assert labels(code) == ["Alice", "John"] and diagram.warnings == []


def test_unknown_line_is_skipped_with_warning() -> None:
    diagram = parse_sequence("sequenceDiagram\n    A->>B: Dane\n    A --> B\n    B-->>A: Wynik")
    assert len(diagram.messages) == 2
    assert diagram.warnings == ["unrecognized statement: 'A --> B'"]
