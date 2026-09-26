from __future__ import annotations

from pathlib import Path

from pyfix.core.models import (
    Confidence,
    ProposedChange,
    RepairLevel,
    RepairProposal,
    Severity,
)
from pyfix.state.diff_store import DiffStore


def _proposal(with_changes: bool = True) -> RepairProposal:
    changes = (
        [
            ProposedChange(
                file_path=Path("app.py"),
                description="Replace usernme with username",
                diff_text="--- app.py\n+++ app.py\n@@\n-usernme\n+username\n",
                new_content="username\n",
            )
        ]
        if with_changes
        else []
    )
    return RepairProposal(
        category="undefined_variable_typo",
        explanation="explanation text",
        confidence_score=0.9,
        risk_level=RepairLevel.SAFE_SUGGESTION,
        severity=Severity.ERROR,
        proposed_changes=changes,
        what_happened="usernme is not defined",
        why_it_happened="username is a close match",
        location="app.py, line 5",
        can_auto_fix=with_changes,
    )


def test_no_diff_ever_saved_loads_as_none(tmp_path):
    assert DiffStore(tmp_path).load() is None


def test_save_and_load_round_trip(tmp_path):
    store = DiffStore(tmp_path)
    store.save(_proposal(), command="run", applied=True)

    record = store.load()
    assert record is not None
    assert record.command == "run"
    assert record.applied is True
    assert record.category == "undefined_variable_typo"
    assert len(record.files) == 1
    assert record.files[0].file_path == "app.py"
    assert "usernme" in record.files[0].diff_text


def test_explanation_only_proposal_saves_nothing(tmp_path):
    store = DiffStore(tmp_path)
    store.save(_proposal(with_changes=False), command="run", applied=False)
    assert store.load() is None


def test_saving_again_overwrites_the_previous_diff(tmp_path):
    store = DiffStore(tmp_path)
    store.save(_proposal(), command="explain", applied=False)
    store.save(_proposal(), command="run", applied=True)

    record = store.load()
    assert record.command == "run"
    assert record.applied is True


def test_corrupted_diff_state_loads_as_none_not_a_crash(tmp_path):
    store = DiffStore(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{not valid json", encoding="utf-8")
    assert store.load() is None


def test_clear_removes_the_state_file(tmp_path):
    store = DiffStore(tmp_path)
    store.save(_proposal(), command="run", applied=True)
    store.clear()
    assert store.load() is None
    store.clear()  # idempotent, never raises
