from __future__ import annotations

from collections.abc import Sequence
import logging
from typing import Any, Protocol

from english_voice_bot.services.openrouter import OpenRouterClient, OpenRouterError

logger = logging.getLogger(__name__)

MISSING_TRANSLATION = "перевод нужно добавить"

DEMO_TRANSLATIONS = {
    "embracing": "принятие / открытое отношение к чему-то",
    "chapter": "глава / этап жизни",
    "excites": "воодушевляет / вызывает интерес",
    "burden": "бремя / нагрузка",
    "feel anxious": "тревожиться / чувствовать беспокойство",
    "rather than": "а не / вместо того чтобы",
}

TRANSLATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "word": {"type": "string"},
                    "translation": {"type": "string"},
                },
                "required": ["word", "translation"],
            },
        }
    },
    "required": ["translations"],
}


class SyncTranslator(Protocol):
    def translate_many(self, words: list[str]) -> dict[str, str]: ...


class AsyncTranslator(Protocol):
    async def translate_many(self, words: list[str]) -> dict[str, str]: ...


class Translator:
    def translate_many(self, words: list[str]) -> dict[str, str]:
        return {
            word: DEMO_TRANSLATIONS.get(word.lower().strip(), MISSING_TRANSLATION)
            for word in words
        }


class OpenRouterTranslator:
    def __init__(self, client: OpenRouterClient) -> None:
        self._client = client

    async def translate_many(self, words: list[str]) -> dict[str, str]:
        if not words:
            return {}

        messages = [
            {
                "role": "system",
                "content": (
                    "You translate English vocabulary into concise natural Russian for Anki cards. "
                    "Return only JSON matching the provided schema. Keep each original English word "
                    "or phrase in the word field. For multiple useful meanings, separate Russian "
                    "variants with ' / '. Do not add examples or explanations."
                ),
            },
            {
                "role": "user",
                "content": "Translate these English words and phrases:\n" + "\n".join(words),
            },
        ]

        data = await self._client.chat_completion_json_schema(
            messages,
            schema_name="english_vocab_translations",
            schema=TRANSLATION_SCHEMA,
            temperature=0.1,
        )
        return _translations_from_response(words, data)


class FallbackTranslator:
    def __init__(self, primary: AsyncTranslator, fallback: SyncTranslator | None = None) -> None:
        self._primary = primary
        self._fallback = fallback or Translator()

    async def translate_many(self, words: list[str]) -> dict[str, str]:
        try:
            return await self._primary.translate_many(words)
        except OpenRouterError:
            logger.exception("OpenRouter translation failed; using fallback translations")
            return self._fallback.translate_many(words)


def _translations_from_response(words: Sequence[str], data: dict[str, Any]) -> dict[str, str]:
    raw_items = data.get("translations")
    if not isinstance(raw_items, list):
        return Translator().translate_many(list(words))

    by_normalized_word: dict[str, str] = {}
    ordered_translations: list[str] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        word = item.get("word")
        translation = item.get("translation")
        if not isinstance(word, str) or not isinstance(translation, str):
            continue
        translation = translation.strip()
        if not translation:
            continue
        by_normalized_word[_normalize_word(word)] = translation
        ordered_translations.append(translation)

    fallback = Translator().translate_many(list(words))
    translations: dict[str, str] = {}
    for index, word in enumerate(words):
        translation = by_normalized_word.get(_normalize_word(word))
        if translation is None and len(ordered_translations) == len(words):
            translation = ordered_translations[index]
        translations[word] = translation or fallback[word]
    return translations


def _normalize_word(word: str) -> str:
    return word.lower().strip()
