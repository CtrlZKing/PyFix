"""Everything that stands between a proposal and the outside world.

No install, no file write, and no subprocess call anywhere in PyFix
is allowed to run without first passing through this module. These
functions raise :class:`UnsafeOperationError` rather than silently
sanitizing input, because silently "fixing" a suspicious input is how
injection bugs slip through review.
"""

from __future__ import annotations

import re
from pathlib import Path

# PEP 503 / PyPI-ish package name: letters, digits, ., -, _  only.
_PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,213}$")

# A conservative allow-list for pip version specifiers appended to a name,
# e.g. "requests==2.31.0". We validate name and specifier separately.
_VERSION_SPEC_RE = re.compile(r"^(==|>=|<=|~=|!=|>|<)[A-Za-z0-9.*+!-]{1,64}$")

_SUSPICIOUS_SUBSTRINGS = (";", "&&", "||", "|", "`", "$(", "\n", "\r", ">", "<", "\\")


class UnsafeOperationError(Exception):
    """Raised when PyFix refuses to perform a requested operation."""


def validate_package_name(name: str) -> str:
    """Validate (and return) a package distribution name.

    Rejects anything that isn't a bare, well-formed package name —
    in particular anything that looks like shell metacharacters
    smuggled in through an error message or an AI suggestion.
    """

    if not name or not isinstance(name, str):
        raise UnsafeOperationError("Empty or invalid package name.")

    candidate = name.strip()

    for bad in _SUSPICIOUS_SUBSTRINGS:
        if bad in candidate:
            raise UnsafeOperationError(
                f"Refusing to install {name!r}: contains disallowed "
                f"character sequence {bad!r}."
            )

    # Split off an optional version specifier and validate each half.
    base = candidate
    for op in ("==", ">=", "<=", "~=", "!=", ">", "<"):
        if op in candidate:
            base, _, spec = candidate.partition(op)
            if not _VERSION_SPEC_RE.match(op + spec):
                raise UnsafeOperationError(
                    f"Refusing to install {name!r}: invalid version specifier."
                )
            break

    if not _PACKAGE_NAME_RE.match(base):
        raise UnsafeOperationError(
            f"Refusing to install {name!r}: not a valid package name."
        )

    return candidate


def validate_argv(argv: list[str]) -> list[str]:
    """Validate a command argument vector before it is ever executed.

    PyFix never builds commands via string concatenation or runs them
    with ``shell=True``; this is the final checkpoint before a
    subprocess call.
    """

    if not argv or not isinstance(argv, list):
        raise UnsafeOperationError("Refusing to run an empty command.")

    for part in argv:
        if not isinstance(part, str):
            raise UnsafeOperationError("Command arguments must be strings.")
        for bad in (";", "&&", "||", "`", "$(", "\n", "\r"):
            if bad in part:
                raise UnsafeOperationError(
                    f"Refusing to run command containing {bad!r}: {argv!r}"
                )

    return argv


def validate_path_within_project(path: Path, project_root: Path) -> Path:
    """Ensure ``path`` resolves to somewhere inside ``project_root``.

    Prevents a proposal (however it was generated) from writing to,
    or deleting, anything outside the user's own project directory.
    """

    resolved_root = project_root.resolve()
    resolved_path = (project_root / path).resolve() if not path.is_absolute() else path.resolve()

    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise UnsafeOperationError(
            f"Refusing to touch path outside the project: {path}"
        ) from exc

    return resolved_path


def is_destructive_command(argv: list[str]) -> bool:
    """Heuristic flag for commands that should require extra confirmation."""

    joined = " ".join(argv).lower()
    destructive_markers = ("uninstall", "rm ", "rmdir", "delete", "remove", "recreate")
    return any(marker in joined for marker in destructive_markers)
