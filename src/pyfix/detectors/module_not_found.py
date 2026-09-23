"""Detector for ModuleNotFoundError / ImportError (missing package)."""

from __future__ import annotations

import re

from pyfix.core.models import (
    Command,
    Confidence,
    ProposedChange,
    RepairLevel,
    RepairProposal,
    Severity,
    VerificationPlan,
)
from pyfix.detectors.base import DetectionContext
from pyfix.execution.pip import build_install_command
from pyfix.packages.resolver import resolve_package

_MODULE_RE = re.compile(r"No module named ['\"]([A-Za-z0-9_.]+)['\"]")


class ModuleNotFoundDetector:
    name = "module_not_found"

    def matches(self, ctx: DetectionContext) -> bool:
        tb = ctx.traceback_info
        return tb.exception_type in ("ModuleNotFoundError", "ImportError") and bool(
            _MODULE_RE.search(tb.message)
        )

    def diagnose(self, ctx: DetectionContext) -> RepairProposal | None:
        tb = ctx.traceback_info
        match = _MODULE_RE.search(tb.message)
        if not match:
            return None

        import_name = match.group(1)
        resolution = resolve_package(import_name)

        location = ""
        if tb.last_frame:
            location = f"{tb.last_frame.file}, line {tb.last_frame.line}"

        # Only auto-propose an install for a package name PyFix is
        # actually confident about (verified mapping or installed
        # metadata elsewhere). A bare heuristic guess ("this identifier
        # might also be its own PyPI name") is not confident enough to
        # act on automatically — see "Never guess package names blindly".
        CONFIDENT_THRESHOLD = 0.7
        if not resolution.resolved or resolution.confidence_score < CONFIDENT_THRESHOLD:
            return RepairProposal(
                category="missing_package_unknown",
                explanation=(
                    f'I found the missing import "{import_name}".\n\n'
                    "I could not safely determine which package provides it.\n"
                    "I will not install an unknown package automatically.\n\n"
                    "You can specify the package manually."
                ),
                confidence_score=resolution.confidence_score,
                risk_level=RepairLevel.EXPLANATION_ONLY,
                severity=Severity.ERROR,
                what_happened=f'Your program tried to import "{import_name}", which is not installed.',
                why_it_happened="PyFix has no verified mapping from this import name to a PyPI package.",
                location=location,
                can_auto_fix=False,
                unresolved_reason="unknown_package_mapping",
            )

        package_name = resolution.distribution_name
        assert package_name is not None

        install_cmd = build_install_command(package_name, ctx.python_executable)

        explanation = (
            "❌ Missing Python package\n\n"
            f"Your program tried to import:\n\n    {import_name}\n\n"
            f"But {import_name} is not installed in the Python environment "
            "currently running this program."
        )

        return RepairProposal(
            category="missing_package",
            explanation=explanation,
            confidence_score=resolution.confidence_score,
            risk_level=RepairLevel.SAFE_ENVIRONMENT_OP,
            severity=Severity.ERROR,
            commands=[install_cmd],
            what_happened=f'Python tried to load "{import_name}", but it isn\'t installed.',
            why_it_happened=(
                f'The import name "{import_name}" maps to the PyPI package '
                f'"{package_name}" ({resolution.source}), which is missing from '
                "this environment."
            ),
            location=location,
            can_auto_fix=True,
            verification_plan=VerificationPlan(
                description=f"Re-run the program and confirm '{import_name}' now imports successfully.",
                rerun_target=ctx.script_path,
            ),
        )
