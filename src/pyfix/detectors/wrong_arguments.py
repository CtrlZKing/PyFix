"""Detector for wrong-argument-count / wrong-keyword TypeErrors.

Python's own TypeError messages for these cases are already precise
("takes 2 positional arguments but 3 were given", "missing 1 required
positional argument: 'tax'", "got an unexpected keyword argument
'taxes'"). This detector parses that message, locates the call site
via the traceback line, and cross-references the *local* function
definition (if PyFix can find it in the same file) to explain exactly
what's wrong.

Per the Level-2 spec, PyFix never invents a missing argument's value
and never silently drops an extra one — those stay explanation-only.
The one case with an unambiguous, safe repair is a keyword-argument
*name* typo with a single close match to a real parameter name.
"""

from __future__ import annotations

import re

from pyfix.analysis.scope import StaticAnalyzer
from pyfix.analysis.typo_resolution import find_typo_candidates
from pyfix.core.models import ProposedChange, RepairLevel, RepairProposal, Severity, VerificationPlan
from pyfix.detectors.base import DetectionContext
from pyfix.diagnostics.models import DiagnosticConfidence
from pyfix.source.rename_editor import build_rename_edit

_TOO_MANY_RE = re.compile(r"takes (?:from \d+ to )?(\d+) positional arguments? but (\d+)(?: positional arguments?)? (?:was|were) given")
_MISSING_RE = re.compile(r"missing (\d+) required (?:positional|keyword-only) arguments?: (.+)")
_UNEXPECTED_KW_RE = re.compile(r"got an unexpected keyword argument ['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]")
_MULTIPLE_VALUES_RE = re.compile(r"got multiple values for argument ['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]")
_FUNC_NAME_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.]*)\(\)")


class WrongArgumentsDetector:
    """Explains (and, for keyword typos, safely fixes) call-site TypeErrors."""

    name = "wrong_arguments"

    def matches(self, ctx: DetectionContext) -> bool:
        tb = ctx.traceback_info
        if tb.exception_type != "TypeError":
            return False
        return bool(
            _TOO_MANY_RE.search(tb.message)
            or _MISSING_RE.search(tb.message)
            or _UNEXPECTED_KW_RE.search(tb.message)
            or _MULTIPLE_VALUES_RE.search(tb.message)
        )

    def diagnose(self, ctx: DetectionContext) -> RepairProposal | None:
        tb = ctx.traceback_info
        if not ctx.script_path.exists() or tb.last_frame is None:
            return None

        source = ctx.script_path.read_text(encoding="utf-8")
        analyzer = StaticAnalyzer(source)
        if not analyzer.is_valid:
            return None

        lineno = tb.last_frame.line
        call = analyzer.call_at_line(lineno)
        func_name_match = _FUNC_NAME_RE.match(tb.message)
        func_name = func_name_match.group(1).split(".")[-1] if func_name_match else (call.func_name if call else None)

        func_info = analyzer.find_function(func_name) if func_name else None
        location = f"{tb.last_frame.file}, line {lineno}"
        offending = analyzer.source_line(lineno).strip()

        kw_match = _UNEXPECTED_KW_RE.search(tb.message)
        if kw_match and func_info is not None:
            proposal = self._diagnose_unexpected_keyword(ctx, source, analyzer, func_info, kw_match.group(1), lineno, location, offending)
            if proposal is not None:
                return proposal

        too_many = _TOO_MANY_RE.search(tb.message)
        if too_many:
            expected, given = too_many.group(1), too_many.group(2)
            return self._explanation_only(
                category="too_many_arguments",
                explanation=(
                    f"❌ Wrong number of arguments\n\n"
                    f"Line {lineno}:\n    {offending}\n\n"
                    f"{func_name or 'This function'}() was called with {given} positional "
                    f"argument(s), but it takes {expected}."
                ),
                what_happened=f"{func_name or 'The function'}() received too many positional arguments.",
                why_it_happened=tb.message,
                location=location,
                confidence=0.95,
            )

        missing = _MISSING_RE.search(tb.message)
        if missing:
            missing_names = missing.group(2)
            return self._explanation_only(
                category="missing_arguments",
                explanation=(
                    f"❌ Missing required argument(s)\n\n"
                    f"Line {lineno}:\n    {offending}\n\n"
                    f"{func_name or 'This function'}() is missing required argument(s): {missing_names}.\n\n"
                    "PyFix cannot safely guess what value to pass, so this is not "
                    "auto-fixed."
                ),
                what_happened=f"{func_name or 'The function'}() call is missing required argument(s).",
                why_it_happened=tb.message,
                location=location,
                confidence=0.95,
            )

        if kw_match:
            return self._explanation_only(
                category="unexpected_keyword",
                explanation=(
                    f"❌ Unexpected keyword argument\n\n"
                    f"Line {lineno}:\n    {offending}\n\n"
                    f"`{kw_match.group(1)}` is not a recognized keyword argument here."
                ),
                what_happened=f"'{kw_match.group(1)}' is not a parameter PyFix could locate a definition for.",
                why_it_happened=tb.message,
                location=location,
                confidence=0.6,
            )

        multi = _MULTIPLE_VALUES_RE.search(tb.message)
        if multi:
            return self._explanation_only(
                category="duplicate_argument",
                explanation=(
                    f"❌ Duplicate argument\n\n"
                    f"Line {lineno}:\n    {offending}\n\n"
                    f"`{multi.group(1)}` was supplied both positionally and as a keyword argument."
                ),
                what_happened=f"'{multi.group(1)}' was given a value twice in the same call.",
                why_it_happened=tb.message,
                location=location,
                confidence=0.95,
            )

        return None

    def _diagnose_unexpected_keyword(self, ctx, source, analyzer, func_info, bad_kw, lineno, location, offending):
        candidates = find_typo_candidates(bad_kw, set(func_info.keyword_names()))
        if candidates.confidence != DiagnosticConfidence.HIGH or candidates.best_match is None:
            return None

        correct_kw = candidates.best_match
        edit = build_rename_edit(source, lineno, bad_kw, correct_kw, file_name=ctx.script_path.name)
        if edit is None:
            return None

        explanation = (
            f"❌ Unexpected keyword argument\n\n"
            f"Line {lineno}:\n    {offending}\n\n"
            f"`{bad_kw}` is not a parameter of {func_info.name}().\n\n"
            f"Did you mean:\n\n    {correct_kw}\n\n"
            "Confidence: HIGH"
        )

        return RepairProposal(
            category="unexpected_keyword_typo",
            explanation=explanation,
            confidence_score=0.9,
            risk_level=RepairLevel.SAFE_SUGGESTION,
            severity=Severity.ERROR,
            affected_files=[ctx.script_path],
            proposed_changes=[
                ProposedChange(
                    file_path=ctx.script_path,
                    description=f'Rename keyword argument "{bad_kw}" to "{correct_kw}" on line {lineno}.',
                    diff_text=edit.diff_text,
                    new_content=edit.new_content,
                )
            ],
            what_happened=f'"{bad_kw}" is not a parameter of {func_info.name}().',
            why_it_happened=f'"{correct_kw}" is a defined parameter of {func_info.name}() and closely matches "{bad_kw}".',
            location=location,
            can_auto_fix=True,
            verification_plan=VerificationPlan(
                description="Parse the edited file to confirm it's still valid, then re-run the program.",
                rerun_target=ctx.script_path,
            ),
        )

    def _explanation_only(self, category, explanation, what_happened, why_it_happened, location, confidence):
        return RepairProposal(
            category=category,
            explanation=explanation,
            confidence_score=confidence,
            risk_level=RepairLevel.EXPLANATION_ONLY,
            severity=Severity.ERROR,
            what_happened=what_happened,
            why_it_happened=why_it_happened,
            location=location,
            can_auto_fix=False,
            unresolved_reason="requires_human_judgment",
        )
