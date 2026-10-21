"""Sphinx configuration for the AudioSuite-Pro API reference.

The API HTML is a developer artefact, not part of the shipped application: it
documents the shared package's public surface, which is what a tool author
imports. Build it with the interpreter that carries the docs requirements::

    python -m pip install -r docs/requirements.txt
    python -m sphinx -b html docs docs/_build/html

Sphinx is in the ``dev`` extra as well, because ``tests/test_docs_build.py``
builds these pages with this configuration and fails on any parser warning
(PLAN P2) -- a defect in a docstring is a defect in the published reference, so
it belongs to the gate rather than to a manual step. This module imports only
the standard library, so ``mypy .`` checks it with the rest of the tree.

Changed in 1.4.1: new module - the Sphinx configuration for the API reference,
stdlib-only so the type gate covers it (PLAN D98).
"""

from __future__ import annotations

import sys
from pathlib import Path

#: The checkout root, so autodoc can import the package without an install.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

project = "AudioSuite-Pro"
author = "AudioSuite-Pro contributors"
copyright = "2026, AudioSuite-Pro contributors"  # noqa: A001 - Sphinx reads it

extensions: list[str] = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
]

# Google-style docstrings are the repository convention (Args/Returns/Raises).
napoleon_google_docstring = True
napoleon_numpy_docstring = False
autodoc_typehints = "description"
autodoc_member_order = "bysource"

html_theme = "alabaster"
exclude_patterns: list[str] = ["_build", "requirements.txt"]
