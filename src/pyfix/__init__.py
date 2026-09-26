"""PyFix — a safety-first Python developer repair tool.

Python errors, explained and fixed.

This module is also PyFix's public Python API. It wraps the same
detection/repair pipeline the CLI uses (see :mod:`pyfix.core.orchestrator`
and :mod:`pyfix.analysis.runner`) — nothing here duplicates logic, it
only adapts it to a stable, importable surface:

    from pyfix import analyze, diagnose

    result = analyze("app.py")
    for issue in result.issues:
        print(issue.location_label(), issue.message)

``repair()``/``verify()`` intentionally are NOT exposed as one-shot,
no-questions-asked functions — PyFix's permission model (see
:mod:`pyfix.core.orchestrator`) requires explicit approval before any
file is modified, and a library call has no user to ask. Use
:func:`diagnose` to get a `RepairProposal`, inspect
``proposal.can_auto_fix`` / ``proposal.explanation`` yourself, and call
:func:`apply_repair` only once your own code has obtained that
approval.
"""

from __future__ import annotations

from pathlib import Path

from pyfix.analysis.runner import run_static_analysis
from pyfix.core.models import RepairOutcome, RepairProposal
from pyfix.core.orchestrator import PyFixSession, apply_proposal, diagnose_run_result
from pyfix.diagnostics.models import Diagnostic
from pyfix.environment.info import detect_environment, find_project_root
from pyfix.execution.runner import run_script

__version__ = "3.1.0"

__all__ = [
    "__version__",
    "analyze",
    "AnalysisResult",
    "diagnose",
    "apply_repair",
    "PyFixSession",
    "RepairProposal",
    "RepairOutcome",
    "Diagnostic",
]


class AnalysisResult:
    """The result of :func:`analyze`: every statically-detectable issue
    found in one file, without executing it."""

    def __init__(self, file_path: Path, issues: list[Diagnostic]):
        self.file_path = file_path
        self.issues = issues

    @property
    def ok(self) -> bool:
        return not self.issues

    def __repr__(self) -> str:  # pragma: no cover - convenience only
        return f"AnalysisResult(file_path={self.file_path!r}, issues={len(self.issues)})"


def _session_for(script: Path) -> PyFixSession:
    script = Path(script)
    project_root = find_project_root(script)
    env = detect_environment(project_root)
    return PyFixSession(
        script_path=script,
        project_root=project_root,
        python_executable=env.python_executable,
        backup_dir=project_root / ".pyfix" / "backups",
        dry_run=True,
    )


def analyze(file_path: str | Path) -> AnalysisResult:
    """Static, no-execution multi-issue scan of one file.

    Equivalent to ``pyfix analyze <file>``. Never runs the target
    program and never touches disk.
    """

    file_path = Path(file_path)
    source = file_path.read_text(encoding="utf-8")
    issues = run_static_analysis(source, file_path)
    return AnalysisResult(file_path=file_path, issues=issues)


def diagnose(file_path: str | Path, args: list[str] | None = None) -> RepairProposal | None:
    """Run ``file_path`` and, if it fails, return a `RepairProposal`
    describing the first diagnosable problem — or ``None`` if the
    program ran successfully or the failure isn't yet recognized.

    This never modifies any file. Inspect ``proposal.can_auto_fix`` and
    ``proposal.explanation``, and only call :func:`apply_repair` after
    your own code (or a human) has approved it.
    """

    session = _session_for(file_path)
    run_result = run_script(session.script_path, session.python_executable, args or [])
    if run_result.succeeded:
        return None
    return diagnose_run_result(session, run_result)


def apply_repair(
    file_path: str | Path, proposal: RepairProposal, *, dry_run: bool = False
) -> RepairOutcome:
    """Apply an ALREADY-APPROVED `RepairProposal` and verify the result.

    Callers are responsible for obtaining approval (e.g. from a human,
    or from their own policy) before calling this — it performs no
    confirmation of its own, exactly like
    :func:`pyfix.core.orchestrator.apply_proposal`, which this wraps.
    """

    session = _session_for(file_path)
    session.dry_run = dry_run
    return apply_proposal(session, proposal)
