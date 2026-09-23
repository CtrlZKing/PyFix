"""Read-only Git awareness.

PyFix never commits, stashes, or discards changes on its own. This
module only reports what it finds so the UI can warn the user and
preserve any uncommitted work before touching source files.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GitStatus:
    is_repo: bool
    branch: str | None = None
    working_tree_clean: bool | None = None


def detect_git(project_root: Path) -> GitStatus:
    if not (project_root / ".git").exists():
        return GitStatus(is_repo=False)

    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], project_root)
    status_output = _run_git(["status", "--porcelain"], project_root)

    return GitStatus(
        is_repo=True,
        branch=branch.strip() if branch else None,
        working_tree_clean=(status_output is not None and status_output.strip() == ""),
    )


def _run_git(args: list[str], cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=5,
            shell=False,
        )
        if result.returncode != 0:
            return None
        return result.stdout
    except Exception:
        return None
