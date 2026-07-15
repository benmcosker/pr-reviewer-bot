"""The worker pool actually runs jobs concurrently, and acks correctly."""

import asyncio

import app.worker.runner as runner
from app.worker.jobs import ReviewJob
from app.worker.queue import JobQueue


def _job(n: int) -> ReviewJob:
    return ReviewJob(
        installation_id=1, owner="o", repo="r", pr_number=n,
        head_sha=f"sha{n}", delivery_id=f"d-{n}",
    )


async def test_pool_processes_jobs_concurrently(monkeypatch):
    running = 0
    peak = 0
    done: list[int] = []

    async def fake_process(job: ReviewJob) -> None:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.05)
        running -= 1
        done.append(job.pr_number)

    monkeypatch.setattr(runner, "process_job", fake_process)

    queue = JobQueue()
    tasks = runner.start_workers(queue, 3)
    for i in range(3):
        await queue.put(_job(i))

    await asyncio.sleep(0.15)
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    assert sorted(done) == [0, 1, 2]
    assert peak == 3  # all three ran at once — not serialized


async def test_pool_survives_poison_job(monkeypatch):
    done: list[int] = []

    async def fake_process(job: ReviewJob) -> None:
        if job.pr_number == 0:
            raise RuntimeError("poison")
        done.append(job.pr_number)

    monkeypatch.setattr(runner, "process_job", fake_process)

    queue = JobQueue()
    tasks = runner.start_workers(queue, 1)  # single worker: must outlive the failure
    await queue.put(_job(0))
    await queue.put(_job(1))

    await asyncio.sleep(0.1)
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    assert done == [1]  # poison consumed and acked; next job still processed


async def test_zero_workers_spawns_nothing():
    assert runner.start_workers(JobQueue(), 0) == []
