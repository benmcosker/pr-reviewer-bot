from app.worker.jobs import ReviewJob

JOB = ReviewJob(
    installation_id=42,
    owner="octo",
    repo="demo",
    pr_number=7,
    head_sha="abc123",
    delivery_id="d-1",
)


def test_round_trip():
    assert ReviewJob.from_json(JOB.to_json()) == JOB


def test_serialization_is_deterministic():
    # the redis queue acks with LREM by exact value — same job, same string
    assert JOB.to_json() == ReviewJob.from_json(JOB.to_json()).to_json()


def test_title_round_trips():
    job = ReviewJob(
        installation_id=42,
        owner="octo",
        repo="demo",
        pr_number=7,
        head_sha="abc123",
        delivery_id="d-1",
        title="Add durable Redis queue",
    )
    assert ReviewJob.from_json(job.to_json()).title == "Add durable Redis queue"


def test_title_defaults_for_legacy_jobs():
    # a job serialized before `title` existed deserializes with the default
    legacy = (
        '{"delivery_id": "d-1", "head_sha": "abc123", "installation_id": 42, '
        '"owner": "octo", "pr_number": 7, "repo": "demo"}'
    )
    assert ReviewJob.from_json(legacy).title == ""
