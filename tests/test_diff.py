from app.review.diff import should_skip, split_diff_by_file

SAMPLE = """\
diff --git a/app/foo.py b/app/foo.py
index 1111111..2222222 100644
--- a/app/foo.py
+++ b/app/foo.py
@@ -1,4 +1,5 @@ def existing():
 import os
-import sys
+import sys  # keep
+import json
 def existing():
     return os.getcwd()
diff --git a/README.md b/README.md
index 3333333..4444444 100644
--- a/README.md
+++ b/README.md
@@ -10,2 +10,3 @@ intro
 line ten
+new line eleven
 line twelve
"""


def test_splits_by_file():
    files = split_diff_by_file(SAMPLE)
    assert [f.path for f in files] == ["app/foo.py", "README.md"]


def test_valid_lines_include_added_and_context():
    files = {f.path: f for f in split_diff_by_file(SAMPLE)}
    foo = files["app/foo.py"]
    # new file: 1 import os, 2 import sys # keep, 3 import json, 4 def, 5 return
    assert {2, 3} <= foo.valid_lines  # the two added lines
    assert 1 in foo.valid_lines       # context line
    # removed "import sys" has no new-file line number
    assert max(foo.valid_lines) == 5


def test_readme_added_line_anchor():
    files = {f.path: f for f in split_diff_by_file(SAMPLE)}
    readme = files["README.md"]
    assert 11 in readme.valid_lines  # "new line eleven"


def test_deletion_is_dropped():
    deletion = (
        "diff --git a/gone.py b/gone.py\n"
        "deleted file mode 100644\n"
        "--- a/gone.py\n"
        "+++ /dev/null\n"
        "@@ -1,2 +0,0 @@\n"
        "-a\n-b\n"
    )
    assert split_diff_by_file(deletion) == []


def test_should_skip():
    globs = ["*.lock", "node_modules/*", "*.png"]
    assert should_skip("poetry.lock", globs)
    assert should_skip("node_modules/left-pad/index.js", globs)
    assert should_skip("logo.png", globs)
    assert not should_skip("app/main.py", globs)
