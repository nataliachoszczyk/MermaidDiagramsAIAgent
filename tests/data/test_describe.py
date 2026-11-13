from mermaiddiagramsaiagent.data.describe import label_coverage, strip_thinking

DIAGRAM = """flowchart TD
    A[Receive order] --> B{Is it paid?}
    B -->|Yes| C[Ship order]
    B -->|No| D[Send reminder]"""


def test_strip_thinking_removes_block() -> None:
    assert strip_thinking("<think>\nhmm, let me see\n</think>\n\nThe process starts.") == "The process starts."


def test_strip_thinking_keeps_plain_text() -> None:
    assert strip_thinking("  The process starts. ") == "The process starts."


def test_label_coverage_all_labels_present() -> None:
    description = "First we receive order. Then: is it paid? If yes, ship order; if not, send reminder."
    assert label_coverage(DIAGRAM, description) == 1.0


def test_label_coverage_counts_paraphrases_as_missing() -> None:
    description = "We receive order and check payment. Paid orders: ship order. Otherwise we remind the customer."
    assert label_coverage(DIAGRAM, description) == 0.5


def test_label_coverage_matches_whole_words_only() -> None:
    assert label_coverage("flowchart TD\n    A[Pay] --> B[Ship]", "Payment is made, shipping follows.") == 0.0
