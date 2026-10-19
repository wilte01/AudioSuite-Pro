"""Markdown format lock: every CHANGELOG line stays reviewable.

``CHANGELOG.md`` is excluded from ``ruff format`` (``[tool.ruff.format]
exclude = ["*.md"]``), so nothing else stops a hand-written or generated entry
from arriving as one 600-character line.  A long line makes the rendered page
fine but the diff unreadable: a one-word edit rewrites the whole paragraph and
``git blame`` attributes every sentence to the last person who touched it.

This lock keeps the file wrapped at the same 88 columns the Python code uses,
with the repository's bullet convention (``- `` at column 0, continuation lines
indented two spaces), no tabs and no trailing whitespace.  It asserts the scan
actually sees the file and its ``Unreleased`` section, so an empty or renamed
changelog fails rather than passing vacuously.

Changed in 1.4.0: adds the CHANGELOG wrapping lock.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

#: Same column limit the Python sources use.
MAX_LINE_LENGTH = 88


def _lines() -> list[str]:
    """Return the changelog's lines without their terminators."""
    return CHANGELOG.read_text(encoding="utf-8").splitlines()


class TestChangelogFormat:
    """The changelog is a wrapped, diff-friendly Markdown document."""

    def test_the_scan_sees_the_changelog(self) -> None:
        """A missing or renamed file must fail, not pass vacuously."""
        assert CHANGELOG.is_file(), f"{CHANGELOG} is missing"
        lines = _lines()
        assert len(lines) > 100, f"changelog scan collapsed: {len(lines)} lines"
        assert "## [Unreleased]" in lines, "the Unreleased section is missing"

    def test_every_line_fits_the_column_limit(self) -> None:
        offenders = [
            f"{number}: {len(line)} cols — {line[:60]}…"
            for number, line in enumerate(_lines(), start=1)
            if len(line) > MAX_LINE_LENGTH
        ]
        assert not offenders, (
            f"CHANGELOG lines over {MAX_LINE_LENGTH} columns must be wrapped "
            "(ruff format excludes Markdown, so this lock owns it):\n  "
            + "\n  ".join(offenders)
        )

    def test_no_tabs_or_trailing_whitespace(self) -> None:
        offenders = [
            f"{number}: {'tab' if chr(9) in line else 'trailing whitespace'}"
            for number, line in enumerate(_lines(), start=1)
            if chr(9) in line or line != line.rstrip()
        ]
        assert not offenders, "CHANGELOG whitespace defects:\n  " + "\n  ".join(
            offenders
        )

    def test_bullets_use_a_two_space_hanging_indent(self) -> None:
        """A wrapped bullet keeps its body indented two spaces, never column 0."""
        offenders: list[str] = []
        in_bullet = False
        for number, line in enumerate(_lines(), start=1):
            if not line.strip():
                in_bullet = False
                continue
            if line.startswith("#"):
                in_bullet = False
                continue
            if line.startswith("- "):
                in_bullet = True
                continue
            if not in_bullet:
                continue
            if line.startswith("  "):
                continue
            offenders.append(f"{number}: {line[:60]}")
        assert not offenders, (
            "a wrapped CHANGELOG bullet must indent its continuation by two "
            "spaces so the list stays one item:\n  " + "\n  ".join(offenders)
        )
