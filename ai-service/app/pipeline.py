from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from app.dialogue import DialogueStore
from app.llm import ChatModel
from app.stt import SpeechToText, SttResult
from app.tts import TextToSpeech

logger = logging.getLogger(__name__)

CLARIFY_TEXT = "I didn't catch that. Could you say it again?"


@dataclass
class PipelineResult:
    audio: bytes
    transcript: str
    reply_text: str
    timings_ms: dict[str, int]
    notes: list[str]


class ClipPipeline:
    def __init__(
        self,
        stt: SpeechToText,
        llm: ChatModel,
        tts: TextToSpeech,
        dialogue: DialogueStore,
    ) -> None:
        self._stt = stt
        self._llm = llm
        self._tts = tts
        self._dialogue = dialogue

    @property
    def tts(self) -> TextToSpeech:
        return self._tts

    @property
    def dialogue(self) -> DialogueStore:
        return self._dialogue

    async def run(
        self,
        session_id: str,
        audio: bytes,
        content_type: str,
        filename: str,
    ) -> PipelineResult:
        started = time.perf_counter()

        stt_started = time.perf_counter()
        stt_result = await self._stt.transcribe(audio, content_type, filename)
        stt_ms = _elapsed_ms(stt_started)

        if _should_clarify(stt_result):
            tts_started = time.perf_counter()
            reply_audio = await self._tts.synthesize(CLARIFY_TEXT)
            timings = {
                "stt": stt_ms,
                "llm": 0,
                "tts": _elapsed_ms(tts_started),
                "total": _elapsed_ms(started),
            }
            logger.info("clip pipeline clarify session=%s timings_ms=%s", session_id, timings)
            return PipelineResult(
                audio=reply_audio,
                transcript=stt_result.text,
                reply_text=CLARIFY_TEXT,
                timings_ms=timings,
                notes=[],
            )

        llm_started = time.perf_counter()
        notes: list[str] = []

        async def generate(history, user_text: str) -> str:
            turn = await self._llm.complete(history, user_text)
            notes.clear()
            notes.extend(turn.notes)
            return turn.reply_text

        reply_text = await self._dialogue.complete_turn(
            session_id,
            stt_result.text,
            generate,
        )
        llm_ms = _elapsed_ms(llm_started)

        tts_started = time.perf_counter()
        reply_audio = await self._tts.synthesize(reply_text)
        timings = {
            "stt": stt_ms,
            "llm": llm_ms,
            "tts": _elapsed_ms(tts_started),
            "total": _elapsed_ms(started),
        }
        logger.info("clip pipeline ok session=%s timings_ms=%s", session_id, timings)
        return PipelineResult(
            audio=reply_audio,
            transcript=stt_result.text,
            reply_text=reply_text,
            timings_ms=timings,
            notes=list(notes),
        )


def _should_clarify(result: SttResult) -> bool:
    return result.no_speech or not result.text.strip()


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
