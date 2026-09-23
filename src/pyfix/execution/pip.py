"""Safe package installation using the CURRENT interpreter's pip.

Never runs a bare ``pip install ...`` string. Always shells out to
``<current-python> -m pip install <package>`` as an argv list, so the
package lands in the exact environment that is running the user's
program — never some other ``pip`` that happens to be on PATH.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from pyfix.core.models import Command
from pyfix.safety.validation import validate_argv, validate_package_name


@dataclass
class InstallResult:
    succeeded: bool
    stdout: str
    stderr: str
    returncode: int


def build_install_command(package_name: str, python_executable: Path | None = None) -> Command:
    """Build (but do not run) the install command for review/display."""

    validated_name = validate_package_name(package_name)
    executable = str(python_executable or sys.executable)
    argv = [executable, "-m", "pip", "install", validated_name]
    validate_argv(argv)
    return Command(
        argv=argv,
        description=f"Install {validated_name} into the active Python environment.",
    )


def run_install(command: Command, timeout: int = 300) -> InstallResult:
    """Actually execute a previously-approved install command.

    This is the only function in PyFix allowed to run ``pip install``.
    It must only ever be called after explicit user approval.
    """

    argv = validate_argv(command.argv)

    try:
        completed = subprocess.run(
            argv,
            cwd=str(command.cwd) if command.cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        return InstallResult(
            succeeded=completed.returncode == 0,
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
        )
    except subprocess.TimeoutExpired as exc:
        return InstallResult(
            succeeded=False,
            stdout=exc.stdout or "" if isinstance(exc.stdout, str) else "",
            stderr=f"Installation timed out after {timeout}s.",
            returncode=-1,
        )
    except OSError as exc:
        return InstallResult(succeeded=False, stdout="", stderr=str(exc), returncode=-1)
