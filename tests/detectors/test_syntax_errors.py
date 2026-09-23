from pathlib import Path

from pyfix.detectors.base import DetectionContext
from pyfix.detectors.syntax_errors import IndentationErrorDetector, SyntaxErrorDetector
from pyfix.traceback.parser import parse_traceback

SYNTAX_TB = '''  File "app.py", line 3
    if True
           ^
SyntaxError: expected ':'
'''

INDENT_TB = '''  File "app.py", line 4
    print("hi")
IndentationError: unexpected indent
'''


def test_syntax_error_is_explanation_only(project_dir: Path):
    tb_info = parse_traceback(SYNTAX_TB)
    ctx = DetectionContext(tb_info, project_dir / "app.py", project_dir, Path("python"))
    detector = SyntaxErrorDetector()
    assert detector.matches(ctx)
    proposal = detector.diagnose(ctx)
    assert proposal is not None
    assert proposal.can_auto_fix is False
    assert proposal.risk_level.name == "EXPLANATION_ONLY"


def test_indentation_error_is_explanation_only(project_dir: Path):
    tb_info = parse_traceback(INDENT_TB)
    ctx = DetectionContext(tb_info, project_dir / "app.py", project_dir, Path("python"))
    detector = IndentationErrorDetector()
    assert detector.matches(ctx)
    proposal = detector.diagnose(ctx)
    assert proposal is not None
    assert proposal.can_auto_fix is False
