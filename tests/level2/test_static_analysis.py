"""Tests for the pure static-analysis pass (`pyfix analyze` / doctor),
using the fixture programs in tests/fixtures/level2/.
"""

from __future__ import annotations

from pathlib import Path

from pyfix.analysis.runner import run_static_analysis
from pyfix.diagnostics.models import DiagnosticCategory, DiagnosticConfidence

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "level2"


def _diagnose(fixture_name: str):
    path = FIXTURES / fixture_name
    source = path.read_text(encoding="utf-8")
    return run_static_analysis(source, path)


def test_wrong_args_fixture_flags_missing_argument():
    diagnostics = _diagnose("wrong_args.py")
    assert any(d.category == DiagnosticCategory.WRONG_ARGUMENTS for d in diagnostics)
    d = next(d for d in diagnostics if d.category == DiagnosticCategory.WRONG_ARGUMENTS)
    assert d.line == 5
    assert d.confidence == DiagnosticConfidence.CERTAIN


def test_undefined_variable_fixture_suggests_username():
    diagnostics = _diagnose("undefined_variable.py")
    matches = [d for d in diagnostics if d.category == DiagnosticCategory.UNDEFINED_VARIABLE]
    assert matches
    d = matches[0]
    assert d.line == 2
    assert "username" in d.proposed_fix_summary


def test_typo_variable_fixture_high_confidence():
    diagnostics = _diagnose("typo_variable.py")
    matches = [d for d in diagnostics if d.category == DiagnosticCategory.UNDEFINED_VARIABLE]
    assert matches
    assert matches[0].confidence == DiagnosticConfidence.HIGH
    assert "total" in matches[0].proposed_fix_summary


def test_unreachable_fixture_flags_line_3():
    diagnostics = _diagnose("unreachable.py")
    matches = [d for d in diagnostics if d.category == DiagnosticCategory.CONTROL_FLOW]
    assert any(d.line == 3 for d in matches)


def test_type_mismatch_fixture_flags_str_plus_int():
    diagnostics = _diagnose("type_mismatch.py")
    matches = [d for d in diagnostics if d.category == DiagnosticCategory.TYPE_MISMATCH]
    assert matches
    assert matches[0].line == 2
    assert matches[0].safe_to_apply is False  # never auto-fixed, per spec


def test_index_out_of_range_fixture_is_certain():
    diagnostics = _diagnose("index_out_of_range.py")
    matches = [d for d in diagnostics if d.category == DiagnosticCategory.INDEXING]
    assert matches
    assert matches[0].line == 2
    assert matches[0].confidence == DiagnosticConfidence.CERTAIN


def test_wrong_keyword_fixture_is_not_flagged_as_wrong_arg_count():
    # This fixture has the *correct* number of arguments (just a typo'd
    # keyword name), so the static positional-count check must not
    # produce a false positive here — the keyword issue is caught by
    # the runtime WrongArgumentsDetector instead (see level2 pipeline tests).
    diagnostics = _diagnose("wrong_keyword.py")
    assert not any(d.category == DiagnosticCategory.WRONG_ARGUMENTS for d in diagnostics)


def test_dynamic_index_is_low_confidence_not_certain(tmp_path):
    path = tmp_path / "dyn.py"
    path.write_text("numbers = [1, 2, 3]\ni = get_index()\nprint(numbers[i])\n", encoding="utf-8")
    diagnostics = run_static_analysis(path.read_text(encoding="utf-8"), path)
    matches = [d for d in diagnostics if d.category == DiagnosticCategory.INDEXING]
    assert matches
    assert matches[0].confidence == DiagnosticConfidence.LOW
    assert matches[0].safe_to_apply is False


def test_valid_program_has_no_diagnostics(tmp_path):
    path = tmp_path / "clean.py"
    path.write_text("def add(a, b):\n    return a + b\n\nprint(add(1, 2))\n", encoding="utf-8")
    diagnostics = run_static_analysis(path.read_text(encoding="utf-8"), path)
    assert diagnostics == []


def test_break_continue_outside_loop_detected(tmp_path):
    path = tmp_path / "bad_flow.py"
    path.write_text("def f():\n    break\n", encoding="utf-8")
    diagnostics = run_static_analysis(path.read_text(encoding="utf-8"), path)
    matches = [d for d in diagnostics if "outside loop" in d.message]
    assert matches
    assert matches[0].confidence == DiagnosticConfidence.CERTAIN


def test_break_inside_loop_in_function_is_not_flagged(tmp_path):
    path = tmp_path / "good_flow.py"
    path.write_text("def f():\n    for x in range(3):\n        break\n", encoding="utf-8")
    diagnostics = run_static_analysis(path.read_text(encoding="utf-8"), path)
    assert not any("outside loop" in d.message for d in diagnostics)
