"""PyFix's local, per-project state: diagnostic logs and the most
recent proposed/applied diff (backing ``pyfix logs`` / ``pyfix
clear-logs`` / ``pyfix diff``).

This deliberately reuses the same per-project ``<project_root>/.pyfix``
directory that :mod:`pyfix.safety.undo` already uses for backups and
the undo log, rather than introducing a second, global,
platform-specific state directory — PyFix already has exactly one
place it writes local state, and everything here stays consistent
with it. Nothing under ``.pyfix`` is ever the user's source code, so
``pyfix clear-logs`` clearing files here can never touch a project
file, a backup, or Git history.
"""

from __future__ import annotations

from pathlib import Path


def pyfix_state_dir(project_root: Path) -> Path:
    """The single per-project directory PyFix ever writes local state
    into. Callers are responsible for creating it (``mkdir(parents=True,
    exist_ok=True)``) before writing — this function never has a side
    effect, so read-only callers (like ``pyfix logs`` on a project
    that's never been touched) don't create the directory just by
    asking about it.
    """

    return project_root / ".pyfix"
