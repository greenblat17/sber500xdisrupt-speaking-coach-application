from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class ClipJob:
    job_id: str
    session_id: str
    status: str = "pending"
    reply_audio: bytes | None = None
    reply_content_type: str = "audio/ogg"
    transcript: str | None = None
    reply_text: str | None = None
    notes: list[str] = field(default_factory=list)
    timings_ms: dict[str, int] | None = None
    error: dict[str, str] | None = None
    created_at: float = field(default_factory=time.monotonic)

    def to_status(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "jobId": self.job_id,
            "status": self.status,
        }
        if self.error is not None:
            payload["error"] = self.error
        if self.status == "ok":
            payload["result"] = {"notes": list(self.notes)}
        if self.transcript is not None:
            payload["transcript"] = self.transcript
        if self.reply_text is not None:
            payload["replyText"] = self.reply_text
        if self.timings_ms is not None:
            payload["timingsMs"] = self.timings_ms
        return payload


class JobStore:
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._jobs: dict[str, ClipJob] = {}

    def create(self, session_id: str) -> ClipJob:
        self.purge()
        job = ClipJob(job_id=str(uuid4()), session_id=session_id)
        self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> ClipJob | None:
        self.purge()
        return self._jobs.get(job_id)

    def purge(self) -> None:
        now = time.monotonic()
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if now - job.created_at > self._ttl_seconds
        ]
        for job_id in expired:
            self._jobs.pop(job_id, None)
