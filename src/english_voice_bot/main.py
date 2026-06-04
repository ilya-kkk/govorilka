from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher

from english_voice_bot.config import Settings
from english_voice_bot.db import create_engine, create_session_factory, init_db
from english_voice_bot.handlers import callbacks, commands, dialogue
from english_voice_bot.logging_config import configure_logging
from english_voice_bot.services.openrouter import OpenRouterClient

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
        logger.info("Starting bot long polling")
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            await dispatcher.start_polling(
                bot,
                settings=settings,
                session_factory=session_factory,
                openrouter_client=openrouter_client,
            )
        finally:
            await bot.session.close()
            await engine.dispose()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
