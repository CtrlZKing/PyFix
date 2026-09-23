from pathlib import Path

from pyfix.environment.info import detect_environment, find_project_root
from pyfix.execution.pip import build_install_command
from pyfix.git.repo import detect_git
from pyfix.packages.resolver import resolve_package


def test_find_project_root_detects_requirements_txt(tmp_path):
    (tmp_path / "requirements.txt").write_text("", encoding="utf-8")
    sub = tmp_path / "src" / "pkg"
    sub.mkdir(parents=True)
    script = sub / "main.py"
    script.write_text("print(1)\n", encoding="utf-8")

    root = find_project_root(script)
    assert root == tmp_path


def test_detect_environment_reports_current_interpreter():
    env = detect_environment()
    import sys

    assert env.python_executable == Path(sys.executable)
    assert env.python_version


def test_install_command_uses_current_interpreter_even_with_spaces_in_path():
    weird_path = Path("/opt/My Python Install/bin/python3")
    cmd = build_install_command("pygame", weird_path)
    assert cmd.argv[0] == str(weird_path)
    # Rendered display must quote the path so it's copy-pasteable, but
    # the actual argv (what's executed) must remain a single element —
    # never a concatenated/shell-escaped string.
    assert len(cmd.argv) == 5
    assert "My Python Install" in cmd.display()


def test_detect_git_reports_not_a_repo_outside_git(tmp_path):
    status = detect_git(tmp_path)
    assert status.is_repo is False


def test_windows_style_path_is_treated_as_plain_string_data():
    # PyFix must not choke on / crash on Windows-style paths even when
    # running tests on POSIX; paths from tracebacks are just strings
    # until validated against the real project root.
    from pyfix.detectors.file_not_found import _FNF_RE

    msg = r"[Errno 2] No such file or directory: 'project\\data\\data.csv'"
    match = _FNF_RE.search(msg)
    assert match is not None
    assert "data.csv" in match.group(1)


def test_package_already_installed_is_detected_via_metadata():
    # `pytest` itself is guaranteed to be installed in the test env.
    resolution = resolve_package("pytest")
    assert resolution.resolved
    assert resolution.source in ("installed-metadata", "common-direct-match")
