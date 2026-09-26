"""Fallback, explanation-only detectors for Syntax/Indentation/Tab errors.

As of 3.0, the small set of SyntaxError/IndentationError shapes PyFix
can classify with real confidence (missing block colon, mismatched
bracket, unambiguous stray indent) are handled *before* these by
:class:`pyfix.detectors.structural_syntax.StructuralSyntaxDetector`,
which can propose an actual repair. These detectors are the fallback
for everything else — PyFix still refuses to guess at ambiguous or
unclassified syntax problems, because that would be exactly the kind
of "reckless automatic code modifier" behavior the product explicitly
rejects. They exist to turn a cryptic pointer-and-caret traceback into
a plain-English explanation with a precise location.
"""

from __future__ import annotations

from pyfix.core.models import RepairLevel, RepairProposal, Severity
from pyfix.detectors.base import DetectionContext


class SyntaxErrorDetector:
    name = "syntax_error"

    def matches(self, ctx: DetectionContext) -> bool:
        return ctx.traceback_info.exception_type == "SyntaxError"

    def diagnose(self, ctx: DetectionContext) -> RepairProposal | None:
        tb = ctx.traceback_info
        location = f"{tb.last_frame.file}, line {tb.last_frame.line}" if tb.last_frame else "unknown location"
        return RepairProposal(
            category="syntax_error",
            explanation=(
                "❌ Syntax error\n\n"
                f"Python could not parse your code: {tb.message}\n\n"
                f"Location: {location}\n\n"
                "PyFix does not automatically rewrite broken syntax — "
                "please fix the line indicated above."
            ),
            confidence_score=0.9,
            risk_level=RepairLevel.EXPLANATION_ONLY,
            severity=Severity.CRITICAL,
            what_happened="Python couldn't understand the structure of your code at this location.",
            why_it_happened=tb.message or "A syntax rule was violated (e.g. a missing colon or bracket).",
            location=location,
            can_auto_fix=False,
            unresolved_reason="syntax_errors_are_not_auto_fixed",
        )


class IndentationErrorDetector:
    name = "indentation_error"

    def matches(self, ctx: DetectionContext) -> bool:
        return ctx.traceback_info.exception_type in ("IndentationError", "TabError")

    def diagnose(self, ctx: DetectionContext) -> RepairProposal | None:
        tb = ctx.traceback_info
        location = f"{tb.last_frame.file}, line {tb.last_frame.line}" if tb.last_frame else "unknown location"
        is_tab = tb.exception_type == "TabError"
        return RepairProposal(
            category="tab_error" if is_tab else "indentation_error",
            explanation=(
                f"❌ {'Inconsistent tabs/spaces' if is_tab else 'Indentation error'}\n\n"
                f"{tb.message}\n\nLocation: {location}\n\n"
                "Python uses indentation to define code blocks — check that this "
                "line lines up with the block it belongs to, and that you aren't "
                "mixing tabs and spaces."
            ),
            confidence_score=0.9,
            risk_level=RepairLevel.EXPLANATION_ONLY,
            severity=Severity.ERROR,
            what_happened="The indentation of this line doesn't match what Python expected.",
            why_it_happened=tb.message,
            location=location,
            can_auto_fix=False,
            unresolved_reason="indentation_is_not_auto_fixed",
        )
