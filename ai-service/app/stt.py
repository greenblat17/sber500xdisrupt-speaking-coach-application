from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from openai import AsyncOpenAI, BadRequestError

from app.audio import to_wav_mono_16k
from app.retry import once_on_retryable


@dataclass
class SttResult:
    text: str
    raw: dict[str, Any] = field(default_factory=dict)
    no_speech: bool = False


class SpeechToText(Protocol):
    async def transcribe(self, audio: bytes, content_type: str, filename: str) -> SttResult:
        ...


class GroqSpeechToText:
    def __init__(self, client: AsyncOpenAI, model: str, ffmpeg_bin: str) -> None:
        self._client = client
        self._model = model
        self._ffmpeg_bin = ffmpeg_bin

    async def transcribe(self, audio: bytes, content_type: str, filename: str) -> SttResult:
        try:
            return await self._transcribe_file(audio, filename, content_type)
        except BadRequestError:
            wav = await to_wav_mono_16k(self._ffmpeg_bin, audio, suffix=_suffix(filename))
            return await self._transcribe_file(wav, "voice.wav", "audio/wav")

    async def _transcribe_file(self, audio: bytes, filename: str, content_type: str) -> SttResult:
        async def call() -> Any:
            return await self._client.audio.transcriptions.create(
                model=self._model,
                file=(filename, audio, content_type),
                language="en",
                response_format="verbose_json",
                timestamp_granularities=["word"],
            )

        response = await once_on_retryable(call)
        payload = _as_dict(response)
        text = str(payload.get("text") or "").strip()
        no_speech_prob = _no_speech_prob(payload)
        return SttResult(text=text, raw=payload, no_speech=not text or no_speech_prob >= 0.8)


def _suffix(filename: str) -> str:
    if "." in filename:
        return "." + filename.rsplit(".", 1)[-1]
    return ".ogg"


def _as_dict(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    dump = getattr(response, "model_dump", None)
    if callable(dump):
        return dump()
    return {"text": getattr(response, "text", "")}


def _no_speech_prob(payload: dict[str, Any]) -> float:
    segments = payload.get("segments") or []
    if not segments:
        return float(payload.get("no_speech_prob") or 0)
    values = [float(segment.get("no_speech_prob") or 0) for segment in segments if isinstance(segment, dict)]
    return max(values) if values else 0.0
