"""Security-focused tests for the Level-2 additions: the rename
editor, the attribute-typo module allow-list, and malicious traceback
content feeding the new detectors.
"""

from __future__ import annotations

from pathlib import Path

from pyfix.detectors.attribute_typo import SAFE_INTROSPECTION_MODULES, AttributeTypoDetector
from pyfix.detectors.base import DetectionContext
from pyfix.detectors.wrong_arguments import WrongArgumentsDetector
from pyfix.source.rename_editor import build_rename_edit
from pyfix.traceback.parser import parse_traceback


def test_rename_editor_returns_none_for_out_of_range_line():
    result = build_rename_edit("x = 1\n", lineno=99, old_name="x", new_name="y")
    assert result is None


def test_rename_editor_returns_none_when_name_absent_on_line():
    result = build_rename_edit("x = 1\ny = 2\n", lineno=2, old_name="zzz", new_name="y")
    assert result is None


def test_rename_editor_only_touches_the_target_line():
    source = "bad = 1\nprint(bad)\nprint(bad)\n"
    result = build_rename_edit(source, lineno=2, old_name="bad", new_name="good")
    assert result is not None
    new_lines = result.new_content.splitlines()
    assert new_lines[0] == "bad = 1"       # untouched
    assert new_lines[1] == "print(good)"   # only this line changed
    assert new_lines[2] == "print(bad)"    # untouched


def test_attribute_detector_never_imports_modules_outside_allowlist():
    # A made-up, dangerous-sounding module name must never be imported
    # for introspection, regardless of how the AttributeError is phrased.
    dangerous_name = "totally_unverified_module_xyz"
    assert dangerous_name not in SAFE_INTROSPECTION_MODULES

    tb = (
        'Traceback (most recent call last):\n'
        '  File "app.py", line 1, in <module>\n'
        f'    {dangerous_name}.whatever()\n'
        f"AttributeError: module '{dangerous_name}' has no attribute 'whatever'\n"
    )
    tb_info = parse_traceback(tb)
    ctx = DetectionContext(tb_info, Path("app.py"), Path("."), Path("python"))
    detector = AttributeTypoDetector()
    proposal = detector.diagnose(ctx)
    assert proposal is not None
    assert proposal.can_auto_fix is False
    assert proposal.category == "attribute_error_unknown"


def test_attribute_detector_allowlist_is_stdlib_only():
    # Guard against someone accidentally widening the allow-list to
    # include network-facing or file-system-mutating third-party code.
    assert SAFE_INTROSPECTION_MODULES == {
        "os", "pathlib", "sys", "math", "json", "re", "random", "datetime",
        "subprocess", "shutil", "collections", "itertools", "typing",
    }


def test_malicious_function_name_in_traceback_does_not_crash_wrong_arguments_detector(project_dir: Path):
    # A crafted traceback message trying to smuggle shell metacharacters
    # into the "function name" PyFix extracts must not cause a crash,
    # and must never be used to build a command (WrongArgumentsDetector
    # never executes anything — this just checks it degrades safely).
    malicious_tb = (
        'Traceback (most recent call last):\n'
        '  File "app.py", line 1, in <module>\n'
        '    os.system("rm -rf /")\n'
        "TypeError: os.system() missing 1 required positional argument: 'x; rm -rf /'\n"
    )
    script = project_dir / "app.py"
    script.write_text('os.system("rm -rf /")\n', encoding="utf-8")
    tb_info = parse_traceback(malicious_tb)
    ctx = DetectionContext(tb_info, script, project_dir, Path("python"))
    detector = WrongArgumentsDetector()

    # Must not raise, and must never produce an executable command.
    proposal = detector.diagnose(ctx)
    if proposal is not None:
        assert proposal.commands == []
        assert proposal.can_auto_fix is False


def test_rename_edit_word_boundary_does_not_match_substring():
    # "cat" must not accidentally match inside "concatenate".
    source = "value = concatenate(a, b)\nprint(cat)\n"
    result = build_rename_edit(source, lineno=1, old_name="cat", new_name="dog")
    # No whole-word "cat" on line 1 (only inside "concatenate"), so this
    # must return None rather than mangling the identifier.
    assert result is None
