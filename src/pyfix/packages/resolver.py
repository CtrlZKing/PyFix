"""Resolve an import name to an installable package, with a confidence score.

PyFix's resolver checks, in order of trust:

1. Already-installed distribution metadata (if some other module in
   the same distribution is importable, this is very high confidence).
2. The verified :mod:`pyfix.packages.mapping` table.
3. A "likely identical" fallback for a plain, PEP 8, non-namespaced
   import name.

If none of these apply, PyFix reports that it does not know the
package and refuses to guess — this is a hard product requirement,
not a nice-to-have.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from importlib import metadata as importlib_metadata

from pyfix.packages.mapping import COMMON_DIRECT_MATCHES, KNOWN_MISMATCHES

_VALID_IMPORT_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class PackageResolution:
    import_name: str
    distribution_name: str | None
    confidence_score: float
    source: str  # "installed-metadata" | "verified-mapping" | "heuristic" | "unknown"

    @property
    def resolved(self) -> bool:
        return self.distribution_name is not None


def resolve_package(import_name: str) -> PackageResolution:
    top_level = import_name.split(".")[0]

    # 1. Already installed under some distribution? (covers editable
    #    installs and namespaced packages we don't otherwise know about)
    dist_name = _find_installed_distribution_for_module(top_level)
    if dist_name:
        return PackageResolution(import_name, dist_name, 0.99, "installed-metadata")

    # 2. Verified mapping table.
    if top_level in KNOWN_MISMATCHES:
        return PackageResolution(import_name, KNOWN_MISMATCHES[top_level], 0.95, "verified-mapping")

    # 3. A small, well-known list of import names that are also their
    #    own verified PyPI distribution name (e.g. pygame, requests).
    if top_level in COMMON_DIRECT_MATCHES:
        return PackageResolution(import_name, top_level, 0.9, "common-direct-match")

    # 4. Heuristic: a well-formed, lowercase-ish single identifier is
    #    *often* also its own PyPI name, but this is a much weaker
    #    signal than the sources above, and never confident enough to
    #    auto-execute without extra scrutiny — PyFix will report it as
    #    "not confident enough" rather than silently guessing.
    if _VALID_IMPORT_NAME_RE.match(top_level) and not top_level.startswith("_"):
        return PackageResolution(import_name, top_level, 0.6, "heuristic")

    return PackageResolution(import_name, None, 0.0, "unknown")


def is_module_installed(import_name: str) -> bool:
    return _find_installed_distribution_for_module(import_name.split(".")[0]) is not None


def _find_installed_distribution_for_module(top_level: str) -> str | None:
    try:
        for dist in importlib_metadata.distributions():
            try:
                top_level_txt = dist.read_text("top_level.txt")
            except Exception:
                top_level_txt = None
            names = []
            if top_level_txt:
                names = [n.strip() for n in top_level_txt.splitlines() if n.strip()]
            elif dist.metadata.get("Name"):
                names = [dist.metadata["Name"].replace("-", "_")]
            if top_level in names:
                return dist.metadata.get("Name")
        return None
    except Exception:
        return None
