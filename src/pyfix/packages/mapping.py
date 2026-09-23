"""A verified import-name -> PyPI-distribution-name mapping.

This is deliberately a small, hand-curated table of well-known cases
where the import name differs from the package you `pip install`.
It is a *verified* source, not a guess — see
:mod:`pyfix.packages.resolver` for how it's combined with other
sources (installed metadata, PyPI lookups) and how confidence is
computed so PyFix never installs a package "an AI guessed."
"""

from __future__ import annotations

# import_name -> distribution_name
KNOWN_MISMATCHES: dict[str, str] = {
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "sklearn": "scikit-learn",
    "bs4": "beautifulsoup4",
    "yaml": "PyYAML",
    "dotenv": "python-dotenv",
    "dateutil": "python-dateutil",
    "serial": "pyserial",
    "usb": "pyusb",
    "Crypto": "pycryptodome",
    "OpenSSL": "pyOpenSSL",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "fitz": "PyMuPDF",
    "cv": "opencv-python",
    "attr": "attrs",
    "jwt": "PyJWT",
    "gi": "PyGObject",
    "markdown_it": "markdown-it-py",
    "google.protobuf": "protobuf",
    "slugify": "python-slugify",
}

# Import names that are almost always identical to the distribution
# name. Kept only as a documentation aid / fast-path allow-list; the
# resolver treats *any* name not otherwise flagged as "likely same".
COMMON_DIRECT_MATCHES = {
    "pygame",
    "requests",
    "numpy",
    "pandas",
    "flask",
    "django",
    "matplotlib",
    "scipy",
    "pytest",
}
