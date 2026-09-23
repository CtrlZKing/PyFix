"""Run the user's target script and capture its result.

Used both for the initial "run and see what breaks" step and for the
mandatory re-run after a repair, so PyFix can *verify* rather than
assume a fix worked.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from pyfix.safety.validation import validate_argv


@dataclass
class RunResult:
    succeeded: bool
    stdout: str
    stderr: str
    returncode: int

    @property
    def traceback_text(self) -> str:
        return self.stderr


def run_script(
    script_path: Path,
    python_executable: Path | None = None,
    args: list[str] | None = None,
    timeout: int = 30,
) -> RunResult:
    executable = str(python_executable or sys.executable)
    argv = [executable, str(script_path), *(args or [])]
    validate_argv(argv)

    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        return RunResult(
            succeeded=completed.returncode == 0,
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
        )
    except subprocess.TimeoutExpired as exc:
        return RunResult(
            succeeded=False,
            stdout=exc.stdout or "" if isinstance(exc.stdout, str) else "",
            stderr=f"Program timed out after {timeout}s (this may be normal for GUI/game loops).",
            returncode=-1,
        )
    except OSError as exc:
        return RunResult(succeeded=False, stdout="", stderr=str(exc), returncode=-1)
