"""The unit of work passed from the webhook to the worker."""

import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ReviewJob:
    installation_id: int
    owner: str
    repo: str
    pr_number: int
    head_sha: str
    delivery_id: str

    def to_json(self) -> str:
        # sort_keys makes the encoding deterministic, so the same job always
        # serializes to the same string (the redis queue LREMs by exact value).
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> "ReviewJob":
        return cls(**json.loads(raw))
