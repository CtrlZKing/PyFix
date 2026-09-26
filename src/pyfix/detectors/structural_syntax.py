"""Detector for the Structural Syntax & Formatting Intelligence subsystem.

Unlike :class:`pyfix.detectors.syntax_errors.SyntaxErrorDetector` (which
never proposes a fix — see that module's docstring for why that used
to be a blanket policy), this detector handles the specific, mechanical
subset of SyntaxError/IndentationError cases that
:mod:`pyfix.analysis.structural` can classify with real confidence: a
missing block colon, a mismatched closing bracket, and the unambiguous
form of a stray indent.

It runs *before* the generic SyntaxErrorDetector/IndentationErrorDetector
in the detector list (see :mod:`pyfix.core.orchestrator`) and falls
through to them (by returning None) for anything it can't classify —
so no existing behavior is lost, it's purely additive.
"""

from __future__ import annotations

import difflib

from pyfix.analysis.structural import StructuralCategory, analyze_structural
from pyfix.core.models import ProposedChange, RepairLevel, RepairProposal, Severity, VerificationPlan
from pyfix.detectors.base import DetectionContext

_CONFIDENCE_LABEL = {
    True: "This is a mechanical, unambiguous repair.",
    False: "PyFix cannot safely invent the missing content automatically.",
}


class StructuralSyntaxDetector:
    name = "structural_syntax"

    def matches(self, ctx: DetectionContext) -> bool:
        return ctx.traceback_info.exception_type in ("SyntaxError", "IndentationError", "TabError")

    def diagnose(self, ctx: DetectionContext) -> RepairProposal | None:
        if not ctx.script_path.exists():
            return None
        try:
            source = ctx.script_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

        finding = analyze_structural(source)
        if finding is None:
            return None  # not a case this subsystem classifies — fall through

        location = f"{ctx.script_path}, line {finding.lineno}"
        explanation = _render_explanation(finding, location)

        if not finding.can_auto_fix or finding.fix_new_content is None:
            return RepairProposal(
                category=f"structural_{finding.category}",
                explanation=explanation,
                confidence_score=finding.confidence,
                risk_level=RepairLevel.EXPLANATION_ONLY,
                severity=Severity.CRITICAL,
                what_happened=finding.what_happened,
                why_it_happened=finding.why_it_happened,
                location=location,
                can_auto_fix=False,
                unresolved_reason=finding.unresolved_reason or "structural_issue_requires_user_judgment",
            )

        diff_text = _make_diff(source, finding.fix_new_content, ctx.script_path.name)

        return RepairProposal(
            category=f"structural_{finding.category}",
            explanation=explanation,
            confidence_score=finding.confidence,
            risk_level=RepairLevel.SAFE_SUGGESTION,
            severity=Severity.CRITICAL,
            affected_files=[ctx.script_path],
            proposed_changes=[
                ProposedChange(
                    file_path=ctx.script_path,
                    description=finding.fix_description,
                    diff_text=diff_text,
                    new_content=finding.fix_new_content,
                )
            ],
            what_happened=finding.what_happened,
            why_it_happened=finding.why_it_happened,
            location=location,
            can_auto_fix=True,
            verification_plan=VerificationPlan(
                description="Parse the edited file to confirm it's still valid, then re-run the program.",
                rerun_target=ctx.script_path,
            ),
        )


def _render_explanation(finding, location: str) -> str:
    lines = [
        "❌ Structural syntax issue",
        "",
        finding.what_happened,
        "",
        finding.why_it_happened,
        "",
        f"Location: {location}",
    ]
    if finding.evidence:
        lines.append("")
        lines.append("Evidence:")
        lines.extend(f"    - {e}" for e in finding.evidence)
    lines.append("")
    if finding.can_auto_fix:
        lines.append(f"Proposed fix: {finding.fix_description}")
        lines.append(f"Confidence: {finding.confidence:.0%}")
    else:
        lines.append(_CONFIDENCE_LABEL[False])
        if finding.category == StructuralCategory.UNCLOSED_BRACKET:
            lines.append("PyFix does not guess where a missing closing bracket should go.")
        elif finding.category == StructuralCategory.MISSING_BLOCK_BODY:
            lines.append("Add the statement(s) this block is supposed to contain.")
    return "\n".join(lines)


def _make_diff(old_source: str, new_source: str, file_name: str) -> str:
    diff = difflib.unified_diff(
        old_source.splitlines(),
        new_source.splitlines(),
        fromfile=file_name,
        tofile=file_name,
        lineterm="",
    )
    return "\n".join(diff)
