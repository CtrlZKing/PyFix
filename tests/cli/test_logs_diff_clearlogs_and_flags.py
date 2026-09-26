from __future__ import annotations

from pathlib import Path

from pyfix.cli.main import main


def test_logs_before_any_run_says_none(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["logs"]) == 0
    assert "No PyFix diagnostic logs yet." in capsys.readouterr().out


def test_diff_before_any_run_says_none(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["diff"]) == 0
    assert "No PyFix-proposed diff is available yet." in capsys.readouterr().out


def test_clear_logs_with_no_logs_is_a_no_op(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["clear-logs", "--yes"]) == 0
    assert "No PyFix diagnostic logs to clear." in capsys.readouterr().out


def test_run_populates_logs_and_diff_then_clear_logs_empties_logs_only(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "broken.py"
    script.write_text("if x == 5\n    print(x)\n", encoding="utf-8")

    main(["run", str(script), "--dry-run"])
    capsys.readouterr()

    assert main(["logs"]) == 0
    logs_out = capsys.readouterr().out
    assert "structural_missing_colon" in logs_out

    assert main(["diff"]) == 0
    diff_out = capsys.readouterr().out
    assert "if x == 5:" in diff_out

    assert main(["clear-logs", "--yes"]) == 0
    capsys.readouterr()

    assert main(["logs"]) == 0
    assert "No PyFix diagnostic logs yet." in capsys.readouterr().out

    # clear-logs must never touch the separate diff store
    assert main(["diff"]) == 0
    assert "if x == 5:" in capsys.readouterr().out


def test_clear_logs_without_yes_requires_confirmation(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "broken.py"
    script.write_text("if x == 5\n    print(x)\n", encoding="utf-8")
    main(["run", str(script), "--dry-run"])
    capsys.readouterr()

    monkeypatch.setattr("builtins.input", lambda *_: "n")
    exit_code = main(["clear-logs"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "No changes made." in out

    # confirmed nothing was actually cleared
    assert main(["logs"]) == 0
    assert "structural_missing_colon" in capsys.readouterr().out


def test_clearing_logs_never_deletes_the_source_file_or_backups(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "broken.py"
    script.write_text("if x == 5\n    print(x)\n", encoding="utf-8")
    main(["run", str(script), "--yes"])
    capsys.readouterr()

    assert script.exists()
    backups_dir = tmp_path / ".pyfix" / "backups"
    backups_existed_before = backups_dir.exists() and any(backups_dir.iterdir())

    main(["clear-logs", "--yes"])

    assert script.exists()
    if backups_existed_before:
        assert any(backups_dir.iterdir())


def test_repeated_clear_logs_is_safe(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["clear-logs", "--yes"]) == 0
    assert main(["clear-logs", "--yes"]) == 0
    assert main(["clear-logs", "--yes"]) == 0


# ------------------------------------------------------- flag ordering


def test_beginner_flag_before_subcommand(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "t.py"
    script.write_text("x = 1\n", encoding="utf-8")
    exit_code = main(["--beginner", "analyze", str(script)])
    assert exit_code == 0


def test_advanced_flag_after_subcommand(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "t.py"
    script.write_text("numbers = [1]\nprint(numbers[5])\n", encoding="utf-8")
    exit_code = main(["analyze", str(script), "--advanced"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "why:" in out  # only printed in advanced mode


def test_advanced_flag_after_subcommand_for_run(tmp_path, capsys, monkeypatch):
    # This exact form used to raise "unrecognized arguments: --advanced"
    # before the shared-parent-parser fix.
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "t.py"
    script.write_text("x = 1\n", encoding="utf-8")
    exit_code = main(["run", str(script), "--dry-run", "--advanced"])
    assert exit_code == 0


def test_beginner_and_advanced_together_is_rejected_even_when_split_across_positions(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "t.py"
    script.write_text("x = 1\n", encoding="utf-8")
    try:
        main(["--beginner", "analyze", str(script), "--advanced"])
        assert False, "expected SystemExit from argparse.error"
    except SystemExit as e:
        assert e.code == 2


def test_flag_before_subcommand_value_survives_when_not_repeated_after(tmp_path, capsys, monkeypatch):
    # `pyfix --advanced run file.py` (no flag after the subcommand) must
    # still result in advanced mode, not be silently reset to the
    # subparser's own default.
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "t.py"
    script.write_text("numbers = [1]\nprint(numbers[5])\n", encoding="utf-8")
    exit_code = main(["--advanced", "analyze", str(script)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "why:" in out
