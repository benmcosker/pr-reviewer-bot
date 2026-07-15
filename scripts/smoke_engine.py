"""Live smoke test for the Claude review engine.

Feeds a real unified diff (with two planted bugs) to `review_file` and checks
that the live structured-output call returns a well-formed Review whose findings
anchor to lines that actually appear in the diff.

Run:  ANTHROPIC_API_KEY=sk-ant-... .venv/bin/python scripts/smoke_engine.py
"""

import asyncio
import sys

from app.review.diff import split_diff_by_file
from app.review.engine import review_file

# A single-file diff that adds a function with a SQL-injection hole and a
# mutable default argument — both should be easy, high-confidence catches.
SAMPLE_DIFF = """\
diff --git a/app/users.py b/app/users.py
index 1111111..2222222 100644
--- a/app/users.py
+++ b/app/users.py
@@ -1,3 +1,12 @@
 import sqlite3

+
+def find_user(db, username):
+    query = "SELECT * FROM users WHERE name = '" + username + "'"
+    return db.execute(query).fetchone()
+
+
+def add_tags(user_id, tags=[]):
+    tags.append("new")
+    return {"user": user_id, "tags": tags}
+
 def healthcheck():
     return "ok"
"""


async def main() -> int:
    files = split_diff_by_file(SAMPLE_DIFF)
    assert len(files) == 1, f"expected 1 file, got {len(files)}"
    fd = files[0]
    print(f"file: {fd.path}")
    print(f"valid anchor lines: {sorted(fd.valid_lines)}\n")

    print("calling Claude (this exercises messages.parse + adaptive thinking)…")
    review = await review_file(fd.path, fd.diff_text)

    print(f"\nsummary: {review.summary}")
    print(f"findings: {len(review.findings)}\n")

    ok = True
    if not review.findings:
        print("!! no findings returned — expected the SQLi and/or mutable default")
        ok = False

    for f in review.findings:
        anchored = f.line in fd.valid_lines
        mark = "ok " if anchored else "OUT-OF-DIFF"
        print(f"  [{mark}] L{f.line} {f.severity}/{f.category}: {f.comment}")
        if not anchored:
            ok = False

    # Did it catch the security bug at all?
    caught_sqli = any(f.category == "security" for f in review.findings)
    print(f"\nsecurity finding present: {caught_sqli}")

    print("\nRESULT:", "PASS" if ok and caught_sqli else "CHECK OUTPUT ABOVE")
    return 0 if (ok and caught_sqli) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
