from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from english_voice_bot.config import Settings
from english_voice_bot.db import session_scope
from english_voice_bot.handlers.guards import reject_callback_if_not_allowed
from english_voice_bot.repositories import clear_session_dialogue, get_or_create_session

router = Router()


@router.callback_query(F.data == "dialogue:reset")
async def reset_callback(
    callback: CallbackQuery,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await callback.answer()
    if await reject_callback_if_not_allowed(callback, settings, already_answered=True):
        return
    if callback.message is None:
        return

    async with session_scope(session_factory) as db:
        session = await get_or_create_session(
            db,
            telegram_chat_id=callback.message.chat.id,
            telegram_user_id=callback.from_user.id,
        )
        deleted_count = await clear_session_dialogue(db, session_id=session.id)
        await db.commit()

    await callback.message.answer(f"🧹 Dialogue history cleared. Removed {deleted_count} messages.")
