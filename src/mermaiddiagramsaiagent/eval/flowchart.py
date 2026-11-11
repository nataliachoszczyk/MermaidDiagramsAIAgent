"""Parse Mermaid flowchart code into a graph of nodes and edges.

Supported: `flowchart`/`graph` header with direction, node shapes, quoted labels, the common link types
(`-->`, `---`, `-.->`, `==>`, `--o`, `--x`, `<-->`, ...), edge labels (`-->|text|` and `-- text -->`),
chains (`A --> B --> C`) and `&` groups (`A & B --> C`).

Comments, styling and subgraph boundaries are skipped silently. Any other line the parser does not
understand is skipped with a warning, so unusual syntax costs that one line instead of the whole diagram.
Whether the code is valid Mermaid is decided by `mmdc`, not by this parser.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field


class ParseError(ValueError):
    """The code is not a flowchart (empty, or missing / wrong header)."""


@dataclass(frozen=True)
class Node:
    id: str
    label: str
    shape: str


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    label: str


@dataclass
class Flowchart:
    direction: str
    nodes: dict[str, Node] = field(default_factory=dict)  # id -> node, in order of first appearance
    edges: list[Edge] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


HEADER_RE = re.compile(r"^(?:flowchart|graph)(?:\s+(TB|TD|BT|RL|LR))?$")
SKIP_RE = re.compile(r"^(?:%%|subgraph\b|end$|classDef\b|class\b|style\b|linkStyle\b|click\b|direction\b)")
NODE_ID_RE = re.compile(r"\w+")
CLASS_SUFFIX_RE = re.compile(r":::[\w-]+")
GROUP_SEPARATOR_RE = re.compile(r"\s*&\s*")
BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")

# Opening delimiter -> possible (closing delimiter, shape name). Longer openings must come first.
SHAPES: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    ("(((", ((")))", "double_circle"),)),
    ("([", (("])", "stadium"),)),
    ("[[", (("]]", "subroutine"),)),
    ("[(", ((")]", "cylinder"),)),
    ("((", (("))", "circle"),)),
    ("{{", (("}}", "hexagon"),)),
    ("[/", (("/]", "parallelogram"), ("\\]", "trapezoid"))),
    ("[\\", (("\\]", "parallelogram_alt"), ("/]", "trapezoid_alt"))),
    ("[", (("]", "rect"),)),
    ("(", ((")", "round"),)),
    ("{", (("}", "rhombus"),)),
    (">", (("]", "asymmetric"),)),
)

# Link without inline text: -->, --->, ---, -.->, -.-, ==>, ===, --o, --x, ~~~, with optional <, o, x head.
ARROW = r"(?:<|o|x)?(?:-{2,}>|-{3,}|-\.+->|-\.+-|={2,}>|={3,}|-{2,}[ox](?!\w)|={2,}[ox](?!\w)|~{3,})"
# Link with inline text: -- text -->, == text ==>, -. text .->
TEXT_LINK = (
    r"(?:<|o|x)?(?:--|==|-\.)\s*(?P<text>\S.*?)\s*"
    r"(?:-{2,}>|-{3,}|={2,}>|={3,}|\.-+>|\.-|-{2,}[ox](?!\w)|={2,}[ox](?!\w))"
)
LINK_RE = re.compile(rf"\s*(?:{ARROW}|{TEXT_LINK})(?:\s*\|(?P<pipe>[^|]*)\|)?\s*")


def parse_flowchart(code: str) -> Flowchart:
    statements = list(_statements(code))
    if not statements:
        raise ParseError("empty diagram")
    header = HEADER_RE.match(statements[0])
    if header is None:
        raise ParseError(f"not a flowchart header: {statements[0]!r}")
    chart = Flowchart(direction=header.group(1) or "TB")
    for statement in statements[1:]:
        if not SKIP_RE.match(statement):
            _parse_statement(statement, chart)
    return chart


def clean_label(raw: str) -> str:
    """Turn a raw label into plain text: drop quotes, markdown backticks and <br>, collapse whitespace."""
    label = raw.strip()
    if len(label) >= 2 and label[0] == label[-1] == '"':
        label = label[1:-1]
    if len(label) >= 2 and label[0] == label[-1] == "`":
        label = label[1:-1]
    label = BR_RE.sub(" ", label)
    return WHITESPACE_RE.sub(" ", label).strip()


def _statements(code: str) -> Iterator[str]:
    """Non-empty statements, without YAML front matter and %% comment lines; `;` separates statements."""
    lines = code.strip().splitlines()
    if lines and lines[0].strip() == "---":
        closing = next((i for i, line in enumerate(lines[1:], 1) if line.strip() == "---"), len(lines) - 1)
        lines = lines[closing + 1 :]
    for line in lines:
        if line.strip().startswith("%%"):
            continue
        for statement in _split_outside_quotes(line, ";"):
            if statement.strip():
                yield statement.strip()


def _split_outside_quotes(text: str, separator: str) -> list[str]:
    parts, current, in_quotes = [], [], False
    for char in text:
        if char == '"':
            in_quotes = not in_quotes
        if char == separator and not in_quotes:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def _parse_statement(statement: str, chart: Flowchart) -> None:
    group, pos = _parse_group(statement, 0, chart)
    if group is None:
        chart.warnings.append(f"unrecognized statement: {statement!r}")
        return
    while (link := LINK_RE.match(statement, pos)) is not None:
        next_group, next_pos = _parse_group(statement, link.end(), chart)
        if next_group is None:
            break
        label = clean_label(link.group("pipe") or link.group("text") or "")
        chart.edges.extend(Edge(src, dst, label) for src in group for dst in next_group)
        group, pos = next_group, next_pos
    rest = statement[pos:].strip()
    if rest:
        chart.warnings.append(f"unparsed text {rest!r} in statement: {statement!r}")


def _parse_group(text: str, pos: int, chart: Flowchart) -> tuple[list[str] | None, int]:
    """Parse `node (& node)*` starting at pos; registers the nodes. Returns (node ids, end) or (None, pos)."""
    ids: list[str] = []
    while True:
        parsed = _parse_node(text, pos, chart)
        if parsed is None:
            return (ids or None), pos
        node_id, pos = parsed
        ids.append(node_id)
        separator = GROUP_SEPARATOR_RE.match(text, pos)
        if separator is None:
            return ids, pos
        pos = separator.end()


def _parse_node(text: str, pos: int, chart: Flowchart) -> tuple[str, int] | None:
    match = NODE_ID_RE.match(text, pos)
    if match is None:
        return None
    node_id, pos = match.group(), match.end()
    shape = _parse_shape(text, pos)
    if shape is not None:
        label, shape_name, pos = shape
        chart.nodes[node_id] = Node(node_id, label, shape_name)  # a later definition overrides, as in Mermaid
    elif node_id not in chart.nodes:
        chart.nodes[node_id] = Node(node_id, node_id, "rect")  # bare id: Mermaid shows the id as label
    if (suffix := CLASS_SUFFIX_RE.match(text, pos)) is not None:
        pos = suffix.end()
    return node_id, pos


def _parse_shape(text: str, pos: int) -> tuple[str, str, int] | None:
    """Parse a shape with its label right after a node id. Returns (label, shape, end) or None."""
    for opening, closings in SHAPES:
        if not text.startswith(opening, pos):
            continue
        start = pos + len(opening)
        found = _find_closing(text, start, closings)
        if found is not None:
            label_end, closing, shape_name = found
            return clean_label(text[start:label_end]), shape_name, label_end + len(closing)
    return None


def _find_closing(text: str, start: int, closings: tuple[tuple[str, str], ...]) -> tuple[int, str, str] | None:
    """Find where the label ends. A quoted label may contain any delimiter characters."""
    search_from = start
    stripped = text[start:].lstrip()
    if stripped.startswith('"'):
        quote_start = len(text) - len(stripped)
        quote_end = text.find('"', quote_start + 1)
        if quote_end == -1:
            return None
        search_from = quote_end + 1
    candidates = [(text.find(closing, search_from), closing, shape) for closing, shape in closings]
    candidates = [c for c in candidates if c[0] != -1]
    return min(candidates) if candidates else None
