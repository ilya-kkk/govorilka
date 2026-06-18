from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

REVIEW_BUTTON_TEXT = "🔍"
ASK_ME_BUTTON_TEXT = "❓"
SETTINGS_BUTTON_TEXT = "⚙️"
RESET_BUTTON_TEXT = "🧹"
SETTINGS_REMINDERS_BUTTON_TEXT = "⏰ Настроить напоминания"
CONFIRM_REMINDERS_BUTTON_TEXT = "✅ Да, подтвердить"


def dialogue_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=REVIEW_BUTTON_TEXT),
                KeyboardButton(text=ASK_ME_BUTTON_TEXT),
                KeyboardButton(text=RESET_BUTTON_TEXT),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Send a voice message in English",
    )


def settings_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=SETTINGS_REMINDERS_BUTTON_TEXT, callback_data="settings:reminders")],
        ]
    )


def reminder_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=CONFIRM_REMINDERS_BUTTON_TEXT, callback_data="settings:reminders:confirm")],
        ]
    )
