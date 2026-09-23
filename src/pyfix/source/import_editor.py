"""Syntax-aware source editing with mandatory diffs and backups.

PyFix never edits source with crude ``str.replace``. Insertion points
are computed from the AST (see :mod:`pyfix.source.ast_utils`), every
edit produces a unified diff for the user to review, and a backup is
written before anything touches disk so ``pyfix undo`` can restore it.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from pyfix.source.ast_utils import SourceAnalysis


@dataclass
class ImportEditResult:
    new_content: str
    diff_text: str
    insert_line: int


def build_add_import_edit(source: str, module_name: str, file_name: str = "game.py") -> ImportEditResult:
    """Compute the edit that adds ``import module_name`` to ``source``.

    This does not touch the filesystem — it only produces the new
    content and a diff, so it can be shown to the user before anything
    is approved.
    """

    analysis = SourceAnalysis(source)
    insert_line = analysis.first_import_line()

    lines = source.splitlines(keepends=True)
    new_line = f"import {module_name}\n"

    insert_idx = min(insert_line - 1, len(lines))
    insert_idx = max(insert_idx, 0)

    new_lines = lines[:insert_idx] + [new_line] + lines[insert_idx:]
    new_content = "".join(new_lines)

    diff = difflib.unified_diff(
        [line.rstrip("\n") for line in lines],
        [line.rstrip("\n") for line in new_lines],
        fromfile=file_name,
        tofile=file_name,
        lineterm="",
    )
    diff_text = "\n".join(diff)

    return ImportEditResult(new_content=new_content, diff_text=diff_text, insert_line=insert_idx + 1)


def write_with_backup(path: Path, new_content: str, backup_dir: Path) -> Path:
    """Write ``new_content`` to ``path``, keeping a timestamped backup.

    Returns the backup path so it can be recorded for ``pyfix undo``.
    """

    import time

    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"{path.name}.{timestamp}.bak"

    original = path.read_text(encoding="utf-8") if path.exists() else ""
    backup_path.write_text(original, encoding="utf-8")

    path.write_text(new_content, encoding="utf-8")
    return backup_path


def restore_from_backup(path: Path, backup_path: Path) -> None:
    content = backup_path.read_text(encoding="utf-8")
    path.write_text(content, encoding="utf-8")
