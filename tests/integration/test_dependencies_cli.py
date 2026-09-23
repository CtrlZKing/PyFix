from pathlib import Path

import pytest

from pyfix.cli.main import main


def test_dependencies_reports_version_mismatch(tmp_path, monkeypatch, capsys):
    # Use a real installed package (pip is always present in any Python
    # environment) but claim a version that can't possibly match, to
    # exercise the mismatch-reporting path without needing network access.
    (tmp_path / "requirements.txt").write_text("pip==0.0.0.dev0\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    exit_code = main(["dependencies"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Environment differs from project requirements" in captured.out


def test_dependencies_reports_missing_package(tmp_path, monkeypatch, capsys):
    (tmp_path / "requirements.txt").write_text("totally_fake_package_xyz==1.0\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    exit_code = main(["dependencies"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "not installed" in captured.out


def test_dependencies_clean_when_no_requirements(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    exit_code = main(["dependencies"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "No requirements.txt found" in captured.out
