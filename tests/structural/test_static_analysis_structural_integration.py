from __future__ import annotations

from pathlib import Path

from pyfix.analysis.runner import run_static_analysis


def test_unparsable_file_now_reports_a_structural_diagnostic_instead_of_nothing(tmp_path):
    # Before 3.0, run_static_analysis returned [] the instant a file
    # failed to parse at all — a whole-file scan went completely silent
    # on the single most common class of beginner bug. It should now
    # still surface what it safely can.
    path = tmp_path / "broken.py"
    source = "if x == 5\n    print(x)\n"
    diagnostics = run_static_analysis(source, path)

    assert len(diagnostics) == 1
    d = diagnostics[0]
    assert d.line == 1
    assert d.safe_to_apply
    assert d.fix_new_content == "if x == 5:\n    print(x)\n"


def test_genuinely_unclassifiable_syntax_error_still_reports_nothing_fabricated(tmp_path):
    path = tmp_path / "broken.py"
    source = "else:\n    print(1)\n"
    diagnostics = run_static_analysis(source, path)
    # structural.py correctly declines to guess here (see
    # test_structural_analysis.py) — the whole-file scan must not
    # invent a diagnosis just to have something to show.
    assert diagnostics == []
