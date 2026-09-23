from pathlib import Path

import pytest

from pyfix.safety.validation import (
    UnsafeOperationError,
    validate_argv,
    validate_package_name,
    validate_path_within_project,
)


def test_valid_package_name_passes():
    assert validate_package_name("pygame") == "pygame"
    assert validate_package_name("opencv-python") == "opencv-python"
    assert validate_package_name("requests==2.31.0") == "requests==2.31.0"


@pytest.mark.parametrize(
    "malicious",
    [
        "pygame && del important_file",
        "pygame; rm -rf /",
        "pygame `whoami`",
        "pygame $(whoami)",
        "pygame | cat /etc/passwd",
        "",
        "pkg\nrm -rf /",
    ],
)
def test_malicious_package_names_are_rejected(malicious):
    with pytest.raises(UnsafeOperationError):
        validate_package_name(malicious)


def test_valid_argv_passes():
    argv = ["/usr/bin/python3", "-m", "pip", "install", "pygame"]
    assert validate_argv(argv) == argv


@pytest.mark.parametrize(
    "malicious_argv",
    [
        ["python", "-c", "import os; os.system('rm -rf /')"],
        ["python && rm -rf /"],
        [],
    ],
)
def test_malicious_argv_is_rejected(malicious_argv):
    with pytest.raises(UnsafeOperationError):
        validate_argv(malicious_argv)


def test_path_within_project_is_allowed(tmp_path):
    file_path = tmp_path / "sub" / "game.py"
    result = validate_path_within_project(Path("sub/game.py"), tmp_path)
    assert result == file_path.resolve()


def test_path_traversal_outside_project_is_rejected(tmp_path):
    with pytest.raises(UnsafeOperationError):
        validate_path_within_project(Path("../../etc/passwd"), tmp_path)


def test_absolute_path_outside_project_is_rejected(tmp_path):
    with pytest.raises(UnsafeOperationError):
        validate_path_within_project(Path("/etc/passwd"), tmp_path)
