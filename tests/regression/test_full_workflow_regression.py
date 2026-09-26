"""Permanent regression test for PyFix's core workflow: a file with
three independent, sequential problems (missing colon -> undefined
variable typo -> out-of-range index) must be walked through in order,
each fixed with permission, and the final unfixable runtime error must
still trigger a static scan that catches the third issue.

This is the exact scenario used throughout the 3.x design notes as
"the actual user workflow" — kept as its own file so it's never
accidentally deleted or weakened alongside other test changes.
"""

from __future__ import annotations

from pyfix.cli.main import main

FIXTURE_SOURCE = (
    "def calculate_total(price, quantity)\n"
    "    return price * quantity\n"
    "\n"
    'username = "Heisenberg"\n'
    "print(usernme)\n"
    "\n"
    "numbers = [1, 2, 3]\n"
    "print(numbers[10])\n"
)


def test_full_multi_error_repair_workflow(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "broken.py"
    script.write_text(FIXTURE_SOURCE, encoding="utf-8")

    exit_code = main(["run", str(script), "--yes"])
    out = capsys.readouterr().out

    # 1-3: missing colon detected, explained, and (since --yes) applied.
    assert "missing its trailing colon" in out
    assert "def calculate_total(price, quantity):" in out

    # 4-5: undefined-variable typo detected and applied.
    assert "usernme" in out
    assert "username" in out

    # 6-7: the program reached the IndexError and PyFix explained the
    # runtime failure without pretending to recognize/auto-fix it.
    assert "IndexError" in out
    assert "does not yet recognize this specific error" in out

    # 8: static analysis still caught the out-of-bounds access even
    # though execution never got past the point above it.
    assert "other statically-detectable issue" in out
    assert "Index 10 is outside bounds" in out or "numbers[10]" in out or "line 8" in out

    # 9: the process terminated with a clear, non-zero "not fully
    # resolved" status rather than silently succeeding.
    assert exit_code == 1

    final_source = script.read_text(encoding="utf-8")
    assert "def calculate_total(price, quantity):" in final_source
    assert "print(username)" in final_source
    # PyFix must NOT have touched the IndexError line — it never
    # invents a fix for something it can't safely determine.
    assert "print(numbers[10])" in final_source


def test_full_workflow_is_also_visible_in_logs_and_diff(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "broken.py"
    script.write_text(FIXTURE_SOURCE, encoding="utf-8")

    main(["run", str(script), "--yes"])
    capsys.readouterr()

    main(["logs", "--advanced"])
    logs_out = capsys.readouterr().out
    assert "structural_missing_colon" in logs_out
    assert "undefined_variable_typo" in logs_out
    assert "unrecognized" in logs_out  # the IndexError, honestly logged as such

    main(["diff"])
    diff_out = capsys.readouterr().out
    # the most recent applied change (the typo fix) is what's retrievable
    assert "usernme" in diff_out or "username" in diff_out
