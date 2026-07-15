"""Redis-backed job queue (v2): durable, shared across processes and hosts.

Layout (all under one namespace):
- ``<ns>:queue``        LIST — pending jobs, JSON-encoded ReviewJobs
- ``<ns>:processing``   LIST — jobs a worker has picked up but not finished
- ``<ns>:delivery:<id>`` STRING with TTL — delivery-id dedupe marker

Reliable-queue pattern: ``get`` atomically moves a job from ``queue`` to
``processing`` (BLMOVE), ``task_done`` removes it (LREM). If a worker dies
mid-job the payload survives in ``processing``; ``recover()`` pushes such
leftovers back onto ``queue``.

Recovery caveat: ``recover()`` assumes no *other* worker is mid-job when it
runs (true when a single deployment restarts as a unit — the normal case).
Running it while workers on another host are busy would double-enqueue their
in-flight jobs. Even then the result is a duplicate review attempt, not
duplicate comments — posting is idempotent per (path, line) via the marker.
"""

import asyncio
from typing import Any

from .jobs import ReviewJob


class RedisJobQueue:
    def __init__(
        self,
        url: str = "redis://localhost:6379/0",
        *,
        dedupe_ttl: int = 86400,
        namespace: str = "prreview",
        client: Any | None = None,  # injectable for tests (fakeredis)
    ) -> None:
        if client is None:
            import redis.asyncio as redis  # lazy: memory backend never pays this import

            client = redis.from_url(url, decode_responses=True)
        self._r = client
        self._ttl = dedupe_ttl
        self._queue = f"{namespace}:queue"
        self._processing = f"{namespace}:processing"
        self._delivery = f"{namespace}:delivery:"

    async def put(self, job: ReviewJob) -> bool:
        """Enqueue a job. Returns False if this delivery id was already seen."""
        if job.delivery_id:
            fresh = await self._r.set(
                self._delivery + job.delivery_id, "1", nx=True, ex=self._ttl
            )
            if not fresh:
                return False
        await self._r.lpush(self._queue, job.to_json())
        return True

    async def get(self) -> ReviewJob:
        """Block until a job is available; move it to the processing list.

        Blocks in 1s slices rather than forever: each timeout is a clean
        cancellation point for graceful shutdown, and a spurious ``None`` (e.g.
        a dropped connection) retries instead of crashing the worker.

        The sleep between empty polls is load-bearing: if the client returns
        ``None`` without suspending (fakeredis does; a broken connection
        might), a bare loop would never yield to the event loop and would
        starve every other task while spinning at 100% CPU.
        """
        while True:
            raw = await self._r.blmove(self._queue, self._processing, 1, "RIGHT", "LEFT")
            if raw is not None:
                return ReviewJob.from_json(raw)
            await asyncio.sleep(0.05)

    async def task_done(self, job: ReviewJob) -> None:
        """Ack: drop the job from the processing list."""
        await self._r.lrem(self._processing, 1, job.to_json())

    async def recover(self) -> int:
        """Requeue jobs orphaned in ``processing`` by a dead worker.

        Call once at startup, before workers begin. Returns the count requeued.
        """
        n = 0
        while await self._r.lmove(self._processing, self._queue, "RIGHT", "LEFT"):
            n += 1
        return n

    async def close(self) -> None:
        await self._r.aclose()
