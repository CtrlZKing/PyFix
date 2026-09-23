"""A deterministic parser for Python tracebacks.

PyFix does not use an LLM to understand a traceback's structure. This
is a small, well-tested, regex/line based parser that extracts the
exception type, message, frames, and chained-exception structure so
that detectors have a reliable structured object to work from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Frame:
    file: str
    line: int
    function: str
    source_line: str | None = None


@dataclass
class TracebackInfo:
    exception_type: str
    message: str
    frames: list[Frame] = field(default_factory=list)
    cause: "TracebackInfo | None" = None   # `raise X from Y`
    context: "TracebackInfo | None" = None  # implicit chaining
    raw_text: str = ""

    @property
    def last_frame(self) -> Frame | None:
        return self.frames[-1] if self.frames else None


_FRAME_RE = re.compile(
    r'^\s*File "(?P<file>.+?)", line (?P<line>\d+), in (?P<function>.+?)\s*$'
)
_EXCEPTION_LINE_RE = re.compile(
    r"^(?P<type>[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Warning|Interrupt|Exit))"
    r"(?::\s*(?P<message>.*))?$"
)
_CAUSE_HEADER = "The above exception was the direct cause of the following exception:"
_CONTEXT_HEADER = "During handling of the above exception, another exception occurred:"


def parse_traceback(text: str) -> TracebackInfo | None:
    """Parse raw traceback text (as printed by the interpreter).

    Returns ``None`` if no recognizable exception line is found. When
    the traceback contains chained exceptions, only the outermost
    (most recently raised) exception's ``TracebackInfo`` is returned,
    with the earlier one(s) attached via ``.cause`` / ``.context``.
    """

    text = text.strip("\n")
    if not text.strip():
        return None

    # Split on chaining headers, preserving order (earliest first).
    sections: list[tuple[str | None, str]] = []
    remaining = text
    header_pattern = re.compile(f"({re.escape(_CAUSE_HEADER)}|{re.escape(_CONTEXT_HEADER)})")
    parts = header_pattern.split(remaining)

    if len(parts) == 1:
        sections.append((None, remaining))
    else:
        sections.append((None, parts[0]))
        i = 1
        while i < len(parts):
            header = parts[i]
            body = parts[i + 1] if i + 1 < len(parts) else ""
            sections.append((header, body))
            i += 2

    parsed_chain: list[tuple[str | None, TracebackInfo]] = []
    for header, section_text in sections:
        info = _parse_single_traceback(section_text)
        if info is not None:
            parsed_chain.append((header, info))

    if not parsed_chain:
        return None

    # Link them: each later one's cause/context is the previous one.
    result: TracebackInfo | None = None
    prev: TracebackInfo | None = None
    for header, info in parsed_chain:
        if prev is not None:
            if header == _CAUSE_HEADER:
                info.cause = prev
            else:
                info.context = prev
        prev = info
        result = info

    if result is not None:
        result.raw_text = text
    return result


def _parse_single_traceback(text: str) -> TracebackInfo | None:
    lines = text.strip("\n").splitlines()
    if not lines:
        return None

    frames: list[Frame] = []
    i = 0
    while i < len(lines):
        m = _FRAME_RE.match(lines[i])
        if m:
            source_line = None
            if i + 1 < len(lines) and lines[i + 1].strip() and not lines[i + 1].startswith("Traceback"):
                candidate = lines[i + 1]
                if not _FRAME_RE.match(candidate) and not _EXCEPTION_LINE_RE.match(candidate.strip()):
                    source_line = candidate.strip()
            frames.append(
                Frame(
                    file=m.group("file"),
                    line=int(m.group("line")),
                    function=m.group("function"),
                    source_line=source_line,
                )
            )
        i += 1

    # The final non-empty line that matches an exception pattern is the
    # actual exception type + message.
    exc_type = None
    exc_message = ""
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            continue
        m = _EXCEPTION_LINE_RE.match(stripped)
        if m:
            exc_type = m.group("type")
            exc_message = m.group("message") or ""
            break
        break  # last non-empty line didn't match -> not a recognizable traceback

    if exc_type is None:
        return None

    return TracebackInfo(exception_type=exc_type, message=exc_message.strip(), frames=frames)
