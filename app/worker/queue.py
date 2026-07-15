"""Job queues with delivery-id de-duplication.

Two implementations behind one small interface (``put`` / ``get`` /
``task_done``):

- :class:`JobQueue` — in-process ``asyncio.Queue``. Zero infrastructure, jobs
  and dedupe state die with the process. The default.
- :class:`~app.worker.redis_queue.RedisJobQueue` — durable, shared across
  processes/hosts. Selected with ``QUEUE_BACKEND=redis``.

``make_queue`` picks one from settings; the redis module is only imported when
actually selected.
"""

import asyncio
from collections import OrderedDict
from typing import TYPE_CHECKING, Protocol

from ..config import Settings
from .jobs import ReviewJob

if TYPE_CHECKING:
    from .redis_queue import RedisJobQueue


class SupportsJobQueue(Protocol):
    async def put(self, job: ReviewJob) -> bool: ...
    async def get(self) -> ReviewJob: ...
    async def task_done(self, job: ReviewJob) -> None: ...


class JobQueue:
    """In-process queue (v1). See module docstring."""

    def __init__(self, maxsize: int = 100, dedupe_size: int = 512) -> None:
        self._queue: asyncio.Queue[ReviewJob] = asyncio.Queue(maxsize=maxsize)
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._dedupe_size = dedupe_size

    async def put(self, job: ReviewJob) -> bool:
        """Enqueue a job. Returns False if this delivery was already seen."""
        if job.delivery_id and job.delivery_id in self._seen:
            return False
        if job.delivery_id:
            self._seen[job.delivery_id] = None
            while len(self._seen) > self._dedupe_size:
                self._seen.popitem(last=False)
        await self._queue.put(job)
        return True

    async def get(self) -> ReviewJob:
        return await self._queue.get()

    async def task_done(self, job: ReviewJob) -> None:
        self._queue.task_done()


def make_queue(settings: Settings) -> "JobQueue | RedisJobQueue":
    if settings.queue_backend == "redis":
        from .redis_queue import RedisJobQueue  # lazy: only pay the import when used

        return RedisJobQueue(settings.redis_url, dedupe_ttl=settings.job_dedupe_ttl)
    return JobQueue()
