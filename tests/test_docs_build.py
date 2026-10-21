"""Gate: the API reference builds with Sphinx's own parser, warning-free.

PLAN_feature_expansion P2. Four real RST defects shipped in 1.4.0 because
nothing parsed these docstrings: the docs build was manual, CI installed no
Sphinx, and the reference covered 11 of the 62 shared modules. A naive
docutils-only scan is *not* a substitute — it reports Sphinx roles
(``:func:``, ``:class:``) as unknown and Napoleon ``Args:`` blocks as broken
indentation, so it would have failed on correct docstrings and taught everyone
to ignore it. This test therefore runs the real builder on the real ``docs/``
tree, with the shipped ``conf.py`` (autodoc + napoleon configured exactly as the
published pages are), and fails on any warning.

A missing Sphinx is a hard failure, not a skip: the toolchain is in the ``dev``
extra precisely so this gate cannot silently disappear.
"""

from __future__ import annotations

import io
from pathlib import Path

from sphinx.application import Sphinx

DOCS = Path(__file__).resolve().parent.parent / "docs"

#: The page that renders every shared module.  Its presence and size prove the
#: build produced a document rather than an empty shell.
API_PAGE = "api.html"


def _build(tmp_path: Path) -> tuple[list[str], Path]:
    """Build ``docs/`` into *tmp_path* and return ``(warnings, outdir)``."""
    outdir = tmp_path / "html"
    doctreedir = tmp_path / "doctrees"
    status = io.StringIO()
    warning = io.StringIO()

    app = Sphinx(
        srcdir=str(DOCS),
        confdir=str(DOCS),
        outdir=str(outdir),
        doctreedir=str(doctreedir),
        buildername="html",
        status=status,
        warning=warning,
        freshenv=True,
    )
    app.build(force_all=True)

    warnings = [line for line in warning.getvalue().splitlines() if line.strip()]
    return warnings, outdir


def test_the_api_reference_builds_without_warnings(tmp_path: Path) -> None:
    warnings, outdir = _build(tmp_path)

    assert warnings == [], (
        "Sphinx reported docstring/RST problems in the API reference:\n"
        + "\n".join(warnings)
    )
    page = outdir / API_PAGE
    assert page.is_file(), f"the build produced no {API_PAGE}"

    html = page.read_text(encoding="utf-8")
    # automodule output names the module *and* its functions; a page that only
    # rendered the prose would pass the warning check while documenting nothing.
    assert "audio_suite_shared.analysis_loader" in html
    assert "librosa_load_with_fallback" in html
    # The page renders 61 modules; a body this small means the automodule
    # directives silently did nothing.
    assert len(html) > 200_000, f"{API_PAGE} is suspiciously small ({len(html)} bytes)"
