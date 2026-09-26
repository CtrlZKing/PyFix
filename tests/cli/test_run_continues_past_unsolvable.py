"""Regression test for the 3.0 architectural fix:

    ONE UNSOLVABLE ERROR MUST NEVER PREVENT PYFIX FROM SEARCHING FOR
    OTHER SOLVABLE ERRORS.

Before this fix, `pyfix run` returned immediately after the first
issue it could not auto-fix (or did not recognize at all), even though
a whole-file static scan could see other, unrelated problems. This
test writes a file with two independent, unrelated problems — one that
blocks execution and can't be safely auto-fixed, and one that's only
visible via static analysis — and asserts the second is still reported.
"""

from __future__ import annotations

import sys
from pathlib import Path

from pyfix.cli.main import main


def test_run_reports_static_issues_after_an_unfixable_runtime_error(tmp_path, capsys, monkeypatch):
    script = tmp_path / "broken.py"
    script.write_text(
        "import this_totally_fake_package_zzz\n"
        "\n"
        "def helper():\n"
        "    return this_name_is_never_defined_anywhere\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    exit_code = main(["run", str(script), "--dry-run"])
    out = capsys.readouterr().out

    assert exit_code == 1
    # The blocking issue (unrecognized/ambiguous import) is still explained...
    assert "this_totally_fake_package_zzz" in out
    # ...AND PyFix kept looking instead of stopping there.
    assert "other statically-detectable issue" in out
    assert "this_name_is_never_defined_anywhere" in out


def test_run_with_no_other_issues_says_nothing_extra(tmp_path, capsys, monkeypatch):
    script = tmp_path / "broken.py"
    script.write_text("import this_totally_fake_package_zzz\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    exit_code = main(["run", str(script), "--dry-run"])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "other statically-detectable issue" not in out
