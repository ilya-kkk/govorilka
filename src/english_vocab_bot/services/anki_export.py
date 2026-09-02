from __future__ import annotations

from collections.abc import Awaitable
from inspect import isawaitable
from pathlib import Path
from typing import Protocol

from english_vocab_bot.anki_builder import build_apkg
from english_vocab_bot.translator import MISSING_TRANSLATION
from english_vocab_bot.validators import validate_apkg


class TranslatorLike(Protocol):
    def translate_many(self, words: list[str]) -> dict[str, str] | Awaitable[dict[str, str]]: ...


async def export_words_to_apkg(
    *,
    words: list[str],
    translator: TranslatorLike,
    output_path: Path,
    deck_name: str,
) -> Path:
    translations_result = translator.translate_many(words)
    if isawaitable(translations_result):
        translations = await translations_result
    else:
        translations = translations_result

    cards = [
        (word, translations.get(word, MISSING_TRANSLATION).strip() or MISSING_TRANSLATION)
        for word in words
    ]
    build_apkg(cards=cards, output_path=output_path, deck_name=deck_name)
    validate_apkg(output_path, expected_cards=len(cards))
    return output_path
