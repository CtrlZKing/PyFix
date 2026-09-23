"""Detector for FileNotFoundError, with a safe "did you mean" suggestion.

PyFix never changes a path automatically — it only searches the
project directory for similarly-named files and proposes them for the
user to choose.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path

from pyfix.core.models import RepairLevel, RepairProposal, Severity
from pyfix.detectors.base import DetectionContext

_FNF_RE = re.compile(r"\[Errno 2\] No such file or directory: ['\"](.+?)['\"]")


class FileNotFoundDetector:
    name = "file_not_found"

    def matches(self, ctx: DetectionContext) -> bool:
        tb = ctx.traceback_info
        return tb.exception_type == "FileNotFoundError"

    def diagnose(self, ctx: DetectionContext) -> RepairProposal | None:
        tb = ctx.traceback_info
        match = _FNF_RE.search(tb.message)
        missing_path = match.group(1) if match else tb.message

        candidates = _find_similar_files(Path(missing_path).name, ctx.project_root)

        location = f"{tb.last_frame.file}, line {tb.last_frame.line}" if tb.last_frame else ""

        suggestion_text = ""
        if candidates:
            rel = [str(c.relative_to(ctx.project_root)) for c in candidates[:3]]
            suggestion_text = "\n\nDid you mean:\n\n" + "\n".join(f"    {r}" for r in rel)

        return RepairProposal(
            category="file_not_found",
            explanation=(
                f'I couldn\'t find "{missing_path}".{suggestion_text}\n\n'
                "PyFix does not change file paths automatically — "
                "update the path in your code if one of these matches."
            ),
            confidence_score=0.7 if candidates else 0.3,
            risk_level=RepairLevel.EXPLANATION_ONLY,
            severity=Severity.ERROR,
            what_happened=f'Your program tried to open "{missing_path}", which does not exist.',
            why_it_happened="This is usually a wrong relative path or a typo in the filename.",
            location=location,
            can_auto_fix=False,
            unresolved_reason="file_path_changes_require_manual_choice",
        )


def _find_similar_files(target_name: str, project_root: Path, max_results: int = 3) -> list[Path]:
    if not target_name or not project_root.exists():
        return []

    all_files = [p for p in project_root.rglob("*") if p.is_file() and ".venv" not in p.parts and ".git" not in p.parts]
    names = {str(p): p.name for p in all_files}

    close = difflib.get_close_matches(target_name, list(names.values()), n=max_results, cutoff=0.6)
    result = []
    seen = set()
    for p in all_files:
        if p.name in close and p.name not in seen:
            result.append(p)
            seen.add(p.name)
    return result
