"""Thin async GitHub REST client with backoff on rate limits and 5xx."""

import asyncio
import logging
import random

import httpx

logger = logging.getLogger(__name__)

_API = "https://api.github.com"
_RETRYABLE = {429, 500, 502, 503, 504}


class GitHubClient:
    def __init__(self, token: str, timeout: float = 30.0, max_retries: int = 4) -> None:
        self._max_retries = max_retries
        self._http = httpx.AsyncClient(
            base_url=_API,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    async def __aenter__(self) -> "GitHubClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._http.aclose()

    async def _request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        last: httpx.Response | None = None
        for attempt in range(self._max_retries + 1):
            resp = await self._http.request(method, url, **kwargs)  # type: ignore[arg-type]
            if resp.status_code not in _RETRYABLE:
                resp.raise_for_status()
                return resp
            last = resp
            if attempt == self._max_retries:
                break
            delay = self._retry_after(resp, attempt)
            logger.warning("GitHub %s %s -> %s, retrying in %.1fs", method, url, resp.status_code, delay)
            await asyncio.sleep(delay)
        assert last is not None
        last.raise_for_status()
        return last

    @staticmethod
    def _retry_after(resp: httpx.Response, attempt: int) -> float:
        header = resp.headers.get("Retry-After")
        if header and header.isdigit():
            return float(header)
        reset = resp.headers.get("X-RateLimit-Reset")
        if resp.status_code in (403, 429) and reset and reset.isdigit():
            import time

            return max(0.0, float(reset) - time.time())
        return min(30.0, (2**attempt) + random.random())

    # --- endpoints -------------------------------------------------------

    async def get_pull_diff(self, owner: str, repo: str, number: int) -> str:
        resp = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{number}",
            headers={"Accept": "application/vnd.github.v3.diff"},
        )
        return resp.text

    async def list_review_comments(self, owner: str, repo: str, number: int) -> list[dict]:
        resp = await self._request("GET", f"/repos/{owner}/{repo}/pulls/{number}/comments")
        return resp.json()

    async def create_review(
        self,
        owner: str,
        repo: str,
        number: int,
        commit_id: str,
        body: str,
        comments: list[dict],
    ) -> dict:
        payload = {"commit_id": commit_id, "event": "COMMENT", "body": body, "comments": comments}
        resp = await self._request("POST", f"/repos/{owner}/{repo}/pulls/{number}/reviews", json=payload)
        return resp.json()

    async def set_status(
        self, owner: str, repo: str, sha: str, state: str, description: str
    ) -> None:
        payload = {"state": state, "description": description[:140], "context": "claude-review"}
        await self._request("POST", f"/repos/{owner}/{repo}/statuses/{sha}", json=payload)
