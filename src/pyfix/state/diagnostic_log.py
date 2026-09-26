"""Structured, persistent diagnostic logging — backs ``pyfix logs`` /
``pyfix clear-logs``.

Design:

* One JSON object per line (JSON Lines), append-only. This is the
  standard "log file" format: writers only ever append a line (cheap,
  no read-modify-write of the whole file, no partial-write corruption
  of earlier entries), and a reader that hits one malformed line can
  skip just that line instead of losing the whole log — unlike the
  single-JSON-array-per-file approach :mod:`pyfix.safety.undo` uses
  for the (much smaller, rarely-corrupted-in-practice) undo log.
* Every field is something PyFix itself already computed (category,
  confidence, location, ...). Nothing from the process environment is
  ever written, so there is no risk of a credential/token/cookie
  ending up in a log file.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pyfix import __version__
from pyfix.state import pyfix_state_dir

_LOG_FILENAME = "logs.jsonl"


@dataclass
class DiagnosticLogEntry:
    """One record of "PyFix looked at something and this is what
    happened" — one per detected issue, not one per CLI invocation, so
    a single ``pyfix run`` that fixes three issues produces three
    entries."""

    timestamp: str
    command: str  # "run" | "analyze" | "explain" | "doctor"
    target: str  # file or project path
    category: str = ""
    severity: str = ""
    confidence: str = ""  # human label, e.g. "high (96%)"
    what_happened: str = ""
    proposed_repair: str = ""
    applied: bool = False
    apply_succeeded: bool | None = None
    verified: bool | None = None
    iteration: int | None = None
    rollback: bool = False
    unresolved_reason: str = ""
    pyfix_version: str = field(default_factory=lambda: __version__)

    def summary_line(self) -> str:
        status = (
            "↩ rolled back" if self.rollback
            else "✓ applied & verified" if self.applied and self.verified
            else "✓ applied (unverified)" if self.applied and self.verified is False
            else "explained only" if not self.applied
            else "applied"
        )
        return f"[{self.timestamp}] {self.command} {self.target} — {self.category or 'unknown'} ({status})"

    def detail_lines(self) -> list[str]:
        lines = [self.summary_line()]
        if self.what_happened:
            lines.append(f"    what happened: {self.what_happened}")
        if self.confidence:
            lines.append(f"    confidence: {self.confidence}")
        if self.severity:
            lines.append(f"    severity: {self.severity}")
        if self.proposed_repair:
            lines.append(f"    proposed repair: {self.proposed_repair}")
        if self.iteration is not None:
            lines.append(f"    iteration: {self.iteration}")
        if self.applied:
            lines.append(f"    apply succeeded: {self.apply_succeeded}")
            lines.append(f"    verified: {self.verified}")
        if self.rollback:
            lines.append("    rolled back: yes")
        if self.unresolved_reason:
            lines.append(f"    unresolved reason: {self.unresolved_reason}")
        lines.append(f"    pyfix version: {self.pyfix_version}")
        return lines


class DiagnosticLog:
    """Append-only JSONL log for one project, plus tolerant reading and
    a safe, scoped ``clear()``."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.path = pyfix_state_dir(project_root) / _LOG_FILENAME

    def record(self, entry: DiagnosticLogEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(entry)) + "\n")

    def read_all(self) -> tuple[list[DiagnosticLogEntry], int]:
        """Return (entries, number_of_corrupt_lines_skipped).

        One malformed line (truncated write, manual edit, disk issue)
        must never make ``pyfix logs`` crash or hide every other entry
        — this is the whole reason JSONL was chosen over one big JSON
        array.
        """

        if not self.path.exists():
            return [], 0

        entries: list[DiagnosticLogEntry] = []
        corrupt = 0
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError:
            return [], 0

        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                entries.append(DiagnosticLogEntry(**data))
            except (json.JSONDecodeError, TypeError):
                corrupt += 1
        return entries, corrupt

    def clear(self) -> int:
        """Delete only this log file. Never touches backups, the undo
        log, the diff store, source files, or anything under .git.
        Returns the number of entries that were cleared."""

        entries, _ = self.read_all()
        try:
            if self.path.exists():
                self.path.unlink()
        except OSError:
            pass
        return len(entries)

    def exists(self) -> bool:
        return self.path.exists()
