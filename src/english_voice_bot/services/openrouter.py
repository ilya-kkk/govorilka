from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Sequence
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class OpenRouterError(RuntimeError):
    """Raised when OpenRouter cannot produce a valid response."""


class OpenRouterClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        chat_model: str,
        stt_model: str,
        tts_model: str,
        tts_voice: str,
        tts_speed: float,
        client: httpx.AsyncClient | None = None,
        timeout: float = 45.0,
        max_retries: int = 2,
        retry_base_delay: float = 0.5,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._chat_model = chat_model
        self._stt_model = stt_model
        self._tts_model = tts_model
        self._tts_voice = tts_voice
        self._tts_speed = tts_speed
        self._timeout = httpx.Timeout(timeout)
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> OpenRouterClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def chat_completion(
        self,
        messages: Sequence[dict[str, str]],
        *,
        temperature: float = 0.7,
    ) -> str:
        payload = {
            "model": self._chat_model,
            "messages": list(messages),
            "temperature": temperature,
        }
        data = await self._post_json("/chat/completions", payload)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenRouterError("Malformed chat completion response") from exc
        if not isinstance(content, str) or not content.strip():
            raise OpenRouterError("Empty chat completion response")
        return content.strip()

    async def chat_completion_json_schema(
        self,
        messages: Sequence[dict[str, str]],
        *,
        schema_name: str,
        schema: dict[str, Any],
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        payload = {
            "model": self._chat_model,
            "messages": list(messages),
            "temperature": temperature,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        data = await self._post_json("/chat/completions", payload)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenRouterError("Malformed structured completion response") from exc
        if not isinstance(content, str) or not content.strip():
            raise OpenRouterError("Empty structured completion response")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise OpenRouterError("Structured completion returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise OpenRouterError("Structured completion returned non-object JSON")
        return parsed

    async def transcribe_ogg(self, audio_bytes: bytes) -> str:
        encoded_audio = base64.b64encode(audio_bytes).decode("ascii")
        payload = {
            "model": self._stt_model,
            "input_audio": {
                "data": encoded_audio,
                "format": "ogg",
            },
        }
        data = await self._post_json("/audio/transcriptions", payload)
        text = data.get("text")
        if not isinstance(text, str):
            raise OpenRouterError("Malformed transcription response")
        return text.strip()

    async def synthesize_speech_mp3(self, text: str) -> bytes:
        payload = {
            "model": self._tts_model,
            "input": text,
            "voice": self._tts_voice,
            "response_format": "mp3",
            "speed": self._tts_speed,
        }
        if self._tts_model.startswith("openai/"):
            payload["provider"] = {
                "options": {
                    "openai": {
                        "instructions": (
                            "Speak naturally, clearly, and conversationally. Use a friendly tone. "
                            "Do not sound like a formal audiobook narrator."
                        )
                    }
                }
            }
        return await self._post_bytes("/audio/speech", payload)

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._post(path, payload)
        try:
            data = response.json()
        except ValueError as exc:
            raise OpenRouterError("OpenRouter returned malformed JSON") from exc
        if not isinstance(data, dict):
            raise OpenRouterError("OpenRouter returned unexpected JSON")
        return data

    async def _post_bytes(self, path: str, payload: dict[str, Any]) -> bytes:
        response = await self._post(path, payload)
        if not response.content:
            raise OpenRouterError("OpenRouter returned empty audio")
        return response.content

    async def _post(self, path: str, payload: dict[str, Any]) -> httpx.Response:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)

        url = f"{self._base_url}{path}"
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.post(url, headers=self._headers, json=payload, timeout=self._timeout)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt < self._max_retries:
                    await self._sleep_before_retry(attempt, path, "network_error")
                    continue
                raise OpenRouterError("OpenRouter request failed") from exc

            if response.status_code in {429} or 500 <= response.status_code <= 599:
                if attempt < self._max_retries:
                    await self._sleep_before_retry(attempt, path, f"http_{response.status_code}")
                    continue

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                message = f"OpenRouter request failed with HTTP {response.status_code}"
                error_detail = self._format_error_detail(response)
                if error_detail:
                    message = f"{message}: {error_detail}"
                raise OpenRouterError(message) from exc
            return response

        raise OpenRouterError("OpenRouter request failed after retries") from last_error

    @staticmethod
    def _format_error_detail(response: httpx.Response) -> str:
        try:
            data = response.json()
        except ValueError:
            return response.text[:500].strip()
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict):
                message = error.get("message")
                if isinstance(message, str):
                    return message[:500]
            message = data.get("message")
            if isinstance(message, str):
                return message[:500]
        return response.text[:500].strip()

    async def _sleep_before_retry(self, attempt: int, path: str, reason: str) -> None:
        delay = self._retry_base_delay * (2**attempt)
        logger.warning(
            "Retrying OpenRouter request",
            extra={"path": path, "attempt": attempt + 1, "reason": reason, "delay": delay},
        )
        if delay > 0:
            await asyncio.sleep(delay)
