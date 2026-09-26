from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pyfix
from pyfix.cli.main import build_parser, main


def test_package_version_is_3_1_0():
    assert pyfix.__version__ == "3.1.0"


def test_cli_version_flag(capsys):
    exit_code = main(["--version"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert out.strip() == "pyfix 3.1.0"
