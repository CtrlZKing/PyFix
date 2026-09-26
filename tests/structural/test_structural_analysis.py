"""Tests for pyfix.analysis.structural — the Structural Syntax &
Formatting Intelligence subsystem.

Every category gets: a positive (bug present, should classify), a
negative (valid code, must NOT false-positive), and — where the
category can be ambiguous — a case proving PyFix stays explanation-only
rather than guessing.
"""

from __future__ import annotations

import ast

import pytest

from pyfix.analysis.structural import StructuralCategory, analyze_structural


# ---------------------------------------------------------------- colons


@pytest.mark.parametrize(
    "source",
    [
        "if x == 5\n    print(x)\n",
        "if y:\n    pass\nelif y\n    print(y)\n",
        "for x in items\n    print(x)\n",
        "while True\n    break\n",
        "def f(x, y)\n    return x + y\n",
        "class Foo\n    pass\n",
        "try:\n    pass\nexcept Exception\n    pass\n",
        "with open('f') as fh\n    pass\n",
        "match x:\n    case 1:\n        pass\nif y\n    pass\n",
    ],
)
def test_missing_colon_detected_and_fixed(source):
    finding = analyze_structural(source)
    assert finding is not None
    assert finding.category == StructuralCategory.MISSING_COLON
    assert finding.can_auto_fix
    assert finding.fix_new_content is not None
    ast.parse(finding.fix_new_content)  # the repair itself must be valid Python


def test_missing_colon_with_trailing_comment_preserves_comment():
    source = "if x == 5  # important\n    print(x)\n"
    finding = analyze_structural(source)
    assert finding.can_auto_fix
    assert "# important" in finding.fix_new_content
    ast.parse(finding.fix_new_content)


def test_missing_colon_in_multiline_def_edits_the_closing_line_only():
    source = "def f(a,\n      b)\n    return a\n"
    finding = analyze_structural(source)
    assert finding.can_auto_fix
    new_lines = finding.fix_new_content.splitlines()
    assert new_lines[0] == "def f(a,"  # untouched
    assert new_lines[1] == "      b):"
    ast.parse(finding.fix_new_content)


@pytest.mark.parametrize(
    "source",
    [
        "x = 5\nprint(x)\n",
        "if x:\n    print(x)\n",
        "def f(a, b):\n    return a + b\n",
        "class Foo:\n    pass\n",
    ],
)
def test_valid_code_is_never_flagged(source):
    assert analyze_structural(source) is None


# --------------------------------------------------------- multiline safety


@pytest.mark.parametrize(
    "source",
    [
        "items = [\n    'one',\n    'two',\n    'three',\n]\nprint(items)\n",
        "result = (\n    value_one +\n    value_two\n)\n",
        "result = some_function(\n    argument_one,\n    argument_two,\n)\n",
        'x = """\nif this looks like code: it is just a string\n"""\n',
        "# if this comment mentions a colon-needing keyword, ignore it\nx = 1\n",
    ],
)
def test_multiline_and_string_and_comment_constructs_are_not_false_positives(source):
    assert analyze_structural(source) is None


# ------------------------------------------------------------- brackets


def test_single_mismatched_bracket_is_auto_fixable():
    source = "items = (1, 2, 3]\n"
    finding = analyze_structural(source)
    assert finding.category == StructuralCategory.MISMATCHED_BRACKET
    assert finding.can_auto_fix
    ast.parse(finding.fix_new_content)
    assert finding.fix_new_content == "items = (1, 2, 3)\n"


def test_unclosed_bracket_is_explanation_only():
    source = "print('hello'\n"
    finding = analyze_structural(source)
    assert finding.category == StructuralCategory.UNCLOSED_BRACKET
    assert not finding.can_auto_fix
    assert finding.fix_new_content is None
    assert finding.unresolved_reason


# --------------------------------------------------------- indentation


def test_unambiguous_stray_indent_is_auto_fixable():
    source = "print('a')\n    print('b')\n"
    finding = analyze_structural(source)
    assert finding.category == StructuralCategory.UNEXPECTED_INDENT
    assert finding.can_auto_fix
    ast.parse(finding.fix_new_content)
    assert finding.fix_new_content == "print('a')\nprint('b')\n"


def test_missing_block_body_is_explanation_only_never_invented():
    source = "if some_condition:\n"  # the body is genuinely absent
    finding = analyze_structural(source)
    assert finding.category == StructuralCategory.MISSING_BLOCK_BODY
    assert not finding.can_auto_fix
    assert finding.fix_new_content is None


# ------------------------------------------------------- honest fallback


def test_ambiguous_or_unclassified_syntax_errors_return_none_not_a_guess():
    # A bare `else` with no matching `if`/`for`/`while` is invalid Python,
    # but *why* is genuinely ambiguous — PyFix must not fabricate a fix.
    source = "else:\n    print(1)\n"
    assert analyze_structural(source) is None
