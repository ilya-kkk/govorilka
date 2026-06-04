from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from english_voice_bot.models import ChatSession, DialogueMessage, utc_now

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"

SOURCE_VOICE = "voice"
SOURCE_TEXT = "text"
SOURCE_GENERATED = "generated"


async def get_or_create_session(
    db: AsyncSession,
    *,
    telegram_chat_id: int,
    telegram_user_id: int,
) -> ChatSession:
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.telegram_chat_id == telegram_chat_id,
            ChatSession.telegram_user_id == telegram_user_id,
        )
    )
    session = result.scalar_one_or_none()
    if session is not None:
        session.updated_at = utc_now()
        await db.flush()
        return session

    session = ChatSession(
        telegram_chat_id=telegram_chat_id,
        telegram_user_id=telegram_user_id,
    )
    db.add(session)
    await db.flush()
    return session


async def add_dialogue_message(
    db: AsyncSession,
    *,
    session_id: int,
    role: str,
    source_type: str,
    content: str,
    telegram_message_id: int | None = None,
) -> DialogueMessage:
    message = DialogueMessage(
        session_id=session_id,
        telegram_message_id=telegram_message_id,
        role=role,
        source_type=source_type,
        content=content,
    )
    db.add(message)
    await db.flush()
    return message


async def get_recent_conversation_context(
    db: AsyncSession,
    *,
    session_id: int,
    limit: int,
) -> list[DialogueMessage]:
    result = await db.execute(
        select(DialogueMessage)
        .where(DialogueMessage.session_id == session_id)
        .order_by(DialogueMessage.id.desc())
        .limit(limit)
    )
    return list(reversed(result.scalars().all()))


async def get_unreviewed_user_messages(
    db: AsyncSession,
    *,
    session_id: int,
    limit: int,
) -> list[DialogueMessage]:
    result = await db.execute(
        select(DialogueMessage)
        .where(
            DialogueMessage.session_id == session_id,
            DialogueMessage.role == ROLE_USER,
            DialogueMessage.reviewed_at.is_(None),
        )
        .order_by(DialogueMessage.id.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_context_around_selected_messages(
    db: AsyncSession,
    *,
    session_id: int,
    selected_message_ids: Sequence[int],
    window_size: int = 3,
) -> list[DialogueMessage]:
    if not selected_message_ids:
        return []

    result = await db.execute(
        select(DialogueMessage)
        .where(DialogueMessage.session_id == session_id)
        .order_by(DialogueMessage.id.asc())
    )
    all_messages = list(result.scalars().all())
    selected_ids = set(selected_message_ids)
    selected_indexes = [index for index, message in enumerate(all_messages) if message.id in selected_ids]
    if not selected_indexes:
        return []

    keep_indexes: set[int] = set()
    for index in selected_indexes:
        start = max(0, index - window_size)
        end = min(len(all_messages), index + window_size + 1)
        keep_indexes.update(range(start, end))

    return [message for index, message in enumerate(all_messages) if index in keep_indexes]


async def mark_messages_reviewed(
    db: AsyncSession,
    *,
    session_id: int,
    message_ids: Sequence[int],
) -> int:
    if not message_ids:
        return 0
    result = await db.execute(
        update(DialogueMessage)
        .where(
            DialogueMessage.session_id == session_id,
            DialogueMessage.role == ROLE_USER,
            DialogueMessage.id.in_(message_ids),
        )
        .values(reviewed_at=utc_now())
    )
    await db.flush()
    return int(result.rowcount or 0)


async def clear_session_dialogue(db: AsyncSession, *, session_id: int) -> int:
    result = await db.execute(delete(DialogueMessage).where(DialogueMessage.session_id == session_id))
    await db.flush()
    return int(result.rowcount or 0)


async def count_session_messages(db: AsyncSession, *, session_id: int) -> int:
    result = await db.execute(
        select(func.count(DialogueMessage.id)).where(DialogueMessage.session_id == session_id)
    )
    return int(result.scalar_one())
