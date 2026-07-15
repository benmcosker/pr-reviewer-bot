"""Unified-diff parsing.

Splits a ``git diff`` into per-file chunks and, for each file, computes the set
of NEW-version line numbers that are valid anchor points for a GitHub review
comment (added lines + context lines). Findings anchored outside this set are
dropped upstream to avoid 422s from GitHub.
"""

import re
from dataclasses import dataclass, field
from fnmatch import fnmatch

_HUNK_NEW_START = re.compile(r"\+(\d+)")


@dataclass
class FileDiff:
    path: str
    diff_text: str
    valid_lines: set[int] = field(default_factory=set)


def split_diff_by_file(diff_text: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    lines: list[str] | None = None
    path: str | None = None
    valid: set[int] = set()
    new_line = 0

    def flush() -> None:
        if lines is not None and path:
            files.append(FileDiff(path=path, diff_text="\n".join(lines), valid_lines=set(valid)))

    for raw in diff_text.splitlines():
        line = raw.rstrip("\r")

        if line.startswith("diff --git"):
            flush()
            lines = [line]
            path = None
            valid = set()
            new_line = 0
            continue

        if lines is None:
            continue
        lines.append(line)

        if line.startswith("+++ "):
            p = line[4:].strip()
            if p == "/dev/null":
                path = None  # deletion — nothing to review on the RIGHT side
            elif p.startswith("b/"):
                path = p[2:]
            else:
                path = p
        elif line.startswith("@@"):
            # @@ -a,b +c,d @@  — c is the new-file start line
            body = line.split("@@", 2)[1]
            m = _HUNK_NEW_START.search(body)
            new_line = int(m.group(1)) if m else 0
        elif line.startswith("+++"):
            pass
        elif line.startswith("+"):
            if new_line:
                valid.add(new_line)
                new_line += 1
        elif line.startswith("---") or line.startswith("-"):
            pass  # removed / old-file header — no new-file line number
        elif line.startswith(" "):
            if new_line:
                valid.add(new_line)
                new_line += 1
        # blank/other lines: ignore

    flush()
    return [f for f in files if f.path]


def should_skip(path: str, skip_globs: list[str]) -> bool:
    return any(fnmatch(path, g) for g in skip_globs)


def estimate_tokens(text: str) -> int:
    """Cheap offline token estimate (~4 chars/token).

    Used as the large-diff gate so we don't pay a ``count_tokens`` round-trip
    before every review; the exact count only matters near the budget edge.
    """
    return len(text) // 4


def split_into_hunks(file_diff: FileDiff) -> list[str]:
    """Split one file's diff into standalone single-hunk mini-diffs.

    Each returned string re-parses on its own (it carries the ``diff --git`` /
    ``---`` / ``+++`` header), so a too-large file can be reviewed one hunk at a
    time. Returns the whole diff unchanged if there are no hunk markers.
    """
    lines = file_diff.diff_text.splitlines()
    header: list[str] = []
    i = 0
    while i < len(lines) and not lines[i].startswith("@@"):
        header.append(lines[i])
        i += 1

    hunks: list[list[str]] = []
    current: list[str] | None = None
    for line in lines[i:]:
        if line.startswith("@@"):
            if current is not None:
                hunks.append(current)
            current = header + [line]
        elif current is not None:
            current.append(line)
    if current is not None:
        hunks.append(current)

    return ["\n".join(h) for h in hunks] or [file_diff.diff_text]
