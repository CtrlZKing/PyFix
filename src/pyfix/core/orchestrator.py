"""The pipeline that turns a crashed program into a verified fix.

    RUN -> ERROR -> DETECT -> EXPLAIN -> PROPOSE -> ASK -> APPLY -> VERIFY -> RERUN

This module contains zero UI code and zero hardcoded detector list
beyond the default registry — it exists so the CLI (or a future GUI)
can drive the same well-tested workflow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from pyfix.core.models import RepairOutcome, RepairProposal
from pyfix.detectors.attribute_typo import AttributeTypoDetector
from pyfix.detectors.base import DetectionContext, Detector
from pyfix.detectors.file_not_found import FileNotFoundDetector
from pyfix.detectors.module_not_found import ModuleNotFoundDetector
from pyfix.detectors.name_error_import import NameErrorImportDetector
from pyfix.detectors.syntax_errors import IndentationErrorDetector, SyntaxErrorDetector
from pyfix.detectors.wrong_arguments import WrongArgumentsDetector
from pyfix.detectors.wrong_environment import WrongEnvironmentDetector
from pyfix.execution.pip import run_install
from pyfix.execution.runner import RunResult, run_script
from pyfix.safety.undo import UndoLog, new_entry
from pyfix.source.ast_utils import SourceAnalysis
from pyfix.source.import_editor import write_with_backup
from pyfix.traceback.parser import TracebackInfo, parse_traceback

# Order matters: more specific detectors run before their more general
# fallback (e.g. WrongEnvironmentDetector before ModuleNotFoundDetector).
DEFAULT_DETECTORS: list[Detector] = [
    WrongEnvironmentDetector(),
    ModuleNotFoundDetector(),
    NameErrorImportDetector(),
    WrongArgumentsDetector(),
    AttributeTypoDetector(),
    FileNotFoundDetector(),
    SyntaxErrorDetector(),
    IndentationErrorDetector(),
]

MAX_REPAIR_ITERATIONS = 5


@dataclass
class PyFixSession:
    script_path: Path
    project_root: Path
    python_executable: Path
    backup_dir: Path
    dry_run: bool = False
    detectors: list[Detector] = field(default_factory=lambda: list(DEFAULT_DETECTORS))


def diagnose_run_result(session: PyFixSession, run_result: RunResult) -> RepairProposal | None:
    """Parse a failed run's stderr and find the first matching detector."""

    if run_result.succeeded:
        return None

    tb_info = parse_traceback(run_result.stderr)
    if tb_info is None:
        return None

    return diagnose_traceback(session, tb_info)


def diagnose_traceback(session: PyFixSession, tb_info: TracebackInfo) -> RepairProposal | None:
    ctx = DetectionContext(
        traceback_info=tb_info,
        script_path=session.script_path,
        project_root=session.project_root,
        python_executable=session.python_executable,
    )
    for detector in session.detectors:
        if detector.matches(ctx):
            proposal = detector.diagnose(ctx)
            if proposal is not None:
                return proposal
    return None


def apply_proposal(session: PyFixSession, proposal: RepairProposal) -> RepairOutcome:
    """Execute an APPROVED proposal and verify the result.

    Callers must have already obtained user permission — this function
    performs no confirmation of its own, so it must never be called
    directly from a UI without a prior explicit "yes."
    """

    if session.dry_run:
        return RepairOutcome(
            proposal=proposal,
            executed=False,
            execution_succeeded=False,
            verified=False,
            detail="Dry run: no changes were made.",
        )

    if not proposal.can_auto_fix:
        return RepairOutcome(
            proposal=proposal,
            executed=False,
            execution_succeeded=False,
            verified=False,
            detail="This proposal is explanation-only and has no automated action.",
        )

    backup_path: Path | None = None
    undo_log = UndoLog(session.backup_dir / "undo_log.json")

    # 1. Apply source changes, if any.
    for change in proposal.proposed_changes:
        if change.new_content is None:
            continue
        backup_path = write_with_backup(change.file_path, change.new_content, session.backup_dir)
        analysis = SourceAnalysis(change.new_content)
        if not analysis.is_valid:
            # Roll back immediately — never leave a broken file behind.
            from pyfix.source.import_editor import restore_from_backup

            restore_from_backup(change.file_path, backup_path)
            return RepairOutcome(
                proposal=proposal,
                executed=True,
                execution_succeeded=False,
                verified=False,
                detail="The edited file failed to parse; the change was reverted.",
                backup_path=backup_path,
            )
        undo_log.record(
            new_entry("source_edit", change.file_path, backup_path, change.description)
        )

    # 2. Run commands, if any (e.g. pip install).
    for command in proposal.commands:
        install_result = run_install(command)
        if not install_result.succeeded:
            return RepairOutcome(
                proposal=proposal,
                executed=True,
                execution_succeeded=False,
                verified=False,
                detail=install_result.stderr or "Command failed.",
                backup_path=backup_path,
            )

    # 3. Verify: re-run the target script.
    verified = False
    detail = "Applied, but no verification step was defined."
    if proposal.verification_plan and proposal.verification_plan.rerun_target:
        rerun = run_script(proposal.verification_plan.rerun_target, session.python_executable)
        verified = rerun.succeeded
        detail = "Program ran successfully after the fix." if verified else rerun.stderr

    return RepairOutcome(
        proposal=proposal,
        executed=True,
        execution_succeeded=True,
        verified=verified,
        detail=detail,
        backup_path=backup_path,
    )
