from __future__ import annotations

from pathlib import Path

from pyfix.state.diagnostic_log import DiagnosticLog, DiagnosticLogEntry


def _entry(**overrides) -> DiagnosticLogEntry:
    base = dict(
        timestamp="2026-01-01 00:00:00",
        command="run",
        target="app.py",
        category="undefined_variable_typo",
        severity="ERROR",
        confidence="high (90%)",
        what_happened="usernme is not defined",
        proposed_repair="usernme -> username",
        applied=True,
        apply_succeeded=True,
        verified=True,
        iteration=1,
    )
    base.update(overrides)
    return DiagnosticLogEntry(**base)


def test_no_log_file_reads_as_empty(tmp_path):
    log = DiagnosticLog(tmp_path)
    entries, corrupt = log.read_all()
    assert entries == []
    assert corrupt == 0
    assert not log.exists()


def test_record_and_read_round_trip(tmp_path):
    log = DiagnosticLog(tmp_path)
    log.record(_entry())
    log.record(_entry(category="structural_missing_colon", iteration=2))

    entries, corrupt = log.read_all()
    assert corrupt == 0
    assert len(entries) == 2
    assert entries[0].category == "undefined_variable_typo"
    assert entries[1].category == "structural_missing_colon"


def test_log_file_lives_under_dot_pyfix(tmp_path):
    log = DiagnosticLog(tmp_path)
    log.record(_entry())
    assert log.path == tmp_path / ".pyfix" / "logs.jsonl"
    assert log.path.exists()


def test_one_corrupted_line_does_not_hide_the_others(tmp_path):
    log = DiagnosticLog(tmp_path)
    log.record(_entry())
    log.path.parent.mkdir(parents=True, exist_ok=True)
    with log.path.open("a", encoding="utf-8") as fh:
        fh.write("{not valid json at all\n")
    log.record(_entry(category="structural_missing_colon"))

    entries, corrupt = log.read_all()
    assert corrupt == 1
    assert len(entries) == 2


def test_empty_and_whitespace_lines_are_skipped_silently(tmp_path):
    log = DiagnosticLog(tmp_path)
    log.record(_entry())
    with log.path.open("a", encoding="utf-8") as fh:
        fh.write("\n   \n")
    entries, corrupt = log.read_all()
    assert corrupt == 0
    assert len(entries) == 1


def test_clear_removes_the_file_and_reports_count(tmp_path):
    log = DiagnosticLog(tmp_path)
    log.record(_entry())
    log.record(_entry())
    cleared = log.clear()
    assert cleared == 2
    assert not log.path.exists()

    entries, corrupt = log.read_all()
    assert entries == []
    assert corrupt == 0


def test_clearing_an_already_empty_log_is_safe(tmp_path):
    log = DiagnosticLog(tmp_path)
    assert log.clear() == 0
    assert log.clear() == 0  # repeated clearing never errors


def test_clear_never_touches_other_pyfix_state(tmp_path):
    (tmp_path / ".pyfix" / "backups").mkdir(parents=True)
    unrelated = tmp_path / ".pyfix" / "backups" / "app.py.bak"
    unrelated.write_text("original source", encoding="utf-8")
    (tmp_path / "real_source.py").write_text("x = 1\n", encoding="utf-8")

    log = DiagnosticLog(tmp_path)
    log.record(_entry())
    log.clear()

    assert unrelated.exists()
    assert unrelated.read_text(encoding="utf-8") == "original source"
    assert (tmp_path / "real_source.py").exists()


def test_summary_line_reflects_status(tmp_path):
    applied_verified = _entry(applied=True, verified=True)
    assert "applied & verified" in applied_verified.summary_line()

    explanation_only = _entry(applied=False, verified=None, category="unclosed_bracket")
    assert "explained only" in explanation_only.summary_line()

    rolled_back = _entry(applied=True, verified=False, rollback=True)
    assert "rolled back" in rolled_back.summary_line()
