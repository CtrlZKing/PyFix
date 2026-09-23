"""A reusable, scope-aware static analysis layer.

This sits on top of :mod:`pyfix.source.ast_utils` (which stays as the
low-level "parse this one file" utility) and understands the things
several Level-2 detectors all need: function signatures, call sites,
which names are defined in which scope, and simple source-range
lookups for locating an AST node from a traceback's (line, col).

Kept intentionally conservative: it never infers types across function
boundaries, never resolves attributes on arbitrary objects, and never
claims certainty it doesn't have. It builds facts; detectors decide
what those facts mean.
"""

from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass, field


@dataclass
class ParamInfo:
    name: str
    has_default: bool
    kind: str  # "positional", "vararg", "kwonly", "kwarg"


@dataclass
class FunctionInfo:
    name: str
    node: ast.FunctionDef | ast.AsyncFunctionDef
    params: list[ParamInfo]
    lineno: int

    def required_positional(self) -> list[str]:
        return [p.name for p in self.params if p.kind == "positional" and not p.has_default]

    def all_positional(self) -> list[str]:
        return [p.name for p in self.params if p.kind == "positional"]

    def has_varargs(self) -> bool:
        return any(p.kind == "vararg" for p in self.params)

    def has_kwargs(self) -> bool:
        return any(p.kind == "kwarg" for p in self.params)

    def keyword_names(self) -> list[str]:
        return [p.name for p in self.params if p.kind in ("positional", "kwonly")]


@dataclass
class CallSite:
    func_name: str
    node: ast.Call
    lineno: int
    col: int
    positional_count: int
    keyword_names: list[str]
    has_star_args: bool
    has_star_kwargs: bool


@dataclass
class ScopeInfo:
    """Names defined somewhere reachable at a given point in the file.

    This is a deliberately coarse approximation of Python scoping
    (module + all enclosing function scopes merged) — good enough to
    tell "is this name defined anywhere plausible" and to generate
    typo candidates, without pretending to be a full symbol-table
    implementation.
    """

    defined_names: set[str] = field(default_factory=set)
    function_names: set[str] = field(default_factory=set)
    class_names: set[str] = field(default_factory=set)
    imported_names: set[str] = field(default_factory=set)


_BUILTIN_NAMES = set(dir(builtins))


class StaticAnalyzer:
    """Whole-file static facts, computed once and reused by detectors."""

    def __init__(self, source: str, tree: ast.AST | None = None):
        self.source = source
        self.tree = tree if tree is not None else _safe_parse(source)
        self._lines = source.splitlines()

    @property
    def is_valid(self) -> bool:
        return self.tree is not None

    def source_line(self, lineno: int) -> str:
        if 1 <= lineno <= len(self._lines):
            return self._lines[lineno - 1]
        return ""

    def source_context(self, lineno: int, radius: int = 1) -> list[str]:
        start = max(1, lineno - radius)
        end = min(len(self._lines), lineno + radius)
        return [self._lines[i - 1] for i in range(start, end + 1)]

    # ---- functions & calls -------------------------------------------------

    def functions(self) -> list[FunctionInfo]:
        if self.tree is None:
            return []
        results = []
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                results.append(_function_info_from_node(node))
        return results

    def find_function(self, name: str) -> FunctionInfo | None:
        for fn in self.functions():
            if fn.name == name:
                return fn
        return None

    def call_sites(self, func_name: str | None = None) -> list[CallSite]:
        if self.tree is None:
            return []
        results = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                name = _call_target_name(node)
                if name is None:
                    continue
                if func_name is not None and name != func_name:
                    continue
                results.append(
                    CallSite(
                        func_name=name,
                        node=node,
                        lineno=node.lineno,
                        col=node.col_offset,
                        positional_count=len(node.args),
                        keyword_names=[kw.arg for kw in node.keywords if kw.arg is not None],
                        has_star_args=any(isinstance(a, ast.Starred) for a in node.args),
                        has_star_kwargs=any(kw.arg is None for kw in node.keywords),
                    )
                )
        return results

    def call_at_line(self, lineno: int) -> CallSite | None:
        candidates = [c for c in self.call_sites() if c.lineno == lineno]
        return candidates[0] if candidates else None

    # ---- names & scope -------------------------------------------------

    def scope_at_line(self, lineno: int) -> ScopeInfo:
        """All names plausibly in scope at ``lineno`` (module + enclosing defs)."""

        scope = ScopeInfo()
        if self.tree is None:
            return scope

        scope.imported_names |= _module_import_names(self.tree)

        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scope.function_names.add(node.name)
            if isinstance(node, ast.ClassDef):
                scope.class_names.add(node.name)

        # Collect module-level assigned names (always visible).
        if isinstance(self.tree, ast.Module):
            for stmt in self.tree.body:
                scope.defined_names |= _assigned_names_in_stmt(stmt)

        # Find the innermost function containing lineno, and add its
        # parameters + local assignments.
        enclosing = _innermost_function_containing(self.tree, lineno)
        if enclosing is not None:
            for arg in _all_args(enclosing.args):
                scope.defined_names.add(arg)
            for stmt in ast.walk(enclosing):
                scope.defined_names |= _assigned_names_in_stmt(stmt)

        scope.defined_names |= scope.function_names | scope.class_names | scope.imported_names
        return scope

    def all_candidate_names(self, lineno: int) -> set[str]:
        """Every name that could reasonably be suggested as a typo fix."""

        scope = self.scope_at_line(lineno)
        return scope.defined_names | _BUILTIN_NAMES


def _safe_parse(source: str) -> ast.AST | None:
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def _call_target_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _all_args(args: ast.arguments) -> list[str]:
    names = []
    for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
        names.append(a.arg)
    if args.vararg:
        names.append(args.vararg.arg)
    if args.kwarg:
        names.append(args.kwarg.arg)
    return names


def _function_info_from_node(node) -> FunctionInfo:
    params: list[ParamInfo] = []
    args = node.args
    positional = list(args.posonlyargs) + list(args.args)
    num_defaults = len(args.defaults)
    num_no_default = len(positional) - num_defaults
    for i, a in enumerate(positional):
        has_default = i >= num_no_default
        params.append(ParamInfo(a.arg, has_default, "positional"))
    if args.vararg:
        params.append(ParamInfo(args.vararg.arg, True, "vararg"))
    for i, a in enumerate(args.kwonlyargs):
        has_default = args.kw_defaults[i] is not None
        params.append(ParamInfo(a.arg, has_default, "kwonly"))
    if args.kwarg:
        params.append(ParamInfo(args.kwarg.arg, True, "kwarg"))
    return FunctionInfo(name=node.name, node=node, params=params, lineno=node.lineno)


def _module_import_names(tree: ast.AST) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


def _assigned_names_in_stmt(stmt: ast.AST) -> set[str]:
    names = set()
    targets_source = []
    if isinstance(stmt, ast.Assign):
        targets_source = stmt.targets
    elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
        targets_source = [stmt.target]
    elif isinstance(stmt, ast.For):
        targets_source = [stmt.target]
    elif isinstance(stmt, ast.comprehension):
        targets_source = [stmt.target]
    elif isinstance(stmt, ast.With):
        for item in stmt.items:
            if item.optional_vars is not None:
                targets_source.append(item.optional_vars)
    elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        names.add(stmt.name)

    for target in targets_source:
        names |= _names_in_target(target)
    return names


def _names_in_target(target: ast.AST) -> set[str]:
    names = set()
    if isinstance(target, ast.Name):
        names.add(target.id)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            names |= _names_in_target(elt)
    return names


def _innermost_function_containing(tree: ast.AST, lineno: int):
    best = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", None) or node.lineno
            if node.lineno <= lineno <= end:
                if best is None or node.lineno >= best.lineno:
                    best = node
    return best
