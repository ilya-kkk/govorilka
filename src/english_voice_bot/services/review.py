from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from english_voice_bot.config import Settings
from english_voice_bot.formatting import escape_markdown_v2, format_review_report, split_telegram_html
from english_voice_bot.prompts import REVIEW_SYSTEM_PROMPT, REVIEW_USER_PROMPT_TEMPLATE
from english_voice_bot.repositories import (
    ROLE_ASSISTANT,
    ROLE_USER,
    get_context_around_selected_messages,
    get_unreviewed_user_messages,
    mark_messages_reviewed,
)
from english_voice_bot.services.openrouter import OpenRouterClient

NO_NEW_MESSAGES_TEXT = "✅ You have no new messages to review. Keep speaking."


@dataclass(frozen=True)
class ReviewResult:
    reviewed_count: int
    sent_chunks: int


def build_review_prompt(context_messages: Sequence[object], selected_message_ids: Sequence[int]) -> str:
    selected = set(selected_message_ids)
    lines: list[str] = []
    for message in context_messages:
        role = getattr(message, "role")
        content = getattr(message, "content")
        message_id = getattr(message, "id")
        if role == ROLE_USER:
            marker = " REVIEW_TARGET" if message_id in selected else ""
            lines.append(f"[learner #{message_id}{marker}] {content}")
        elif role == ROLE_ASSISTANT:
            lines.append(f"[assistant #{message_id}] {content}")

    return REVIEW_USER_PROMPT_TEMPLATE.format(dialogue="\n".join(lines))


async def run_review_flow(
    db: AsyncSession,
    *,
    session_id: int,
    openrouter_client: OpenRouterClient,
    settings: Settings,
    send_html: Callable[[str], Awaitable[None]],
) -> ReviewResult:
    unreviewed_messages = await get_unreviewed_user_messages(
        db,
        session_id=session_id,
        limit=settings.max_review_messages,
    )
    if not unreviewed_messages:
        await send_html(escape_markdown_v2(NO_NEW_MESSAGES_TEXT))
        return ReviewResult(reviewed_count=0, sent_chunks=1)

    selected_ids = [message.id for message in unreviewed_messages]
    context = await get_context_around_selected_messages(
        db,
        session_id=session_id,
        selected_message_ids=selected_ids,
    )
    prompt = build_review_prompt(context, selected_ids)
    report = await openrouter_client.chat_completion(
        [
            {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )
    formatted_report = format_review_report(report)
    chunks = split_telegram_html(formatted_report)
    for chunk in chunks:
        await send_html(chunk)

    reviewed_count = await mark_messages_reviewed(db, session_id=session_id, message_ids=selected_ids)
    await db.commit()
    return ReviewResult(reviewed_count=reviewed_count, sent_chunks=len(chunks))
