"""Webhook signature verification (pure, no framework deps)."""

import hashlib
import hmac


def verify_signature(body: bytes, header: str, secret: str) -> bool:
    """Verify GitHub's ``X-Hub-Signature-256`` header against the raw body.

    Fails closed if the secret is unset or the header is missing/malformed.
    """
    if not secret or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)
