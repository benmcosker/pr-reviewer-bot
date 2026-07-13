# PR Reviewer Bot

A GitHub App that reviews pull requests with Claude. It verifies the webhook,
pulls the diff, asks the Claude API for a structured review, and posts inline
comments back on the PR.

See [DESIGN.md](DESIGN.md) for the full architecture and rationale.

## Layout

```
app/
  main.py            FastAPI app; starts the background worker on startup
  config.py          settings (env / .env), loaded lazily
  web/
    security.py      X-Hub-Signature-256 HMAC verification
    webhooks.py      POST /webhooks — verify, enqueue, 202
  worker/
    jobs.py          ReviewJob
    queue.py         in-process asyncio queue + delivery-id dedupe (Redis is the v2 seam)
    runner.py        the job loop: auth → diff → review → post
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

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env      # fill in GitHub App + Anthropic credentials
```

## Run

```bash
uvicorn app.main:app --reload
curl localhost:8000/healthz            # {"status":"ok"}
```

Forward GitHub webhooks to localhost during development with
[smee.io](https://smee.io) or `ngrok http 8000`, and point the GitHub App's
webhook URL at it.

## Test

```bash
pytest
```

The unit tests (signature verification, diff parsing, finding filters) run with
no network access and no API key. See `DESIGN.md` §11 for the wider test plan.

## Status

Scaffold — all components are in place and wired end to end. Next per
`DESIGN.md` §13: exercise against a real PR (installation token → diff → review →
comments), then harden retries and large-diff chunking.
