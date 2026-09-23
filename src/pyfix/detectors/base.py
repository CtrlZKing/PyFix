"""Common interface for all repair detectors.

Adding a new error category to PyFix means writing one class that
implements :class:`Detector` — nothing else in the pipeline needs to
change. This is the extensibility seam the whole architecture is
built around.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pyfix.core.models import RepairProposal
from pyfix.traceback.parser import TracebackInfo


class DetectionContext:
    """Everything a detector might need, gathered once per run."""

    def __init__(
        self,
        traceback_info: TracebackInfo,
        script_path: Path,
        project_root: Path,
        python_executable: Path,
    ):
        self.traceback_info = traceback_info
        self.script_path = script_path
        self.project_root = project_root
        self.python_executable = python_executable


class Detector(Protocol):
    """A detector inspects a DetectionContext and may produce a proposal."""

    name: str

    def matches(self, ctx: DetectionContext) -> bool:
        """Cheap check: is this the right detector for this traceback?"""
        ...

    def diagnose(self, ctx: DetectionContext) -> RepairProposal | None:
        """Produce a fully-specified RepairProposal, or None if it can't."""
        ...
