"""Pure static-analysis checks that don't require a runtime traceback.

Unreachable code, "break outside loop", constant conditions, and
statically-provable out-of-bounds indexing don't necessarily throw an
exception PyFix could catch from a run — some never throw at all
(unreachable code just silently never executes). So these live as a
static pass over the AST, used by ``pyfix analyze`` and folded into
``pyfix doctor``, rather than as traceback-triggered detectors.

Every check here only reports what it can prove from the AST alone —
no cross-module type inference, no execution. When something can't be
proven, the check either says nothing or (for genuinely useful partial
information, like a dynamic index) reports a LOW-confidence "possible"
diagnostic that is explicitly never auto-fixed.
"""

from __future__ import annotations

import ast
from pathlib import Path

from pyfix.diagnostics.models import Diagnostic, DiagnosticCategory, DiagnosticConfidence, DiagnosticSeverity

_TERMINATORS = (ast.Return, ast.Raise, ast.Break, ast.Continue)


def check_unreachable_code(tree: ast.AST, file_path: Path, source_lines: list[str]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []

    def scan_body(body: list[ast.stmt]) -> None:
        terminated_at: int | None = None
        for stmt in body:
            if terminated_at is not None:
                diagnostics.append(
                    Diagnostic(
                        file=file_path,
                        line=stmt.lineno,
                        category=DiagnosticCategory.CONTROL_FLOW,
                        severity=DiagnosticSeverity.WARNING,
                        message="Unreachable statement.",
                        confidence=DiagnosticConfidence.CERTAIN,
                        what_happened="This statement can never execute.",
                        why_it_happened=(
                            f"Line {terminated_at} always exits this block "
                            "(return/raise/break/continue) before control reaches here."
                        ),
                        offending_expression=_line_text(source_lines, stmt.lineno),
                        safe_to_apply=False,
                    )
                )
                # Only report the first unreachable statement in a run to
                # avoid spamming the user with every line after it.
                break
            if isinstance(stmt, _TERMINATORS):
                terminated_at = stmt.lineno
            # Recurse into nested blocks (if/for/while/with/try/function bodies).
            for child_body_attr in ("body", "orelse", "finalbody"):
                child_body = getattr(stmt, child_body_attr, None)
                if child_body:
                    scan_body(child_body)
            if isinstance(stmt, ast.Try):
                for handler in stmt.handlers:
                    scan_body(handler.body)

    if isinstance(tree, ast.Module):
        scan_body(tree.body)
    return diagnostics


def check_break_continue_outside_loop(tree: ast.AST, file_path: Path, source_lines: list[str]) -> list[Diagnostic]:
    # Python's own compiler already refuses to run code where `break`/
    # `continue` appear outside a loop (SyntaxError at compile time), so
    # this can only fire on an AST built without full compilation context
    # (e.g. a fragment) — kept for completeness and defensive coverage,
    # but in practice `pyfix run` will already have hit a SyntaxError
    # first for a whole invalid file.
    diagnostics: list[Diagnostic] = []

    def walk(node: ast.AST, loop_depth: int) -> None:
        for child in ast.iter_child_nodes(node):
            next_depth = loop_depth
            if isinstance(child, (ast.For, ast.AsyncFor, ast.While)):
                next_depth += 1
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                # A new function scope resets loop context.
                walk(child, 0)
                continue
            if isinstance(child, ast.Break) and loop_depth == 0:
                diagnostics.append(_flow_error(file_path, child.lineno, "break", source_lines))
            if isinstance(child, ast.Continue) and loop_depth == 0:
                diagnostics.append(_flow_error(file_path, child.lineno, "continue", source_lines))
            walk(child, next_depth)

    walk(tree, 0)
    return diagnostics


def _flow_error(file_path: Path, lineno: int, keyword: str, source_lines: list[str]) -> Diagnostic:
    return Diagnostic(
        file=file_path,
        line=lineno,
        category=DiagnosticCategory.CONTROL_FLOW,
        severity=DiagnosticSeverity.CRITICAL,
        message=f"'{keyword}' outside loop.",
        confidence=DiagnosticConfidence.CERTAIN,
        what_happened=f"`{keyword}` was used outside of a `for`/`while` loop.",
        why_it_happened=f"`{keyword}` only has meaning inside a loop body.",
        offending_expression=_line_text(source_lines, lineno),
        safe_to_apply=False,
    )


def check_constant_conditions(tree: ast.AST, file_path: Path, source_lines: list[str]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.While)) and not isinstance(node, ast.While):
            pass
        if isinstance(node, ast.If):
            verdict = _constant_bool(node.test)
            if verdict is not None:
                kind = "always true" if verdict else "always false"
                diagnostics.append(
                    Diagnostic(
                        file=file_path,
                        line=node.lineno,
                        category=DiagnosticCategory.CONTROL_FLOW,
                        severity=DiagnosticSeverity.WARNING,
                        message=f"Condition is statically {kind}.",
                        confidence=DiagnosticConfidence.CERTAIN,
                        what_happened=f"This `if` condition is {kind}, based only on its literal value.",
                        why_it_happened="The condition doesn't depend on any runtime value PyFix can see change.",
                        offending_expression=_line_text(source_lines, node.lineno),
                        safe_to_apply=False,
                    )
                )
        if isinstance(node, ast.While):
            verdict = _constant_bool(node.test)
            if verdict is True and not _loop_has_exit(node):
                diagnostics.append(
                    Diagnostic(
                        file=file_path,
                        line=node.lineno,
                        category=DiagnosticCategory.CONTROL_FLOW,
                        severity=DiagnosticSeverity.WARNING,
                        message="Possible infinite loop.",
                        confidence=DiagnosticConfidence.LOW,
                        what_happened="This loop's condition is always true and PyFix found no `break` or `return` inside it.",
                        why_it_happened="Without a visible exit, this loop may run forever.",
                        offending_expression=_line_text(source_lines, node.lineno),
                        safe_to_apply=False,
                    )
                )
    return diagnostics


def check_static_index_bounds(tree: ast.AST, file_path: Path, source_lines: list[str]) -> list[Diagnostic]:
    """Flag literal-index access into a literal list/tuple that is
    provably out of range — plus a low-confidence note for genuinely
    dynamic indices, since PyFix cannot prove those are safe either.

    Handles both a subscript directly on a literal (``[1, 2, 3][10]``)
    and a subscript on a variable that was assigned a literal
    list/tuple earlier in the same scope (``numbers = [1, 2, 3]`` ...
    ``numbers[10]``) — the latter is the common real-world shape.
    """

    diagnostics: list[Diagnostic] = []
    literal_lengths = _collect_simple_literal_container_lengths(tree)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        container_len = _literal_container_length(node.value)
        if container_len is None and isinstance(node.value, ast.Name):
            container_len = literal_lengths.get(node.value.id)
        index_value = _literal_int_index(node.slice)

        if container_len is None:
            continue  # not a literal we can reason about

        if index_value is None:
            diagnostics.append(
                Diagnostic(
                    file=file_path,
                    line=node.lineno,
                    category=DiagnosticCategory.INDEXING,
                    severity=DiagnosticSeverity.INFO,
                    message="Index is dynamic; bounds cannot be proven.",
                    confidence=DiagnosticConfidence.LOW,
                    what_happened="This index is a variable, not a literal, so PyFix cannot prove it's in range.",
                    why_it_happened="Only literal indices into literal collections can be checked statically.",
                    offending_expression=_line_text(source_lines, node.lineno),
                    safe_to_apply=False,
                )
            )
            continue

        normalized = index_value if index_value >= 0 else container_len + index_value
        if not (0 <= normalized < container_len):
            diagnostics.append(
                Diagnostic(
                    file=file_path,
                    line=node.lineno,
                    category=DiagnosticCategory.INDEXING,
                    severity=DiagnosticSeverity.ERROR,
                    message=f"Index {index_value} is outside bounds 0..{container_len - 1}.",
                    confidence=DiagnosticConfidence.CERTAIN,
                    what_happened=f"Index {index_value} is out of range for a collection of length {container_len}.",
                    why_it_happened=f"The collection literal has {container_len} elements (indices 0..{container_len - 1}).",
                    offending_expression=_line_text(source_lines, node.lineno),
                    safe_to_apply=False,
                )
            )
    return diagnostics


def check_obvious_type_mismatches(tree: ast.AST, file_path: Path, source_lines: list[str]) -> list[Diagnostic]:
    """Flag statically-obvious `str + int`-style literal mismatches.

    Deliberately narrow: only fires when BOTH operands are literals
    (or a variable directly assigned from a literal in the same
    function/module scope) with the specific unsupported str/number
    combination — never a general type inferencer.
    """

    diagnostics: list[Diagnostic] = []
    literal_types = _collect_simple_literal_types(tree)

    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Add):
            continue
        left_type = _literal_type(node.left, literal_types)
        right_type = _literal_type(node.right, literal_types)
        if left_type is None or right_type is None:
            continue
        if {left_type, right_type} == {"str", "number"}:
            diagnostics.append(
                Diagnostic(
                    file=file_path,
                    line=node.lineno,
                    category=DiagnosticCategory.TYPE_MISMATCH,
                    severity=DiagnosticSeverity.ERROR,
                    message="Text and number cannot be combined with '+'.",
                    confidence=DiagnosticConfidence.HIGH,
                    what_happened="This expression adds a piece of text to a number.",
                    why_it_happened="Python does not implicitly convert between str and int/float.",
                    offending_expression=_line_text(source_lines, node.lineno),
                    safe_to_apply=False,
                    proposed_fix_summary=(
                        "A likely type mismatch was detected, but PyFix cannot safely "
                        "determine the intended conversion (str(x) vs int(x))."
                    ),
                )
            )
    return diagnostics


# ---------------------------------------------------------------- helpers

def _line_text(source_lines: list[str], lineno: int) -> str:
    if 1 <= lineno <= len(source_lines):
        return source_lines[lineno - 1].strip()
    return ""


def _constant_bool(test: ast.expr) -> bool | None:
    if isinstance(test, ast.Constant) and isinstance(test.value, bool):
        return test.value
    if isinstance(test, ast.Constant) and isinstance(test.value, (int, float)):
        return bool(test.value)
    if isinstance(test, ast.Compare) and len(test.ops) == 1 and len(test.comparators) == 1:
        left, right = test.left, test.comparators[0]
        if isinstance(left, ast.Constant) and isinstance(right, ast.Constant):
            try:
                op = test.ops[0]
                if isinstance(op, ast.Eq):
                    return left.value == right.value
                if isinstance(op, ast.NotEq):
                    return left.value != right.value
            except Exception:
                return None
    return None


def _loop_has_exit(node: ast.While) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Break):
            return True
        if isinstance(child, (ast.Return,)):
            return True
    return False


def _literal_container_length(node: ast.expr) -> int | None:
    if isinstance(node, (ast.List, ast.Tuple)):
        return len(node.elts)
    return None


def _collect_simple_literal_container_lengths(tree: ast.AST) -> dict[str, int]:
    """name -> length, only for names assigned a literal list/tuple
    exactly once anywhere in the file (never reassigned), so a stale
    length is never used for a variable that's mutated or rebound
    later.
    """

    assignment_counts: dict[str, int] = {}
    literal_lengths: dict[str, int] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            assignment_counts[name] = assignment_counts.get(name, 0) + 1
            length = _literal_container_length(node.value)
            if length is not None:
                literal_lengths[name] = length
            else:
                literal_lengths.pop(name, None)

    return {name: length for name, length in literal_lengths.items() if assignment_counts.get(name) == 1}


def _literal_int_index(node: ast.expr) -> int | None:
    target = node
    if isinstance(target, ast.UnaryOp) and isinstance(target.op, ast.USub) and isinstance(target.operand, ast.Constant):
        if isinstance(target.operand.value, int):
            return -target.operand.value
    if isinstance(target, ast.Constant) and isinstance(target.value, int) and not isinstance(target.value, bool):
        return target.value
    return None


def _collect_simple_literal_types(tree: ast.AST) -> dict[str, str]:
    """name -> "str" | "number" for module/function-level `x = <literal>` assigns."""

    types: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            lit = _literal_kind(node.value)
            if lit:
                types[node.targets[0].id] = lit
    return types


def _literal_kind(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return "str"
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return "number"
    return None


def _literal_type(node: ast.expr, literal_types: dict[str, str]) -> str | None:
    direct = _literal_kind(node)
    if direct:
        return direct
    if isinstance(node, ast.Name):
        return literal_types.get(node.id)
    return None
