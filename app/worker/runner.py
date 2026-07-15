"""The worker loop: pull a job, run the full review, post results."""

import asyncio
import logging

from ..config import Settings, get_settings
from ..github.auth import auth
from ..github.client import GitHubClient
from ..github.review import post_review
from ..review.diff import (
    FileDiff,
    estimate_tokens,
    should_skip,
    split_diff_by_file,
    split_into_hunks,
)
from ..review.engine import review_file
from ..review.schema import Finding, build_summary, cap_nits
from .jobs import ReviewJob
from .queue import SupportsJobQueue
from .retry import call_with_retries

logger = logging.getLogger(__name__)


def _review_units(fd: FileDiff, settings: Settings) -> list[str]:
    """The diff text(s) to send for one file: the whole file if it fits the
    token budget, otherwise one unit per hunk (DESIGN §6)."""
    if estimate_tokens(fd.diff_text) <= settings.max_diff_tokens:
        return [fd.diff_text]
    return split_into_hunks(fd)


async def _review_one_file(
    fd: FileDiff, settings: Settings
) -> tuple[list[Finding], bool, bool]:
    """Review a single file. Returns (findings, errored, had_oversize_unit).

    A file's review is retried in isolation; if it still fails it's reported as
    errored rather than sinking the whole PR.
    """
    findings: list[Finding] = []
    errored = False
    oversize = False
    for unit in _review_units(fd, settings):
        if estimate_tokens(unit) > settings.max_diff_tokens:
            # A single hunk that blows the budget — skip it, note it.
            oversize = True
            logger.warning("skipping oversize hunk in %s", fd.path)
            continue
        try:
            review = await call_with_retries(
                lambda u=unit: review_file(fd.path, u),
                attempts=settings.max_review_retries,
                label=f"review {fd.path}",
            )
        except Exception:
            logger.exception("giving up on %s after %d attempts", fd.path, settings.max_review_retries)
            errored = True
            continue
        for finding in review.findings:
            finding.path = fd.path  # trust our file boundary
            if finding.line in fd.valid_lines:
                findings.append(finding)
    return findings, errored, oversize


async def process_job(job: ReviewJob) -> None:
    settings = get_settings()
    token = await auth.token(job.installation_id)

    async with GitHubClient(
        token, timeout=settings.request_timeout, max_retries=settings.max_http_retries
    ) as gh:
        await gh.set_status(job.owner, job.repo, job.head_sha, "pending", "Claude is reviewing this PR…")
        try:
            raw = await gh.get_pull_diff(job.owner, job.repo, job.pr_number)
            files = [f for f in split_diff_by_file(raw) if not should_skip(f.path, settings.skip_globs)]

            findings: list[Finding] = []
            reviewed = 0
            failed_files: list[str] = []
            oversize_files: list[str] = []
            for fd in files[: settings.max_files_per_pr]:
                file_findings, errored, oversize = await _review_one_file(fd, settings)
                findings.extend(file_findings)
                reviewed += 1
                if errored:
                    failed_files.append(fd.path)
                if oversize:
                    oversize_files.append(fd.path)

            findings = cap_nits(findings, settings.max_nits_per_file)
            summary = build_summary(findings, reviewed, len(files), oversize_files, failed_files)
            await post_review(gh, job, findings, summary)

            # Fail the check only if every attempted file errored; otherwise the
            # review is usable even if partial.
            if failed_files and len(failed_files) == reviewed:
                await gh.set_status(job.owner, job.repo, job.head_sha, "failure", "Review failed for all files")
            else:
                desc = f"{len(findings)} comment(s) across {reviewed} file(s)"
                if failed_files:
                    desc += f", {len(failed_files)} errored"
                await gh.set_status(job.owner, job.repo, job.head_sha, "success", desc)
        except Exception:
            # Infrastructure failure (auth/diff fetch) — the per-file path above
            # handles review errors itself.
            logger.exception("review failed for %s#%d", job.repo, job.pr_number)
            await gh.set_status(job.owner, job.repo, job.head_sha, "failure", "Review failed — see logs")
            raise


async def worker_loop(queue: SupportsJobQueue, name: str = "worker") -> None:
    logger.info("%s started", name)
    while True:
        job = await queue.get()
        try:
            await process_job(job)
        except asyncio.CancelledError:
            # No ack: on the redis backend the job stays in `processing`, so
            # recover() requeues it on the next boot instead of losing it.
            raise
        except Exception:
            # process_job already logged; keep the worker alive for the next
            # job. Fall through to the ack — a poison job must not requeue.
            pass
        await queue.task_done(job)


def start_workers(queue: SupportsJobQueue, n: int) -> list[asyncio.Task]:
    """Spawn ``n`` concurrent worker loops on one queue.

    ``n`` bounds how many PRs are reviewed at once — the throttle against both
    rate-limited APIs. ``n=0`` means this process only enqueues (a web process
    in the split web/worker deployment).
    """
    return [
        asyncio.create_task(worker_loop(queue, name=f"worker-{i}"), name=f"worker-{i}")
        for i in range(n)
    ]
