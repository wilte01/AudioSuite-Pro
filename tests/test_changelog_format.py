"""Locks: both change-history files stay reviewable, and stay split by audience.

``CHANGELOG.md`` is excluded from ``ruff format`` (``[tool.ruff.format]
exclude = ["*.md"]``), so nothing else stops a hand-written or generated entry
from arriving as one 600-character line.  A long line makes the rendered page
fine but the diff unreadable: a one-word edit rewrites the whole paragraph and
``git blame`` attributes every sentence to the last person who touched it.

The format half keeps each file wrapped at the same 88 columns the Python code
uses, with the repository's bullet convention (``- `` at column 0, continuation
lines indented two spaces), no tabs and no trailing whitespace.  It asserts the
scan actually sees each file and its ``Unreleased`` section, so an empty or
renamed changelog fails rather than passing vacuously.

The audience half holds the split the maintenance cycle introduced (functional
backlog U2): ``CHANGELOG.md`` records what a user can run or observe, and
``TECHNICAL_CHANGELOG.md`` carries the gate, CI, tests, tooling,
behaviour-neutral refactors and dependency bumps.  A reader looking up the
defect they just hit must not have to parse the second audience's bullets, and
the boundary is enforced rather than left to taste: a bullet's bold lead-in —
its subject — may not name developer work.

Changed in 1.4.0: adds the CHANGELOG wrapping lock.
Changed in 2.2.1: the format lock is parameterised over both change-history
files, and ``TestChangelogAudience`` holds the user/technical boundary
(functional backlog U2).  It is proved able to fail by the two bullets the split
moved, which it rejects here rather than by having watched them once.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
USER_CHANGELOG = REPO_ROOT / "CHANGELOG.md"
TECHNICAL_CHANGELOG = REPO_ROOT / "TECHNICAL_CHANGELOG.md"
CHANGELOGS = (USER_CHANGELOG, TECHNICAL_CHANGELOG)

#: Same column limit the Python sources use.
MAX_LINE_LENGTH = 88

#: Words that name developer work.  A user-facing bullet's lead-in may not use
#: one: a gate, a test or a CI job is not something a user can run or observe.
DEVELOPER_STEMS: tuple[str, ...] = (
    "test",
    "pytest",
    "gate",
    "workflow",
    "ruff",
    "mypy",
    "coverage",
    "benchmark",
    "lint",
)

#: ``(lead-in fragment, word)`` pairs that legitimately carry one anyway.  Each
#: needs its reason recorded, the way ``test_test_file_naming.py``'s do; the
#: entry must still match a real bullet, so a stale one fails.
ALLOWED: tuple[tuple[str, str, str], ...] = (
    (
        "Audio Refinery file-integrity gate",
        "gate",
        "the integrity gate is the user-facing name of the stage that rejects a "
        "corrupt file up front; it is not the release gate",
    ),
)


def _lines(path: Path) -> list[str]:
    """Return a changelog's lines without their terminators."""
    return path.read_text(encoding="utf-8").splitlines()


def _bullets(path: Path) -> list[str]:
    """Return each top-level bullet's full text, continuation lines joined."""
    bullets: list[str] = []
    current: list[str] = []
    for line in _lines(path):
        if line.startswith("- "):
            if current:
                bullets.append("\n".join(current))
            current = [line]
        elif current and line.strip() and not line.startswith("#"):
            current.append(line)
        elif current:
            bullets.append("\n".join(current))
            current = []
    if current:
        bullets.append("\n".join(current))
    return bullets


def _lead_in(bullet: str) -> str:
    """Return a bullet's subject: its bold lead-in, or its first sentence.

    A bare bullet (no bold lead-in) is its own subject, so its first sentence is
    what the audience lock reads.
    """
    match = re.match(r"- \*\*(.+?)\*\*", bullet)
    if match:
        return match.group(1)
    plain = bullet[2:]
    return plain.split(". ")[0]


def developer_words(text: str) -> set[str]:
    """Return the developer-work words *text* uses.

    Args:
        text: A bullet's lead-in.

    Returns:
        The stems found, plus ``"ci"`` when the abbreviation appears as a word.
    """
    found: set[str] = set()
    for stem in DEVELOPER_STEMS:
        if re.search(rf"\b{stem}\w*", text, re.IGNORECASE):
            found.add(stem)
    if re.search(r"\bCI\b", text):
        found.add("ci")
    return found


def _allowed(lead_in: str, word: str) -> bool:
    """Whether *word* is allowlisted for a bullet with this lead-in."""
    return any(
        fragment in lead_in and allowed == word for fragment, allowed, _ in ALLOWED
    )


@pytest.mark.parametrize("path", CHANGELOGS, ids=lambda path: path.name)
class TestChangelogFormat:
    """Each change-history file is a wrapped, diff-friendly Markdown document."""

    def test_the_scan_sees_the_changelog(self, path: Path) -> None:
        """A missing or renamed file must fail, not pass vacuously."""
        assert path.is_file(), f"{path} is missing"
        lines = _lines(path)
        assert len(lines) > 100, f"{path.name} scan collapsed: {len(lines)} lines"
        assert "## [Unreleased]" in lines, f"{path.name}: Unreleased is missing"

    def test_every_line_fits_the_column_limit(self, path: Path) -> None:
        offenders = [
            f"{number}: {len(line)} cols — {line[:60]}…"
            for number, line in enumerate(_lines(path), start=1)
            if len(line) > MAX_LINE_LENGTH
        ]
        assert not offenders, (
            f"{path.name} lines over {MAX_LINE_LENGTH} columns must be wrapped "
            "(ruff format excludes Markdown, so this lock owns it):\n  "
            + "\n  ".join(offenders)
        )

    def test_no_tabs_or_trailing_whitespace(self, path: Path) -> None:
        offenders = [
            f"{number}: {'tab' if chr(9) in line else 'trailing whitespace'}"
            for number, line in enumerate(_lines(path), start=1)
            if chr(9) in line or line != line.rstrip()
        ]
        assert not offenders, f"{path.name} whitespace defects:\n  " + "\n  ".join(
            offenders
        )

    def test_bullets_use_a_two_space_hanging_indent(self, path: Path) -> None:
        """A wrapped bullet keeps its body indented two spaces, never column 0."""
        offenders: list[str] = []
        in_bullet = False
        for number, line in enumerate(_lines(path), start=1):
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
            f"a wrapped {path.name} bullet must indent its continuation by two "
            "spaces so the list stays one item:\n  " + "\n  ".join(offenders)
        )


class TestChangelogAudience:
    """``CHANGELOG.md`` carries only what a user can run or observe (U2)."""

    def test_the_scan_sees_the_bullets(self) -> None:
        """Two files, two audiences: neither half may go empty unnoticed."""
        user_bullets = _bullets(USER_CHANGELOG)
        technical_bullets = _bullets(TECHNICAL_CHANGELOG)
        headings = [line for line in _lines(USER_CHANGELOG) if line.startswith("## [")]

        assert len(user_bullets) > 100, (
            f"user changelog scan collapsed: {len(user_bullets)} bullets"
        )
        assert technical_bullets, "the technical changelog holds no bullets at all"
        assert len(headings) > 10, f"version scan collapsed: {len(headings)} headings"

    def test_no_bullet_opens_on_developer_work(self) -> None:
        """A bullet's subject is what decides its audience."""
        offenders: list[str] = []
        used_allowlist: set[tuple[str, str]] = set()
        for bullet in _bullets(USER_CHANGELOG):
            lead_in = _lead_in(bullet)
            for word in sorted(developer_words(lead_in)):
                if _allowed(lead_in, word):
                    used_allowlist.add(
                        next(
                            (fragment, allowed)
                            for fragment, allowed, _ in ALLOWED
                            if fragment in lead_in and allowed == word
                        )
                    )
                    continue
                offenders.append(f"{word!r} in: {lead_in[:80]}")
        assert not offenders, (
            "these CHANGELOG.md bullets open on developer work, so they belong in "
            "TECHNICAL_CHANGELOG.md:\n  " + "\n  ".join(offenders)
        )
        assert used_allowlist == {(fragment, word) for fragment, word, _ in ALLOWED}, (
            "a stale allowlist entry no longer matches a real bullet"
        )

    def test_the_lock_rejects_the_two_bullets_the_split_moved(self) -> None:
        """The proof it can fail, kept as a test rather than a one-off run."""
        release_gate = "The release gate reports its progress while it runs."
        refinery_tests = (
            "Two Refinery tests are gated on a measured capability, not on `CI`."
        )

        assert {"gate"} <= developer_words(release_gate)
        assert {"test", "gate", "ci"} <= developer_words(refinery_tests)

    def test_the_user_file_points_at_the_technical_one(self) -> None:
        """The detail is moved, never lost, and a reader can follow it."""
        text = USER_CHANGELOG.read_text(encoding="utf-8")
        header = text.split("## [Unreleased]")[0]

        assert "TECHNICAL_CHANGELOG.md" in header, (
            "CHANGELOG.md must point at the technical file in its header"
        )
        assert TECHNICAL_CHANGELOG.is_file()
        assert "CHANGELOG.md" in TECHNICAL_CHANGELOG.read_text(encoding="utf-8")
