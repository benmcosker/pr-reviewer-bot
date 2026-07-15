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
