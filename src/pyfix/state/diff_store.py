"""Persistence for ``pyfix diff`` — the most recent PyFix-proposed or
applied diff, retrievable from a separate CLI invocation.

A :class:`pyfix.core.models.RepairProposal` only exists in memory for
the process that produced it (`pyfix run`, `pyfix explain`). For
`pyfix diff` to show it from a *later*, separate `pyfix diff` process,
it has to be written down — this module is that single, small,
single-slot state file (one JSON object, not a growing log — "the
most recent diff" is a specific, bounded thing to remember, unlike the
open-ended history `DiagnosticLog` keeps).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pyfix.core.models import RepairProposal
from pyfix.state import pyfix_state_dir

_DIFF_FILENAME = "last_diff.json"


@dataclass
class FileDiff:
    file_path: str
    description: str
    diff_text: str


@dataclass
class DiffRecord:
    timestamp: str
    command: str
    category: str
    applied: bool
    files: list[FileDiff] = field(default_factory=list)


class DiffStore:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.path = pyfix_state_dir(project_root) / _DIFF_FILENAME

    def save(self, proposal: RepairProposal, *, command: str, applied: bool) -> None:
        if not proposal.proposed_changes:
            return  # nothing to persist — an explanation-only proposal has no diff
        record = DiffRecord(
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            command=command,
            category=proposal.category,
            applied=applied,
            files=[
                FileDiff(file_path=str(c.file_path), description=c.description, diff_text=c.diff_text)
                for c in proposal.proposed_changes
                if c.diff_text
            ],
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(record), indent=2), encoding="utf-8")

    def load(self) -> DiffRecord | None:
        """Returns None both when no diff has ever been recorded AND
        when the state file is unreadable/corrupted — either way,
        `pyfix diff` must say "no diff available" rather than crash or
        fabricate one."""

        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            files = [FileDiff(**f) for f in data.get("files", [])]
            return DiffRecord(
                timestamp=data["timestamp"],
                command=data["command"],
                category=data["category"],
                applied=data["applied"],
                files=files,
            )
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            return None

    def clear(self) -> None:
        try:
            if self.path.exists():
                self.path.unlink()
        except OSError:
            pass
