from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

from redis.asyncio import Redis


@dataclass
class ChatMessage:
    role: str
    content: str


class DialogueStore(Protocol):
    async def create(self, session_id: str | None = None) -> str: ...

    async def exists(self, session_id: str) -> bool: ...

    async def complete_turn(
        self,
        session_id: str,
        user_text: str,
        generate: Callable[[list[ChatMessage], str], Awaitable[str]],
    ) -> str: ...

    async def aclose(self) -> None: ...


@dataclass
class _Session:
    messages: list[ChatMessage] = field(default_factory=list)
    updated_at: float = field(default_factory=time.monotonic)


class MemoryDialogueStore:
    def __init__(self, max_messages: int, ttl_seconds: int) -> None:
        self._max_messages = max_messages
        self._ttl_seconds = ttl_seconds
        self._sessions: dict[str, _Session] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._meta = asyncio.Lock()

    async def create(self, session_id: str | None = None) -> str:
        requested = (session_id or "").strip()
        if requested:
            async with await self._lock_for(requested):
                if self._live_session(requested) is None:
                    self._sessions[requested] = _Session()
                return requested
        new_id = str(uuid4())
        self._sessions[new_id] = _Session()
        return new_id

    async def exists(self, session_id: str) -> bool:
        async with await self._lock_for(session_id):
            return self._live_session(session_id) is not None

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
            session.messages = _trim(session.messages, self._max_messages)
            session.updated_at = time.monotonic()
            return reply

    async def aclose(self) -> None:
        return None

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


class RedisDialogueStore:
    def __init__(self, redis: Redis, max_messages: int, ttl_seconds: int) -> None:
        self._redis = redis
        self._max_messages = max_messages
        self._ttl_seconds = ttl_seconds
        self._locks: dict[str, asyncio.Lock] = {}
        self._meta = asyncio.Lock()

    async def create(self, session_id: str | None = None) -> str:
        requested = (session_id or "").strip()
        session_id = requested or str(uuid4())
        async with await self._lock_for(session_id):
            key = _session_key(session_id)
            if requested and await self._redis.exists(key):
                await self._redis.expire(key, self._ttl_seconds)
                return session_id
            added = await self._redis.set(
                key,
                _dump_messages([]),
                ex=self._ttl_seconds,
                nx=True,
            )
            if not added:
                await self._redis.expire(key, self._ttl_seconds)
            return session_id

    async def exists(self, session_id: str) -> bool:
        return bool(await self._redis.exists(_session_key(session_id)))

    async def history(self, session_id: str) -> list[ChatMessage]:
        raw = await self._redis.get(_session_key(session_id))
        if raw is None:
            return []
        return _load_messages(raw)

    async def complete_turn(
        self,
        session_id: str,
        user_text: str,
        generate: Callable[[list[ChatMessage], str], Awaitable[str]],
    ) -> str:
        async with await self._lock_for(session_id):
            key = _session_key(session_id)
            raw = await self._redis.get(key)
            history = _load_messages(raw) if raw is not None else []
            reply = await generate(history, user_text)
            messages = history + [
                ChatMessage("user", user_text),
                ChatMessage("assistant", reply),
            ]
            messages = _trim(messages, self._max_messages)
            await self._redis.set(key, _dump_messages(messages), ex=self._ttl_seconds)
            return reply

    async def aclose(self) -> None:
        await self._redis.aclose()

    async def _lock_for(self, session_id: str) -> asyncio.Lock:
        async with self._meta:
            lock = self._locks.get(session_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[session_id] = lock
            return lock


def build_dialogue_store(settings: Any, redis: Redis | None = None) -> DialogueStore:
    max_messages = settings.dialogue_max_messages
    ttl_seconds = settings.dialogue_ttl_seconds
    if redis is not None:
        return RedisDialogueStore(redis, max_messages, ttl_seconds)
    url = getattr(settings, "redis_url", None)
    if url:
        return RedisDialogueStore(Redis.from_url(url, decode_responses=True), max_messages, ttl_seconds)
    return MemoryDialogueStore(max_messages, ttl_seconds)


def _session_key(session_id: str) -> str:
    return f"session:{session_id}"


def _trim(messages: list[ChatMessage], max_messages: int) -> list[ChatMessage]:
    overflow = len(messages) - max_messages
    if overflow > 0:
        return messages[overflow:]
    return messages


def _dump_messages(messages: list[ChatMessage]) -> str:
    return json.dumps({"messages": [{"role": item.role, "content": item.content} for item in messages]})


def _load_messages(raw: str | bytes) -> list[ChatMessage]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    payload = json.loads(raw)
    items = payload.get("messages") if isinstance(payload, dict) else []
    if not isinstance(items, list):
        return []
    messages: list[ChatMessage] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "")
        if role:
            messages.append(ChatMessage(role=role, content=content))
    return messages
