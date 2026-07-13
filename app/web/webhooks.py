"""The single GitHub webhook endpoint.

Does the minimum: verify the HMAC, filter to reviewable events, enqueue a job,
and ACK fast (GitHub wants a response within ~10s). All slow work happens in the
worker.
"""

import json
import logging

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from ..config import get_settings
from ..worker.jobs import ReviewJob
from .security import verify_signature

logger = logging.getLogger(__name__)

router = APIRouter()

_REVIEWABLE_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}


@router.post("/webhooks")
async def receive(request: Request) -> Response:
    body = await request.body()
    settings = get_settings()

    signature = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(body, signature, settings.github_webhook_secret):
        raise HTTPException(status_code=401, detail="invalid signature")

    event = request.headers.get("X-GitHub-Event", "")
    if event != "pull_request":
        return Response(status_code=204)  # ping and everything else

    payload = json.loads(body)
    if payload.get("action") not in _REVIEWABLE_ACTIONS:
        return Response(status_code=204)

    try:
        pr = payload["pull_request"]
        job = ReviewJob(
            installation_id=payload["installation"]["id"],
            owner=payload["repository"]["owner"]["login"],
            repo=payload["repository"]["name"],
            pr_number=payload["number"],
            head_sha=pr["head"]["sha"],
            delivery_id=request.headers.get("X-GitHub-Delivery", ""),
        )
    except KeyError as exc:  # malformed / unexpected payload
        logger.warning("dropping webhook, missing field: %s", exc)
        return Response(status_code=204)

    enqueued = await request.app.state.queue.put(job)
    logger.info("webhook %s %s#%d enqueued=%s", event, job.repo, job.pr_number, enqueued)
    return JSONResponse({"enqueued": enqueued, "delivery": job.delivery_id}, status_code=202)
