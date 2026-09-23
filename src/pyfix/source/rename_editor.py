"""Syntax-aware, single-occurrence identifier renaming.

Used for typo fixes (``usernmae`` -> ``username``) and unexpected
keyword-argument typo fixes. Deliberately narrow in scope: it replaces
only the exact identifier occurrence(s) the caller identifies (by line
number, optionally by column), using a word-boundary regex scoped to
that one line — never a blind whole-file ``str.replace``. This mirrors
the safety posture of :mod:`pyfix.source.import_editor`.

This is intentionally more conservative than a full AST-rewrite: it
will not rename other occurrences of the same identifier elsewhere in
the file, because PyFix cannot safely assume every occurrence is the
same mistake. Confidence and scope are about *this* diagnosis, at
*this* location.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass


@dataclass
class RenameEditResult:
    new_content: str
    diff_text: str
    line_before: str
    line_after: str


def build_rename_edit(
    source: str,
    lineno: int,
    old_name: str,
    new_name: str,
    file_name: str = "file.py",
    column: int | None = None,
) -> RenameEditResult | None:
    """Replace one identifier occurrence on ``lineno`` with ``new_name``.

    If ``column`` is given, only the occurrence starting at that column
    is replaced. Otherwise, if ``old_name`` appears exactly once as a
    whole word on that line, that occurrence is replaced; if it appears
    more than once, all whole-word occurrences on that line are
    replaced (still never touching other lines).

    Returns ``None`` if the target line/name can't be found, so the
    caller can fall back to an explanation-only diagnosis rather than
    guessing.
    """

    lines = source.splitlines(keepends=True)
    if not (1 <= lineno <= len(lines)):
        return None

    line = lines[lineno - 1]
    pattern = re.compile(rf"\b{re.escape(old_name)}\b")

    if not pattern.search(line):
        return None

    if column is not None:
        # Replace only the occurrence starting exactly at `column`.
        match = None
        for m in pattern.finditer(line):
            if m.start() == column:
                match = m
                break
        if match is None:
            return None
        new_line = line[: match.start()] + new_name + line[match.end():]
    else:
        new_line = pattern.sub(new_name, line)

    new_lines = list(lines)
    new_lines[lineno - 1] = new_line
    new_content = "".join(new_lines)

    diff = difflib.unified_diff(
        [l.rstrip("\n") for l in lines],
        [l.rstrip("\n") for l in new_lines],
        fromfile=file_name,
        tofile=file_name,
        lineterm="",
    )
    diff_text = "\n".join(diff)

    return RenameEditResult(
        new_content=new_content,
        diff_text=diff_text,
        line_before=line.rstrip("\n"),
        line_after=new_line.rstrip("\n"),
    )
