"""Deterministic, AST-based source analysis.

PyFix never decides "this name is probably an import" using an LLM or
a fuzzy heuristic alone — it parses the real Python AST to see how a
name is actually used, and only then assigns a confidence score.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass
class ImportInfo:
    module: str
    asname: str | None
    lineno: int
    is_from_import: bool
    imported_names: list[str] | None = None  # for `from x import a, b`


@dataclass
class NameUsage:
    name: str
    lineno: int
    col: int
    is_call: bool
    is_attribute_access: bool


class SourceAnalysis:
    """Parsed view of one source file, safe to compute repeatedly."""

    def __init__(self, source: str):
        self.source = source
        self.tree: ast.AST | None
        self.syntax_error: SyntaxError | None = None
        try:
            self.tree = ast.parse(source)
        except SyntaxError as exc:
            self.tree = None
            self.syntax_error = exc

    @property
    def is_valid(self) -> bool:
        return self.tree is not None

    def imports(self) -> list[ImportInfo]:
        if self.tree is None:
            return []
        results: list[ImportInfo] = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    results.append(
                        ImportInfo(
                            module=alias.name,
                            asname=alias.asname,
                            lineno=node.lineno,
                            is_from_import=False,
                        )
                    )
            elif isinstance(node, ast.ImportFrom):
                results.append(
                    ImportInfo(
                        module=node.module or "",
                        asname=None,
                        lineno=node.lineno,
                        is_from_import=True,
                        imported_names=[a.name for a in node.names],
                    )
                )
        return results

    def top_level_names_bound_by_imports(self) -> set[str]:
        """The local names that become available because of imports."""

        bound: set[str] = set()
        for imp in self.imports():
            if imp.is_from_import:
                bound.update(imp.imported_names or [])
            else:
                # `import a.b.c` binds the name `a` in the local namespace,
                # unless aliased.
                bound.add(imp.asname or imp.module.split(".")[0])
        return bound

    def find_name_usages(self, name: str) -> list[NameUsage]:
        if self.tree is None:
            return []
        usages: list[NameUsage] = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name) and node.id == name:
                parent_is_call = False
                usages.append(
                    NameUsage(
                        name=name,
                        lineno=node.lineno,
                        col=node.col_offset,
                        is_call=parent_is_call,
                        is_attribute_access=False,
                    )
                )
        return usages

    def is_name_used_as_module(self, name: str) -> bool:
        """True if ``name`` is used the way a module typically is: ``name.attr``."""

        if self.tree is None:
            return False
        for node in ast.walk(self.tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == name
            ):
                return True
        return False

    def is_name_assigned(self, name: str) -> bool:
        """True if ``name`` is ever assigned to (a local var, not just used)."""

        if self.tree is None:
            return False
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == name:
                        return True
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == name:
                    return True
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
        return False

    def first_import_line(self) -> int:
        """Best line number to insert a brand-new top-level import at."""

        if self.tree is None or not isinstance(self.tree, ast.Module):
            return 1

        body = self.tree.body
        # Skip a leading module docstring.
        idx = 0
        if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
            if isinstance(body[0].value.value, str):
                idx = 1

        # If there are already imports, insert after the last leading import.
        last_import_idx = idx - 1
        for i in range(idx, len(body)):
            if isinstance(body[i], (ast.Import, ast.ImportFrom)):
                last_import_idx = i
            else:
                break

        if last_import_idx >= idx:
            return body[last_import_idx].end_lineno + 1  # type: ignore[attr-defined]
        return body[idx].lineno if idx < len(body) else 1
