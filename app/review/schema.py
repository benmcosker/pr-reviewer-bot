"""Structured-output models for a review, plus small pure helpers.

These live apart from ``engine.py`` so they can be imported (and unit-tested)
without pulling in the Anthropic SDK.
"""

from typing import Literal

from pydantic import BaseModel

Severity = Literal["blocker", "warning", "nit"]
Category = Literal["correctness", "security", "performance", "style", "test"]


class Finding(BaseModel):
    path: str
    line: int  # line number in the file's NEW version (GitHub RIGHT side)
    severity: Severity
    category: Category
    comment: str  # inline message, markdown


class Review(BaseModel):
    summary: str
    findings: list[Finding]


def cap_nits(findings: list[Finding], max_per_file: int) -> list[Finding]:
    """Keep every blocker/warning; cap ``nit`` findings per file.

    Better recall from the model, noise controlled on our side.
    """
    kept: list[Finding] = []
    nit_counts: dict[str, int] = {}
    for f in findings:
        if f.severity != "nit":
            kept.append(f)
            continue
        n = nit_counts.get(f.path, 0)
        if n < max_per_file:
            kept.append(f)
            nit_counts[f.path] = n + 1
    return kept


def build_summary(findings: list[Finding], reviewed: int, total: int) -> str:
    """A short overall body for the PR review."""
    if not findings:
        base = f"Reviewed {reviewed} file(s) — no issues found. ✅"
    else:
        by_sev: dict[str, int] = {}
        for f in findings:
            by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
        parts = [f"{by_sev[s]} {s}" for s in ("blocker", "warning", "nit") if s in by_sev]
        base = f"Reviewed {reviewed} file(s): " + ", ".join(parts) + "."
    if total > reviewed:
        base += f" ({total - reviewed} file(s) skipped.)"
    return base + "\n\n_🤖 Automated review by Claude._"
