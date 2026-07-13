import hashlib
import hmac

from app.web.security import verify_signature

SECRET = "topsecret"


def _sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_valid_signature():
    body = b'{"action":"opened"}'
    assert verify_signature(body, _sign(body), SECRET) is True


def test_wrong_secret():
    body = b'{"action":"opened"}'
    assert verify_signature(body, _sign(body, "other"), SECRET) is False


def test_tampered_body():
    body = b'{"action":"opened"}'
    sig = _sign(body)
    assert verify_signature(b'{"action":"closed"}', sig, SECRET) is False


def test_missing_or_malformed_header():
    body = b"{}"
    assert verify_signature(body, "", SECRET) is False
    assert verify_signature(body, "md5=deadbeef", SECRET) is False


def test_empty_secret_fails_closed():
    body = b"{}"
    assert verify_signature(body, _sign(body), "") is False
