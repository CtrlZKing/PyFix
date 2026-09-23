"""Detect facts about the Python environment actually running the program.

This module never guesses which ``pip`` is "probably" right. It asks
the currently-running interpreter (``sys.executable``) for the truth,
because that is the interpreter PyFix must install into.
"""

from __future__ import annotations

import os
import platform
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path


@dataclass
class EnvironmentInfo:
    python_executable: Path
    python_version: str
    is_virtualenv: bool
    is_conda: bool
    venv_name: str | None
    site_packages: list[Path]
    project_root: Path | None
    os_name: str

    def summary_lines(self) -> list[str]:
        lines = [
            "PYTHON ENVIRONMENT",
            "",
            "Interpreter:",
            f"    {self.python_executable}",
            "",
            "Version:",
            f"    {self.python_version}",
            "",
            "Environment:",
            f"    {self.venv_name or ('conda' if self.is_conda else 'system / global')}",
            "",
            "Package manager:",
            "    pip",
        ]
        return lines


def detect_environment(project_root: Path | None = None) -> EnvironmentInfo:
    executable = Path(sys.executable)
    version = platform.python_version()

    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    is_conda = bool(os.environ.get("CONDA_DEFAULT_ENV")) or "conda" in sys.version.lower()

    venv_name = None
    if in_venv:
        venv_name = Path(sys.prefix).name
    elif is_conda:
        venv_name = os.environ.get("CONDA_DEFAULT_ENV")

    site_packages = [Path(p) for p in sysconfig.get_paths().values() if "site-packages" in p or "purelib" in p]
    site_packages = list(dict.fromkeys(site_packages))  # dedupe, keep order

    return EnvironmentInfo(
        python_executable=executable,
        python_version=version,
        is_virtualenv=in_venv,
        is_conda=is_conda,
        venv_name=venv_name,
        site_packages=site_packages,
        project_root=project_root,
        os_name=platform.system(),
    )


def find_project_root(start: Path) -> Path:
    """Walk upward from ``start`` looking for common project markers."""

    markers = ("pyproject.toml", "requirements.txt", ".venv", ".git", "setup.py")
    current = start.resolve()
    if current.is_file():
        current = current.parent

    for candidate in (current, *current.parents):
        if any((candidate / marker).exists() for marker in markers):
            return candidate

    return current
