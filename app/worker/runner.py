"""The worker loop: pull a job, run the full review, post results."""

import asyncio
import logging

from ..config import get_settings
from ..github.auth import auth
from ..github.client import GitHubClient
from ..github.review import post_review
from ..review.diff import should_skip, split_diff_by_file
from ..review.engine import review_file
from ..review.schema import Finding, build_summary, cap_nits
from .jobs import ReviewJob
from .queue import JobQueue

logger = logging.getLogger(__name__)


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
            for fd in files[: settings.max_files_per_pr]:
                review = await review_file(fd.path, fd.diff_text)
                for finding in review.findings:
                    # Trust our own file boundary; drop anchors outside the diff.
                    finding.path = fd.path
                    if finding.line in fd.valid_lines:
                        findings.append(finding)
                reviewed += 1

            findings = cap_nits(findings, settings.max_nits_per_file)
            summary = build_summary(findings, reviewed, len(files))
            await post_review(gh, job, findings, summary)

            await gh.set_status(
                job.owner,
                job.repo,
                job.head_sha,
                "success",
                f"{len(findings)} comment(s) across {reviewed} file(s)",
            )
        except Exception:
            logger.exception("review failed for %s#%d", job.repo, job.pr_number)
            await gh.set_status(job.owner, job.repo, job.head_sha, "failure", "Review failed — see logs")
            raise


async def worker_loop(queue: JobQueue) -> None:
    logger.info("worker started")
    while True:
        job = await queue.get()
        try:
            await process_job(job)
        except asyncio.CancelledError:
            raise
        except Exception:
            # process_job already logged; keep the worker alive for the next job.
            pass
        finally:
            queue.task_done()
