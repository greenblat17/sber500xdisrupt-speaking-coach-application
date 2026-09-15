from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    trimmed = value.strip()
    return trimmed if trimmed else default


def _int_env(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None:
        return default
    return int(raw)


def _float_env(name: str, default: float) -> float:
    raw = _env(name)
    if raw is None:
        return default
    return float(raw)


@dataclass(frozen=True)
class Settings:
    groq_api_key: str | None
    openai_api_key: str | None
    openai_base_url: str
    groq_base_url: str
    stt_model: str
    llm_model: str
    tts_model: str
    tts_voice: str
    tts_response_format: str
    ffmpeg_bin: str
    redis_url: str | None
    dialogue_ttl_seconds: int
    dialogue_max_messages: int
    job_ttl_seconds: int
    pipeline_timeout_seconds: float
    log_level: str

    @staticmethod
    def from_env() -> Settings:
        return Settings(
            groq_api_key=_env("GROQ_API_KEY"),
            openai_api_key=_env("OPENAI_API_KEY"),
            openai_base_url=_env("OPENAI_BASE_URL", "https://openrouter.ai/api/v1") or "https://openrouter.ai/api/v1",
            groq_base_url=_env("GROQ_BASE_URL", "https://api.groq.com/openai/v1") or "https://api.groq.com/openai/v1",
            stt_model=_env("STT_MODEL", "whisper-large-v3") or "whisper-large-v3",
            llm_model=_env("LLM_MODEL", "openai/gpt-4o-mini") or "openai/gpt-4o-mini",
            tts_model=_env("TTS_MODEL", "hexgrad/kokoro-82m") or "hexgrad/kokoro-82m",
            tts_voice=_env("TTS_VOICE", "af_heart") or "af_heart",
            tts_response_format=_env("TTS_RESPONSE_FORMAT", "mp3") or "mp3",
            ffmpeg_bin=_env("FFMPEG_BIN", "ffmpeg") or "ffmpeg",
            redis_url=_env("REDIS_URL"),
            dialogue_ttl_seconds=_int_env("DIALOGUE_TTL_SECONDS", 86400),
            dialogue_max_messages=_int_env("DIALOGUE_MAX_MESSAGES", 40),
            job_ttl_seconds=_int_env("JOB_TTL_SECONDS", 600),
            pipeline_timeout_seconds=_float_env("PIPELINE_TIMEOUT_SECONDS", 60),
            log_level=_env("LOG_LEVEL", "INFO") or "INFO",
        )
