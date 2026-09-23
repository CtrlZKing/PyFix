from pathlib import Path

from pyfix.detectors.attribute_typo import AttributeTypoDetector
from pyfix.detectors.base import DetectionContext
from pyfix.detectors.wrong_arguments import WrongArgumentsDetector
from pyfix.traceback.parser import parse_traceback


def _write(project_dir: Path, name: str, content: str) -> Path:
    path = project_dir / name
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------- wrong arguments

MISSING_ARG_TB = '''Traceback (most recent call last):
  File "app.py", line 5, in <module>
    total = calculate_total(500)
TypeError: calculate_total() missing 1 required positional argument: 'tax'
'''

TOO_MANY_ARGS_TB = '''Traceback (most recent call last):
  File "app.py", line 5, in <module>
    total = calculate_total(500, 0.1, 99)
TypeError: calculate_total() takes 2 positional arguments but 3 were given
'''

UNEXPECTED_KW_TB = '''Traceback (most recent call last):
  File "app.py", line 5, in <module>
    print(calculate_total(price=500, taxes=0.18))
TypeError: calculate_total() got an unexpected keyword argument 'taxes'
'''

DUPLICATE_ARG_TB = '''Traceback (most recent call last):
  File "app.py", line 5, in <module>
    calculate_total(500, price=1)
TypeError: calculate_total() got multiple values for argument 'price'
'''

FUNC_SOURCE = "def calculate_total(price, tax):\n    return price + tax\n\n\n"


def test_missing_argument_is_explanation_only(project_dir: Path):
    script = _write(project_dir, "app.py", FUNC_SOURCE + "total = calculate_total(500)\n")
    ctx = DetectionContext(parse_traceback(MISSING_ARG_TB), script, project_dir, Path("python"))
    detector = WrongArgumentsDetector()
    assert detector.matches(ctx)
    proposal = detector.diagnose(ctx)
    assert proposal is not None
    assert proposal.can_auto_fix is False
    assert proposal.category == "missing_arguments"
    assert "tax" in proposal.explanation


def test_too_many_arguments_is_explanation_only(project_dir: Path):
    script = _write(project_dir, "app.py", FUNC_SOURCE + "total = calculate_total(500, 0.1, 99)\n")
    ctx = DetectionContext(parse_traceback(TOO_MANY_ARGS_TB), script, project_dir, Path("python"))
    detector = WrongArgumentsDetector()
    proposal = detector.diagnose(ctx)
    assert proposal is not None
    assert proposal.can_auto_fix is False
    assert proposal.category == "too_many_arguments"


def test_unexpected_keyword_typo_is_auto_fixable(project_dir: Path):
    script = _write(project_dir, "app.py", FUNC_SOURCE + "print(calculate_total(price=500, taxes=0.18))\n")
    ctx = DetectionContext(parse_traceback(UNEXPECTED_KW_TB), script, project_dir, Path("python"))
    detector = WrongArgumentsDetector()
    proposal = detector.diagnose(ctx)
    assert proposal is not None
    assert proposal.can_auto_fix is True
    assert proposal.category == "unexpected_keyword_typo"
    assert "tax=0.18" in proposal.proposed_changes[0].new_content
    assert "taxes=0.18" not in proposal.proposed_changes[0].new_content


def test_duplicate_argument_is_explanation_only(project_dir: Path):
    script = _write(project_dir, "app.py", FUNC_SOURCE + "calculate_total(500, price=1)\n")
    ctx = DetectionContext(parse_traceback(DUPLICATE_ARG_TB), script, project_dir, Path("python"))
    detector = WrongArgumentsDetector()
    proposal = detector.diagnose(ctx)
    assert proposal is not None
    assert proposal.can_auto_fix is False
    assert proposal.category == "duplicate_argument"


def test_unrecognized_keyword_with_no_close_match_is_left_unfixed(project_dir: Path):
    # `nonsense` has no plausible relationship to `price`/`tax`, so
    # PyFix must not guess.
    tb = '''Traceback (most recent call last):
  File "app.py", line 5, in <module>
    print(calculate_total(price=500, nonsense=1))
TypeError: calculate_total() got an unexpected keyword argument 'nonsense'
'''
    script = _write(project_dir, "app.py", FUNC_SOURCE + "print(calculate_total(price=500, nonsense=1))\n")
    ctx = DetectionContext(parse_traceback(tb), script, project_dir, Path("python"))
    detector = WrongArgumentsDetector()
    proposal = detector.diagnose(ctx)
    assert proposal is not None
    assert proposal.can_auto_fix is False


# ---------------------------------------------------------------- attribute typos

LIST_ATTR_TB = '''Traceback (most recent call last):
  File "app.py", line 2, in <module>
    items.apend("x")
AttributeError: 'list' object has no attribute 'apend'
'''

MODULE_ATTR_TB = '''Traceback (most recent call last):
  File "app.py", line 2, in <module>
    math.sqrtt(4)
AttributeError: module 'math' has no attribute 'sqrtt'
'''

UNSAFE_MODULE_ATTR_TB = '''Traceback (most recent call last):
  File "app.py", line 2, in <module>
    requests.gett(url)
AttributeError: module 'requests' has no attribute 'gett'
'''


def test_builtin_list_attribute_typo_suggests_append(project_dir: Path):
    script = _write(project_dir, "app.py", "items = []\nitems.apend('x')\n")
    ctx = DetectionContext(parse_traceback(LIST_ATTR_TB), script, project_dir, Path("python"))
    detector = AttributeTypoDetector()
    assert detector.matches(ctx)
    proposal = detector.diagnose(ctx)
    assert proposal is not None
    assert "append" in proposal.explanation
    assert proposal.can_auto_fix is False  # explanation-only by design


def test_stdlib_module_attribute_typo_suggests_correction(project_dir: Path):
    script = _write(project_dir, "app.py", "import math\nmath.sqrtt(4)\n")
    ctx = DetectionContext(parse_traceback(MODULE_ATTR_TB), script, project_dir, Path("python"))
    detector = AttributeTypoDetector()
    proposal = detector.diagnose(ctx)
    assert proposal is not None
    assert "sqrt" in proposal.explanation


def test_non_safelisted_module_is_not_introspected(project_dir: Path):
    # PyFix must NOT import arbitrary/third-party modules just to
    # inspect them — even a plausible-looking one like `requests`.
    script = _write(project_dir, "app.py", "import requests\nrequests.gett('http://x')\n")
    ctx = DetectionContext(parse_traceback(UNSAFE_MODULE_ATTR_TB), script, project_dir, Path("python"))
    detector = AttributeTypoDetector()
    proposal = detector.diagnose(ctx)
    assert proposal is not None
    assert proposal.can_auto_fix is False
    assert proposal.category == "attribute_error_unknown"
    assert "cannot" in proposal.explanation.lower() or "cannot" in proposal.why_it_happened.lower()


def test_unknown_builtin_attribute_with_no_close_match(project_dir: Path):
    tb = '''Traceback (most recent call last):
  File "app.py", line 2, in <module>
    items.zzzznomatch()
AttributeError: 'list' object has no attribute 'zzzznomatch'
'''
    script = _write(project_dir, "app.py", "items = []\nitems.zzzznomatch()\n")
    ctx = DetectionContext(parse_traceback(tb), script, project_dir, Path("python"))
    detector = AttributeTypoDetector()
    proposal = detector.diagnose(ctx)
    assert proposal is not None
    assert proposal.can_auto_fix is False
    assert proposal.category == "attribute_error_unknown"
