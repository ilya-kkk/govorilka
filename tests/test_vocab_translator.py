from __future__ import annotations

from english_vocab_bot.translator import MISSING_TRANSLATION, Translator, _translations_from_response


def test_demo_translator_returns_known_and_missing_translations() -> None:
    translator = Translator()

    assert translator.translate_many(["chapter", "unknown word"]) == {
        "chapter": "глава / этап жизни",
        "unknown word": MISSING_TRANSLATION,
    }


def test_translations_from_response_matches_words_case_insensitively() -> None:
    result = _translations_from_response(
        ["Chapter", "feel anxious"],
        {
            "translations": [
                {"word": "chapter", "translation": "глава"},
                {"word": "Feel Anxious", "translation": "тревожиться"},
            ]
        },
    )

    assert result == {
        "Chapter": "глава",
        "feel anxious": "тревожиться",
    }
