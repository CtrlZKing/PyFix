"""Shared fixtures. Every test that needs a "project" uses a fresh
tmp_path — PyFix tests NEVER run against the developer's real project.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    (tmp_path / "requirements.txt").write_text("", encoding="utf-8")
    return tmp_path


def write_script(project_dir: Path, name: str, content: str) -> Path:
    path = project_dir / name
    path.write_text(content, encoding="utf-8")
    return path
