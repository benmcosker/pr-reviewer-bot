"""Live smoke test for the GitHub path.

Against a real open PR, exercises: diff fetch (diff media type) -> diff parsing
-> inline-comment posting via create_review (the 422-prone part) -> commit
status -> read-back + dedupe.

Auth: uses GITHUB_TOKEN (a PAT) if set. Otherwise falls back to the GitHub App
installation-token path (needs GITHUB_APP_ID, GITHUB_PRIVATE_KEY,
SMOKE_INSTALLATION_ID) so the same script can validate auth.py too.

Config comes from the environment or a local .env:
    GITHUB_TOKEN=github_pat_...        # or the App creds above
    SMOKE_OWNER=benmcosker
    SMOKE_REPO=some-repo
    SMOKE_PR=1

Run:  .venv/bin/python scripts/smoke_github.py
"""

import asyncio
import os
import re
import sys

from app.github.client import GitHubClient
from app.github.review import MARKER, post_review
from app.review.diff import split_diff_by_file
from app.review.schema import Finding, build_summary
from app.worker.jobs import ReviewJob


def load_env(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def first_added_line(diff_text: str) -> int | None:
    """Line number (new file) of the first added line — safest anchor."""
    new = 0
    for l in diff_text.splitlines():
        if l.startswith("@@"):
            m = re.search(r"\+(\d+)", l.split("@@")[1])
            new = int(m.group(1)) if m else 0
        elif l.startswith("+++"):
            continue
        elif l.startswith("+"):
            return new
        elif l.startswith(" "):
            new += 1
    return None


async def get_token() -> tuple[str, str]:
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"], "PAT"
    from app.github.auth import auth  # reads GITHUB_APP_ID / GITHUB_PRIVATE_KEY

    inst = int(os.environ["SMOKE_INSTALLATION_ID"])
    return await auth.token(inst), f"installation-token (inst={inst})"


async def main() -> int:
    load_env()
    owner = os.environ["SMOKE_OWNER"]
    repo = os.environ["SMOKE_REPO"]
    pr = int(os.environ["SMOKE_PR"])
    post = "--post" in sys.argv  # default: read-only dry run

    token, mode = await get_token()
    print(f"target: {owner}/{repo}#{pr}")
    print(f"auth:   {mode}")
    print(f"mode:   {'POST (writes to the PR)' if post else 'DRY RUN (read-only)'}\n")

    async with GitHubClient(token) as gh:
        pull = (await gh._request("GET", f"/repos/{owner}/{repo}/pulls/{pr}")).json()
        head_sha = pull["head"]["sha"]
        print(f"PR: {pull['title']!r}  head={head_sha[:8]}  state={pull['state']}")

        diff = await gh.get_pull_diff(owner, repo, pr)
        print(f"diff: {len(diff)} bytes")
        files = split_diff_by_file(diff)
        print(f"files in diff: {[f.path for f in files]}")

        target = next((f for f in files if first_added_line(f.diff_text)), None)
        assert target, "no added lines to anchor a comment on in this PR"
        line = first_added_line(target.diff_text)
        print(f"anchoring smoke comment at {target.path}:{line}")

        if not post:
            print("\nDRY RUN complete — no writes made. Re-run with --post to post the comment.")
            return 0

        print()
        job = ReviewJob(
            installation_id=int(os.environ.get("SMOKE_INSTALLATION_ID", 0)),
            owner=owner,
            repo=repo,
            pr_number=pr,
            head_sha=head_sha,
            delivery_id="smoke",
        )
        findings = [
            Finding(
                path=target.path,
                line=line,
                severity="nit",
                category="style",
                comment=(
                    "Smoke test from the PR Reviewer Bot GitHub-path check — "
                    "confirms inline comments post and anchor correctly. Safe to resolve."
                ),
            )
        ]
        summary = build_summary(findings, reviewed=1, total=len(files))

        print("posting review + commit status…")
        await post_review(gh, job, findings, summary)
        await gh.set_status(owner, repo, head_sha, "success", "smoke test ok")

        # read back to confirm the comment landed (and dedupe would catch a re-run)
        comments = await gh.list_review_comments(owner, repo, pr)
        mine = [c for c in comments if MARKER in (c.get("body") or "")]
        print(f"\nour comments now visible on the PR: {len(mine)}")
        for c in mine:
            print(f"  {c['path']}:{c.get('line')}  {c['html_url']}")

    ok = len(mine) >= 1
    print("\nRESULT:", "PASS" if ok else "CHECK OUTPUT ABOVE")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
