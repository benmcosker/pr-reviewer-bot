"""The unit of work passed from the webhook to the worker."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewJob:
    installation_id: int
    owner: str
    repo: str
    pr_number: int
    head_sha: str
    delivery_id: str
