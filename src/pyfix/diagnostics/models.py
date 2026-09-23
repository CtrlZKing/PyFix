"""The Level-2 diagnostic model.

A :class:`Diagnostic` is PyFix's unit of static/runtime analysis
output — deliberately separate from :class:`pyfix.core.models.RepairProposal`
(the V1 execution-pipeline object). Many diagnostics never become a
repair proposal at all (e.g. "unreachable code", "possible IndexError")
because PyFix has nothing safe to *do* about them — it can only
explain them. A :class:`Diagnostic` may optionally carry a
``proposed_fix`` (itself a :class:`pyfix.core.models.RepairProposal`)
when, and only when, PyFix is confident enough to act.

This keeps the existing V1 pipeline (detect -> propose -> permission ->
execute -> verify, all built around ``RepairProposal``) completely
intact; Level-2 analysis is additive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class DiagnosticConfidence(Enum):
    """Five-tier confidence, per the Level-2 spec.

    This is intentionally a different (finer-grained) scale than
    :class:`pyfix.core.models.Confidence` (HIGH/MEDIUM/LOW), which
    remains used by the original V1 RepairProposal display. Mapping
    between the two happens only at the point a Diagnostic produces a
    RepairProposal (see :mod:`pyfix.repairs.proposal_builder`).
    """

    CERTAIN = "CERTAIN"   # deterministic: derived from language rules, not a guess
    HIGH = "HIGH"         # very likely correct; safe to propose a fix
    MEDIUM = "MEDIUM"     # plausible; propose but require explicit approval
    LOW = "LOW"           # heuristic; explain only, unless user opts into experimental fixes
    UNKNOWN = "UNKNOWN"   # detected something is wrong, but no safe diagnosis

    def allows_default_proposal(self) -> bool:
        """Whether PyFix may show an actionable [Y/N] fix by default."""

        return self in (DiagnosticConfidence.CERTAIN, DiagnosticConfidence.HIGH, DiagnosticConfidence.MEDIUM)


class DiagnosticSeverity(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class DiagnosticCategory(Enum):
    SYNTAX = "syntax"
    UNDEFINED_VARIABLE = "undefined_variable"
    WRONG_ARGUMENTS = "wrong_arguments"
    TYPE_MISMATCH = "type_mismatch"
    CONTROL_FLOW = "control_flow"
    INDEXING = "indexing"
    ATTRIBUTE_USAGE = "attribute_usage"
    IMPORT = "import"
    ENVIRONMENT = "environment"
    OTHER = "other"


@dataclass
class Evidence:
    """A single fact PyFix used to reach a diagnosis — shown on request,
    not by default, so beginners aren't overwhelmed (Level-2 spec §15)."""

    description: str


@dataclass
class Diagnostic:
    """One finding, from one line of one file, with everything needed
    to explain it and, optionally, fix it.
    """

    file: Path
    line: int
    category: DiagnosticCategory
    severity: DiagnosticSeverity
    message: str
    confidence: DiagnosticConfidence

    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None

    what_happened: str = ""
    why_it_happened: str = ""
    offending_expression: str = ""
    source_context: list[str] = field(default_factory=list)

    evidence: list[Evidence] = field(default_factory=list)
    proposed_fix_summary: str = ""
    safe_to_apply: bool = False

    # Populated only when safe_to_apply is True — see
    # pyfix.repairs.proposal_builder for how this becomes an
    # executable RepairProposal.
    fix_diff: str = ""
    fix_new_content: str | None = None

    def location_label(self) -> str:
        loc = f"{self.file}:{self.line}"
        if self.column is not None:
            loc += f":{self.column}"
        return loc
