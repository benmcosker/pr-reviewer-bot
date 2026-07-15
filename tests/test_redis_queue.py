import asyncio

import fakeredis
import pytest

from app.worker.jobs import ReviewJob
from app.worker.redis_queue import RedisJobQueue


def _job(delivery: str, pr: int = 1) -> ReviewJob:
    return ReviewJob(
        installation_id=1, owner="o", repo="r", pr_number=pr,
        head_sha="sha", delivery_id=delivery,
    )


@pytest.fixture
def queue() -> RedisJobQueue:
    return RedisJobQueue(client=fakeredis.FakeAsyncRedis(decode_responses=True))


async def test_put_get_round_trip(queue):
    job = _job("d-1")
    assert await queue.put(job) is True
    assert await queue.get() == job


async def test_delivery_dedupe(queue):
    assert await queue.put(_job("dup")) is True
    assert await queue.put(_job("dup")) is False  # same delivery id
    assert await queue.put(_job("")) is True      # empty id never dedupes


async def test_fifo_order(queue):
    for i in range(3):
        await queue.put(_job(f"d-{i}", pr=i))
    assert [(await queue.get()).pr_number for _ in range(3)] == [0, 1, 2]


async def test_task_done_acks_processing(queue):
    job = _job("d-1")
    await queue.put(job)
    await queue.get()
    assert await queue._r.llen(queue._processing) == 1  # in flight
    await queue.task_done(job)
    assert await queue._r.llen(queue._processing) == 0  # acked


async def test_recover_requeues_orphans(queue):
    a, b = _job("d-a", pr=1), _job("d-b", pr=2)
    await queue.put(a)
    await queue.put(b)
    await queue.get()  # a picked up …
    await queue.get()  # … b picked up; neither acked (worker "died")
    assert await queue.recover() == 2
    # both are retrievable again, original order preserved
    assert {(await queue.get()).pr_number for _ in range(2)} == {1, 2}


async def test_get_blocks_until_put(queue):
    async def delayed_put():
        await asyncio.sleep(0.05)
        await queue.put(_job("late"))

    asyncio.get_running_loop().create_task(delayed_put())
    job = await asyncio.wait_for(queue.get(), timeout=2)
    assert job.delivery_id == "late"
