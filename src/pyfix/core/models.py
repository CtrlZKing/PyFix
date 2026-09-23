"""Core data model for PyFix's repair pipeline.

Every repair — no matter which detector produced it — is represented
as a :class:`RepairProposal`. This is the single object that flows
through: Detection -> Diagnosis -> Confidence -> Proposed action ->
Permission -> Execution -> Verification.

Nothing outside :mod:`pyfix.execution` and :mod:`pyfix.source` is
allowed to touch the filesystem, the network, or a subprocess. Every
other part of the codebase only ever produces or reads a
``RepairProposal``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class RepairLevel(Enum):
    """How intrusive a proposed repair is."""

    EXPLANATION_ONLY = 0          # Level 0: no modification at all
    SAFE_SUGGESTION = 1           # Level 1: e.g. add a missing import
    SAFE_ENVIRONMENT_OP = 2       # Level 2: e.g. install a package
    PROJECT_MODIFICATION = 3      # Level 3: e.g. edit requirements.txt
    DESTRUCTIVE = 4               # Level 4: deleting things, never automatic


class Severity(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Confidence(Enum):
    """Coarse confidence bucket, always paired with a numeric score."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @staticmethod
    def from_score(score: float) -> "Confidence":
        if score >= 0.85:
            return Confidence.HIGH
        if score >= 0.5:
            return Confidence.MEDIUM
        return Confidence.LOW


@dataclass
class ProposedChange:
    """A single, specific, diff-able change to one file."""

    file_path: Path
    description: str
    diff_text: str = ""
    new_content: str | None = None  # full new file content, when applicable


@dataclass
class Command:
    """A single command PyFix intends to execute.

    Commands are always represented as an argv list — never a shell
    string — so they can be executed safely with ``shell=False`` and
    displayed to the user exactly as they will run.
    """

    argv: list[str]
    description: str = ""
    cwd: Path | None = None

    def display(self) -> str:
        return " ".join(_quote(part) for part in self.argv)


def _quote(part: str) -> str:
    if " " in part or "" == part:
        return f'"{part}"'
    return part


@dataclass
class VerificationPlan:
    """How PyFix will confirm a repair actually worked."""

    description: str
    rerun_target: Path | None = None  # re-run this script after the fix


@dataclass
class RepairProposal:
    """A fully-specified, not-yet-executed repair.

    This is the object the UI shows to the user, and the only object
    the execution layer is allowed to act on — and only after the
    user has explicitly approved it.
    """

    category: str
    explanation: str
    confidence_score: float
    risk_level: RepairLevel
    severity: Severity = Severity.ERROR
    affected_files: list[Path] = field(default_factory=list)
    proposed_changes: list[ProposedChange] = field(default_factory=list)
    commands: list[Command] = field(default_factory=list)
    verification_plan: VerificationPlan | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    what_happened: str = ""
    why_it_happened: str = ""
    location: str = ""
    can_auto_fix: bool = False
    unresolved_reason: str = ""

    @property
    def confidence(self) -> Confidence:
        return Confidence.from_score(self.confidence_score)

    def requires_extra_confirmation(self) -> bool:
        return self.risk_level == RepairLevel.DESTRUCTIVE


@dataclass
class RepairOutcome:
    """The truthful result of attempting a RepairProposal.

    PyFix must never claim success it did not verify. This object is
    the only source of truth for the "✓ Fixed" / "✗ Failed" messages.
    """

    proposal: RepairProposal
    executed: bool
    execution_succeeded: bool
    verified: bool
    detail: str = ""
    backup_path: Path | None = None

    @property
    def fully_resolved(self) -> bool:
        return self.executed and self.execution_succeeded and self.verified
