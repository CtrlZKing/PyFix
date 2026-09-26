"""Structural Syntax & Formatting Intelligence.

PyFix 2.x could *explain* a SyntaxError/IndentationError but never
attempted to repair one — see :mod:`pyfix.detectors.syntax_errors`.
This module is the analyzer that makes a small, well-understood set of
structural problems (a missing block colon, a mismatched closing
bracket, an unambiguous stray indent) safely auto-fixable, while
staying honest about everything else.

Design constraint: this is NOT a regex-based "saw the word `if`, add a
colon" hack. Every classification here is driven by the diagnostics
Python's own PEG parser already computes (``SyntaxError.msg`` /
``.lineno`` / ``.offset``), which are themselves derived from real
grammar analysis. Regex is only used to *parse those diagnostic
messages*, never to scan arbitrary source for keywords. Multi-line
statements, brackets, and strings are therefore handled correctly for
free, because the parser (not us) is the one that found the location.

Every finding here carries a confidence and an explicit auto-fixability
flag. Ambiguous cases (unclosed brackets, missing block bodies, "else"
with no matching block) are deliberately left as explanation-only:
PyFix must never invent code it cannot justify.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from pyfix.diagnostics.models import Diagnostic, DiagnosticCategory, DiagnosticConfidence, DiagnosticSeverity, Evidence

_CLOSERS = {"(": ")", "[": "]", "{": "}"}

_MISMATCH_RE = re.compile(
    r"closing parenthesis '(?P<found>[)\]}])' does not match "
    r"opening parenthesis '(?P<opener>[([{])'"
)
_NEVER_CLOSED_RE = re.compile(r"'(?P<opener>[([{])' was never closed")
_INDENTED_BLOCK_RE = re.compile(
    r"expected an indented block after '(?P<keyword>\w+)' statement on line (?P<line>\d+)"
)


class StructuralCategory:
    MISSING_COLON = "missing_colon"
    MISMATCHED_BRACKET = "mismatched_bracket"
    UNCLOSED_BRACKET = "unclosed_bracket"
    MISSING_BLOCK_BODY = "missing_block_body"
    UNEXPECTED_INDENT = "unexpected_indent"
    OTHER = "other_structural"


@dataclass
class StructuralFinding:
    """One structural diagnosis, independent of how it will be displayed.

    ``fix_new_content`` is populated only when ``can_auto_fix`` is True
    and the repair is a single, unambiguous, mechanical edit.
    """

    category: str
    lineno: int
    offset: int | None
    raw_message: str
    what_happened: str
    why_it_happened: str
    confidence: float  # 0.0-1.0, same scale as RepairProposal.confidence_score
    can_auto_fix: bool
    fix_description: str = ""
    fix_new_content: str | None = None
    unresolved_reason: str = ""
    evidence: list[str] = field(default_factory=list)


def analyze_structural(source: str) -> StructuralFinding | None:
    """Classify the SyntaxError (if any) that parsing ``source`` raises.

    Returns None when the source parses cleanly, or when it fails in a
    way this subsystem does not (yet) have a specific classification
    for — callers fall back to the generic syntax-error explanation in
    that case, so nothing is ever silently dropped.
    """

    try:
        ast.parse(source)
        return None
    except SyntaxError as exc:
        return _classify(source, exc)


def _confidence_bucket(score: float) -> DiagnosticConfidence:
    if score >= 0.95:
        return DiagnosticConfidence.CERTAIN
    if score >= 0.8:
        return DiagnosticConfidence.HIGH
    if score >= 0.5:
        return DiagnosticConfidence.MEDIUM
    return DiagnosticConfidence.LOW


def structural_finding_to_diagnostic(finding: StructuralFinding, file_path: Path) -> Diagnostic:
    """Adapt a :class:`StructuralFinding` into the Level-2 ``Diagnostic``
    model used by ``pyfix analyze`` / ``pyfix doctor`` for whole-file,
    multi-issue reporting."""

    return Diagnostic(
        file=file_path,
        line=finding.lineno,
        column=finding.offset,
        category=DiagnosticCategory.SYNTAX,
        severity=DiagnosticSeverity.CRITICAL,
        message=finding.what_happened,
        confidence=_confidence_bucket(finding.confidence),
        what_happened=finding.what_happened,
        why_it_happened=finding.why_it_happened,
        evidence=[Evidence(description=e) for e in finding.evidence],
        proposed_fix_summary=finding.fix_description,
        safe_to_apply=finding.can_auto_fix,
        fix_new_content=finding.fix_new_content,
    )


def _classify(source: str, exc: SyntaxError) -> StructuralFinding | None:
    msg = exc.msg or ""
    lines = source.splitlines(keepends=True)
    lineno = exc.lineno or 1

    if msg == "expected ':'":
        return _missing_colon(lines, lineno, exc.offset)

    m = _MISMATCH_RE.search(msg)
    if m:
        return _mismatched_bracket(lines, lineno, exc.offset, m.group("found"), m.group("opener"))

    m = _NEVER_CLOSED_RE.search(msg)
    if m:
        return _unclosed_bracket(lineno, exc.offset, m.group("opener"))

    m = _INDENTED_BLOCK_RE.search(msg)
    if m:
        return _missing_block_body(m.group("keyword"), int(m.group("line")))

    if msg == "unexpected indent":
        return _unexpected_indent(lines, lineno)

    return None


def _line_text(lines: list[str], lineno: int) -> str:
    if 1 <= lineno <= len(lines):
        return lines[lineno - 1]
    return ""


def _missing_colon(lines: list[str], lineno: int, offset: int | None) -> StructuralFinding:
    line = _line_text(lines, lineno)
    stripped = line.rstrip("\n\r")
    code_before = stripped
    keyword_match = re.match(r"\s*(if|elif|else|for|while|def|class|try|except|finally|with|match|case)\b", stripped)
    keyword = keyword_match.group(1) if keyword_match else "this statement"

    fix_new_content: str | None = None
    fix_description = ""
    can_auto_fix = False

    if offset is not None and 1 <= offset <= len(line) + 1:
        idx = offset - 1
        prefix = line[:idx]
        suffix = line[idx:]
        code_part = prefix.rstrip(" \t")
        trailing_ws = prefix[len(code_part):]
        if suffix.lstrip(" \t").startswith("#") or suffix.strip() == "":
            new_line = code_part + ":" + (" " if suffix.lstrip(" \t").startswith("#") else "") + suffix.lstrip(" \t")
        else:
            # Shouldn't normally happen (parser points right before the
            # newline/comment) but stay safe and just insert in place.
            new_line = code_part + ":" + trailing_ws + suffix
        new_lines = list(lines)
        new_lines[lineno - 1] = new_line
        fix_new_content = "".join(new_lines)
        fix_description = f"Insert ':' at the end of line {lineno}."
        can_auto_fix = True

    return StructuralFinding(
        category=StructuralCategory.MISSING_COLON,
        lineno=lineno,
        offset=offset,
        raw_message="expected ':'",
        what_happened=f"The `{keyword}` statement on line {lineno} is missing its trailing colon.",
        why_it_happened=(
            f"Python block statements ({keyword!r} included) must end the line that opens "
            "the block with `:`. The parser reached the end of this statement without "
            "finding one."
        ),
        confidence=0.97,
        can_auto_fix=can_auto_fix,
        fix_description=fix_description,
        fix_new_content=fix_new_content,
        evidence=[f"Line {lineno}: {code_before!r}", "Python's parser reports: expected ':'"],
    )


def _mismatched_bracket(
    lines: list[str], lineno: int, offset: int | None, found: str, opener: str
) -> StructuralFinding:
    expected = _CLOSERS.get(opener, found)
    line = _line_text(lines, lineno)

    fix_new_content: str | None = None
    fix_description = ""
    can_auto_fix = False

    if offset is not None and 1 <= offset <= len(line):
        idx = offset - 1
        if line[idx] == found:
            new_line = line[:idx] + expected + line[idx + 1 :]
            new_lines = list(lines)
            new_lines[lineno - 1] = new_line
            fix_new_content = "".join(new_lines)
            fix_description = f"Replace '{found}' with '{expected}' on line {lineno}."
            can_auto_fix = True

    return StructuralFinding(
        category=StructuralCategory.MISMATCHED_BRACKET,
        lineno=lineno,
        offset=offset,
        raw_message=f"closing parenthesis '{found}' does not match opening parenthesis '{opener}'",
        what_happened=f"A closing `{found}` on line {lineno} doesn't match the `{opener}` it's closing.",
        why_it_happened=(
            f"`{opener}` was opened earlier and Python expects it to be closed with "
            f"`{expected}`, but `{found}` appears instead."
        ),
        confidence=0.95,
        can_auto_fix=can_auto_fix,
        fix_description=fix_description,
        fix_new_content=fix_new_content,
        evidence=[f"Line {lineno}: {line.rstrip()!r}", "Python's parser reports the specific bracket mismatch."],
    )


def _unclosed_bracket(lineno: int, offset: int | None, opener: str) -> StructuralFinding:
    expected = _CLOSERS.get(opener, "")
    return StructuralFinding(
        category=StructuralCategory.UNCLOSED_BRACKET,
        lineno=lineno,
        offset=offset,
        raw_message=f"'{opener}' was never closed",
        what_happened=f"A `{opener}` opened on line {lineno} is never closed with `{expected}`.",
        why_it_happened=(
            f"Python scanned the rest of the file looking for the matching `{expected}` "
            "and reached the end without finding one."
        ),
        confidence=0.6,
        can_auto_fix=False,
        unresolved_reason="unclosed_bracket_insertion_point_is_ambiguous",
        evidence=[f"Opened at line {lineno}, column {offset}.", f"No matching '{expected}' was found."],
    )


def _missing_block_body(keyword: str, keyword_line: int) -> StructuralFinding:
    return StructuralFinding(
        category=StructuralCategory.MISSING_BLOCK_BODY,
        lineno=keyword_line,
        offset=None,
        raw_message=f"expected an indented block after '{keyword}' statement on line {keyword_line}",
        what_happened=f"The `{keyword}` statement on line {keyword_line} has no body.",
        why_it_happened=(
            "Python requires at least one indented statement inside every block. "
            "Nothing followed this line at a deeper indentation level."
        ),
        confidence=0.9,
        can_auto_fix=False,
        unresolved_reason="missing_block_body_cannot_be_invented",
        evidence=[f"Line {keyword_line} opens a `{keyword}` block.", "No indented statement follows it."],
    )


def _unexpected_indent(lines: list[str], lineno: int) -> StructuralFinding:
    line = _line_text(lines, lineno)
    indent = len(line) - len(line.lstrip(" \t"))

    # Look back for the previous non-blank line to see whether it opens
    # a block (ends with ':') — if it does, this isn't actually a
    # "stray" indent (that's a different, ambiguous situation Python
    # would have reported differently), so we only auto-fix when the
    # previous line clearly does NOT open a block.
    prev_idx = lineno - 2
    prev_line = ""
    while prev_idx >= 0:
        candidate = lines[prev_idx]
        if candidate.strip() != "":
            prev_line = candidate
            break
        prev_idx -= 1

    prev_stripped = prev_line.rstrip("\n\r")
    prev_indent = len(prev_line) - len(prev_line.lstrip(" \t"))
    opens_block = prev_stripped.rstrip().endswith(":")

    can_auto_fix = False
    fix_new_content: str | None = None
    fix_description = ""

    if prev_line and not opens_block and indent > prev_indent:
        new_line = (" " * prev_indent) + line.lstrip(" \t")
        new_lines = list(lines)
        new_lines[lineno - 1] = new_line
        fix_new_content = "".join(new_lines)
        fix_description = f"Reduce indentation of line {lineno} to match line {lineno - 1}."
        can_auto_fix = True

    return StructuralFinding(
        category=StructuralCategory.UNEXPECTED_INDENT,
        lineno=lineno,
        offset=None,
        raw_message="unexpected indent",
        what_happened=f"Line {lineno} is indented, but there is no open block that requires it.",
        why_it_happened=(
            "Python tracks blocks by indentation. This line is indented further than the "
            "block it's part of, so the parser can't tell what block it's supposed to "
            "belong to."
        ),
        confidence=0.75 if can_auto_fix else 0.4,
        can_auto_fix=can_auto_fix,
        fix_description=fix_description,
        fix_new_content=fix_new_content,
        unresolved_reason="" if can_auto_fix else "unexpected_indent_target_is_ambiguous",
        evidence=[f"Line {lineno}: {line.rstrip()!r}", f"Previous non-blank line: {prev_stripped!r}"],
    )
