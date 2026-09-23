from pathlib import Path

from pyfix.core.models import RepairLevel
from pyfix.detectors.base import DetectionContext
from pyfix.detectors.module_not_found import ModuleNotFoundDetector
from pyfix.traceback.parser import parse_traceback

PYGAME_TB = '''Traceback (most recent call last):
  File "game.py", line 1, in <module>
    import pygame
ModuleNotFoundError: No module named 'pygame'
'''

CV2_TB = '''Traceback (most recent call last):
  File "app.py", line 1, in <module>
    import cv2
ModuleNotFoundError: No module named 'cv2'
'''

REQUESTS_TB = '''Traceback (most recent call last):
  File "app.py", line 1, in <module>
    import requests
ModuleNotFoundError: No module named 'requests'
'''

UNKNOWN_TB = '''Traceback (most recent call last):
  File "app.py", line 1, in <module>
    import totally_made_up_pkg_xyz_998877
ModuleNotFoundError: No module named 'totally_made_up_pkg_xyz_998877'
'''


def _ctx(tb_text: str, project_root: Path) -> DetectionContext:
    tb_info = parse_traceback(tb_text)
    return DetectionContext(
        traceback_info=tb_info,
        script_path=project_root / "game.py",
        project_root=project_root,
        python_executable=Path("python"),
    )


def test_pygame_missing_proposes_install(project_dir: Path):
    detector = ModuleNotFoundDetector()
    ctx = _ctx(PYGAME_TB, project_dir)
    assert detector.matches(ctx)
    proposal = detector.diagnose(ctx)
    assert proposal is not None
    assert proposal.category == "missing_package"
    assert proposal.can_auto_fix
    assert proposal.risk_level == RepairLevel.SAFE_ENVIRONMENT_OP
    assert any("pygame" in c.display() for c in proposal.commands)


def test_cv2_maps_to_opencv_python(project_dir: Path, monkeypatch):
    import pyfix.packages.resolver as resolver_module

    monkeypatch.setattr(resolver_module, "_find_installed_distribution_for_module", lambda _: None)
    detector = ModuleNotFoundDetector()
    ctx = _ctx(CV2_TB, project_dir)
    proposal = detector.diagnose(ctx)
    assert proposal is not None
    assert any("opencv-python" in c.display() for c in proposal.commands)


def test_requests_missing_proposes_install(project_dir: Path):
    detector = ModuleNotFoundDetector()
    ctx = _ctx(REQUESTS_TB, project_dir)
    proposal = detector.diagnose(ctx)
    assert proposal is not None
    assert any("requests" in c.display() for c in proposal.commands)


def test_unknown_package_is_not_guessed(project_dir: Path):
    detector = ModuleNotFoundDetector()
    ctx = _ctx(UNKNOWN_TB, project_dir)
    proposal = detector.diagnose(ctx)
    assert proposal is not None
    assert proposal.can_auto_fix is False
    assert proposal.category == "missing_package_unknown"
    assert not proposal.commands
