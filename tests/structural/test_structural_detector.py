from __future__ import annotations

from pathlib import Path

from pyfix.core.orchestrator import PyFixSession, apply_proposal, diagnose_traceback
from pyfix.execution.runner import run_script
from pyfix.traceback.parser import parse_traceback

import sys


def _session(tmp_path: Path) -> PyFixSession:
    return PyFixSession(
        script_path=tmp_path / "script.py",
        project_root=tmp_path,
        python_executable=Path(sys.executable),
        backup_dir=tmp_path / ".pyfix" / "backups",
    )


def test_missing_colon_end_to_end_proposal_and_apply(tmp_path):
    script = tmp_path / "script.py"
    script.write_text("def greet(name)\n    print('hello ' + name)\n\ngreet('world')\n", encoding="utf-8")

    run_result = run_script(script, Path(sys.executable))
    assert not run_result.succeeded

    tb_info = parse_traceback(run_result.stderr)
    assert tb_info is not None
    assert tb_info.exception_type == "SyntaxError"

    session = _session(tmp_path)
    proposal = diagnose_traceback(session, tb_info)

    assert proposal is not None
    assert proposal.category == "structural_missing_colon"
    assert proposal.can_auto_fix
    assert proposal.proposed_changes
    assert proposal.proposed_changes[0].new_content == (
        "def greet(name):\n    print('hello ' + name)\n\ngreet('world')\n"
    )

    outcome = apply_proposal(session, proposal)
    assert outcome.executed
    assert outcome.execution_succeeded
    assert outcome.verified
    assert script.read_text(encoding="utf-8") == (
        "def greet(name):\n    print('hello ' + name)\n\ngreet('world')\n"
    )


def test_unclosed_bracket_is_explanation_only_end_to_end(tmp_path):
    script = tmp_path / "script.py"
    script.write_text("print('hello'\n", encoding="utf-8")

    run_result = run_script(script, Path(sys.executable))
    tb_info = parse_traceback(run_result.stderr)
    session = _session(tmp_path)
    proposal = diagnose_traceback(session, tb_info)

    assert proposal is not None
    assert proposal.category == "structural_unclosed_bracket"
    assert not proposal.can_auto_fix
    assert not proposal.proposed_changes


def test_ambiguous_syntax_error_falls_through_to_generic_explanation(tmp_path):
    # `else:` with no matching if/for/while — structural.py deliberately
    # returns None for this (see test_structural_analysis.py), so the
    # StructuralSyntaxDetector must fall through and let the generic
    # SyntaxErrorDetector still explain it (never silently drop it).
    script = tmp_path / "script.py"
    script.write_text("else:\n    print(1)\n", encoding="utf-8")

    run_result = run_script(script, Path(sys.executable))
    tb_info = parse_traceback(run_result.stderr)
    session = _session(tmp_path)
    proposal = diagnose_traceback(session, tb_info)

    assert proposal is not None
    assert proposal.category == "syntax_error"  # the generic fallback, not structural_*
    assert not proposal.can_auto_fix
