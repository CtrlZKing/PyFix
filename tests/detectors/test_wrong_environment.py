from pathlib import Path

import pyfix.detectors.wrong_environment as we_module
from pyfix.detectors.base import DetectionContext
from pyfix.detectors.wrong_environment import WrongEnvironmentDetector
from pyfix.traceback.parser import parse_traceback

PYGAME_TB = '''Traceback (most recent call last):
  File "game.py", line 1, in <module>
    import pygame
ModuleNotFoundError: No module named 'pygame'
'''


def test_returns_none_when_no_other_interpreter_has_it(project_dir: Path, monkeypatch):
    monkeypatch.setattr(we_module, "_find_other_python_with_module", lambda *a, **k: None)
    tb_info = parse_traceback(PYGAME_TB)
    ctx = DetectionContext(tb_info, project_dir / "game.py", project_dir, Path("python"))
    detector = WrongEnvironmentDetector()
    assert detector.diagnose(ctx) is None


def test_proposes_install_into_active_env_when_found_elsewhere(project_dir: Path, monkeypatch):
    monkeypatch.setattr(
        we_module, "_find_other_python_with_module", lambda *a, **k: "C:\\Python312\\python.exe"
    )
    tb_info = parse_traceback(PYGAME_TB)
    ctx = DetectionContext(
        tb_info, project_dir / "game.py", project_dir, Path("project\\.venv\\Scripts\\python.exe")
    )
    detector = WrongEnvironmentDetector()
    proposal = detector.diagnose(ctx)
    assert proposal is not None
    assert proposal.category == "wrong_environment"
    assert "C:\\Python312\\python.exe" in proposal.why_it_happened
