# English Voice Bot

A personal Telegram bot for practicing spoken English. Send a voice message, get an immediate transcription, hear a short spoken reply, and reveal the written answer only when you are ready. The review button analyzes new learner messages and gives concise corrections in Russian.

## Features

- Telegram long polling with aiogram 3.x.
- Voice-message transcription through OpenRouter Speech-to-Text.
- Friendly conversation replies through an OpenRouter chat model.
- Text-to-Speech replies through OpenRouter, sent back as Telegram voice messages.
- Hidden assistant text using Telegram spoiler formatting.
- Reply keyboard action: `🔍 Find my mistakes`.
- Inline action: `🧹 Reset dialogue`.
- Local SQLite persistence with SQLAlchemy async API.
- No permanent audio storage.

## Create a Telegram Bot

1. Open Telegram and message `@BotFather`.
2. Send `/newbot`.
3. Choose a display name and username for the bot.
4. Copy the bot token BotFather gives you.
5. Put that token into `TELEGRAM_BOT_TOKEN` in your `.env` file.

## Configure Environment

Create `.env` from the example:

```bash
cp .env.example .env
```

Fill in:

```env
TELEGRAM_BOT_TOKEN=your-telegram-token
OPENROUTER_API_KEY=your-openrouter-api-key
```

By default, any private-chat user can use the bot. To restrict it, use numeric Telegram user IDs:

```env
ALLOWED_TELEGRAM_USER_IDS=123456789,987654321
```

Telegram usernames are not supported in this setting because the bot checks Telegram's stable numeric
`from_user.id`.

The default chat model is configured as an explicit free non-Chinese OpenRouter model:

```env
OPENROUTER_CHAT_MODEL=openai/gpt-oss-120b:free
```

STT and TTS may still consume a small OpenRouter credit balance. To switch STT to the cheaper English-oriented alternative:

```env
OPENROUTER_STT_MODEL=nvidia/parakeet-tdt-0.6b-v3
```

The default TTS model is configured to an OpenRouter speech model currently returned by the Models API:

```env
OPENROUTER_TTS_MODEL=hexgrad/kokoro-82m
OPENROUTER_TTS_VOICE=af_heart
```

## Install Dependencies

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run Locally

```bash
source .venv/bin/activate
python -m english_voice_bot.main
```

The bot uses long polling. Do not configure Telegram webhooks for this MVP.

## Run Tests

```bash
source .venv/bin/activate
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest
```

Tests mock Telegram/OpenRouter boundaries and do not make paid API calls.

## Run With Docker

```bash
docker build -t english-voice-bot .
docker run --rm --env-file .env -v "$PWD/data:/app/data" english-voice-bot
```

The volume keeps `data/bot.sqlite3` on the host.

## Run With Docker Compose

Create and fill `.env` first:

```bash
cp .env.example .env
```

Then start the bot:

```bash
docker compose up -d --build
```

View logs:

```bash
docker compose logs -f bot
```

Stop it:

```bash
docker compose down
```

Compose uses `./data:/app/data`, so the SQLite database stays on the host.

## Review Cursor

Learner messages are stored in `dialogue_messages` with `reviewed_at = NULL`. `/review` and the `🔍 Find my mistakes` reply button select only unreviewed user messages, send them to the review prompt, and mark those exact user-message rows as reviewed only after the report is successfully sent to Telegram.

Assistant messages are stored as context but are not marked reviewed. `/reset` and the reset inline button delete the current session dialogue history.

## Audio Storage

Incoming Telegram audio is downloaded into memory, sent to OpenRouter STT, and discarded. Generated TTS audio is also kept only in memory long enough to send it to Telegram. Audio files are not stored permanently.
# govorilka
