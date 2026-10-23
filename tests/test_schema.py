from app.review.schema import Finding, build_summary, cap_nits, render_intent


def _f(path: str, line: int, severity: str) -> Finding:
    return Finding(path=path, line=line, severity=severity, category="style", comment="x")


def test_cap_nits_keeps_all_non_nits():
    findings = [_f("a.py", i, "warning") for i in range(5)]
    assert len(cap_nits(findings, max_per_file=1)) == 5


def test_cap_nits_limits_nits_per_file():
    findings = [_f("a.py", i, "nit") for i in range(5)] + [_f("b.py", i, "nit") for i in range(5)]
    kept = cap_nits(findings, max_per_file=2)
    assert sum(1 for f in kept if f.path == "a.py") == 2
    assert sum(1 for f in kept if f.path == "b.py") == 2


def test_summary_clean():
    assert "no issues" in build_summary([], reviewed=3, total=3)


def test_summary_counts_and_skips():
    findings = [_f("a.py", 1, "blocker"), _f("a.py", 2, "nit")]
    summary = build_summary(findings, reviewed=2, total=5)
    assert "1 blocker" in summary
    assert "1 nit" in summary
    assert "3 file(s) skipped" in summary


def test_summary_oversize_and_failed():
    findings = [_f("a.py", 1, "warning")]
    summary = build_summary(
        findings, reviewed=3, total=3, oversize=["big.py"], failed=["x.py", "y.py"]
    )
    assert "1 file(s) too large to review in full" in summary
    assert "2 file(s) errored after retries" in summary


def test_render_intent_includes_intent_and_breakdown():
    out = render_intent(
        "Adds a durable Redis queue so jobs survive restarts.",
        [("app/worker/redis_queue.py", "New reliable-queue backend."), ("README.md", "Documents the seam.")],
    )
    assert "What this PR does" in out
    assert "survive restarts" in out
    assert "### File breakdown" in out
    assert "- **`app/worker/redis_queue.py`** — New reliable-queue backend." in out
    assert "- **`README.md`** — Documents the seam." in out


def test_render_intent_drops_empty_summaries():
    out = render_intent("Does a thing.", [("a.py", "Real summary."), ("b.py", "  ")])
    assert "a.py" in out
    assert "b.py" not in out


def test_render_intent_omits_breakdown_when_no_summaries():
    out = render_intent("Does a thing.", [])
    assert "Does a thing." in out
    assert "File breakdown" not in out
