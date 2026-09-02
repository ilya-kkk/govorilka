from __future__ import annotations

from pathlib import Path

from english_vocab_bot.anki_builder import build_apkg
from english_vocab_bot.services.anki_export import export_words_to_apkg
from english_vocab_bot.translator import Translator
from english_vocab_bot.validators import validate_apkg


def test_build_apkg_creates_valid_package(tmp_path: Path) -> None:
    cards = [
        ("chapter", "глава / этап жизни"),
        ("feel anxious", "тревожиться / чувствовать беспокойство"),
    ]

    output_path = tmp_path / "test_vocab.apkg"

    build_apkg(cards, output_path)

    validate_apkg(output_path, expected_cards=2)


async def test_export_words_to_apkg_uses_translator(tmp_path: Path) -> None:
    output_path = tmp_path / "exported_vocab.apkg"

    await export_words_to_apkg(
        words=["chapter", "unknown word"],
        translator=Translator(),
        output_path=output_path,
        deck_name="English Vocabulary",
    )

    validate_apkg(output_path, expected_cards=2)
