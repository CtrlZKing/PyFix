from pyfix.traceback.parser import parse_traceback

MODULE_NOT_FOUND_TB = '''Traceback (most recent call last):
  File "game.py", line 1, in <module>
    import pygame
ModuleNotFoundError: No module named 'pygame'
'''

NAME_ERROR_TB = '''Traceback (most recent call last):
  File "game.py", line 2, in <module>
    pygame.init()
NameError: name 'pygame' is not defined
'''

CHAINED_TB = '''Traceback (most recent call last):
  File "a.py", line 1, in <module>
    raise ValueError("root cause")
ValueError: root cause

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "b.py", line 5, in <module>
    raise RuntimeError("wrapped") from exc
RuntimeError: wrapped
'''


def test_parses_module_not_found():
    info = parse_traceback(MODULE_NOT_FOUND_TB)
    assert info is not None
    assert info.exception_type == "ModuleNotFoundError"
    assert "pygame" in info.message
    assert info.last_frame.file == "game.py"
    assert info.last_frame.line == 1


def test_parses_name_error():
    info = parse_traceback(NAME_ERROR_TB)
    assert info is not None
    assert info.exception_type == "NameError"
    assert "pygame" in info.message


def test_parses_chained_exception():
    info = parse_traceback(CHAINED_TB)
    assert info is not None
    assert info.exception_type == "RuntimeError"
    assert info.cause is not None
    assert info.cause.exception_type == "ValueError"


def test_returns_none_for_garbage():
    assert parse_traceback("not a traceback at all") is None


def test_returns_none_for_empty():
    assert parse_traceback("") is None
