from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from english_voice_bot.repositories import sync_practice_questions

logger = logging.getLogger(__name__)
QuestionRow = tuple[str, str, str | None]

BUILTIN_AI_BUSINESS_QUESTIONS = (
    "How can a small business use AI without making its product feel generic?",
    "What AI task would you automate first in a startup, and why?",
    "How should a company decide whether to build an AI feature or buy an existing tool?",
    "What is one business risk of relying too much on AI-generated content?",
    "How can AI help a founder understand customers better?",
    "What kind of AI product would you pay for every month?",
    "How would you explain the value of an AI assistant to a non-technical business owner?",
    "What is more important for an AI startup: a better model or better distribution?",
    "How can companies use AI while still keeping a human touch?",
    "What business process do you think AI will change the most in the next five years?",
    "How would you test whether an AI feature actually saves users time?",
    "What is one ethical concern a business should consider before using AI?",
    "How can AI help with marketing without sounding fake?",
    "What would make you trust an AI tool with important business decisions?",
    "How should a founder talk about AI in a pitch without overhyping it?",
)


def normalize_question_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def question_source_key(text: str) -> str:
    normalized = normalize_question_text(text).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def question_rows_from_texts(texts: list[str], *, topic: str | None = None) -> list[QuestionRow]:
    rows: list[QuestionRow] = []
    seen: set[str] = set()
    for text in texts:
        normalized = normalize_question_text(text)
        if not normalized:
            continue
        source_key = question_source_key(normalized)
        if source_key in seen:
            continue
        seen.add(source_key)
        rows.append((source_key, normalized, topic))
    return rows


async def seed_question_bank(
    db: AsyncSession,
    *,
    question_bank_path: str,
    include_builtin: bool,
) -> int:
    rows: list[QuestionRow] = []
    if include_builtin:
        rows.extend(question_rows_from_texts(list(BUILTIN_AI_BUSINESS_QUESTIONS), topic="AI and business"))

    path = Path(question_bank_path)
    if path.exists():
        rows.extend(load_question_rows_from_json(path, default_topic="AI and business"))
    else:
        logger.info("Question bank file not found", extra={"path": str(path)})

    return await sync_practice_questions(db, questions=rows)


def load_questions_from_json(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return extract_question_texts(data)


def load_question_rows_from_json(path: Path, *, default_topic: str | None = None) -> list[QuestionRow]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return extract_question_rows(data, default_topic=default_topic)


def extract_question_texts(data: Any) -> list[str]:
    texts: list[str] = []
    _collect_question_texts(data, texts)
    deduped: list[str] = []
    seen: set[str] = set()
    for text in texts:
        source_key = question_source_key(text)
        if source_key in seen:
            continue
        seen.add(source_key)
        deduped.append(text)
    return deduped


def extract_question_rows(data: Any, *, default_topic: str | None = None) -> list[QuestionRow]:
    if isinstance(data, dict) and isinstance(data.get("questions"), list):
        rows = _question_rows_from_question_objects(data["questions"], default_topic=default_topic)
        if rows:
            return rows
    return question_rows_from_texts(extract_question_texts(data), topic=default_topic)


def _question_rows_from_question_objects(
    questions: list[Any],
    *,
    default_topic: str | None,
) -> list[QuestionRow]:
    rows: list[QuestionRow] = []
    seen: set[str] = set()
    for index, item in enumerate(questions, start=1):
        if not isinstance(item, dict):
            continue

        text = _question_text_from_mapping(item)
        if text is None:
            continue

        source_key = _source_key_from_question_object(item, text=text, index=index)
        if source_key in seen:
            source_key = question_source_key(f"{source_key}:{index}:{text}")
        seen.add(source_key)
        rows.append((source_key, text, _question_topic_from_mapping(item, default_topic=default_topic)))
    return rows


def _question_text_from_mapping(item: dict[str, Any]) -> str | None:
    for key in ("question", "text", "prompt"):
        value = item.get(key)
        if isinstance(value, str):
            normalized = normalize_question_text(value)
            if normalized:
                return normalized
    return None


def _source_key_from_question_object(item: dict[str, Any], *, text: str, index: int) -> str:
    raw_id = item.get("id")
    if raw_id is not None:
        normalized_id = normalize_question_text(str(raw_id))
        if normalized_id:
            source_key = f"json:{normalized_id}"
            if len(source_key) <= 64 and re.fullmatch(r"[\w:.-]+", source_key):
                return source_key
            return question_source_key(source_key)
    return question_source_key(f"{index}:{text}")


def _question_topic_from_mapping(item: dict[str, Any], *, default_topic: str | None) -> str | None:
    for key in ("category", "section", "topic"):
        value = item.get(key)
        if isinstance(value, str):
            normalized = normalize_question_text(value)
            if normalized:
                return normalized
    return default_topic


def _collect_question_texts(value: Any, texts: list[str]) -> None:
    if isinstance(value, str):
        stripped = normalize_question_text(value)
        if _looks_like_question(stripped):
            texts.append(stripped)
        return

    if isinstance(value, list):
        for item in value:
            _collect_question_texts(item, texts)
        return

    if not isinstance(value, dict):
        return

    text = _question_text_from_mapping(value)
    if text is not None:
        texts.append(text)
        return

    for item in value.values():
        if isinstance(item, list | dict):
            _collect_question_texts(item, texts)


def _looks_like_question(text: str) -> bool:
    return bool(text) and (text.endswith("?") or len(text.split()) >= 4)
