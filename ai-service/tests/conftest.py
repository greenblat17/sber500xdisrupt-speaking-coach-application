from __future__ import annotations

from app.config import Settings
from app.dialogue import DialogueStore
from app.llm import ChatModel, LlmTurn
from app.main import create_app
from app.pipeline import ClipPipeline
from app.stt import SpeechToText, SttResult
from app.tts import TextToSpeech


def test_settings() -> Settings:
    return Settings(
        groq_api_key=None,
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        groq_base_url="https://api.groq.com/openai/v1",
        stt_model="whisper-large-v3",
        llm_model="gpt-5.6-luna",
        tts_model="gpt-4o-mini-tts",
        tts_voice="coral",
        tts_response_format="opus",
        ffmpeg_bin="ffmpeg",
        dialogue_ttl_seconds=86400,
        dialogue_max_messages=40,
        job_ttl_seconds=600,
        pipeline_timeout_seconds=60,
        log_level="INFO",
    )


class FakeStt(SpeechToText):
    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)
        self.calls = 0

    async def transcribe(self, audio: bytes, content_type: str, filename: str) -> SttResult:
        self.calls += 1
        text = self._texts.pop(0) if self._texts else ""
        return SttResult(text=text, no_speech=not text.strip())


class FakeLlm(ChatModel):
    def __init__(self, notes: list[str] | None = None) -> None:
        self.calls: list[tuple[list[str], str]] = []
        self.notes = list(notes or [])

    async def complete(self, history, user_text: str) -> LlmTurn:
        self.calls.append(([item.content for item in history], user_text))
        return LlmTurn(reply_text=f"Got it: {user_text}", notes=list(self.notes))


class FakeTts(TextToSpeech):
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def synthesize(self, text: str) -> bytes:
        self.texts.append(text)
        return b"OggS" + text.encode("utf-8")


def build_app(
    stt: FakeStt | None = None,
    llm: FakeLlm | None = None,
    tts: FakeTts | None = None,
    dialogue: DialogueStore | None = None,
):
    stt = stt or FakeStt(["hello"])
    llm = llm or FakeLlm()
    tts = tts or FakeTts()
    dialogue = dialogue or DialogueStore(max_messages=40, ttl_seconds=86400)
    pipeline = ClipPipeline(stt=stt, llm=llm, tts=tts, dialogue=dialogue)
    return create_app(settings=test_settings(), pipeline=pipeline), stt, llm, tts
