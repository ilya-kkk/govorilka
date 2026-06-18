from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from english_voice_bot.config import Settings
from english_voice_bot.db import create_engine, create_session_factory, init_db
from english_voice_bot.handlers import callbacks, commands, dialogue, settings as settings_handlers
from english_voice_bot.logging_config import configure_logging
from english_voice_bot.services.openrouter import OpenRouterClient
from english_voice_bot.services.reminder_scheduler import run_reminder_scheduler

logger = logging.getLogger(__name__)


async def main() -> None:
    configure_logging()
    settings = Settings()

    engine = create_engine(settings.database_url)
    await init_db(engine)
    session_factory = create_session_factory(engine)

    bot = Bot(token=settings.telegram_bot_token_value)
    dispatcher = Dispatcher()
    dispatcher.include_router(commands.router)
    dispatcher.include_router(settings_handlers.router)
    dispatcher.include_router(callbacks.router)
    dispatcher.include_router(dialogue.router)

    async with OpenRouterClient(
        api_key=settings.openrouter_api_key_value,
        base_url=settings.openrouter_base_url,
        chat_model=settings.openrouter_chat_model,
        stt_model=settings.openrouter_stt_model,
        tts_model=settings.openrouter_tts_model,
        tts_voice=settings.openrouter_tts_voice,
        tts_speed=settings.openrouter_tts_speed,
    ) as openrouter_client:
        reminder_scheduler_task = asyncio.create_task(
            run_reminder_scheduler(
                bot,
                session_factory,
                interval_seconds=settings.reminder_check_interval_seconds,
            )
        )
        logger.info("Starting bot long polling")
        try:
            await bot.set_my_commands(
                [
                    BotCommand(command="start", description="Show intro"),
                    BotCommand(command="help", description="Show commands"),
                    BotCommand(command="settings", description="Configure reminders"),
                    BotCommand(command="review", description="Review new learner messages"),
                    BotCommand(command="reset", description="Clear dialogue"),
                ]
            )
            await bot.delete_webhook(drop_pending_updates=True)
            await dispatcher.start_polling(
                bot,
                settings=settings,
                session_factory=session_factory,
                openrouter_client=openrouter_client,
            )
        finally:
            reminder_scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await reminder_scheduler_task
            await bot.session.close()
            await engine.dispose()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
