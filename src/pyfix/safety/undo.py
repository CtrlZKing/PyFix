"""A tiny, append-only log of reversible changes, backing `pyfix undo`.

Every source-file edit PyFix performs is recorded here alongside the
backup path written by :func:`pyfix.source.import_editor.write_with_backup`,
so the most recent change can be rolled back exactly.

PyFix does not promise to undo everything (e.g. a completed
``pip install`` is only "undone" by uninstalling, which is its own
Level-4 destructive proposal) — this module only ever claims to
reverse what it can actually reverse.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class UndoEntry:
    timestamp: str
    kind: str  # "source_edit" | "requirements_edit"
    target_path: str
    backup_path: str
    description: str


class UndoLog:
    def __init__(self, log_path: Path):
        self.log_path = log_path

    def record(self, entry: UndoEntry) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        entries = self._read_all()
        entries.append(asdict(entry))
        self.log_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")

    def last(self) -> UndoEntry | None:
        entries = self._read_all()
        if not entries:
            return None
        return UndoEntry(**entries[-1])

    def pop_last(self) -> UndoEntry | None:
        entries = self._read_all()
        if not entries:
            return None
        last = entries.pop()
        self.log_path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
        return UndoEntry(**last)

    def _read_all(self) -> list[dict]:
        if not self.log_path.exists():
            return []
        try:
            return json.loads(self.log_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []


def new_entry(kind: str, target_path: Path, backup_path: Path, description: str) -> UndoEntry:
    return UndoEntry(
        timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
        kind=kind,
        target_path=str(target_path),
        backup_path=str(backup_path),
        description=description,
    )
