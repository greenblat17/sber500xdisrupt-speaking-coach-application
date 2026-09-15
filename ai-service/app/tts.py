from __future__ import annotations

from typing import Any, Protocol

from openai import AsyncOpenAI

from app.audio import to_ogg_opus
from app.retry import once_on_retryable

TTS_INSTRUCTIONS = (
    "Warm conversational speaking partner. Natural pace, not a textbook narrator, not overly cheerful."
)


class TextToSpeech(Protocol):
    async def synthesize(self, text: str) -> bytes:
        ...


class OpenAiTextToSpeech:
    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        voice: str,
        response_format: str,
        ffmpeg_bin: str,
    ) -> None:
        self._client = client
        self._model = model
        self._voice = voice
        self._response_format = response_format
        self._ffmpeg_bin = ffmpeg_bin

    async def synthesize(self, text: str) -> bytes:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "voice": self._voice,
            "input": text,
            "response_format": self._response_format,
        }
        if self._model.startswith("openai/"):
            kwargs["instructions"] = TTS_INSTRUCTIONS

        async def call() -> Any:
            return await self._client.audio.speech.create(**kwargs)

        response = await once_on_retryable(call)
        payload = await _audio_bytes(response)
        suffix = ".opus" if self._response_format == "opus" else f".{self._response_format}"
        return await to_ogg_opus(self._ffmpeg_bin, payload, suffix=suffix)


async def _audio_bytes(response: Any) -> bytes:
    if isinstance(response, (bytes, bytearray)):
        return bytes(response)
    read = getattr(response, "aread", None)
    if callable(read):
        return bytes(await read())
    content = getattr(response, "content", None)
    if callable(content):
        return bytes(content())
    if isinstance(content, (bytes, bytearray)):
        return bytes(content)
    raise RuntimeError("tts response had no audio bytes")
