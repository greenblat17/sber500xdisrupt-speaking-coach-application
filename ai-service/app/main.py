from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from openai import AsyncOpenAI

from app.config import Settings
from app.dialogue import DialogueStore
from app.jobs import ClipJob, JobStore
from app.llm import OpenAiChatModel
from app.pipeline import ClipPipeline
from app.sessions import GREETING_TEXT, SessionRegistry
from app.stt import GroqSpeechToText
from app.tts import OpenAiTextToSpeech

logger = logging.getLogger(__name__)

CONTENT_TYPE_OGG = "audio/ogg"


def create_app(
    settings: Settings | None = None,
    pipeline: ClipPipeline | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    logging.basicConfig(level=settings.log_level)
    jobs = JobStore(ttl_seconds=settings.job_ttl_seconds)
    clip_pipeline = pipeline or _build_pipeline(settings)
    sessions = SessionRegistry()
    greeting_audio: bytes | None = None
    greeting_lock = asyncio.Lock()
    tasks: set[asyncio.Task[None]] = set()

    app = FastAPI()
    app.state.settings = settings
    app.state.jobs = jobs
    app.state.pipeline = clip_pipeline

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/sessions", status_code=201)
    def create_session() -> dict:
        session_id = sessions.create()
        return {"sessionId": session_id, "greeting": {"text": GREETING_TEXT}}

    @app.get("/v1/sessions/{session_id}/greeting/audio")
    async def greeting_audio_route(session_id: str) -> Response:
        if not sessions.exists(session_id):
            raise HTTPException(status_code=404, detail="unknown session")
        nonlocal greeting_audio
        async with greeting_lock:
            if greeting_audio is None:
                greeting_audio = await clip_pipeline.tts.synthesize(GREETING_TEXT)
            return Response(content=greeting_audio, media_type=CONTENT_TYPE_OGG)

    @app.post("/v1/clips", status_code=202)
    async def create_clip(
        sessionId: str = Form(),
        audio: UploadFile = File(),
    ) -> dict[str, str]:
        if not sessions.exists(sessionId):
            raise HTTPException(status_code=404, detail="unknown session")
        payload = await audio.read()
        if not payload:
            raise HTTPException(status_code=400, detail="empty audio")
        job = jobs.create(sessionId)
        content_type = audio.content_type or "audio/ogg"
        filename = audio.filename or "voice.ogg"
        task = asyncio.create_task(
            _run_job(job, payload, content_type, filename, clip_pipeline, settings.pipeline_timeout_seconds),
        )
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return {"jobId": job.job_id}

    @app.get("/v1/clips/{job_id}")
    def get_clip(job_id: str) -> JSONResponse:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown job")
        return JSONResponse(job.to_status())

    @app.get("/v1/clips/{job_id}/audio")
    def get_audio(job_id: str) -> Response:
        job = jobs.get(job_id)
        if job is None or job.status != "ok" or job.reply_audio is None:
            return Response(status_code=404)
        return Response(content=job.reply_audio, media_type=job.reply_content_type)

    return app


def _build_pipeline(settings: Settings) -> ClipPipeline:
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is required")
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required")
    groq = AsyncOpenAI(api_key=settings.groq_api_key, base_url=settings.groq_base_url)
    openai_headers = {}
    if "openrouter.ai" in settings.openai_base_url:
        openai_headers = {
            "HTTP-Referer": "https://github.com/greenblat17/sber500xdisrupt-speaking-coach-application",
            "X-Title": "Speaking Coach",
        }
    openai_client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        default_headers=openai_headers or None,
    )
    return ClipPipeline(
        stt=GroqSpeechToText(groq, settings.stt_model, settings.ffmpeg_bin),
        llm=OpenAiChatModel(openai_client, settings.llm_model),
        tts=OpenAiTextToSpeech(
            openai_client,
            settings.tts_model,
            settings.tts_voice,
            settings.tts_response_format,
            settings.ffmpeg_bin,
        ),
        dialogue=DialogueStore(settings.dialogue_max_messages, settings.dialogue_ttl_seconds),
    )


async def _run_job(
    job: ClipJob,
    audio: bytes,
    content_type: str,
    filename: str,
    pipeline: ClipPipeline,
    timeout_seconds: float,
) -> None:
    try:
        result = await asyncio.wait_for(
            pipeline.run(job.session_id, audio, content_type, filename),
            timeout=timeout_seconds,
        )
        job.transcript = result.transcript
        job.reply_text = result.reply_text
        job.notes = list(result.notes)
        job.timings_ms = result.timings_ms
        job.reply_audio = result.audio
        job.reply_content_type = CONTENT_TYPE_OGG
        job.status = "ok"
    except Exception as error:
        logger.exception("clip job failed job_id=%s session=%s", job.job_id, job.session_id)
        job.status = "error"
        job.error = {"code": _error_code(error), "message": _public_error(error)}


def _error_code(error: BaseException) -> str:
    if isinstance(error, TimeoutError) or isinstance(error, asyncio.TimeoutError):
        return "timeout"
    return "pipeline_failed"


def _public_error(error: BaseException) -> str:
    text = str(error).strip() or error.__class__.__name__
    if len(text) > 240:
        return text[:240]
    return text
