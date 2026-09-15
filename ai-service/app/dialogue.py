from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class _Session:
    messages: list[ChatMessage] = field(default_factory=list)
    updated_at: float = field(default_factory=time.monotonic)


class DialogueStore:
    def __init__(self, max_messages: int, ttl_seconds: int) -> None:
        self._max_messages = max_messages
        self._ttl_seconds = ttl_seconds
        self._sessions: dict[str, _Session] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._meta = asyncio.Lock()

    async def history(self, session_id: str) -> list[ChatMessage]:
        async with await self._lock_for(session_id):
            session = self._live_session(session_id)
            if session is None:
                return []
            return list(session.messages)

    async def complete_turn(
        self,
        session_id: str,
        user_text: str,
        generate: Callable[[list[ChatMessage], str], Awaitable[str]],
    ) -> str:
        async with await self._lock_for(session_id):
            session = self._live_session(session_id)
            history = list(session.messages) if session is not None else []
            reply = await generate(history, user_text)
            if session is None:
                session = _Session()
                self._sessions[session_id] = session
            session.messages.append(ChatMessage("user", user_text))
            session.messages.append(ChatMessage("assistant", reply))
            overflow = len(session.messages) - self._max_messages
            if overflow > 0:
                session.messages = session.messages[overflow:]
            session.updated_at = time.monotonic()
            return reply

    async def _lock_for(self, session_id: str) -> asyncio.Lock:
        async with self._meta:
            lock = self._locks.get(session_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[session_id] = lock
            return lock

    def _live_session(self, session_id: str) -> _Session | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if time.monotonic() - session.updated_at > self._ttl_seconds:
            self._sessions.pop(session_id, None)
            return None
        return session
