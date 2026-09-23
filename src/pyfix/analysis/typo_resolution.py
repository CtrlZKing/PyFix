"""Shared "did you mean...?" logic for identifier typos.

Used by both the undefined-variable detector and the unexpected-
keyword-argument detector so the same confidence rules apply
everywhere: a single, very close candidate is HIGH confidence; several
plausible candidates, or one only loosely similar, is LOW confidence
and explanation-only; nothing close is UNKNOWN.

Edit distance (not just a similarity ratio) is used as the primary
signal: identifier typos are usually one or two character edits away
from the intended name (a transposition, a missing/extra letter, a
pluralization slip like ``tax`` -> ``taxes``), and a plain ratio
under-scores exactly these short-string cases.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

from pyfix.diagnostics.models import DiagnosticConfidence

LOW_CONFIDENCE_RATIO = 0.6


@dataclass
class TypoCandidateResult:
    candidates: list[str]
    confidence: DiagnosticConfidence
    best_match: str | None

    @property
    def has_single_high_confidence_match(self) -> bool:
        return self.confidence == DiagnosticConfidence.HIGH and self.best_match is not None


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            current[j] = min(
                previous[j] + 1,      # deletion
                current[j - 1] + 1,   # insertion
                previous[j - 1] + cost,  # substitution
            )
        previous = current
    return previous[-1]


def _is_high_confidence_edit(misspelled: str, candidate: str) -> bool:
    # A common short-identifier typo pattern: one is a prefix of the
    # other and they differ by only a couple of characters (e.g. a
    # pluralization slip like "tax" -> "taxes", or "total" -> "totale").
    shorter_str, longer_str = sorted((misspelled, candidate), key=len)
    if longer_str.startswith(shorter_str) and (len(longer_str) - len(shorter_str)) <= 2:
        return True

    distance = _levenshtein(misspelled, candidate)
    shorter = min(len(misspelled), len(candidate))
    if shorter <= 4:
        return distance <= 1
    return distance <= 2


def find_typo_candidates(
    misspelled: str,
    known_names: set[str] | list[str],
    max_candidates: int = 3,
) -> TypoCandidateResult:
    pool = sorted(n for n in known_names if n and n != misspelled)
    if not pool:
        return TypoCandidateResult([], DiagnosticConfidence.UNKNOWN, None)

    close = difflib.get_close_matches(misspelled, pool, n=max_candidates, cutoff=LOW_CONFIDENCE_RATIO)
    # Edit distance can find good matches difflib's ratio cutoff misses
    # for very short identifiers (e.g. "taxes" -> "tax"), so also scan
    # the pool directly for a low-edit-distance match.
    edit_matches = [name for name in pool if _is_high_confidence_edit(misspelled, name)]
    for name in edit_matches:
        if name not in close:
            close.append(name)

    if not close:
        return TypoCandidateResult([], DiagnosticConfidence.UNKNOWN, None)

    scored = [(name, difflib.SequenceMatcher(None, misspelled, name).ratio()) for name in close]
    scored.sort(key=lambda pair: pair[1], reverse=True)

    high_confidence_matches = [name for name in close if _is_high_confidence_edit(misspelled, name)]

    if len(high_confidence_matches) == 1:
        return TypoCandidateResult([high_confidence_matches[0]], DiagnosticConfidence.HIGH, high_confidence_matches[0])

    if len(high_confidence_matches) > 1:
        # More than one candidate is an equally tiny edit away — PyFix
        # will not guess which one was meant.
        return TypoCandidateResult(high_confidence_matches[:max_candidates], DiagnosticConfidence.LOW, None)

    return TypoCandidateResult([name for name, _ in scored], DiagnosticConfidence.LOW, None)
