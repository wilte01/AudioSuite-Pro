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

Changed in 2.1.0: new file - the authored-format whitelist and the
machine-specific path scan (PLAN_docs_consolidation P4.2, P4.3).
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

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
