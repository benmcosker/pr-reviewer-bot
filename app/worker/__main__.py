"""Standalone worker process:  python -m app.worker

Runs WORKER_CONCURRENCY worker loops against the shared redis queue, with no
web server. Pair it with a web process running WORKER_CONCURRENCY=0 (enqueue
only) for the split web/worker deployment (DESIGN §12 v2).

Requires QUEUE_BACKEND=redis — an in-memory queue can't be shared with the web
process, so a standalone memory worker would sit idle forever.
"""

import asyncio
import logging
import sys

from ..config import get_settings
from .queue import make_queue
from .runner import start_workers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("app.worker")


async def main() -> None:
    settings = get_settings()
    if settings.queue_backend != "redis":
        sys.exit("standalone workers need QUEUE_BACKEND=redis (a memory queue can't be shared)")
    if settings.worker_concurrency < 1:
        sys.exit("WORKER_CONCURRENCY must be >= 1 for a standalone worker")

    queue = make_queue(settings)
    requeued = await queue.recover()
    if requeued:
        logger.info("requeued %d orphaned job(s)", requeued)

    tasks = start_workers(queue, settings.worker_concurrency)
    logger.info("standalone worker up: %d loop(s) on %s", len(tasks), settings.redis_url)
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await queue.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("worker shutting down")
