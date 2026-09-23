"""Plain-text terminal rendering for PyFix.

Kept dependency-free (no third-party TUI library required) so PyFix's
core workflow works in any terminal, including the plain Windows
Command Prompt.
"""

from __future__ import annotations

from pyfix.core.models import Command, RepairOutcome, RepairProposal


def banner() -> str:
    return (
        "┌───────────────────────────────────────────┐\n"
        "│ PYFIX                                      │\n"
        "│ Python repair assistant                    │\n"
        "└───────────────────────────────────────────┘"
    )


def render_proposal(proposal: RepairProposal, beginner: bool = False) -> str:
    lines = [proposal.explanation]

    if proposal.what_happened:
        lines.append("")
        lines.append("What happened?")
        lines.append("")
        lines.append(f"    {proposal.what_happened}")

    if not beginner and proposal.why_it_happened:
        lines.append("")
        lines.append(f"Why: {proposal.why_it_happened}")

    if proposal.location:
        lines.append("")
        lines.append(f"Location: {proposal.location}")

    for change in proposal.proposed_changes:
        if change.diff_text:
            lines.append("")
            lines.append("Proposed change:")
            lines.append("")
            lines.append(change.diff_text)

    for command in proposal.commands:
        lines.append("")
        lines.append("Command PyFix will execute:")
        lines.append("")
        lines.append(f"    {command.display()}")

    lines.append("")
    lines.append(f"Confidence: {proposal.confidence.value} ({proposal.confidence_score:.0%})")

    if proposal.can_auto_fix:
        lines.append("")
        lines.append("Apply this fix?")
        lines.append("")
        lines.append("    [Y] Yes")
        lines.append("    [N] No")
        lines.append("    [D] Show details")
        lines.append("    [C] Cancel")
    else:
        lines.append("")
        lines.append("PyFix cannot safely automate this. See the explanation above.")

    return "\n".join(lines)


def render_outcome(outcome: RepairOutcome) -> str:
    if outcome.fully_resolved:
        return "✓ Problem fixed\n✓ Program started successfully"
    if not outcome.executed:
        return f"No changes were made. {outcome.detail}"
    if outcome.executed and not outcome.execution_succeeded:
        return f"✗ The fix could not be applied: {outcome.detail}"
    if outcome.executed and outcome.execution_succeeded and not outcome.verified:
        return (
            "⚠ The original problem was resolved, but the program encountered "
            f"another error:\n\n{outcome.detail}"
        )
    return outcome.detail


def render_doctor_report(lines: list[str]) -> str:
    header = "PYFIX PROJECT DOCTOR\n" + "─" * 37
    return "\n".join([header, "", *lines])
