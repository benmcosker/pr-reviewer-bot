from app.review.schema import Finding, build_summary, cap_nits


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
