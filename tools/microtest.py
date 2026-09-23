"""A tiny, dependency-free stand-in for the parts of pytest our test
suite uses (fixtures, monkeypatch, capsys, tmp_path, parametrize,
raises, mark.skip). This exists ONLY because this sandbox has no
network access to `pip install pytest`. It is not shipped with PyFix
and is not a replacement for running the real pytest suite.

Usage: python3 tools/microtest.py
"""

from __future__ import annotations

import importlib.util
import inspect
import io
import shutil
import sys
import tempfile
import traceback as tb_module
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
TESTS = REPO_ROOT / "tests"


# ---------------------------------------------------------------- fake pytest
class _Mark:
    @staticmethod
    def parametrize(argnames, argvalues):
        def decorator(func):
            func.__pytest_parametrize__ = (argnames, argvalues)
            return func
        return decorator

    @staticmethod
    def skip(reason=""):
        def decorator(func):
            func.__pytest_skip__ = reason
            return func
        return decorator


class _FakeRaises:
    def __init__(self, exc_type):
        self.exc_type = exc_type

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            raise AssertionError(f"DID NOT RAISE {self.exc_type}")
        return issubclass(exc_type, self.exc_type)


def _fixture(func=None, **kwargs):
    if func is None:
        def wrapper(f):
            f.__is_fixture__ = True
            return f
        return wrapper
    func.__is_fixture__ = True
    return func


class _FakePytestModule:
    mark = _Mark()
    fixture = staticmethod(_fixture)
    raises = _FakeRaises


sys.modules["pytest"] = _FakePytestModule()  # type: ignore
sys.path.insert(0, str(SRC))


# ---------------------------------------------------------------- fixtures
class MonkeyPatch:
    def __init__(self):
        self._undo: list[tuple[object, str, object, bool]] = []
        self._old_cwd = None

    def setattr(self, obj, name, value):
        had = hasattr(obj, name)
        old = getattr(obj, name, None)
        self._undo.append((obj, name, old, had))
        setattr(obj, name, value)

    def chdir(self, path):
        import os
        if self._old_cwd is None:
            self._old_cwd = os.getcwd()
        os.chdir(str(path))

    def undo(self):
        import os
        for obj, name, old, had in reversed(self._undo):
            if had:
                setattr(obj, name, old)
            else:
                delattr(obj, name)
        if self._old_cwd is not None:
            os.chdir(self._old_cwd)


class Capsys:
    def __init__(self):
        self._old_out = sys.stdout
        self._old_err = sys.stderr
        self.out_buf = io.StringIO()
        self.err_buf = io.StringIO()
        sys.stdout = self.out_buf
        sys.stderr = self.err_buf

    def readouterr(self):
        class R:
            pass
        r = R()
        r.out = self.out_buf.getvalue()
        r.err = self.err_buf.getvalue()
        self.out_buf.truncate(0)
        self.out_buf.seek(0)
        self.err_buf.truncate(0)
        self.err_buf.seek(0)
        return r

    def restore(self):
        sys.stdout = self._old_out
        sys.stderr = self._old_err


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore
    return module


def _collect_fixtures(conftest_module):
    fixtures = {}
    if conftest_module is None:
        return fixtures
    for name, obj in vars(conftest_module).items():
        if callable(obj) and getattr(obj, "__is_fixture__", False):
            fixtures[name] = obj
    return fixtures


def _resolve_arg(name, custom_fixtures, cleanup, tmp_path_cache):
    if name == "tmp_path":
        if "tmp_path" not in tmp_path_cache:
            d = tempfile.mkdtemp(prefix="pyfix_microtest_")
            tmp_path_cache["tmp_path"] = Path(d)
            cleanup.append(lambda: shutil.rmtree(d, ignore_errors=True))
        return tmp_path_cache["tmp_path"]
    if name == "monkeypatch":
        mp = MonkeyPatch()
        cleanup.append(mp.undo)
        return mp
    if name == "capsys":
        cs = Capsys()
        cleanup.append(cs.restore)
        return cs
    if name in custom_fixtures:
        func = custom_fixtures[name]
        params = list(inspect.signature(func).parameters)
        kwargs = {p: _resolve_arg(p, custom_fixtures, cleanup, tmp_path_cache) for p in params}
        return func(**kwargs)
    raise KeyError(f"Unknown fixture: {name}")


def run_test_function(func, custom_fixtures):
    cleanup = []
    tmp_path_cache = {}
    try:
        params = list(inspect.signature(func).parameters)
        kwargs = {p: _resolve_arg(p, custom_fixtures, cleanup, tmp_path_cache) for p in params}
        func(**kwargs)
        return True, None
    except Exception as exc:  # noqa: BLE001
        return False, "".join(tb_module.format_exception(type(exc), exc, exc.__traceback__))
    finally:
        for fn in reversed(cleanup):
            try:
                fn()
            except Exception:
                pass


def main() -> int:
    test_files = sorted(TESTS.rglob("test_*.py"))
    total = 0
    passed = 0
    failed = 0
    skipped = 0
    failures: list[tuple[str, str]] = []

    for test_file in test_files:
        rel = test_file.relative_to(REPO_ROOT)
        conftest_path = test_file.parent / "conftest.py"
        if not conftest_path.exists():
            conftest_path = TESTS / "conftest.py"
        conftest_module = _load_module(conftest_path, f"conftest_{test_file.stem}") if conftest_path.exists() else None
        custom_fixtures = _collect_fixtures(conftest_module)

        module = _load_module(test_file, f"testmod_{test_file.stem}_{id(test_file)}")

        for name, obj in list(vars(module).items()):
            if not (name.startswith("test_") and callable(obj)):
                continue

            skip_reason = getattr(obj, "__pytest_skip__", None)
            if skip_reason is not None:
                skipped += 1
                print(f"SKIP  {rel}::{name}  ({skip_reason})")
                continue

            parametrize = getattr(obj, "__pytest_parametrize__", None)
            if parametrize:
                argnames, argvalues = parametrize
                arg_list = [a.strip() for a in argnames.split(",")] if isinstance(argnames, str) else list(argnames)
                for raw_value in argvalues:
                    if len(arg_list) == 1:
                        values = (raw_value,)
                    elif isinstance(raw_value, (list, tuple)):
                        values = tuple(raw_value)
                    else:
                        values = (raw_value,)
                    total += 1

                    def bound(**extra):
                        pass

                    # Build a wrapper that supplies the parametrized args.
                    fixed = dict(zip(arg_list, values))

                    def make_call(fixed_args, target_func=obj):
                        def _call(**fixture_kwargs):
                            return target_func(**fixed_args, **fixture_kwargs)
                        # Expose the non-parametrized params for fixture resolution
                        sig_params = [
                            p for p in inspect.signature(target_func).parameters
                            if p not in fixed_args
                        ]
                        _call.__signature__ = inspect.Signature(
                            [inspect.Parameter(p, inspect.Parameter.POSITIONAL_OR_KEYWORD) for p in sig_params]
                        )
                        return _call

                    wrapped = make_call(fixed)
                    ok, err = run_test_function(wrapped, custom_fixtures)
                    label = f"{rel}::{name}{values}"
                    if ok:
                        passed += 1
                        print(f"PASS  {label}")
                    else:
                        failed += 1
                        print(f"FAIL  {label}")
                        failures.append((label, err))
                continue

            total += 1
            ok, err = run_test_function(obj, custom_fixtures)
            label = f"{rel}::{name}"
            if ok:
                passed += 1
                print(f"PASS  {label}")
            else:
                failed += 1
                print(f"FAIL  {label}")
                failures.append((label, err))

    print()
    print(f"{passed} passed, {failed} failed, {skipped} skipped out of {total + skipped} collected")

    if failures:
        print()
        print("=" * 70)
        print("FAILURES")
        print("=" * 70)
        for label, err in failures:
            print(f"\n--- {label} ---")
            print(err)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
