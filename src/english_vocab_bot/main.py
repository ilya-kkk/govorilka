from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack, suppress

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from english_voice_bot.logging_config import configure_logging
from english_voice_bot.services.openrouter import OpenRouterClient
from english_vocab_bot.config import VocabularySettings
from english_vocab_bot.db import create_engine, create_session_factory, init_db
from english_vocab_bot.handlers import callbacks, commands, words
from english_vocab_bot.services.scheduler import run_daily_vocab_scheduler
from english_vocab_bot.translator import FallbackTranslator, OpenRouterTranslator, Translator

logger = logging.getLogger(__name__)


async def main() -> None:
    configure_logging()
    settings = VocabularySettings()

    engine = create_engine(settings.vocab_database_url)
    await init_db(engine)
    session_factory = create_session_factory(engine)

    bot = Bot(token=settings.vocab_bot_token_value)
    dispatcher = Dispatcher()
    dispatcher.include_router(commands.router)
    dispatcher.include_router(callbacks.router)
    dispatcher.include_router(words.router)

    async with AsyncExitStack() as stack:
        translator: Translator | FallbackTranslator = Translator()
        openrouter_api_key = settings.openrouter_api_key_value
        if openrouter_api_key is not None:
            openrouter_client = await stack.enter_async_context(
                OpenRouterClient(
                    api_key=openrouter_api_key,
                    base_url=settings.openrouter_base_url,
                    chat_model=settings.openrouter_chat_model,
                    chat_fallback_models=settings.openrouter_chat_fallback_models,
                    stt_model=settings.openrouter_stt_model,
                    tts_model=settings.openrouter_tts_model,
                    tts_voice=settings.openrouter_tts_voice,
                    tts_speed=settings.openrouter_tts_speed,
                )
            )
            translator = FallbackTranslator(OpenRouterTranslator(openrouter_client))
        else:
            logger.warning("OPENROUTER_API_KEY is empty; vocabulary exports will use placeholder translations")

        scheduler_task = asyncio.create_task(
            run_daily_vocab_scheduler(bot, session_factory, settings=settings)
        )
        logger.info("Starting vocabulary bot long polling")
        try:
            await bot.set_my_commands(
                [
                    BotCommand(command="start", description="Start collecting vocabulary"),
                    BotCommand(command="today", description="Show today's vocabulary list"),
                    BotCommand(command="help", description="Show commands"),
                ]
            )
            await bot.delete_webhook(drop_pending_updates=True)
            await dispatcher.start_polling(
                bot,
                settings=settings,
                session_factory=session_factory,
                translator=translator,
            )
        finally:
            scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await scheduler_task
            await bot.session.close()
            await engine.dispose()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
