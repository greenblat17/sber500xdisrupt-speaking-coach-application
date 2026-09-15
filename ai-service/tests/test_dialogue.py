from __future__ import annotations

import pytest
from fakeredis import FakeAsyncRedis

from app.dialogue import MemoryDialogueStore, RedisDialogueStore, build_dialogue_store
from tests.conftest import test_settings as settings_for_tests


@pytest.mark.asyncio
async def test_memory_create_is_get_or_create() -> None:
    store = MemoryDialogueStore(max_messages=40, ttl_seconds=86400)

    async def generate(history, user_text: str) -> str:
        return f"echo:{user_text}:{len(history)}"

    first = await store.create("tg-1")
    assert first == "tg-1"
    await store.complete_turn("tg-1", "hello", generate)
    second = await store.create("tg-1")
    assert second == "tg-1"
    history = await store.history("tg-1")
    assert [item.content for item in history] == ["hello", "echo:hello:0"]


@pytest.mark.asyncio
async def test_memory_unknown_session_does_not_exist() -> None:
    store = MemoryDialogueStore(max_messages=40, ttl_seconds=86400)
    assert await store.exists("missing") is False


@pytest.mark.asyncio
async def test_memory_trims_old_messages() -> None:
    store = MemoryDialogueStore(max_messages=2, ttl_seconds=86400)
    await store.create("s")

    async def generate(history, user_text: str) -> str:
        return "ok"

    await store.complete_turn("s", "one", generate)
    await store.complete_turn("s", "two", generate)
    history = await store.history("s")
    assert [item.content for item in history] == ["two", "ok"]


@pytest.mark.asyncio
async def test_redis_create_does_not_wipe_messages() -> None:
    redis = FakeAsyncRedis(decode_responses=True)
    store = RedisDialogueStore(redis, max_messages=40, ttl_seconds=86400)

    async def generate(history, user_text: str) -> str:
        return "ok"

    await store.create("tg-9")
    await store.complete_turn("tg-9", "hello", generate)
    await store.create("tg-9")
    history = await store.history("tg-9")
    assert [item.content for item in history] == ["hello", "ok"]
    assert await store.exists("missing") is False
    await store.aclose()


def test_build_store_without_redis_url_is_memory() -> None:
    store = build_dialogue_store(settings_for_tests())
    assert isinstance(store, MemoryDialogueStore)
