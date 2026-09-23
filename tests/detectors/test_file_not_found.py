from pathlib import Path

from pyfix.detectors.base import DetectionContext
from pyfix.detectors.file_not_found import FileNotFoundDetector
from pyfix.traceback.parser import parse_traceback

FNF_TB = '''Traceback (most recent call last):
  File "app.py", line 2, in <module>
    open("data.csv")
FileNotFoundError: [Errno 2] No such file or directory: 'data.csv'
'''


def test_suggests_similar_file(project_dir: Path):
    data_dir = project_dir / "data"
    data_dir.mkdir()
    (data_dir / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    tb_info = parse_traceback(FNF_TB)
    ctx = DetectionContext(tb_info, project_dir / "app.py", project_dir, Path("python"))

    detector = FileNotFoundDetector()
    assert detector.matches(ctx)
    proposal = detector.diagnose(ctx)

    assert proposal is not None
    assert proposal.can_auto_fix is False  # PyFix never changes paths automatically
    assert "data/data.csv" in proposal.explanation or "data\\data.csv" in proposal.explanation


def test_no_suggestion_when_nothing_similar(project_dir: Path):
    tb_info = parse_traceback(FNF_TB)
    ctx = DetectionContext(tb_info, project_dir / "app.py", project_dir, Path("python"))
    detector = FileNotFoundDetector()
    proposal = detector.diagnose(ctx)
    assert proposal is not None
    assert "Did you mean" not in proposal.explanation
