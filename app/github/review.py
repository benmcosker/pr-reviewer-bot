"""Map findings to inline comments and post one batched PR review.

Comments are tagged with a hidden marker so re-runs on ``synchronize`` don't
stack duplicates at the same (path, line).
"""

import logging

from ..review.schema import Finding
from ..worker.jobs import ReviewJob
from .client import GitHubClient

logger = logging.getLogger(__name__)

MARKER = "<!-- claude-review -->"


def _comment_body(f: Finding) -> str:
    return f"**{f.severity} · {f.category}** — {f.comment}\n\n{MARKER}"


async def post_review(
    gh: GitHubClient, job: ReviewJob, findings: list[Finding], summary: str
) -> None:
    existing = await gh.list_review_comments(job.owner, job.repo, job.pr_number)
    seen = {
        (c.get("path"), c.get("line"))
        for c in existing
        if MARKER in (c.get("body") or "")
    }

    comments = [
        {"path": f.path, "line": f.line, "side": "RIGHT", "body": _comment_body(f)}
        for f in findings
        if (f.path, f.line) not in seen
    ]

    if not comments and not summary:
        return

    await gh.create_review(
        job.owner, job.repo, job.pr_number, job.head_sha, summary, comments
    )
    logger.info("posted review with %d comment(s) for %s#%d", len(comments), job.repo, job.pr_number)
