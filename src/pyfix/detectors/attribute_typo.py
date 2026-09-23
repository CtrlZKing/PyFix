"""Detector for AttributeError typos on builtin types and known-safe modules.

Two sources of ground truth, both safe:

1. Builtin types (list, dict, str, set, tuple, ...) — PyFix already has
   these in-process; no import or introspection risk at all.
2. A small allow-list of standard-library modules (see
   ``SAFE_INTROSPECTION_MODULES``) that are always part of the running
   interpreter, so importing them for ``dir()`` introspection executes
   no project code and no third-party code.

PyFix deliberately does NOT import arbitrary modules (including the
user's own project modules) just to inspect them — that would execute
untrusted code, which the product's safety rules forbid.
"""

from __future__ import annotations

import difflib
import importlib
import re

from pyfix.core.models import RepairLevel, RepairProposal, Severity
from pyfix.detectors.base import DetectionContext

_OBJECT_ATTR_RE = re.compile(r"'([A-Za-z_][A-Za-z0-9_.]*)' object has no attribute '([A-Za-z_][A-Za-z0-9_]*)'")
_MODULE_ATTR_RE = re.compile(r"module '([A-Za-z_][A-Za-z0-9_.]*)' has no attribute '([A-Za-z_][A-Za-z0-9_]*)'")

# Only these modules are ever imported for introspection. All are part
# of the Python standard library and always available in the running
# interpreter — importing them cannot execute project or third-party code.
SAFE_INTROSPECTION_MODULES = {
    "os", "pathlib", "sys", "math", "json", "re", "random", "datetime",
    "subprocess", "shutil", "collections", "itertools", "typing",
}

_BUILTIN_TYPES = {
    "list": list,
    "dict": dict,
    "str": str,
    "set": set,
    "tuple": tuple,
    "frozenset": frozenset,
    "int": int,
    "float": float,
    "bytes": bytes,
}

_HIGH_CONFIDENCE_RATIO = 0.75


class AttributeTypoDetector:
    name = "attribute_typo"

    def matches(self, ctx: DetectionContext) -> bool:
        tb = ctx.traceback_info
        if tb.exception_type != "AttributeError":
            return False
        return bool(_OBJECT_ATTR_RE.search(tb.message) or _MODULE_ATTR_RE.search(tb.message))

    def diagnose(self, ctx: DetectionContext) -> RepairProposal | None:
        tb = ctx.traceback_info
        location = f"{tb.last_frame.file}, line {tb.last_frame.line}" if tb.last_frame else ""

        module_match = _MODULE_ATTR_RE.search(tb.message)
        if module_match:
            return self._diagnose_module_attribute(module_match, location)

        obj_match = _OBJECT_ATTR_RE.search(tb.message)
        if obj_match:
            return self._diagnose_object_attribute(obj_match, location)

        return None

    def _diagnose_module_attribute(self, match, location) -> RepairProposal | None:
        module_name, bad_attr = match.group(1), match.group(2)

        if module_name not in SAFE_INTROSPECTION_MODULES:
            return RepairProposal(
                category="attribute_error_unknown",
                explanation=(
                    f"❌ Attribute error\n\n"
                    f'`{module_name}.{bad_attr}` does not exist.\n\n'
                    "PyFix only safely introspects a small set of standard-library "
                    f"modules, and `{module_name}` is not one of them, so it cannot "
                    "confirm a correction without importing untrusted code."
                ),
                confidence_score=0.3,
                risk_level=RepairLevel.EXPLANATION_ONLY,
                severity=Severity.ERROR,
                what_happened=f'"{module_name}" has no attribute "{bad_attr}".',
                why_it_happened="PyFix cannot safely introspect this module to suggest a correction.",
                location=location,
                can_auto_fix=False,
                unresolved_reason="module_not_in_safe_introspection_list",
            )

        try:
            module = importlib.import_module(module_name)
        except ImportError:
            return None

        candidates = _closest_public_names(bad_attr, dir(module))
        return self._build_typo_proposal(
            category="attribute_typo",
            subject=f"{module_name}.{bad_attr}",
            bad_attr=bad_attr,
            candidates=candidates,
            correct_form=lambda c: f"{module_name}.{c}",
            location=location,
        )

    def _diagnose_object_attribute(self, match, location) -> RepairProposal | None:
        type_name, bad_attr = match.group(1), match.group(2)

        builtin_type = _BUILTIN_TYPES.get(type_name)
        if builtin_type is None:
            return RepairProposal(
                category="attribute_error_unknown",
                explanation=(
                    f"❌ Attribute error\n\n"
                    f"A `{type_name}` object has no attribute `{bad_attr}`.\n\n"
                    "PyFix does not have verified information about this type's "
                    "attributes, so it will not guess a correction."
                ),
                confidence_score=0.3,
                risk_level=RepairLevel.EXPLANATION_ONLY,
                severity=Severity.ERROR,
                what_happened=f'A "{type_name}" object has no attribute "{bad_attr}".',
                why_it_happened="This type isn't in PyFix's verified builtin-type knowledge.",
                location=location,
                can_auto_fix=False,
                unresolved_reason="type_not_in_verified_list",
            )

        candidates = _closest_public_names(bad_attr, dir(builtin_type))
        return self._build_typo_proposal(
            category="attribute_typo",
            subject=f"{type_name} object's .{bad_attr}",
            bad_attr=bad_attr,
            candidates=candidates,
            correct_form=lambda c: f".{c}()" if callable(getattr(builtin_type, c, None)) else f".{c}",
            location=location,
        )

    def _build_typo_proposal(self, category, subject, bad_attr, candidates, correct_form, location) -> RepairProposal:
        if not candidates:
            return RepairProposal(
                category="attribute_error_unknown",
                explanation=(
                    f"❌ Attribute error\n\n"
                    f"`{subject}` does not exist, and PyFix found no close match "
                    "among the known attributes."
                ),
                confidence_score=0.3,
                risk_level=RepairLevel.EXPLANATION_ONLY,
                severity=Severity.ERROR,
                what_happened=f'"{bad_attr}" is not a known attribute.',
                location=location,
                can_auto_fix=False,
                unresolved_reason="no_close_match",
            )

        best = candidates[0]
        confidence_label = "HIGH" if len(candidates) == 1 else "MEDIUM"
        # Explanation-only: PyFix does not know every call site that
        # would need updating, so it reports the typo but leaves the
        # edit to the (much more targeted, line-scoped) call-site
        # detectors / manual correction. See README for rationale.
        return RepairProposal(
            category=category,
            explanation=(
                f"❌ Likely typo\n\n"
                f"`{subject}` does not exist.\n\n"
                f"Did you mean:\n\n    {correct_form(best)}\n\n"
                f"Confidence: {confidence_label}"
            ),
            confidence_score=0.85 if len(candidates) == 1 else 0.5,
            risk_level=RepairLevel.EXPLANATION_ONLY,
            severity=Severity.ERROR,
            what_happened=f'"{bad_attr}" is not a real attribute.',
            why_it_happened=f"The closest known match is: {', '.join(candidates)}.",
            location=location,
            can_auto_fix=False,
            unresolved_reason="attribute_fix_requires_manual_review",
        )


def _closest_public_names(bad_name: str, names, max_results: int = 2) -> list[str]:
    public = [n for n in names if not n.startswith("_")]
    close = difflib.get_close_matches(bad_name, public, n=max_results, cutoff=_HIGH_CONFIDENCE_RATIO)
    return close
