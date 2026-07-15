"""FastAPI application entrypoint.

On startup, create the job queue and spawn the background worker task; on
shutdown, cancel it cleanly.

Run locally:  uvicorn app.main:app --reload
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from .web import webhooks
from .worker.queue import make_queue
from .worker.runner import start_workers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    queue = make_queue(settings)
    app.state.queue = queue

    if hasattr(queue, "recover"):  # redis backend: requeue jobs orphaned by a crash
        requeued = await queue.recover()
        if requeued:
            logger.info("requeued %d orphaned job(s) from a previous run", requeued)

    tasks = start_workers(queue, settings.worker_concurrency)
    logger.info(
        "queue=%s workers=%d", settings.queue_backend, settings.worker_concurrency
    )
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if hasattr(queue, "close"):
            await queue.close()


app = FastAPI(title="PR Reviewer Bot", lifespan=lifespan)
app.include_router(webhooks.router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
