"""End-to-end Level-2 tests: real subprocess runs through the full
V1 pipeline (unchanged) now producing Level-2 diagnoses and, where
safe, Level-2 fixes.
"""

from __future__ import annotations

import sys
from pathlib import Path

from pyfix.core.orchestrator import PyFixSession, apply_proposal, diagnose_run_result
from pyfix.execution.runner import run_script
from pyfix.safety.undo import UndoLog
from pyfix.source.import_editor import restore_from_backup


def _write(project_dir: Path, name: str, content: str) -> Path:
    path = project_dir / name
    path.write_text(content, encoding="utf-8")
    return path


def _session(script: Path, project_dir: Path) -> PyFixSession:
    return PyFixSession(
        script_path=script,
        project_root=project_dir,
        python_executable=Path(sys.executable),
        backup_dir=project_dir / ".pyfix" / "backups",
    )


def test_variable_typo_end_to_end_fix_and_verify(project_dir: Path):
    script = _write(project_dir, "app.py", "total = 5\nprint(totale)\n")
    session = _session(script, project_dir)

    run_result = run_script(script, session.python_executable)
    assert not run_result.succeeded

    proposal = diagnose_run_result(session, run_result)
    assert proposal is not None
    assert proposal.category == "undefined_variable_typo"

    outcome = apply_proposal(session, proposal)
    assert outcome.fully_resolved
    assert "print(total)" in script.read_text(encoding="utf-8")


def test_keyword_typo_end_to_end_fix_backup_and_undo(project_dir: Path):
    source = "def calculate_total(price, tax):\n    return price + tax\n\n\nprint(calculate_total(price=500, taxes=0.18))\n"
    script = _write(project_dir, "shop.py", source)
    session = _session(script, project_dir)

    run_result = run_script(script, session.python_executable)
    assert not run_result.succeeded

    proposal = diagnose_run_result(session, run_result)
    assert proposal is not None
    assert proposal.category == "unexpected_keyword_typo"

    outcome = apply_proposal(session, proposal)
    assert outcome.fully_resolved
    assert "taxes=" not in script.read_text(encoding="utf-8")

    # Undo must restore the exact original source.
    undo_log = UndoLog(session.backup_dir / "undo_log.json")
    entry = undo_log.pop_last()
    assert entry is not None
    restore_from_backup(Path(entry.target_path), Path(entry.backup_path))
    assert script.read_text(encoding="utf-8") == source


def test_missing_argument_case_never_modifies_the_file(project_dir: Path):
    source = "def calculate_total(price, tax):\n    return price + tax\n\n\ntotal = calculate_total(500)\n"
    script = _write(project_dir, "shop.py", source)
    session = _session(script, project_dir)

    run_result = run_script(script, session.python_executable)
    proposal = diagnose_run_result(session, run_result)
    assert proposal is not None
    assert proposal.can_auto_fix is False

    outcome = apply_proposal(session, proposal)
    assert outcome.executed is False
    assert script.read_text(encoding="utf-8") == source


def test_dry_run_never_touches_file_for_keyword_typo(project_dir: Path):
    source = "def calculate_total(price, tax):\n    return price + tax\n\n\nprint(calculate_total(price=500, taxes=0.18))\n"
    script = _write(project_dir, "shop.py", source)
    session = PyFixSession(
        script_path=script,
        project_root=project_dir,
        python_executable=Path(sys.executable),
        backup_dir=project_dir / ".pyfix" / "backups",
        dry_run=True,
    )
    run_result = run_script(script, session.python_executable)
    proposal = diagnose_run_result(session, run_result)
    assert proposal is not None and proposal.can_auto_fix

    outcome = apply_proposal(session, proposal)
    assert outcome.executed is False
    assert script.read_text(encoding="utf-8") == source


def test_attribute_typo_never_auto_modifies(project_dir: Path):
    source = "items = []\nitems.apend('x')\n"
    script = _write(project_dir, "app.py", source)
    session = _session(script, project_dir)

    run_result = run_script(script, session.python_executable)
    proposal = diagnose_run_result(session, run_result)
    assert proposal is not None
    assert proposal.can_auto_fix is False

    outcome = apply_proposal(session, proposal)
    assert outcome.executed is False
    assert script.read_text(encoding="utf-8") == source
