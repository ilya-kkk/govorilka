from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import zipfile


def validate_cards(cards: list[tuple[str, str]]) -> None:
    if not cards:
        raise ValueError("Cards list is empty")

    seen_fronts: set[str] = set()
    for front, back in cards:
        front = front.strip()
        back = back.strip()
        if not front:
            raise ValueError("Card front is empty")
        if not back:
            raise ValueError("Card back is empty")

        normalized_front = front.lower()
        if normalized_front in seen_fronts:
            raise ValueError(f"Duplicate card front: {front}")
        seen_fronts.add(normalized_front)


def validate_apkg(path: Path, expected_cards: int) -> None:
    if not path.exists():
        raise ValueError("APKG file does not exist")

    if path.stat().st_size == 0:
        raise ValueError("APKG file is empty")

    if not zipfile.is_zipfile(path):
        raise ValueError("APKG file is not a valid zip archive")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        with zipfile.ZipFile(path, "r") as zf:
            names = set(zf.namelist())

            if "collection.anki2" not in names:
                raise ValueError("collection.anki2 missing inside APKG")

            if "media" not in names:
                raise ValueError("media manifest missing inside APKG")

            zf.extract("collection.anki2", tmp_path)

        db_path = tmp_path / "collection.anki2"
        conn = sqlite3.connect(db_path)
        try:
            notes_count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
            cards_count = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        finally:
            conn.close()

    if notes_count != expected_cards:
        raise ValueError(f"Expected {expected_cards} notes, got {notes_count}")

    if cards_count != expected_cards:
        raise ValueError(f"Expected {expected_cards} cards, got {cards_count}")
