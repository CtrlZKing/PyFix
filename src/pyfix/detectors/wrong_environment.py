"""Detect a ModuleNotFoundError caused by running the wrong interpreter.

If the missing package is installed somewhere on the machine, but not
in the environment PyFix is currently running with, this is a much
more specific — and more useful — diagnosis than "just install it
here," because it flags the possibility the user meant to activate a
virtual environment.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

from pyfix.core.models import RepairLevel, RepairProposal, Severity
from pyfix.detectors.base import DetectionContext
from pyfix.execution.pip import build_install_command
from pyfix.packages.resolver import resolve_package
from pyfix.safety.validation import validate_argv

_MODULE_RE = re.compile(r"No module named ['\"]([A-Za-z0-9_.]+)['\"]")


class WrongEnvironmentDetector:
    """Runs *before* :class:`ModuleNotFoundDetector` in priority order.

    Only fires when it can affirmatively show the package exists
    elsewhere on the system, via a different interpreter than the one
    currently running.
    """

    name = "wrong_environment"

    def matches(self, ctx: DetectionContext) -> bool:
        tb = ctx.traceback_info
        return tb.exception_type in ("ModuleNotFoundError", "ImportError") and bool(
            _MODULE_RE.search(tb.message)
        )

    def diagnose(self, ctx: DetectionContext) -> RepairProposal | None:
        tb = ctx.traceback_info
        match = _MODULE_RE.search(tb.message)
        if not match:
            return None
        import_name = match.group(1)

        other_location = _find_other_python_with_module(import_name, ctx.python_executable)
        if other_location is None:
            return None  # let ModuleNotFoundDetector handle the plain case

        resolution = resolve_package(import_name)
        package_name = resolution.distribution_name or import_name

        install_cmd = None
        if resolution.resolved:
            install_cmd = build_install_command(package_name, ctx.python_executable)

        explanation = (
            "❌ Package installed in another environment\n\n"
            f"{import_name} exists here:\n\n    {other_location}\n\n"
            "But your program is running with:\n\n"
            f"    {ctx.python_executable}\n\n"
            f"{import_name} is not installed in that environment."
        )

        return RepairProposal(
            category="wrong_environment",
            explanation=explanation,
            confidence_score=resolution.confidence_score if resolution.resolved else 0.5,
            risk_level=RepairLevel.SAFE_ENVIRONMENT_OP,
            severity=Severity.ERROR,
            commands=[install_cmd] if install_cmd else [],
            what_happened=(
                f'"{import_name}" is installed for a different Python installation, '
                "not the one running your program."
            ),
            why_it_happened=f"Found {import_name} available via: {other_location}",
            location=f"{tb.last_frame.file}, line {tb.last_frame.line}" if tb.last_frame else "",
            can_auto_fix=install_cmd is not None,
        )


def _find_other_python_with_module(import_name: str, current_executable: Path) -> str | None:
    """Best-effort: check common alternate launchers for this module.

    This never executes anything beyond a read-only `-c "import X"`
    probe against well-known, non-user-controlled launcher names.
    """

    candidates = ["python3", "python", "py"] if sys.platform != "win32" else ["py", "python", "python3"]
    top_level = import_name.split(".")[0]

    for candidate in candidates:
        try:
            resolved = _resolve_on_path(candidate)
        except Exception:
            continue
        if resolved is None or Path(resolved).resolve() == Path(current_executable).resolve():
            continue
        try:
            argv = [resolved, "-c", f"import {top_level}"]
            validate_argv(argv)
            result = subprocess.run(argv, capture_output=True, timeout=5, shell=False)
            if result.returncode == 0:
                return resolved
        except Exception:
            continue
    return None


def _resolve_on_path(name: str) -> str | None:
    import shutil

    return shutil.which(name)
