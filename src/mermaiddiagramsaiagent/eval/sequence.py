"""Parse Mermaid sequenceDiagram code into participants and messages.

Supported: `participant` / `actor` declarations with aliases (`participant A as Alice`), the JSON configuration
(`participant A@{ "type": "database", "alias": "Baza" }`), `create participant`, participants that are only used
in a message or a note, and messages with every arrow type (`->>`, `-->>`, `->`, `-->`, `-x`, `--x`, `-)`, `--)`,
`<<->>`, `<<-->>`, half arrows), the activation suffix (`->>+`, `-->>-`) and central connections (`()`).

Notes, activations, blocks (`loop`, `alt`, `opt`, `par`, `critical`, `break`, `rect`, `box`), `autonumber`,
`title` and actor menus are skipped silently: a message inside a block is still a message, the block itself is
not scored (design.md §4.3). Any other line is skipped with a warning. Whether the code is valid Mermaid is
decided by `mmdc`, not by this parser. Unlike in a flowchart, quotation marks around an alias or a message
text are not syntax: Mermaid draws them, so they stay in the text.
"""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from mermaiddiagramsaiagent.eval.flowchart import ParseError, clean_text

HEADER = "sequenceDiagram"
DEFAULT_KIND = "participant"


@dataclass(frozen=True)
class Participant:
    id: str
    label: str  # the text Mermaid shows: the alias if there is one, otherwise the id
    kind: str  # "participant", "actor", or the "type" of the JSON configuration (e.g. "database")


@dataclass(frozen=True)
class Message:
    src: str
    dst: str
    text: str
    arrow: str


@dataclass
class SequenceDiagram:
    participants: dict[str, Participant] = field(default_factory=dict)  # id -> participant, in order of appearance
    messages: list[Message] = field(default_factory=list)  # in the order of the diagram
    warnings: list[str] = field(default_factory=list)


# Longer arrows first, so that `-->>` is not read as `-->` followed by `>`.
ARROWS = (
    "<<-->>", "<<->>", "-->>", "->>", "--x", "-x", "--)", "-)",
    "--|\\", "--|/", "-|\\", "-|/", "/|--", "/|-", "\\\\--", "\\\\-",
    "--\\\\", "-\\\\", "--//", "-//", "//--", "//-", "-->", "->",
)  # fmt: skip
ARROW = "|".join(re.escape(arrow) for arrow in ARROWS)
MESSAGE_RE = re.compile(
    rf"^(?P<src>[^:]+?)\s*(?:\(\))?(?P<arrow>{ARROW})(?:\(\))?\s*[+-]?\s*(?P<dst>[^:]+?)\s*:(?P<text>.*)$",
    re.IGNORECASE,
)
PARTICIPANT_RE = re.compile(
    r"^(?:create\s+)?(?P<kind>participant|actor)\s+"
    r"(?P<id>.+?)\s*(?:@(?P<config>\{.*\}))?(?:\s+as\s+(?P<alias>.+))?$",
    re.IGNORECASE,
)
NOTE_RE = re.compile(r"^note\s+(?:right\s+of|left\s+of|over)\s+(?P<ids>[^:]+):", re.IGNORECASE)
SKIP_RE = re.compile(
    r"^(?:end|else|and|option|loop|alt|opt|par|par_over|critical|break|rect|box|autonumber|activate|deactivate|"
    r"destroy|title|accTitle|accDescr|link|links|properties|details)\b",
    re.IGNORECASE,
)
SEMICOLON_RE = re.compile(r"(#\w+;)|;")  # `;` ends a statement, except in an entity code such as `#59;`


def parse_sequence(code: str) -> SequenceDiagram:
    statements = list(_statements(code))
    if not statements:
        raise ParseError("empty diagram")
    if statements[0] != HEADER:
        raise ParseError(f"not a sequenceDiagram header: {statements[0]!r}")
    diagram = SequenceDiagram()
    for statement in statements[1:]:
        _parse_statement(statement, diagram)
    return diagram


def _statements(code: str) -> Iterator[str]:
    """Non-empty statements, without YAML front matter and %% comment lines; `;` separates statements."""
    lines = code.strip().splitlines()
    if lines and lines[0].strip() == "---":
        closing = next((i for i, line in enumerate(lines[1:], 1) if line.strip() == "---"), len(lines) - 1)
        lines = lines[closing + 1 :]
    for line in lines:
        if line.strip().startswith("%%"):
            continue
        for statement in SEMICOLON_RE.sub(lambda m: m.group(1) or "\n", line).split("\n"):
            if statement.strip():
                yield statement.strip()


def _parse_statement(statement: str, diagram: SequenceDiagram) -> None:
    """Notes come before messages (a note text may contain an arrow), messages before the skipped keywords."""
    if (declaration := PARTICIPANT_RE.match(statement)) is not None:
        _declare(declaration, diagram)
    elif (note := NOTE_RE.match(statement)) is not None:
        for participant_id in note.group("ids").split(","):
            _use(participant_id.strip(), diagram)
    elif (message := MESSAGE_RE.match(statement)) is not None:
        src, dst = message.group("src"), message.group("dst")
        _use(src, diagram)
        _use(dst, diagram)
        diagram.messages.append(Message(src, dst, clean_text(message.group("text")), message.group("arrow")))
    elif not SKIP_RE.match(statement):
        diagram.warnings.append(f"unrecognized statement: {statement!r}")


def _declare(declaration: re.Match[str], diagram: SequenceDiagram) -> None:
    """An explicit declaration. The `as` alias wins over the "alias" of the JSON configuration."""
    participant_id = declaration.group("id")
    config = _parse_config(declaration.group("config"))
    alias = declaration.group("alias") or config.get("alias")
    existing = diagram.participants.get(participant_id)
    if existing is not None and alias is None:
        return  # declared again without a new label: Mermaid keeps the first one
    kind = str(config.get("type") or declaration.group("kind").lower())
    label = clean_text(str(alias)) if alias is not None else participant_id
    diagram.participants[participant_id] = Participant(participant_id, label, kind)


def _parse_config(raw: str | None) -> dict[str, object]:
    try:
        config = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}
    return config if isinstance(config, dict) else {}


def _use(participant_id: str, diagram: SequenceDiagram) -> None:
    """A participant used without a declaration is created on first use, with its id as label."""
    if participant_id and participant_id not in diagram.participants:
        diagram.participants[participant_id] = Participant(participant_id, participant_id, DEFAULT_KIND)
