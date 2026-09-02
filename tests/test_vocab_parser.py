from __future__ import annotations

from english_vocab_bot.parser import parse_words


def test_parse_words_removes_empty_lines_and_duplicates() -> None:
    raw = """
    Embracing
    chapter

    embracing
    feel anxious
     rather than
    """

    assert parse_words(raw) == [
        "Embracing",
        "chapter",
        "feel anxious",
        "rather than",
    ]
