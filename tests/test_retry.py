import pytest

from app.worker.retry import call_with_retries


async def test_succeeds_first_try():
    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        return "ok"

    assert await call_with_retries(factory, attempts=3, base_delay=0, jitter=False) == "ok"
    assert calls["n"] == 1


async def test_retries_then_succeeds():
    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("boom")
        return "ok"

    assert await call_with_retries(factory, attempts=3, base_delay=0, jitter=False) == "ok"
    assert calls["n"] == 3


async def test_exhausts_and_reraises_last():
    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError, match="nope"):
        await call_with_retries(factory, attempts=2, base_delay=0, jitter=False)
    assert calls["n"] == 2
