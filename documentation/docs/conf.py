"""Sphinx configuration for the AudioSuite-Pro documentation site.

The HTML is a developer artefact, not part of the shipped application: it
documents the shared package's public surface, which is what a tool author
imports, and renders the committed pages under ``documentation/docs/``. Build it
with the interpreter that carries the ``dev`` extra (Sphinx and MyST live there,
so the build gate cannot silently lose its toolchain)::

    uv sync --extra dev
    python utilities/build_docs_site.py     # build + stage the publish tree

Sphinx is in the ``dev`` extra, because ``tests/test_docs_build.py`` builds these
pages with this configuration and fails on any parser warning (PLAN P2) -- a
defect in a docstring is a defect in the published reference, so it belongs to
the gate rather than to a manual step. This module imports only the standard
library, so ``mypy .`` checks it with the rest of the tree.

Changed in 1.4.1: new module - the Sphinx configuration for the API reference,
stdlib-only so the type gate covers it (PLAN D98).
Changed in 2.1.0: the ``docs/requirements.txt`` install line and its
``exclude_patterns`` entry are gone with that file - the toolchain is declared
once, in ``pyproject.toml``'s ``dev`` extra (PLAN_docs_consolidation P1.7).
Changed in 2.1.0: every page is Markdown, rendered by MyST. One authored prose
format across the repository was D1's whole point, and the RST island was the
last second format (PLAN_docs_consolidation P3.1).

Changed in 2.1.7: ``ROOT`` is ``parents[2]``: this file now sits three levels down
(``documentation/docs/``), and ``parent.parent`` would point at ``documentation``.

"""

from __future__ import annotations

import sys
from pathlib import Path

#: The checkout root, so autodoc can import the package without an install.
#: This file lives at ``documentation/docs/conf.py``, three levels down - a
#: ``parent.parent`` here would point at ``documentation/``, and autodoc would
#: fail to import every documented module.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

project = "AudioSuite-Pro"
author = "AudioSuite-Pro contributors"
copyright = "2026, AudioSuite-Pro contributors"  # noqa: A001 - Sphinx reads it

extensions: list[str] = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
]

#: Every page is Markdown; the renderer is MyST (PLAN_docs_consolidation D1).
source_suffix: dict[str, str] = {".md": "markdown"}

#: MyST extensions the committed pages use.  ``deflist`` renders the plugin
#: guide's state table (``loaded`` / ``disabled`` / ``rejected``), whose
#: definitions must not collapse into one paragraph.
myst_enable_extensions: list[str] = ["deflist"]

#: The index links committed repository files that live *outside*
#: ``documentation/docs/`` -- the user guides' Markdown sources, the README and
#: the changelog.  Sphinx only resolves documents inside its source directory, so
#: without this MyST reports each of those links as ``myst.xref_missing`` and the
#: build gate goes red for links that are correct in the repository.  Cross-page
#: links inside ``documentation/docs/`` use the explicit ``{doc}`` role, so
#: nothing that *can* be resolved is lost.  Note the corollary: a wrong relative
#: link to a repository file is *not* a warning, so
#: ``utilities/build_docs_site.STAGED_*`` and ``test_docs_build``'s
#: link walk are what prove those hrefs resolve.
myst_all_links_external = True

# Google-style docstrings are the repository convention (Args/Returns/Raises).
napoleon_google_docstring = True
napoleon_numpy_docstring = False
autodoc_typehints = "description"
autodoc_member_order = "bysource"

html_theme = "alabaster"
exclude_patterns: list[str] = ["_build"]
