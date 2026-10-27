"""Locks: documentation has one authored format, and no machine-specific paths.

PLAN_docs_consolidation P4.2 and P4.3. Both lock a *class* of regression rather
than a file, which is why they are one module:

1. *Authored-format whitelist* - inside the documentation trees the only
   authored suffix is ``.md``. ``.docx``/``.pptx`` are permitted as generated
   artefacts (their sources are locked by ``test_user_guide_hygiene.py``),
   and ``.py`` only because the two suite-level generators live beside the
   artefacts they write. A new ``.rst``/``.txt``/``.adoc`` page fails here until
   someone adds it to the approved set **deliberately** - which is the point:
   the RST island this plan removed grew back one page at a time because no lock
   named the authored formats (D1).
2. *Absolute-path scan* - no first-party documentation tool may name a path on
   one developer's machine. Twenty-four retired guide generators wrote to
   ``D:\\Users\\<name>\\...``, so the committed scripts only ran on one host; a
   path like that must not come back through a renderer, a test or a page.

Both scans read the working tree and assert a non-empty result set, so a
mis-scoped walk fails loudly instead of passing vacuously (AGENTS.md, "Never
lose a rule to a scripted edit").

A third lock is *about* the first two: ``TestDocsLocksRunOnTheirOwn`` holds the
``docs-locks`` CI job (D22) to every module whose subject is a committed
document, so a stale guide fails in minutes instead of 15-20 minutes into the
suite matrix - and so the job cannot quietly lose a lock.

Changed in 2.1.0: new file - the authored-format whitelist and the
machine-specific path scan (PLAN_docs_consolidation P4.2, P4.3).
Changed in 2.1.0: adds ``TestDocsLocksRunOnTheirOwn``, the lock behind the
dedicated CI job (PLAN_docs_consolidation D22).
Changed in 2.1.5: the job also runs ``tests/test_suite_docs_tool_coverage.py``,
and the classification walk recognises its name family. Its subject is a
committed document - the CLI reference and the new-user deck - but the name it
was given misses the ``test_docs*`` / ``test_user_guide*`` / ``test_guide*`` /
``test_api_*`` families, so the walk never saw it, the file was never classified,
and its failures stayed 15-20 minutes into the suite matrix.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.ci_workflow import job as ci_job

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The only authored prose format (PLAN_docs_consolidation D1/D5).
AUTHORED = frozenset({".md"})

#: Generated artefacts: permitted, and each must be reproducible (hygiene lock).
ARTEFACTS = frozenset({".docx", ".pptx"})

#: Suite-level generators live beside the artefact they write.
CODE = frozenset({".py"})

APPROVED = AUTHORED | ARTEFACTS | CODE

#: The documentation trees the whitelist governs.
DOC_TREES = ("docs", "user_guides")

#: Every tracked path with one of these suffixes is scanned for absolute paths.
SCAN_TREES = ("user_guides", "utilities", "docs")
SCAN_SUFFIXES = frozenset({".py", ".md", ".rst", ".toml", ".yml", ".yaml", ".json"})

#: The document locks CI runs together, before the full suite (D22). Each
#: module's subject is a committed document: a guide artefact and its source,
#: the ``docs/`` pages, the generated index and README tables, the changelog,
#: the reference and deck's tool coverage, or the Help button's path resolution.
DOCS_LOCKS: tuple[str, ...] = (
    "tests/test_user_guide_hygiene.py",
    "tests/test_docs_formats.py",
    "tests/test_docs_index.py",
    "tests/test_guide_resolution.py",
    "tests/test_api_reference.py",
    "tests/test_readme.py",
    "tests/test_changelog_format.py",
    "tests/test_suite_docs_tool_coverage.py",
)

#: Document-shaped modules the fast job deliberately leaves to the full suite.
DOCS_LOCKS_DEFERRED: dict[str, str] = {
    "tests/test_docs_build.py": (
        "builds the Sphinx site, whose autodoc imports the documented package; "
        "the test job publishes what its verdict certifies (P3.2)"
    ),
    "tests/test_docstring_coverage.py": (
        "its subject is docstring coverage in the source tree, not a committed document"
    ),
}

#: A Windows drive path that points into a user profile or a system folder.
_ABSOLUTE = re.compile(
    r"(?<![A-Za-z])[A-Za-z]:[\\/]{1,2}(?:Users|Documents|Desktop|Program Files)",
    re.IGNORECASE,
)


def tracked_paths() -> list[str]:
    """Return every tracked path, POSIX-style, relative to the repository root.

    Returns:
        Sorted forward-slashed paths.

    Raises:
        subprocess.CalledProcessError: If git is unavailable or this is not a
            repository.
    """
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return sorted(line.strip() for line in result.stdout.splitlines() if line.strip())


@pytest.fixture(scope="module")
def tracked() -> Iterator[list[str]]:
    """The tracked-file set, read once per module.

    Yields:
        Sorted POSIX paths relative to the repository root.
    """
    yield tracked_paths()


class TestAuthoredFormatWhitelist:
    """The documentation trees contain only approved file types."""

    def test_only_approved_suffixes_are_tracked(self, tracked: list[str]) -> None:
        """Every tracked documentation file has an approved suffix."""
        files = [
            path
            for path in tracked
            if path.split("/", 1)[0] in DOC_TREES and not path.endswith("/")
        ]
        assert len(files) >= 40, (
            f"only {len(files)} documentation files found - the walk is broken, "
            "so this lock would pass vacuously"
        )

        offenders = sorted(
            path for path in files if Path(path).suffix.lower() not in APPROVED
        )
        assert not offenders, (
            "documentation ships in a format outside the approved set "
            f"({', '.join(sorted(APPROVED))}). Authored prose is Markdown; "
            "`.docx`/`.pptx` are generated artefacts and `.py` is a generator. "
            "A new format needs a deliberate entry in tests/test_docs_formats.py "
            "(PLAN_docs_consolidation P4.2):\n  " + "\n  ".join(offenders)
        )

    def test_no_reStructuredText_page_is_tracked(self, tracked: list[str]) -> None:
        """D1 converted the RST island; a new ``.rst`` page is a regression."""
        rst = [path for path in tracked if path.lower().endswith(".rst")]
        assert not rst, (
            "RST pages are tracked again. Every documentation page is Markdown "
            "rendered by MyST (PLAN_docs_consolidation D1/P4.2):\n  "
            + "\n  ".join(sorted(rst))
        )

    def test_docs_holds_no_generated_artefact(self, tracked: list[str]) -> None:
        """The Sphinx tree holds pages and its config, never an artefact."""
        artefacts = [
            path
            for path in tracked
            if path.startswith("docs/") and Path(path).suffix.lower() in ARTEFACTS
        ]
        assert not artefacts, (
            "a generated artefact lives under docs/; artefacts belong beside "
            "their source under user_guides/ (D7):\n  " + "\n  ".join(artefacts)
        )


class TestNoMachineSpecificPaths:
    """Documentation tooling never names a path on one machine."""

    def test_no_absolute_windows_path_in_documentation_tooling(
        self, tracked: list[str]
    ) -> None:
        """No first-party doc file names ``<drive>:\\Users\\...``."""
        files = [
            path
            for path in tracked
            if path.split("/", 1)[0] in SCAN_TREES
            and Path(path).suffix.lower() in SCAN_SUFFIXES
        ]
        assert len(files) >= 10, (
            f"only {len(files)} files scanned - the walk is broken, so this lock "
            "would pass vacuously"
        )

        offenders: list[str] = []
        for path in files:
            absolute = REPO_ROOT / path
            if not absolute.is_file():
                continue
            text = absolute.read_text(encoding="utf-8", errors="replace")
            for number, line in enumerate(text.splitlines(), start=1):
                if _ABSOLUTE.search(line):
                    offenders.append(f"{path}:{number}: {line.strip()[:100]}")

        assert not offenders, (
            "documentation tooling names a machine-specific absolute path. It "
            "must resolve paths from the repository root or the script's own "
            "location (PLAN_docs_consolidation P4.3):\n  " + "\n  ".join(offenders)
        )


def _document_lock_modules() -> set[str]:
    """Return every test module whose subject is a committed document.

    The families are named rather than derived from a list of subjects the
    files do not declare: a module about a document is called
    ``test_docs*``/``test_user_guide*``/``test_guide*``/``test_api_*``,
    ``test_suite_docs*`` (a suite-wide document), or it locks the README or the
    changelog by name.

    Returns:
        POSIX paths relative to the repository root, e.g. ``tests/test_docs_index.py``.
    """
    prefixes = (
        "test_docs",
        "test_user_guide",
        "test_guide",
        "test_api_",
        "test_suite_docs",
    )
    names = {
        path.name
        for path in (REPO_ROOT / "tests").glob("test_*.py")
        if path.name.startswith(prefixes)
    }
    names |= {"test_readme.py", "test_changelog_format.py"}
    return {f"tests/{name}" for name in names}


class TestDocsLocksRunOnTheirOwn:
    """The document locks are a CI job of their own, and it runs all of them.

    Lock (3), PLAN_docs_consolidation D22. The suite still owns correctness -
    these are the same test modules - but a lock that only speaks 15 minutes
    into a three-interpreter matrix is a lock people work around. Two failures
    this catches: a lock dropped from the job's command (so the job is green
    while a guide rots), and a new document lock that nobody added to the job
    (so it keeps running only in the full suite).
    """

    def test_the_job_runs_every_lock(self) -> None:
        """Each listed lock is named in the ``docs-locks`` job's steps."""
        block = ci_job("docs-locks")
        assert len(DOCS_LOCKS) >= 8, (
            f"{len(DOCS_LOCKS)} locks listed - the list shrank, so the job would "
            "silently stop covering a document"
        )
        missing = [path for path in DOCS_LOCKS if path not in block]
        assert not missing, (
            "the docs-locks job in ci.yml does not run these locks, so their "
            "failures are back to surfacing only in the full suite "
            "(PLAN_docs_consolidation D22):\n  " + "\n  ".join(missing)
        )

    def test_every_document_lock_is_classified(self) -> None:
        """The walk and the two lists agree, in both directions.

        A module the walk finds must be listed here or deferred; and a listed
        module must be one the walk can find. The second direction is not
        decorative: a lock whose module name misses every family is invisible
        to the walk, so removing a family from ``_document_lock_modules`` - or
        naming a new lock outside them - would drop it back to "unclassified in
        practice" with every assertion above still green.
        """
        discovered = _document_lock_modules()
        assert len(discovered) >= 10, (
            f"only {len(discovered)} document lock modules found - the walk is "
            "broken, so this lock would pass vacuously"
        )
        stale = sorted(set(DOCS_LOCKS_DEFERRED) - discovered)
        assert not stale, (
            "these modules are deferred from the docs-locks job but no longer "
            "exist; remove them from DOCS_LOCKS_DEFERRED:\n  " + "\n  ".join(stale)
        )
        invisible = sorted((set(DOCS_LOCKS) | set(DOCS_LOCKS_DEFERRED)) - discovered)
        assert not invisible, (
            "these locks are listed for the docs-locks job, but the "
            "classification walk cannot see them: their module names match no "
            "family, so they are unclassified in practice and a new file of the "
            "same shape would go unnoticed. Add the family to "
            "_document_lock_modules:\n  " + "\n  ".join(invisible)
        )
        unclassified = sorted(discovered - set(DOCS_LOCKS) - set(DOCS_LOCKS_DEFERRED))
        assert not unclassified, (
            "document lock modules are not classified for the docs-locks job. "
            "Add each to DOCS_LOCKS (and to the job's command in ci.yml) or to "
            "DOCS_LOCKS_DEFERRED with a reason (PLAN_docs_consolidation D22):\n  "
            + "\n  ".join(unclassified)
        )
