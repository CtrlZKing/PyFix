from pathlib import Path

from pyfix.detectors.base import DetectionContext
from pyfix.detectors.name_error_import import NameErrorImportDetector
from pyfix.traceback.parser import parse_traceback

MISSING_IMPORT_TB = '''Traceback (most recent call last):
  File "game.py", line 2, in <module>
    pygame.init()
NameError: name 'pygame' is not defined
'''

NOT_AN_IMPORT_TB = '''Traceback (most recent call last):
  File "app.py", line 2, in <module>
    print(totale)
NameError: name 'totale' is not defined
'''


def _write(project_dir: Path, name: str, content: str) -> Path:
    path = project_dir / name
    path.write_text(content, encoding="utf-8")
    return path


def test_missing_import_high_confidence_proposes_diff(project_dir: Path):
    script = _write(project_dir, "game.py", "pygame.init()\n")
    tb_info = parse_traceback(MISSING_IMPORT_TB)
    ctx = DetectionContext(tb_info, script, project_dir, Path("python"))

    detector = NameErrorImportDetector()
    assert detector.matches(ctx)
    proposal = detector.diagnose(ctx)

    assert proposal is not None
    assert proposal.category == "missing_import"
    assert proposal.can_auto_fix
    assert proposal.proposed_changes
    assert "import pygame" in proposal.proposed_changes[0].new_content
    assert "+import pygame" in proposal.proposed_changes[0].diff_text


def test_name_error_variable_typo_is_high_confidence_and_proposes_rename(project_dir: Path):
    # `totale` is a very close typo of `total`, which is defined and in
    # scope — this is the flagship Level-2 "did you mean" case, and
    # PyFix should confidently propose the rename.
    script = _write(project_dir, "app.py", "total = 5\nprint(totale)\n")
    tb_info = parse_traceback(NOT_AN_IMPORT_TB)
    ctx = DetectionContext(tb_info, script, project_dir, Path("python"))

    detector = NameErrorImportDetector()
    proposal = detector.diagnose(ctx)

    assert proposal is not None
    assert proposal.category == "undefined_variable_typo"
    assert proposal.can_auto_fix is True
    assert proposal.confidence.value == "high"
    assert "total" in proposal.proposed_changes[0].new_content
    assert "totale" not in proposal.proposed_changes[0].new_content


def test_name_error_with_no_close_candidates_is_uncertain(project_dir: Path):
    # Nothing in scope is remotely similar to `zzznope` — PyFix must
    # not invent a suggestion out of nowhere.
    script = _write(project_dir, "app.py", "print(zzznope)\n")
    tb_text = (
        'Traceback (most recent call last):\n'
        '  File "app.py", line 1, in <module>\n'
        '    print(zzznope)\n'
        "NameError: name 'zzznope' is not defined\n"
    )
    tb_info = parse_traceback(tb_text)
    ctx = DetectionContext(tb_info, script, project_dir, Path("python"))

    detector = NameErrorImportDetector()
    proposal = detector.diagnose(ctx)

    assert proposal is not None
    assert proposal.can_auto_fix is False
    assert proposal.category == "name_error_uncertain"


def test_name_error_with_multiple_close_candidates_is_ambiguous(project_dir: Path):
    # Two equally-plausible candidates ("cat" and "car") both similar to
    # "caa" — PyFix must not silently pick one.
    script = _write(project_dir, "app.py", "cat = 1\ncar = 2\nprint(caa)\n")
    tb_text = (
        'Traceback (most recent call last):\n'
        '  File "app.py", line 3, in <module>\n'
        '    print(caa)\n'
        "NameError: name 'caa' is not defined\n"
    )
    tb_info = parse_traceback(tb_text)
    ctx = DetectionContext(tb_info, script, project_dir, Path("python"))

    detector = NameErrorImportDetector()
    proposal = detector.diagnose(ctx)

    assert proposal is not None
    assert proposal.can_auto_fix is False
    assert proposal.category == "undefined_variable_ambiguous"


def test_already_imported_name_is_skipped(project_dir: Path):
    # If pygame really is imported, this NameError has some other cause
    # (e.g. shadowing) — the detector should decline rather than
    # propose a duplicate import.
    script = _write(project_dir, "game.py", "import pygame\npygame.init()\n")
    tb_info = parse_traceback(MISSING_IMPORT_TB)
    ctx = DetectionContext(tb_info, script, project_dir, Path("python"))

    detector = NameErrorImportDetector()
    proposal = detector.diagnose(ctx)
    assert proposal is None
