from __future__ import annotations

from pathlib import Path

import pytest

from english_vocab_bot.validators import validate_apkg, validate_cards


def test_validate_cards_rejects_empty_list() -> None:
    with pytest.raises(ValueError):
        validate_cards([])


def test_validate_cards_rejects_empty_front() -> None:
    with pytest.raises(ValueError):
        validate_cards([("", "перевод")])


def test_validate_cards_rejects_empty_back() -> None:
    with pytest.raises(ValueError):
        validate_cards([("chapter", "")])


def test_validate_cards_rejects_duplicate_front() -> None:
    with pytest.raises(ValueError):
        validate_cards(
            [
                ("chapter", "глава"),
                ("Chapter", "глава"),
            ]
        )


def test_validate_apkg_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        validate_apkg(tmp_path / "missing.apkg", expected_cards=1)
