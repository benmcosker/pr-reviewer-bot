"""In-process job queue with delivery-id de-duplication.

v1 uses an ``asyncio.Queue`` — one process, simplest thing that demonstrates the
webhook/worker decoupling. The public surface (``put`` / ``get`` / ``task_done``)
is deliberately small so a Redis-backed implementation (arq/RQ) can drop in.
"""

import asyncio
from collections import OrderedDict

from .jobs import ReviewJob


class JobQueue:
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

    def task_done(self) -> None:
        self._queue.task_done()
