"""Detector for NameError caused by a forgotten `import` OR a typo'd name.

Not every NameError is a missing import — a typo'd variable name is
also a NameError. This detector first checks whether the undefined
name is used the way a module is used (``name.attr``) and plausibly
maps to an installable package; if that's not confident, it falls back
to scope-aware "did you mean...?" typo resolution (Level-2) before
finally giving up and reporting an explanation-only "possible problem."
"""

from __future__ import annotations

import re

from pyfix.analysis.scope import StaticAnalyzer
from pyfix.analysis.typo_resolution import find_typo_candidates
from pyfix.core.models import (
    Confidence,
    ProposedChange,
    RepairLevel,
    RepairProposal,
    Severity,
    VerificationPlan,
)
from pyfix.detectors.base import DetectionContext
from pyfix.diagnostics.models import DiagnosticConfidence
from pyfix.packages.resolver import resolve_package
from pyfix.source.ast_utils import SourceAnalysis
from pyfix.source.import_editor import build_add_import_edit
from pyfix.source.rename_editor import build_rename_edit

_NAME_RE = re.compile(r"name ['\"]([A-Za-z_][A-Za-z0-9_]*)['\"] is not defined")


class NameErrorImportDetector:
    name = "name_error_missing_import"

    def matches(self, ctx: DetectionContext) -> bool:
        tb = ctx.traceback_info
        return tb.exception_type == "NameError" and bool(_NAME_RE.search(tb.message))

    def diagnose(self, ctx: DetectionContext) -> RepairProposal | None:
        tb = ctx.traceback_info
        match = _NAME_RE.search(tb.message)
        if not match:
            return None

        undefined_name = match.group(1)

        if not ctx.script_path.exists():
            return None

        source = ctx.script_path.read_text(encoding="utf-8")
        analysis = SourceAnalysis(source)

        if not analysis.is_valid:
            return None  # let the SyntaxError detector handle this file

        already_imported = undefined_name in analysis.top_level_names_bound_by_imports()
        if already_imported:
            # Not actually a missing import; something else is going on.
            return None

        used_as_module = analysis.is_name_used_as_module(undefined_name)
        assigned_elsewhere = analysis.is_name_assigned(undefined_name)

        resolution = resolve_package(undefined_name)

        # Confidence combines: (a) is it used like a module, (b) do we
        # recognize it as an installable package, (c) is it NOT also
        # assigned as a local variable somewhere (which would suggest
        # a typo/ordering bug rather than a missing import).
        import_score = 0.0
        if used_as_module:
            import_score += 0.5
        if resolution.resolved and resolution.source != "unknown":
            import_score += 0.4
        if assigned_elsewhere:
            import_score -= 0.4
        import_score = max(0.0, min(import_score, 0.97))

        location = ""
        if tb.last_frame:
            location = f"{tb.last_frame.file}, line {tb.last_frame.line}"

        if import_score >= 0.5:
            edit = build_add_import_edit(source, undefined_name, file_name=ctx.script_path.name)

            explanation = (
                "❌ Missing import\n\n"
                f"Your code uses:\n\n    {undefined_name}\n\n"
                f"but {undefined_name} has not been imported.\n\n"
                f"PyFix suggests adding:\n\n    import {undefined_name}\n\n"
                f"to the beginning of {ctx.script_path.name}."
            )

            return RepairProposal(
                category="missing_import",
                explanation=explanation,
                confidence_score=import_score,
                risk_level=RepairLevel.SAFE_SUGGESTION,
                severity=Severity.ERROR,
                affected_files=[ctx.script_path],
                proposed_changes=[
                    ProposedChange(
                        file_path=ctx.script_path,
                        description=f"Add 'import {undefined_name}' at line {edit.insert_line}.",
                        diff_text=edit.diff_text,
                        new_content=edit.new_content,
                    )
                ],
                what_happened=f'"{undefined_name}" is used but was never imported.',
                why_it_happened=f'"{undefined_name}" is used like a module (e.g. "{undefined_name}.something()").',
                location=location,
                can_auto_fix=True,
                verification_plan=VerificationPlan(
                    description="Parse the edited file to confirm it's still valid, then re-run the program.",
                    rerun_target=ctx.script_path,
                ),
            )

        # Not confidently a missing import — try scope-aware typo
        # resolution before giving up (Level-2 §3).
        if tb.last_frame is not None:
            typo_proposal = self._diagnose_as_typo(ctx, source, undefined_name, tb.last_frame.line, location)
            if typo_proposal is not None:
                return typo_proposal

        return RepairProposal(
            category="name_error_uncertain",
            explanation=(
                f'⚠ Possible problem\n\n"{undefined_name}" is not defined, but PyFix '
                "is not confident enough that this is a missing import or a typo "
                "to modify your code automatically."
            ),
            confidence_score=max(import_score, 0.0),
            risk_level=RepairLevel.EXPLANATION_ONLY,
            severity=Severity.ERROR,
            what_happened=f'"{undefined_name}" was used but never defined.',
            why_it_happened="This could be a typo, a missing import, or a variable used before assignment.",
            location=location,
            can_auto_fix=False,
            unresolved_reason="low_confidence",
        )

    def _diagnose_as_typo(
        self, ctx: DetectionContext, source: str, undefined_name: str, lineno: int, location: str
    ) -> RepairProposal | None:
        analyzer = StaticAnalyzer(source)
        if not analyzer.is_valid:
            return None

        candidates_pool = analyzer.all_candidate_names(lineno)
        result = find_typo_candidates(undefined_name, candidates_pool)

        if result.confidence == DiagnosticConfidence.UNKNOWN:
            return None  # nothing close enough to even mention

        if result.confidence != DiagnosticConfidence.HIGH or result.best_match is None:
            # Plausible candidates exist, but not confidently enough to
            # act on — explain, list them, do not modify anything.
            candidate_list = ", ".join(result.candidates)
            return RepairProposal(
                category="undefined_variable_ambiguous",
                explanation=(
                    f'⚠ Possible typo\n\nLine referenced "{undefined_name}", which is not defined.\n\n'
                    f"PyFix found similar names nearby ({candidate_list}) but is not confident "
                    "enough to pick one automatically."
                ),
                confidence_score=0.4,
                risk_level=RepairLevel.EXPLANATION_ONLY,
                severity=Severity.ERROR,
                what_happened=f'"{undefined_name}" is undefined and could be a typo.',
                why_it_happened=f"Multiple similarly-named identifiers are in scope: {candidate_list}.",
                location=location,
                can_auto_fix=False,
                unresolved_reason="ambiguous_typo_candidates",
            )

        candidate = result.best_match
        edit = build_rename_edit(source, lineno, undefined_name, candidate, file_name=ctx.script_path.name)
        if edit is None:
            return None

        explanation = (
            f"❌ Undefined variable `{undefined_name}`\n\n"
            f"Did you mean:\n\n    {candidate}\n\n"
            "Confidence: HIGH"
        )

        return RepairProposal(
            category="undefined_variable_typo",
            explanation=explanation,
            confidence_score=0.9,
            risk_level=RepairLevel.SAFE_SUGGESTION,
            severity=Severity.ERROR,
            affected_files=[ctx.script_path],
            proposed_changes=[
                ProposedChange(
                    file_path=ctx.script_path,
                    description=f'Replace "{undefined_name}" with "{candidate}" on line {lineno}.',
                    diff_text=edit.diff_text,
                    new_content=edit.new_content,
                )
            ],
            what_happened=f'"{undefined_name}" is not defined anywhere in scope.',
            why_it_happened=f'"{candidate}" is a very close match already defined nearby — this is likely a typo.',
            location=location,
            can_auto_fix=True,
            verification_plan=VerificationPlan(
                description="Parse the edited file to confirm it's still valid, then re-run the program.",
                rerun_target=ctx.script_path,
            ),
        )
