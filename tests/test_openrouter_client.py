from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx

from english_voice_bot.services.openrouter import OpenRouterClient, OpenRouterError


def make_client(*, tts_model: str = "tts-model") -> OpenRouterClient:
    return OpenRouterClient(
        api_key="secret",
        base_url="https://openrouter.ai/api/v1",
        chat_model="chat-model",
        stt_model="stt-model",
        tts_model=tts_model,
        tts_voice="nova",
        tts_speed=1.0,
        max_retries=2,
        retry_base_delay=0,
    )


@pytest.mark.asyncio
@respx.mock
async def test_stt_request_shape() -> None:
    route = respx.post("https://openrouter.ai/api/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "hello"})
    )

    async with make_client() as client:
        text = await client.transcribe_ogg(b"ogg-bytes")

    payload = json.loads(route.calls.last.request.content)
    assert text == "hello"
    assert payload == {
        "model": "stt-model",
        "input_audio": {
            "data": base64.b64encode(b"ogg-bytes").decode("ascii"),
            "format": "ogg",
        },
    }
    assert route.calls.last.request.headers["Authorization"] == "Bearer secret"


@pytest.mark.asyncio
@respx.mock
async def test_tts_request_shape() -> None:
    route = respx.post("https://openrouter.ai/api/v1/audio/speech").mock(
        return_value=httpx.Response(200, content=b"mp3")
    )

    async with make_client() as client:
        audio = await client.synthesize_speech_mp3("Hi there")

    payload = json.loads(route.calls.last.request.content)
    assert audio == b"mp3"
    assert payload["model"] == "tts-model"
    assert payload["input"] == "Hi there"
    assert payload["voice"] == "nova"
    assert payload["response_format"] == "mp3"
    assert payload["speed"] == 1.0
    assert "provider" not in payload


@pytest.mark.asyncio
@respx.mock
async def test_tts_request_includes_instructions_for_openai_model() -> None:
    route = respx.post("https://openrouter.ai/api/v1/audio/speech").mock(
        return_value=httpx.Response(200, content=b"mp3")
    )

    async with make_client(tts_model="openai/gpt-4o-mini-tts") as client:
        audio = await client.synthesize_speech_mp3("Hi there")

    payload = json.loads(route.calls.last.request.content)
    assert audio == b"mp3"
    assert "instructions" in payload["provider"]["options"]["openai"]


@pytest.mark.asyncio
@respx.mock
async def test_openrouter_error_includes_response_message() -> None:
    respx.post("https://openrouter.ai/api/v1/audio/speech").mock(
        return_value=httpx.Response(
            400,
            json={"error": {"message": "Model does not exist", "code": 400}},
        )
    )

    async with make_client() as client:
        with pytest.raises(OpenRouterError, match="Model does not exist"):
            await client.synthesize_speech_mp3("Hi there")


@pytest.mark.asyncio
@respx.mock
async def test_chat_completion_request_shape() -> None:
    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Assistant answer"}}]},
        )
    )

    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "hello"}]
    async with make_client() as client:
        answer = await client.chat_completion(messages, temperature=0.7)

    payload = json.loads(route.calls.last.request.content)
    assert answer == "Assistant answer"
    assert payload == {"model": "chat-model", "messages": messages, "temperature": 0.7}


@pytest.mark.asyncio
@respx.mock
async def test_structured_chat_completion_request_shape() -> None:
    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"ok": true}'}}]},
        )
    )

    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["ok"],
        "properties": {"ok": {"type": "boolean"}},
    }
    messages = [{"role": "user", "content": "return json"}]
    async with make_client() as client:
        answer = await client.chat_completion_json_schema(
            messages,
            schema_name="test_schema",
            schema=schema,
        )

    payload = json.loads(route.calls.last.request.content)
    assert answer == {"ok": True}
    assert payload == {
        "model": "chat-model",
        "messages": messages,
        "temperature": 0.1,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "test_schema",
                "strict": True,
                "schema": schema,
            },
        },
    }


@pytest.mark.asyncio
@respx.mock
async def test_retries_429_and_5xx_responses() -> None:
    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(429, json={"error": "rate limit"}),
            httpx.Response(500, json={"error": "server"}),
            httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}),
        ]
    )

    async with make_client() as client:
        answer = await client.chat_completion([{"role": "user", "content": "hello"}])

    assert answer == "ok"
    assert route.call_count == 3
