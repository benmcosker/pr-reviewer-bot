"""Retry an async operation with exponential backoff.

Used to retry a single file's Claude review in isolation, so a transient
failure on one file doesn't sink the rest of the PR (DESIGN §7).
"""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def call_with_retries(
    factory: Callable[[], Awaitable[T]],
    *,
    attempts: int,
    base_delay: float = 1.0,
    jitter: bool = True,
    label: str = "operation",
) -> T:
    """Await ``factory()``, retrying on any exception up to ``attempts`` times.

    ``factory`` is a zero-arg callable returning a fresh awaitable each call (so
    the coroutine can actually be re-run). Re-raises the last exception if every
    attempt fails.
    """
    last: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await factory()
        except Exception as exc:  # noqa: BLE001 — intentionally broad; caller decides fatality
            last = exc
            if attempt == attempts:
                break
            delay = base_delay * (2 ** (attempt - 1))
            if jitter:
                delay += random.random()
            logger.warning(
                "%s failed (attempt %d/%d): %s — retrying in %.1fs",
                label, attempt, attempts, exc, delay,
            )
            await asyncio.sleep(delay)
    assert last is not None
    raise last
