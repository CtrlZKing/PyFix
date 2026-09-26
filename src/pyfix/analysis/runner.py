"""Run every static (no-execution) check against one file and return a
single, ordered list of diagnostics — the "multi-diagnostic reporting"
entry point used by ``pyfix analyze`` and folded into ``pyfix doctor``.
"""

from __future__ import annotations

from pathlib import Path

from pyfix.analysis import level2_checks as checks
from pyfix.analysis.scope import StaticAnalyzer
from pyfix.analysis.static_call_checks import check_undefined_variables, check_wrong_argument_counts
from pyfix.analysis.structural import analyze_structural, structural_finding_to_diagnostic
from pyfix.diagnostics.models import Diagnostic


def run_static_analysis(source: str, file_path: Path) -> list[Diagnostic]:
    analyzer = StaticAnalyzer(source)
    if not analyzer.is_valid:
        # The file doesn't parse at all, so none of the checks below
        # (which all need a valid AST) can run. That used to mean
        # "report nothing" — instead, hand off to the structural
        # analyzer so a whole-file scan still surfaces *something*
        # actionable instead of going silent on the first SyntaxError.
        finding = analyze_structural(source)
        if finding is not None:
            return [structural_finding_to_diagnostic(finding, file_path)]
        return []

    tree = analyzer.tree
    lines = source.splitlines()

    diagnostics: list[Diagnostic] = []
    diagnostics += check_undefined_variables(analyzer, file_path)
    diagnostics += check_wrong_argument_counts(analyzer, file_path)
    diagnostics += checks.check_unreachable_code(tree, file_path, lines)
    diagnostics += checks.check_break_continue_outside_loop(tree, file_path, lines)
    diagnostics += checks.check_constant_conditions(tree, file_path, lines)
    diagnostics += checks.check_static_index_bounds(tree, file_path, lines)
    diagnostics += checks.check_obvious_type_mismatches(tree, file_path, lines)

    diagnostics.sort(key=lambda d: d.line)
    return diagnostics
