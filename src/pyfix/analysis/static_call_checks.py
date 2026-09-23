"""Static (no-execution) versions of the undefined-variable and
wrong-argument-count checks, for multi-diagnostic reporting (`pyfix
analyze` / `pyfix doctor`) — as opposed to the traceback-triggered
detectors in :mod:`pyfix.detectors`, which fire on an actual runtime
exception. These intentionally reuse the same underlying logic
(:mod:`pyfix.analysis.scope`, :mod:`pyfix.analysis.typo_resolution`)
so the two code paths never disagree with each other.
"""

from __future__ import annotations

import ast
import builtins
from pathlib import Path

from pyfix.analysis.scope import StaticAnalyzer
from pyfix.analysis.typo_resolution import find_typo_candidates
from pyfix.diagnostics.models import Diagnostic, DiagnosticCategory, DiagnosticConfidence, DiagnosticSeverity

_BUILTIN_NAMES = set(dir(builtins))


def check_undefined_variables(analyzer: StaticAnalyzer, file_path: Path) -> list[Diagnostic]:
    """Flag `ast.Name` loads that are not defined anywhere PyFix can see.

    Conservative by construction: it only ever flags a name once it has
    checked module scope, the innermost enclosing function's parameters
    and locals, all imports, all def/class names, and all builtins.
    False negatives (missing a real bug) are preferred over false
    positives (flagging valid code) here.
    """

    diagnostics: list[Diagnostic] = []
    if analyzer.tree is None:
        return diagnostics

    seen_lines: set[tuple[int, str]] = set()

    for node in ast.walk(analyzer.tree):
        if not (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)):
            continue
        name = node.id
        if name in _BUILTIN_NAMES:
            continue

        scope = analyzer.scope_at_line(node.lineno)
        if name in scope.defined_names:
            continue

        key = (node.lineno, name)
        if key in seen_lines:
            continue
        seen_lines.add(key)

        candidates = find_typo_candidates(name, analyzer.all_candidate_names(node.lineno))
        message = f"Undefined variable `{name}`."
        confidence = DiagnosticConfidence.HIGH if candidates.has_single_high_confidence_match else DiagnosticConfidence.MEDIUM
        proposed = ""
        if candidates.has_single_high_confidence_match:
            proposed = f"Did you mean `{candidates.best_match}`?"
        elif candidates.candidates:
            proposed = f"Similar names in scope: {', '.join(candidates.candidates)}."

        diagnostics.append(
            Diagnostic(
                file=file_path,
                line=node.lineno,
                column=node.col_offset,
                category=DiagnosticCategory.UNDEFINED_VARIABLE,
                severity=DiagnosticSeverity.ERROR,
                message=message,
                confidence=confidence,
                what_happened=f'"{name}" is used but never defined in a scope PyFix could find.',
                why_it_happened="No assignment, parameter, import, or definition for this name was found.",
                offending_expression=analyzer.source_line(node.lineno).strip(),
                proposed_fix_summary=proposed,
                safe_to_apply=False,  # static pass never edits; see NameErrorImportDetector for the live-run fix path
            )
        )

    return diagnostics


def check_wrong_argument_counts(analyzer: StaticAnalyzer, file_path: Path) -> list[Diagnostic]:
    """Flag call sites of *locally-defined* functions with an
    unambiguous argument-count mismatch — skips anything with
    ``*args``/``**kwargs`` or keyword arguments, which make static
    counting unreliable.
    """

    diagnostics: list[Diagnostic] = []
    if analyzer.tree is None:
        return diagnostics

    for call in analyzer.call_sites():
        func = analyzer.find_function(call.func_name)
        if func is None:
            continue
        if func.has_varargs() or func.has_kwargs() or call.has_star_args or call.has_star_kwargs:
            continue
        if call.keyword_names:
            continue  # keyword calls are handled by the runtime WrongArgumentsDetector

        required = len(func.required_positional())
        maximum = len(func.all_positional())
        given = call.positional_count

        if required <= given <= maximum:
            continue

        if given < required:
            message = f"{func.name}() called with {given} argument(s) but requires at least {required}."
        else:
            message = f"{func.name}() called with {given} argument(s) but accepts at most {maximum}."

        diagnostics.append(
            Diagnostic(
                file=file_path,
                line=call.lineno,
                column=call.col,
                category=DiagnosticCategory.WRONG_ARGUMENTS,
                severity=DiagnosticSeverity.ERROR,
                message=message,
                confidence=DiagnosticConfidence.CERTAIN,
                what_happened=message,
                why_it_happened=f"{func.name}() is defined at line {func.lineno} with parameters: {', '.join(p.name for p in func.params) or '(none)'}.",
                offending_expression=analyzer.source_line(call.lineno).strip(),
                safe_to_apply=False,
            )
        )

    return diagnostics
