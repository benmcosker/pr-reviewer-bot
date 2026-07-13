"""FastAPI application entrypoint.

On startup, create the job queue and spawn the background worker task; on
shutdown, cancel it cleanly.

Run locally:  uvicorn app.main:app --reload
"""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from .web import webhooks
from .worker.queue import JobQueue
from .worker.runner import worker_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    queue = JobQueue()
    app.state.queue = queue
    task = asyncio.create_task(worker_loop(queue))
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="PR Reviewer Bot", lifespan=lifespan)
app.include_router(webhooks.router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
