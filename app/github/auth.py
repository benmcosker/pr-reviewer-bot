"""GitHub App authentication: app JWT -> short-lived installation token.

Installation tokens are cached in memory per installation until just before
expiry.
"""

import asyncio
import time
from datetime import datetime

import httpx
import jwt

from ..config import get_settings

_API = "https://api.github.com"


def _epoch(iso: str) -> float:
    # GitHub returns e.g. "2026-07-12T18:00:00Z"
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


class InstallationAuth:
    def __init__(self) -> None:
        self._cache: dict[int, tuple[str, float]] = {}
        self._lock = asyncio.Lock()

    def _app_jwt(self) -> str:
        settings = get_settings()
        now = int(time.time())
        key = settings.github_private_key.replace("\\n", "\n")
        # iss must be a string — PyJWT rejects a bare int App ID.
        payload = {"iat": now - 60, "exp": now + 9 * 60, "iss": str(settings.github_app_id)}
        return jwt.encode(payload, key, algorithm="RS256")

    async def token(self, installation_id: int) -> str:
        settings = get_settings()
        async with self._lock:
            cached = self._cache.get(installation_id)
            if cached and cached[1] - 60 > time.time():
                return cached[0]

            headers = {
                "Authorization": f"Bearer {self._app_jwt()}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
                resp = await client.post(
                    f"{_API}/app/installations/{installation_id}/access_tokens",
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()

            token = data["token"]
            self._cache[installation_id] = (token, _epoch(data["expires_at"]))
            return token


# Module-level singleton — one token cache for the process.
auth = InstallationAuth()
