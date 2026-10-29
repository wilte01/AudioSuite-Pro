"""Gate: the API reference builds with Sphinx's own parser, warning-free.

PLAN_feature_expansion P2. Four real RST defects shipped in 1.4.0 because
nothing parsed these docstrings: the docs build was manual, CI installed no
Sphinx, and the reference covered 11 of the 62 shared modules. A naive
docutils-only scan is *not* a substitute — it reports Sphinx roles
(``:func:``, ``:class:``) as unknown and Napoleon ``Args:`` blocks as broken
indentation, so it would have failed on correct docstrings and taught everyone
to ignore it. This test therefore runs the real builder on the real
``documentation/docs/``
tree, with the shipped ``conf.py`` (autodoc + napoleon configured exactly as the
published pages are), and fails on any warning.

A missing Sphinx is a hard failure, not a skip: the toolchain is in the ``dev``
extra precisely so this gate cannot silently disappear.

Changed in 1.4.1: new file - the docs-build gate that fails on any Sphinx
warning, so a malformed docstring cannot reach the published reference (P2).
Changed in 2.1.1: two more locks, both about the artifact rather than a page
(PLAN_feature_expansion.md, Sprint 8). ``TestPublishedTreeIsSelfContained``
stages the site with ``utilities/build_docs_site.py`` - the same function CI
runs - and walks every ``href``/``src`` in the result, because twelve links in
the pages pointed at targets the artifact never published or could not
resolve. ``TestTheCertifiedBuildIsTheDelivery`` holds the workflow to that
tree: the test job stages and uploads it, and there is deliberately no Pages
deploy while publication is blocked (D9). `AGENTS.md` is not staged - it is the
repository's instruction file, not an end-user document (D13).

Changed in 2.1.7: the Sphinx source is ``documentation/docs/`` and the staged pages keep
that depth, so ``../../README.md`` resolves.

"""

from __future__ import annotations

import importlib.util
import io
import sys
from html.parser import HTMLParser
from pathlib import Path
from types import ModuleType
from urllib.parse import unquote, urlsplit

import pytest
from sphinx.application import Sphinx

from tests.ci_workflow import job as ci_job
from tests.ci_workflow import step as ci_step
from tests.ci_workflow import workflow_text

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS = REPO_ROOT / "documentation" / "docs"

#: The staging step both this module and CI run (PLAN_feature_expansion D7).
STAGER = REPO_ROOT / "utilities" / "build_docs_site.py"

#: The page that renders every shared module.  Its presence and size prove the
#: build produced a document rather than an empty shell.
API_PAGE = "api.html"

#: A floor on the links the self-containment lock actually resolves.  The staged
#: tree carried 239 internal link occurrences at 2.1.1; a walk that suddenly
#: finds a handful is broken, and would otherwise pass vacuously.
MIN_CHECKED_LINKS = 200


def _build(tmp_path: Path) -> tuple[list[str], Path]:
    """Build the documentation source into *tmp_path*.

    Returns:
        The Sphinx warnings and the directory the pages were written to.
    """
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


class _Links(HTMLParser):
    """Collect every ``href``/``src`` value a rendered page carries."""

    def __init__(self) -> None:
        super().__init__()
        self.found: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Record the link-bearing attributes of one start tag.

        Args:
            tag: The element name (unused; ``a`` and ``link`` both matter).
            attrs: The element's attributes.
        """
        for name, value in attrs:
            if name in ("href", "src") and value:
                self.found.append(value)


def _load_stager() -> ModuleType:
    """Load ``utilities/build_docs_site.py`` by path (it is not a package).

    Returns:
        The staging module, so the lock runs the function CI runs.
    """
    assert STAGER.is_file(), f"the shared staging step is missing: {STAGER}"
    spec = importlib.util.spec_from_file_location("build_docs_site_locked", STAGER)
    assert spec is not None and spec.loader is not None, f"cannot load {STAGER}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def published(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Stage the site once and return the publish root.

    Args:
        tmp_path_factory: pytest's temporary directory factory.

    Returns:
        The staged publish root.
    """
    out = tmp_path_factory.mktemp("publish") / "site"
    _load_stager().stage(REPO_ROOT, out)
    return out


def _link_report(page: Path, root: Path) -> tuple[int, list[str], list[str]]:
    """Resolve one page's internal links against the publish root.

    Args:
        page: The rendered page.
        root: The publish root every target must stay inside.

    Returns:
        ``(checked, missing, escaping)`` - the number of internal links seen, the
        dangling ones, and the ones that leave the tree.
    """
    parser = _Links()
    parser.feed(page.read_text(encoding="utf-8", errors="replace"))
    checked = 0
    missing: list[str] = []
    escaping: list[str] = []
    source = page.relative_to(root).as_posix()
    for raw in parser.found:
        split = urlsplit(raw)
        # An external URL, a mailto: and a pure #anchor are not tree claims.
        if split.scheme in ("http", "https", "mailto") or not split.path:
            continue
        checked += 1
        target = (page.parent / unquote(split.path)).resolve()
        try:
            relative = target.relative_to(root).as_posix()
        except ValueError:
            escaping.append(f"{source} -> {raw}")
            continue
        if not target.exists():
            missing.append(f"{source} -> {raw} (expected {relative})")
    return checked, missing, escaping


class TestPublishedTreeIsSelfContained:
    """The staged artifact works without a checkout (Items 8.1/8.2)."""

    def test_every_internal_link_resolves(self, published: Path) -> None:
        """No page may link outside the publish root or to a missing file."""
        pages = sorted((published / "documentation" / "docs").rglob("*.html"))
        assert len(pages) >= 8, f"only {len(pages)} pages staged - the walk is broken"

        checked = 0
        missing: list[str] = []
        escaping: list[str] = []
        for page in pages:
            seen, absent, escaped = _link_report(page, published)
            checked += seen
            missing.extend(absent)
            escaping.extend(escaped)

        assert not escaping, "the staged tree links outside itself:\n  " + "\n  ".join(
            sorted(set(escaping))
        )
        assert not missing, (
            "the staged tree has dangling links - stage the target in "
            "utilities/build_docs_site.py, or fix the source link:\n  "
            + "\n  ".join(sorted(set(missing)))
        )
        assert checked >= MIN_CHECKED_LINKS, (
            f"only {checked} internal links checked (floor {MIN_CHECKED_LINKS}): the "
            "walk is broken, so this lock would pass vacuously"
        )

    def test_the_publish_root_opens_on_the_front_door(self, published: Path) -> None:
        """The root ``index.html`` redirects to the staged pages."""
        redirect = published / "index.html"
        assert redirect.is_file(), "the publish root has no index.html"
        # The pages keep the checkout's depth (documentation/docs), because the
        # pages link repository-root files with ``../../``; a shallower publish
        # root would make every such link escape the artifact.
        assert "url=documentation/docs/" in redirect.read_text(encoding="utf-8")
        assert (published / "documentation" / "docs" / "index.html").is_file()

    def test_every_staged_target_exists(self, published: Path) -> None:
        """Each file and directory the stager names is really in the tree."""
        stager = _load_stager()
        staged_files = tuple(stager.STAGED_FILES)
        staged_dirs = tuple(stager.STAGED_DIRS)
        assert len(staged_files) >= 4, f"the staged file list shrank: {staged_files}"
        assert len(staged_dirs) >= 2, f"the staged directory list shrank: {staged_dirs}"

        absent = [name for name in staged_files if not (published / name).is_file()]
        absent += [name for name in staged_dirs if not (published / name).is_dir()]
        assert not absent, "the staging step did not publish:\n  " + "\n  ".join(absent)

    def test_the_instruction_file_is_not_shipped(self, published: Path) -> None:
        """The repository's own instructions stay out of the artifact (D13)."""
        staged = tuple(_load_stager().STAGED_FILES)
        assert "AGENTS.md" not in staged, (
            "AGENTS.md is in the copy list again; it is the repository's "
            "instruction file for contributors, not an end-user document (D13)"
        )
        assert not (published / "AGENTS.md").exists(), (
            "the artifact carries AGENTS.md; the pages no longer link it, and "
            "the copy hands the repository's instructions to whoever opens "
            "the zip (D13)"
        )

    def test_the_doctrees_stay_out_of_the_publish_root(self, published: Path) -> None:
        """Sphinx's build cache must not ship in the artifact (D8)."""
        assert not (published / "documentation" / "docs" / ".doctrees").exists(), (
            "sphinx wrote .doctrees inside the published pages; the staging step "
            "must pass -d outside the publish root"
        )


class TestTheCertifiedBuildIsTheDelivery:
    """What ships is the tree the suite certified (D7/D9)."""

    def test_the_test_job_stages_through_the_shared_step(self) -> None:
        """CI runs the staging module, not a second copy of its commands."""
        block = ci_job("test")

        assert "uv run python utilities/build_docs_site.py" in block, (
            "the test job no longer builds the site through the shared staging "
            "step, so the artifact and this lock can disagree"
        )

    def test_the_test_job_uploads_the_staged_tree(self) -> None:
        """The docs-html artifact is the staged tree, and an empty one fails."""
        block = ci_job("test")
        upload = ci_step(block, "Upload the documentation site")

        assert "name: docs-html" in upload, upload
        assert "path: documentation/docs/_build/" in upload, upload
        assert "if-no-files-found: error" in upload, (
            "an empty artifact would look like success; the upload must fail"
        )

    def test_no_pages_deploy_runs_while_publication_is_blocked(self) -> None:
        """Publication is blocked by entitlement, so no deploy job may appear."""
        text = workflow_text()

        assert "actions/deploy-pages" not in text, (
            "a Pages deploy appeared while publication is blocked: GitHub Pages "
            "cannot be enabled for a private repository on the free plan "
            "(PLAN_feature_expansion D9). Decide hosting first, then add the job."
        )
