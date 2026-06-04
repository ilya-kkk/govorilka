from __future__ import annotations

from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Message

from english_voice_bot.config import Settings


def is_allowed_user(user_id: int | None, settings: Settings) -> bool:
    if user_id is None:
        return False
    return not settings.allowed_telegram_user_ids or user_id in settings.allowed_telegram_user_ids


async def reject_message_if_not_allowed(message: Message, settings: Settings) -> bool:
    if message.chat.type != ChatType.PRIVATE:
        await message.answer("Please open a private chat with me first.")
        return True
    if not is_allowed_user(message.from_user.id if message.from_user else None, settings):
        await message.answer("This bot is private.")
        return True
    return False


async def reject_callback_if_not_allowed(
    callback: CallbackQuery,
    settings: Settings,
    *,
    already_answered: bool = False,
) -> bool:
    if not is_allowed_user(callback.from_user.id if callback.from_user else None, settings):
        if already_answered and callback.message is not None:
            await callback.message.answer("This bot is private.")
        else:
            await callback.answer("This bot is private.", show_alert=True)
        return True
    return False
