# PR Reviewer Bot — Design Document

A GitHub App that performs automated code review with Claude. It listens for
pull-request webhooks, pulls the diff, asks the Claude API for a structured
review, and posts the findings back as inline review comments.

**Status:** design — no code yet.
**Stack:** Python 3.12 · FastAPI · a queue + worker · the `anthropic` SDK · GitHub REST API.

---

## 1. Goals

**Primary:** a working GitHub App that reviews real PRs and leaves useful,
correctly-anchored inline comments.

**What it's meant to show off (portfolio framing):**

- Inbound webhooks with signature verification.
- GitHub App authentication (JWT → short-lived installation token).
- Async job processing — a fast webhook ACK decoupled from slow work via a
  queue + worker (the same pattern as the APScheduler jobs in Faceplant).
- LLM prompt engineering with **structured output** (guaranteed-parseable JSON).
- Resilience against two rate-limited external APIs (GitHub + Claude): retries,
  backoff, and idempotency.

**Non-goals (v1):** multi-file "whole repo" reasoning, a web dashboard, review
of non-diff context, or supporting GitLab/Bitbucket. Keep the surface small.

---

## 2. Architecture

```
   GitHub                         PR Reviewer Bot
 ┌──────────┐   webhook POST    ┌───────────────────────────────────────────┐
 │  PR       │ ───────────────► │  FastAPI  /webhooks                        │
 │  opened/  │                  │   1. verify X-Hub-Signature-256 (HMAC)     │
 │  synced   │ ◄─────────────── │   2. enqueue job, return 202 immediately   │
 └──────────┘   inline comments └───────────────┬───────────────────────────┘
      ▲                                          │ job
      │                                          ▼
      │                          ┌───────────────────────────────────────────┐
      │  POST review comments    │  Worker (async)                            │
      └──────────────────────────│   3. mint installation token (JWT)         │
                                 │   4. fetch PR diff via GitHub API          │
                                 │   5. call Claude → structured findings     │
                                 │   6. map findings → inline comments        │
                                 │   7. POST a PR review                       │
                                 └───────────────────────────────────────────┘
```

The webhook handler does almost nothing — verify, enqueue, ACK. GitHub expects a
response within ~10s and retries on failure, so all slow work (diff fetch, the
Claude call, comment posting) happens in the worker.

---

## 3. Components

### 3.1 Webhook receiver (`app/web/webhooks.py`)
- `POST /webhooks` — the single GitHub endpoint.
- Verifies `X-Hub-Signature-256` (HMAC-SHA256 of the raw body with the app's
  webhook secret) **before parsing**. Reject with 401 on mismatch.
- Filters to events we care about: `pull_request` with action in
  `{opened, synchronize, reopened, ready_for_review}`. Everything else → 204.
- Enqueues `ReviewJob(installation_id, repo, pr_number, head_sha, delivery_id)`
  and returns `202 Accepted`. The `X-GitHub-Delivery` header is our idempotency
  key.
- `GET /healthz` for liveness.

### 3.2 Queue + worker (`app/worker/`)
- **v1 queue:** in-process `asyncio.Queue` + a background task started on FastAPI
  startup. Simplest thing that demonstrates the decoupling and runs on one box.
- **v2 (stretch):** Redis-backed (`arq` or `RQ`) so the queue survives restarts
  and can scale to multiple workers. The job contract stays identical, so this
  is a drop-in swap — worth calling out in the README as the seam.
- The worker owns ret/backoff for the external calls and updates a
  commit-status check (`pending → success/failure`) so activity is visible on
  the PR.

### 3.3 GitHub App auth (`app/github/auth.py`)
GitHub Apps don't use a static token. Per review:
1. Build a short-lived **JWT** (RS256) signed with the app's private key —
   `iss = app_id`, `iat/exp` ≤ 10 min.
2. Exchange it for an **installation access token**:
   `POST /app/installations/{installation_id}/access_tokens`. Valid ~1h,
   scoped to that install.
3. Cache the installation token in memory keyed by `installation_id` until a
   minute before expiry; refresh on demand.

### 3.4 Diff fetch (`app/github/client.py`)
- `GET /repos/{owner}/{repo}/pulls/{n}` with `Accept: application/vnd.github.v3.diff`
  for the unified diff, plus the JSON form for file/line metadata.
- Skip generated/vendored/lockfiles and anything over a size threshold.
- If the diff exceeds the model budget, chunk by file and review per-file (see §6).

### 3.5 Claude review engine (`app/review/engine.py`)
- Builds the prompt (system + per-file diff), calls the Claude API, and returns
  a validated list of findings. Details in §6.

### 3.6 Comment poster (`app/github/review.py`)
- Maps each finding to an inline comment anchored on `(path, line, side)`.
- Posts **one** PR review via
  `POST /repos/{owner}/{repo}/pulls/{n}/reviews` with all comments batched and
  `event: COMMENT` (never auto-`REQUEST_CHANGES` in v1 — too aggressive).
- De-dupes against the bot's existing comments on that `head_sha` so re-runs on
  `synchronize` don't stack duplicates.

---

## 4. Request flow (happy path)

1. Dev opens PR → GitHub sends `pull_request.opened`.
2. `/webhooks` verifies HMAC, enqueues job, returns 202 (< 200ms).
3. Worker picks up job, mints an installation token.
4. Worker sets a `pending` commit status ("Claude is reviewing…").
5. Worker fetches the diff, splits into reviewable files.
6. For each file, worker calls Claude and collects findings.
7. Worker filters/dedupes findings, posts one batched PR review.
8. Worker sets commit status `success` with a summary count.

---

## 5. Claude integration

> Model defaults reflect the current Claude API. Using `claude-opus-4-8` with
> adaptive thinking — code review is a strong Opus use case. `claude-sonnet-5`
> is the cost-conscious swap (same request shape) if per-review cost matters.

### 5.1 The call

```python
# app/review/engine.py
from anthropic import Anthropic
from pydantic import BaseModel
from typing import Literal

client = Anthropic()  # reads ANTHROPIC_API_KEY (or an `ant auth login` profile)

class Finding(BaseModel):
    path: str
    line: int                      # line in the file's NEW version (RIGHT side)
    severity: Literal["blocker", "warning", "nit"]
    category: Literal["correctness", "security", "performance", "style", "test"]
    comment: str                   # the inline message, markdown

class Review(BaseModel):
    summary: str
    findings: list[Finding]

def review_file(path: str, diff: str) -> Review:
    resp = client.messages.parse(
        model="claude-opus-4-8",
        max_tokens=8000,
        thinking={"type": "adaptive"},           # let Claude decide how hard to think
        output_config={"effort": "high"},
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,               # frozen — see §5.2
            "cache_control": {"type": "ephemeral"},  # cache the stable prefix
        }],
        messages=[{
            "role": "user",
            "content": f"File: {path}\n\nUnified diff:\n```diff\n{diff}\n```",
        }],
        output_format=Review,                    # structured output → validated Review
    )
    return resp.parsed_output
```

Key points, all verified against the current API:
- **Structured output** via `messages.parse()` + a Pydantic model. The response
  is schema-validated — no brittle JSON string-parsing. (Structured outputs are
  supported on Opus 4.8 / Sonnet 5 and work with extended thinking; they are
  **not** compatible with citations.)
- **Adaptive thinking** (`{"type": "adaptive"}`) — the current models reject the
  old `budget_tokens` form with a 400. Effort is set via `output_config.effort`.
- **Prompt caching** on the frozen system prompt so repeated reviews only pay
  full price for the changing diff. Keep the system prompt byte-stable (no
  timestamps/IDs interpolated in) or the cache silently misses.
- No assistant-prefill (rejected on current models) — the schema does the
  output-shaping instead.

### 5.2 Prompt design
- **System prompt (frozen):** role ("senior reviewer"), what to flag and what to
  ignore, the severity rubric, and an explicit "report line numbers from the NEW
  file version" instruction so anchoring is reliable. Being prescriptive about
  *when* to comment matters — current models follow the system prompt closely,
  so avoid "flag EVERYTHING" language that overtriggers nits.
- **User turn:** file path + the unified diff for that file only.
- **Coverage vs. noise:** ask for findings with a `severity`, then filter
  `nit`-level down to a cap (e.g. max 3 nits/file) on our side rather than asking
  the model to self-censor. Better recall, we control the volume.

### 5.3 Anchoring findings to the diff
GitHub's review-comment API anchors on `(path, line, side)` where `line` must be
part of the diff hunk. The model returns a file line number; we validate each
finding's line falls within an added/changed hunk range (parsed from the diff)
and drop any that don't — this prevents 422s from GitHub and silently-wrong
anchors.

---

## 6. Handling large diffs
- **Per-file review** is the default unit — keeps each Claude call small,
  cacheable, and independently retryable.
- Token-count the diff with `client.messages.count_tokens()` before sending;
  if a single file's diff is still too big, review only its hunks with a few
  lines of surrounding context.
- Skip: lockfiles, `vendor/`, `node_modules/`, generated code, binary/large
  files. Configurable glob list.
- Cap total files per PR (e.g. 40) to bound cost; note the skip in the summary.

---

## 7. Resilience (two rate-limited APIs)

| Concern | Approach |
|---|---|
| Claude 429 / 5xx | The `anthropic` SDK auto-retries with backoff (`max_retries`, default 2). Bump to 4 for the worker. Respect `retry-after`. |
| GitHub 429 / abuse limits | Honor `Retry-After` / `X-RateLimit-Reset`; exponential backoff with jitter on 403/429/5xx. |
| Duplicate deliveries | GitHub retries webhooks. Dedupe on `X-GitHub-Delivery`; also make comment-posting idempotent per `head_sha`. |
| Partial failure mid-review | Per-file jobs fail independently; a failed file is retried without re-reviewing succeeded ones. |
| Poison jobs | Cap retries (e.g. 3), then mark commit status `failure` with a short reason and drop. |

---

## 8. Project layout

```
pr-reviewer-bot/
├── DESIGN.md                  ← this file
├── pyproject.toml
├── .env.example
├── app/
│   ├── main.py                # FastAPI app, startup wires the worker
│   ├── config.py              # pydantic-settings: secrets & tunables
│   ├── web/
│   │   └── webhooks.py        # /webhooks, HMAC verify, enqueue
│   ├── worker/
│   │   ├── queue.py           # asyncio.Queue (v1) → arq/Redis (v2)
│   │   └── runner.py          # the job loop
│   ├── github/
│   │   ├── auth.py            # JWT → installation token (+ cache)
│   │   ├── client.py          # diff fetch, REST helpers
│   │   └── review.py          # post batched PR review
│   └── review/
│       ├── engine.py          # Claude call, structured output
│       ├── prompt.py          # SYSTEM_PROMPT
│       └── diff.py            # hunk parsing, line validation
└── tests/
    ├── fixtures/              # sample webhook payloads + diffs
    ├── test_webhook_sig.py
    ├── test_diff_anchor.py
    └── test_engine.py         # mocked Claude client
```

---

## 9. Config & secrets (`.env`)

| Var | Purpose |
|---|---|
| `GITHUB_APP_ID` | App identifier |
| `GITHUB_PRIVATE_KEY` | RS256 key for JWT signing (PEM) |
| `GITHUB_WEBHOOK_SECRET` | HMAC secret for signature verification |
| `ANTHROPIC_API_KEY` | Claude API key (or use an `ant auth login` profile) |
| `REVIEW_MODEL` | default `claude-opus-4-8` |
| `MAX_FILES_PER_PR`, `SKIP_GLOBS` | cost/scope guards |

Never log the raw private key or tokens. Installation tokens live in memory only.

---

## 10. GitHub App setup (one-time)
1. Create a GitHub App (Settings → Developer settings → GitHub Apps).
2. **Permissions:** Pull requests: Read & Write, Contents: Read, Checks/Commit
   statuses: Write, Metadata: Read.
3. **Subscribe to events:** Pull request.
4. **Webhook URL:** the public `/webhooks` endpoint (ngrok/smee for local dev).
5. Generate a private key, set a webhook secret.
6. Install the app on a test repo.

## 11. Local dev & testing
- `smee.io` or `ngrok` to forward GitHub webhooks to localhost.
- Golden-file tests: recorded webhook payloads + diffs in `tests/fixtures/`.
- Mock the Claude client in unit tests; one opt-in integration test hits the
  real API behind an env flag.
- `test_diff_anchor.py` is the highest-value test — line-mapping bugs are what
  produce 422s and wrong anchors in production.

## 12. Deployment
- Single container (uvicorn) on Fly.io / Render / a small VM — the in-process
  queue means one process is enough for v1.
- v2: separate web + worker processes sharing Redis.

---

## 13. Build order (milestones)

1. **Skeleton** — FastAPI app, `/webhooks` with HMAC verify, `/healthz`,
   `202` + log. Prove deliveries arrive and verify.
2. **GitHub auth** — JWT → installation token → fetch a PR diff and print it.
3. **Claude review** — `engine.py` end-to-end on a saved diff fixture, print
   structured findings. (Prototype this in isolation first — it's the core.)
4. **Post comments** — map findings → one batched PR review; get the anchoring
   right against a real PR.
5. **Wire the worker** — move steps 2–4 behind the queue; add commit-status
   updates.
6. **Resilience** — retries, dedupe on delivery id + head sha, large-diff
   chunking.
7. **Polish** — skip globs, nit caps, README with the "swap to Redis" seam
   called out.

## 14. Stretch goals
- Redis-backed queue + multiple workers.
- `@bot` mention commands (re-review, ignore file).
- Summary comment with counts by severity.
- Persist reviews (SQLite) for a tiny stats page.
- Prompt-cache warming and per-repo custom review guidelines.
```
