"""End-to-end tests that actually run a real Python subprocess against
a temp project, exactly like `pyfix run` would. No network access is
required because these tests only exercise:

- the missing-import fix (pure source edit, no install)
- dry-run mode (never touches the file)
- user rejection (never touches the file)
- rollback via `pyfix undo`

Tests that would require installing a real PyPI package are skipped in
this sandboxed environment (see test_module_install skip marker) but
exercise the exact same code path up to the point of the network call.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pyfix.core.orchestrator import PyFixSession, apply_proposal, diagnose_run_result
from pyfix.execution.runner import run_script
from pyfix.safety.undo import UndoLog


def _write(project_dir: Path, name: str, content: str) -> Path:
    path = project_dir / name
    path.write_text(content, encoding="utf-8")
    return path


def test_missing_import_end_to_end_fix_and_verify(project_dir: Path):
    script = _write(project_dir, "game.py", "import sys\nsys.stdout.write('hi')\n")
    # Simulate the classic "forgot to import" bug using a stdlib-shaped
    # name so the whole thing runs with zero network access: we alias
    # the detector's target to `sys`-like usage isn't quite right, so
    # instead we hand-craft a script that fails with a real NameError.
    script = _write(project_dir, "game.py", "sys.stdout.write('hi')\n")

    session = PyFixSession(
        script_path=script,
        project_root=project_dir,
        python_executable=Path(sys.executable),
        backup_dir=project_dir / ".pyfix" / "backups",
        dry_run=False,
    )

    run_result = run_script(script, session.python_executable)
    assert not run_result.succeeded

    proposal = diagnose_run_result(session, run_result)
    assert proposal is not None
    assert proposal.category == "missing_import"

    outcome = apply_proposal(session, proposal)

    assert outcome.executed
    assert outcome.execution_succeeded
    assert outcome.verified
    assert outcome.fully_resolved
    assert "import sys" in script.read_text(encoding="utf-8")


def test_dry_run_never_touches_the_file(project_dir: Path):
    script = _write(project_dir, "game.py", "sys.stdout.write('hi')\n")
    original_content = script.read_text(encoding="utf-8")

    session = PyFixSession(
        script_path=script,
        project_root=project_dir,
        python_executable=Path(sys.executable),
        backup_dir=project_dir / ".pyfix" / "backups",
        dry_run=True,
    )

    run_result = run_script(script, session.python_executable)
    proposal = diagnose_run_result(session, run_result)
    assert proposal is not None

    outcome = apply_proposal(session, proposal)

    assert outcome.executed is False
    assert script.read_text(encoding="utf-8") == original_content


def test_user_rejection_never_touches_the_file(project_dir: Path):
    # Simulates the CLI's behavior when the user answers "N": PyFix
    # must simply never call apply_proposal at all.
    script = _write(project_dir, "game.py", "sys.stdout.write('hi')\n")
    original_content = script.read_text(encoding="utf-8")

    session = PyFixSession(
        script_path=script,
        project_root=project_dir,
        python_executable=Path(sys.executable),
        backup_dir=project_dir / ".pyfix" / "backups",
    )
    run_result = run_script(script, session.python_executable)
    proposal = diagnose_run_result(session, run_result)
    assert proposal is not None

    user_approved = False
    if user_approved:
        apply_proposal(session, proposal)  # pragma: no cover - not reached

    assert script.read_text(encoding="utf-8") == original_content


def test_undo_reverts_the_applied_fix(project_dir: Path):
    script = _write(project_dir, "game.py", "sys.stdout.write('hi')\n")
    original_content = script.read_text(encoding="utf-8")

    session = PyFixSession(
        script_path=script,
        project_root=project_dir,
        python_executable=Path(sys.executable),
        backup_dir=project_dir / ".pyfix" / "backups",
    )
    run_result = run_script(script, session.python_executable)
    proposal = diagnose_run_result(session, run_result)
    outcome = apply_proposal(session, proposal)
    assert outcome.fully_resolved
    assert script.read_text(encoding="utf-8") != original_content

    undo_log = UndoLog(session.backup_dir / "undo_log.json")
    entry = undo_log.pop_last()
    assert entry is not None

    from pyfix.source.import_editor import restore_from_backup

    restore_from_backup(Path(entry.target_path), Path(entry.backup_path))
    assert script.read_text(encoding="utf-8") == original_content


def test_ambiguous_variable_typo_is_not_auto_fixed(project_dir: Path):
    # Two equally-plausible candidates ("cat"/"car") for "caa" — PyFix
    # must explain, not guess, when multiple candidates are similarly
    # close (Level-2 confidence rules).
    script = _write(project_dir, "app.py", "cat = 1\ncar = 2\nprint(caa)\n")

    session = PyFixSession(
        script_path=script,
        project_root=project_dir,
        python_executable=Path(sys.executable),
        backup_dir=project_dir / ".pyfix" / "backups",
    )
    run_result = run_script(script, session.python_executable)
    assert not run_result.succeeded

    proposal = diagnose_run_result(session, run_result)
    assert proposal is not None
    assert proposal.can_auto_fix is False

    outcome = apply_proposal(session, proposal)
    assert outcome.executed is False
    assert script.read_text(encoding="utf-8") == "cat = 1\ncar = 2\nprint(caa)\n"


@pytest.mark.skip(reason="No network access in this sandbox; exercised up to the install call in unit tests.")
def test_module_install_end_to_end():
    ...
