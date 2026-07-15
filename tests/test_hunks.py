from app.review.diff import estimate_tokens, split_diff_by_file, split_into_hunks

MULTI_HUNK = """\
diff --git a/svc.py b/svc.py
index aaa..bbb 100644
--- a/svc.py
+++ b/svc.py
@@ -1,3 +1,4 @@
 import os
+import sys
 def a():
     return 1
@@ -20,2 +21,3 @@ def b():
 x = 1
+y = 2
 z = 3
"""


def test_estimate_tokens():
    assert estimate_tokens("a" * 400) == 100
    assert estimate_tokens("") == 0


def test_split_into_hunks_produces_standalone_diffs():
    fd = split_diff_by_file(MULTI_HUNK)[0]
    hunks = split_into_hunks(fd)
    assert len(hunks) == 2

    union: set[int] = set()
    for h in hunks:
        # each mini-diff must re-parse on its own, carrying the file header
        sub = split_diff_by_file(h)
        assert len(sub) == 1
        assert sub[0].path == "svc.py"
        assert sub[0].valid_lines  # non-empty
        union |= sub[0].valid_lines

    # the hunks partition the file's anchorable lines exactly
    assert union == fd.valid_lines
    assert fd.valid_lines == {1, 2, 3, 4, 21, 22, 23}


def test_single_hunk_returns_whole_diff():
    single = """\
diff --git a/x.py b/x.py
--- a/x.py
+++ b/x.py
@@ -1,1 +1,2 @@
 a
+b
"""
    fd = split_diff_by_file(single)[0]
    hunks = split_into_hunks(fd)
    assert len(hunks) == 1
    assert split_diff_by_file(hunks[0])[0].valid_lines == fd.valid_lines
