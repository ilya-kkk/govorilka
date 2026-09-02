from __future__ import annotations


def parse_words(raw_text: str) -> list[str]:
    """Parse newline-separated words/phrases, preserving first-seen spelling."""
    words: list[str] = []
    seen: set[str] = set()

    for line in raw_text.splitlines():
        word = line.strip()
        if not word:
            continue

        normalized = word.lower()
        if normalized in seen:
            continue

        seen.add(normalized)
        words.append(word)

    return words
