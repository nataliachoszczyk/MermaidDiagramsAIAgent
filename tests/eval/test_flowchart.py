import pytest

from mermaiddiagramsaiagent.eval.flowchart import Edge, Node, ParseError, clean_label, parse_flowchart


def edge_pairs(code: str) -> list[tuple[str, str]]:
    return [(e.src, e.dst) for e in parse_flowchart(code).edges]


# --- header ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "direction"),
    [("flowchart TD", "TD"), ("flowchart LR", "LR"), ("graph TB", "TB"), ("flowchart", "TB"), ("graph BT;", "BT")],
)
def test_header_direction(header: str, direction: str) -> None:
    assert parse_flowchart(f"{header}\n    A --> B").direction == direction


@pytest.mark.parametrize("code", ["", "   \n  ", "sequenceDiagram\n    A->>B: hi", "Flowchart TD\n A --> B"])
def test_invalid_header_raises(code: str) -> None:
    with pytest.raises(ParseError):
        parse_flowchart(code)


def test_front_matter_and_init_directive_are_skipped() -> None:
    code = '---\ntitle: Proces\n---\n%%{init: {"theme": "dark"}}%%\nflowchart TD\n    A --> B'
    assert edge_pairs(code) == [("A", "B")]


# --- nodes ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("definition", "shape"),
    [
        ("A[Złóż wniosek]", "rect"),
        ("A(Złóż wniosek)", "round"),
        ("A([Złóż wniosek])", "stadium"),
        ("A[[Złóż wniosek]]", "subroutine"),
        ("A[(Złóż wniosek)]", "cylinder"),
        ("A((Złóż wniosek))", "circle"),
        ("A(((Złóż wniosek)))", "double_circle"),
        ("A{Złóż wniosek}", "rhombus"),
        ("A{{Złóż wniosek}}", "hexagon"),
        ("A>Złóż wniosek]", "asymmetric"),
        ("A[/Złóż wniosek/]", "parallelogram"),
        ("A[\\Złóż wniosek\\]", "parallelogram_alt"),
        ("A[/Złóż wniosek\\]", "trapezoid"),
        ("A[\\Złóż wniosek/]", "trapezoid_alt"),
    ],
)
def test_node_shapes(definition: str, shape: str) -> None:
    chart = parse_flowchart(f"flowchart TD\n    {definition}")
    assert chart.nodes == {"A": Node("A", "Złóż wniosek", shape)}
    assert chart.warnings == []


def test_quoted_label_may_contain_delimiters() -> None:
    chart = parse_flowchart('flowchart TD\n    A["Czy kwota > 1000 (brutto)? [PLN]"] --> B')
    assert chart.nodes["A"].label == "Czy kwota > 1000 (brutto)? [PLN]"


def test_label_starting_with_paren_falls_back_to_rect() -> None:
    chart = parse_flowchart("flowchart TD\n    A[(opcjonalnie) sprawdź dane]")
    assert chart.nodes["A"] == Node("A", "(opcjonalnie) sprawdź dane", "rect")


def test_bare_id_uses_id_as_label() -> None:
    chart = parse_flowchart("flowchart TD\n    Start --> Koniec")
    assert chart.nodes == {"Start": Node("Start", "Start", "rect"), "Koniec": Node("Koniec", "Koniec", "rect")}


def test_node_defined_once_and_referenced_later_keeps_label() -> None:
    chart = parse_flowchart("flowchart TD\n    A[Start] --> B[Krok]\n    B --> A")
    assert chart.nodes["A"].label == "Start"
    assert len(chart.nodes) == 2


def test_repeated_definition_is_one_node() -> None:
    chart = parse_flowchart("flowchart TD\n    A --> Z([Koniec])\n    B --> Z([Koniec])")
    assert list(chart.nodes) == ["A", "Z", "B"]


def test_label_defined_after_first_reference() -> None:
    chart = parse_flowchart("flowchart TD\n    A --> B\n    B[Zapisz dane]")
    assert chart.nodes["B"] == Node("B", "Zapisz dane", "rect")


def test_class_suffix_is_ignored() -> None:
    chart = parse_flowchart("flowchart TD\n    A[Start]:::green --> B:::red")
    assert edge_pairs("flowchart TD\n    A[Start]:::green --> B:::red") == [("A", "B")]
    assert chart.nodes["A"].label == "Start"
    assert chart.warnings == []


def test_polish_characters_in_ids() -> None:
    assert edge_pairs("flowchart TD\n    Zgłoszenie --> Weryfikacja") == [("Zgłoszenie", "Weryfikacja")]


# --- edges ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("arrow", ["-->", "--->", "---", "-.->", "-.-", "==>", "===", "--o", "--x", "<-->", "~~~"])
def test_link_types(arrow: str) -> None:
    chart = parse_flowchart(f"flowchart TD\n    A {arrow} B")
    assert [(e.src, e.dst) for e in chart.edges] == [("A", "B")]
    assert chart.warnings == []


def test_links_without_spaces() -> None:
    assert edge_pairs("flowchart TD\n    A-->B\n    B-.->C") == [("A", "B"), ("B", "C")]


@pytest.mark.parametrize(
    "link", ["-->|Tak|", "--> |Tak|", "-- Tak -->", "-- Tak ---", "-. Tak .->", "== Tak ==>", '-->|"Tak"|']
)
def test_edge_labels(link: str) -> None:
    chart = parse_flowchart(f"flowchart TD\n    A{{Czy poprawne?}} {link} B[Zapisz]")
    assert chart.edges == [Edge("A", "B", "Tak")]
    assert chart.warnings == []


def test_chain() -> None:
    assert edge_pairs("flowchart LR\n    A --> B --> C --> D") == [("A", "B"), ("B", "C"), ("C", "D")]


def test_chain_with_labels_and_shapes() -> None:
    chart = parse_flowchart("flowchart LR\n    A[Start] -->|wejście| B{Decyzja} -- nie --> C([Koniec])")
    assert chart.edges == [Edge("A", "B", "wejście"), Edge("B", "C", "nie")]
    assert chart.nodes["B"].shape == "rhombus"


def test_ampersand_groups() -> None:
    assert edge_pairs("flowchart TD\n    A & B --> C & D") == [("A", "C"), ("A", "D"), ("B", "C"), ("B", "D")]


def test_semicolons_separate_statements() -> None:
    assert edge_pairs("graph TD;\n    A-->B;\n    B-->C; C-->D") == [("A", "B"), ("B", "C"), ("C", "D")]


# --- skipped and unknown lines --------------------------------------------------------------------


def test_styling_subgraphs_and_comments_are_skipped_silently() -> None:
    code = """flowchart TD
    %% komentarz
    subgraph Płatność [Obsługa płatności]
        direction LR
        A[Zapłać] --> B[Potwierdź]
    end
    classDef zielony fill:#9f9
    class A zielony
    style B fill:#f99
    linkStyle 0 stroke:#333
    click A "https://example.com"
    """
    chart = parse_flowchart(code)
    assert [(e.src, e.dst) for e in chart.edges] == [("A", "B")]
    assert chart.warnings == []


def test_unknown_line_is_skipped_with_warning() -> None:
    chart = parse_flowchart("flowchart TD\n    A --> B\n    ??? coś dziwnego\n    B --> C")
    assert [(e.src, e.dst) for e in chart.edges] == [("A", "B"), ("B", "C")]
    assert len(chart.warnings) == 1


def test_unparsed_tail_is_reported() -> None:
    chart = parse_flowchart("flowchart TD\n    A --> B ???")
    assert [(e.src, e.dst) for e in chart.edges] == [("A", "B")]
    assert len(chart.warnings) == 1


# --- labels ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('"Zapisz dane"', "Zapisz dane"),
        ("Zapisz<br>dane", "Zapisz dane"),
        ("Zapisz<br/>dane", "Zapisz dane"),
        ("Zapisz <BR /> dane", "Zapisz dane"),
        ('"`**Zapisz** dane`"', "**Zapisz** dane"),
        ("  Zapisz   dane  ", "Zapisz dane"),
    ],
)
def test_clean_label(raw: str, expected: str) -> None:
    assert clean_label(raw) == expected


# --- realistic example ----------------------------------------------------------------------------


def test_realistic_diagram() -> None:
    code = """flowchart TD
    A([Start]) --> B[Klient składa zamówienie]
    B --> C{Czy produkt jest dostępny?}
    C -->|Tak| D[Przyjmij płatność]
    C -->|Nie| E[Poinformuj klienta]
    D --> F([Koniec])
    E --> F([Koniec])
    """
    chart = parse_flowchart(code)
    assert [n.label for n in chart.nodes.values()] == [
        "Start",
        "Klient składa zamówienie",
        "Czy produkt jest dostępny?",
        "Przyjmij płatność",
        "Poinformuj klienta",
        "Koniec",
    ]
    assert sum(n.shape == "rhombus" for n in chart.nodes.values()) == 1
    assert chart.edges == [
        Edge("A", "B", ""),
        Edge("B", "C", ""),
        Edge("C", "D", "Tak"),
        Edge("C", "E", "Nie"),
        Edge("D", "F", ""),
        Edge("E", "F", ""),
    ]
    assert chart.warnings == []
