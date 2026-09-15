from __future__ import annotations

from uuid import uuid4

GREETING_TEXT = (
    "Hi! I'm SpeakEasy AI. Send me a voice message and let's practice English."
)


class SessionRegistry:
    def __init__(self) -> None:
        self._ids: set[str] = set()

    def create(self) -> str:
        session_id = str(uuid4())
        self._ids.add(session_id)
        return session_id

    def exists(self, session_id: str) -> bool:
        return session_id in self._ids
