from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import openai

T = TypeVar("T")


def is_retryable(error: BaseException) -> bool:
    if isinstance(error, openai.RateLimitError):
        return True
    if isinstance(error, openai.APIStatusError):
        return error.status_code is not None and (error.status_code == 429 or error.status_code >= 500)
    return False


async def once_on_retryable(factory: Callable[[], Awaitable[T]], delay_seconds: float = 0.5) -> T:
    try:
        return await factory()
    except Exception as error:
        if not is_retryable(error):
            raise
        await asyncio.sleep(delay_seconds)
        return await factory()
