from __future__ import annotations

import json

from pyfix.cli.main import main


def test_analyze_json_is_valid_json_with_no_ansi_or_unicode_icons(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "broken.py"
    script.write_text("numbers = [1, 2, 3]\nprint(numbers[10])\n", encoding="utf-8")

    exit_code = main(["analyze", str(script), "--json"])
    out = capsys.readouterr().out

    assert exit_code == 1
    data = json.loads(out)  # must parse cleanly — the whole point of --json
    assert data["issue_count"] == 1
    issue = data["issues"][0]
    assert issue["category"] == "indexing"
    assert issue["line"] == 2
    assert "\x1b" not in out  # no ANSI escape codes
    assert "❌" not in out and "⚠️" not in out  # no terminal icons


def test_analyze_json_on_clean_file_reports_zero_issues(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "clean.py"
    script.write_text("x = 1\nprint(x)\n", encoding="utf-8")

    exit_code = main(["analyze", str(script), "--json"])
    data = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert data["issue_count"] == 0
    assert data["issues"] == []


def test_analyze_json_missing_file_reports_structured_error(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    missing = tmp_path / "nope.py"

    exit_code = main(["analyze", str(missing), "--json"])
    data = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert "error" in data


def test_analyze_never_executes_the_target_file(tmp_path, capsys, monkeypatch):
    # A file whose top-level code would raise/exit if executed. `analyze`
    # must complete normally either way, proving it never ran it.
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "would_explode_if_run.py"
    script.write_text("import sys\nsys.exit('analyze must never execute this')\n", encoding="utf-8")

    exit_code = main(["analyze", str(script)])
    assert exit_code in (0, 1)  # completed normally, not a SystemExit propagating out
