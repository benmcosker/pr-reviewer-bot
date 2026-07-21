# PR Reviewer Bot

[![CI](https://github.com/benmcosker/pr-reviewer-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/benmcosker/pr-reviewer-bot/actions/workflows/ci.yml)

A GitHub App that reviews pull requests with Claude. It verifies the webhook,
pulls the diff, asks the Claude API for a structured review, and posts inline
comments back on the PR.

See [DESIGN.md](DESIGN.md) for the full architecture and rationale.

## Live on Faceplant

This isn't a demo. pr-reviewer-bot runs on my
[Faceplant](https://github.com/benmcosker/Faceplant) project, reviewing real
pull requests as they open. The reviews below are unedited — the bot posted
them; I'm just linking them.

## Layout

```
app/
  main.py            FastAPI app; starts the background worker on startup
  config.py          settings (env / .env), loaded lazily
  web/
    security.py      X-Hub-Signature-256 HMAC verification
    webhooks.py      POST /webhooks — verify, enqueue, 202
  worker/
    jobs.py          ReviewJob (+ JSON round-trip for the redis backend)
    queue.py         in-process asyncio queue + delivery-id dedupe; make_queue factory
    redis_queue.py   durable shared queue (BLMOVE/LREM reliable pattern + recovery)
    runner.py        the job loop: auth → diff → review → post; start_workers pool
    __main__.py      standalone worker process (python -m app.worker)
    retry.py         per-file retry with backoff
  github/
    auth.py          app JWT → cached installation token
    client.py        REST client with backoff on 429/5xx
    review.py        map findings → inline comments, post one batched review
  review/
    schema.py        Finding / Review pydantic models + helpers
    prompt.py        frozen system prompt (cached prefix)
    diff.py          unified-diff parsing + line-anchor validation
    engine.py        the Claude call (structured output, adaptive thinking)
tests/               pure unit tests (no network, no API key needed)
```

## Installation

You need a **GitHub App** (the bot's identity) and an **Anthropic API key**.

### 1. Clone and install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env      # you'll fill this in over the next steps
```

### 2. Create the GitHub App

Go to **Settings → Developer settings → GitHub Apps → New GitHub App**
(<https://github.com/settings/apps/new>) and set:

- **Webhook → Active**, **Webhook URL** = your public `/webhooks` endpoint
  (for local dev, a [smee.io](https://smee.io) channel — see step 5), and a
  **Webhook secret** (any random string; `openssl rand -hex 24`).
- **Repository permissions:**
  - **Pull requests** → Read and write
  - **Contents** → Read-only
  - **Commit statuses** → Read and write
  - (**Metadata** → Read-only is required automatically)
- **Subscribe to events:** **Pull request**.

Create the App, then from its **General** page:

- Copy the **App ID** → `GITHUB_APP_ID` in `.env`.
- Set the same webhook secret → `GITHUB_WEBHOOK_SECRET` in `.env`.

### 3. Private key → `.env`

On the App's General page, **Generate a private key** (downloads a `.pem`).
Fold it into `.env` as a single escaped line. Write `awk`'s output straight to
the file — piping it through `echo`/`$(...)` in some shells (e.g. zsh) turns the
`\n` back into real newlines and breaks the value:

```bash
{ printf 'GITHUB_PRIVATE_KEY='; awk 'BEGIN{ORS="\\n"} 1' path/to/key.pem; echo; } >> .env
```

Then add your `ANTHROPIC_API_KEY`. (See [.env.example](.env.example) for every
supported variable.)

### 4. Install the App on your repositories

On the App's page → **Install App** → choose your account/org → select the
repositories to review. The bot reviews any PR opened or updated on those repos.

### 5. Run it

```bash
uvicorn app.main:app                       # starts the receiver + worker
curl localhost:8000/healthz                # {"status":"ok"}
```

For local development, forward GitHub's webhooks to your machine with smee
(point the App's Webhook URL at the channel):

```bash
npx smee-client -u https://smee.io/<your-channel> -t http://localhost:8000/webhooks
```

Open or update a PR on an installed repo — the bot posts inline review comments
and a `claude-review` commit status within seconds. In production, deploy the
process behind a public HTTPS URL and use that as the Webhook URL instead of smee
(see [DESIGN.md](DESIGN.md) §12).

## Scaling

Concurrency and durability are separate knobs:

- **Concurrent PRs** — `WORKER_CONCURRENCY` (default 4) sets how many reviews
  run at once, with any backend. It's also the throttle against the two
  rate-limited APIs, so don't crank it blindly.
- **Durability / multiple processes** — the default `memory` queue is
  in-process: zero infrastructure, but queued jobs die with the process. Set
  `QUEUE_BACKEND=redis` (and `REDIS_URL`) for a durable queue shared across
  processes: jobs survive restarts (a reliable-queue pattern requeues work
  orphaned by a crash), and webhook delivery-ids dedupe across all workers.

With redis you can split web from workers:

```bash
WORKER_CONCURRENCY=0 uvicorn app.main:app    # web: verify + enqueue only
python -m app.worker                          # workers: run this on 1..N hosts
```

A single process with the memory queue is plenty for one account's repos; the
redis split is for surviving redeploys and scaling out.

## Test

```bash
pytest
```

The unit tests (signature verification, diff parsing, finding filters, retry)
run with no network access and no API key. Live smoke tests for each half of the
pipeline live in [scripts/](scripts) and read credentials from `.env`.

## Status

Working v1 — validated end to end against a live GitHub App: webhook → auth →
diff → Claude review → inline comments → commit status. See `DESIGN.md` §14 for
stretch goals (Redis-backed queue, `@bot` commands, persisted stats).
