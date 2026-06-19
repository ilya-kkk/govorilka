from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from english_voice_bot.repositories import count_practice_questions, upsert_practice_questions
from english_voice_bot.services.question_bank import (
    extract_question_texts,
    load_question_rows_from_json,
    load_questions_from_json,
    seed_question_bank,
)


def test_extract_question_texts_supports_common_json_shapes() -> None:
    data = {
        "AI": [
            "How can AI improve sales?",
            {"question": "What AI tool would you build for founders?"},
        ],
        "items": [{"text": "How should a company measure AI ROI?"}],
    }

    texts = extract_question_texts(data)

    assert texts == [
        "How can AI improve sales?",
        "What AI tool would you build for founders?",
        "How should a company measure AI ROI?",
    ]


def test_load_questions_from_json(tmp_path) -> None:
    path = tmp_path / "Questions.json"
    path.write_text(
        json.dumps([{"prompt": "What business process should AI automate first?"}]),
        encoding="utf-8",
    )

    assert load_questions_from_json(path) == ["What business process should AI automate first?"]


def test_load_repository_questions_json() -> None:
    path = Path(__file__).resolve().parents[1] / "questions.json"

    rows = load_question_rows_from_json(path, default_topic="AI and business")

    assert len(rows) == 378
    assert rows[0] == (
        "json:1",
        "How would you structure a production FastAPI service for an LLM-powered application?",
        "Python, Backend Engineering, and APIs",
    )


async def test_seed_question_bank_loads_json_file(
    tmp_path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    path = tmp_path / "questions.json"
    path.write_text(
        json.dumps(["How can AI help customer support?", "How can AI help customer support?"]),
        encoding="utf-8",
    )

    async with session_factory() as db:
        inserted = await seed_question_bank(db, question_bank_path=str(path), include_builtin=False)
        total = await count_practice_questions(db)

    assert inserted == 1
    assert total == 1


async def test_seed_question_bank_removes_stale_questions(
    tmp_path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    path = tmp_path / "questions.json"
    path.write_text(json.dumps(["How should a team evaluate an AI feature?"]), encoding="utf-8")

    async with session_factory() as db:
        await upsert_practice_questions(db, questions=[("stale", "Old fallback question?", "AI")])
        inserted = await seed_question_bank(db, question_bank_path=str(path), include_builtin=False)
        total = await count_practice_questions(db)

    assert inserted == 1
    assert total == 1
