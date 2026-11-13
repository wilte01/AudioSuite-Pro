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

Changed in 2.6.0: adds ``TestChangelogCategories``.  The five sections from
2.4.1 forward reached both files as flat bullet lists - ``promote_changelog``
copies the ``[Unreleased]`` body verbatim and nothing required a category - so
the six Keep a Changelog headings are restored across 70 bullets and now
enforced, with the bold lead-in deciding the category exactly as it decides the
audience.

Changed in 2.7.0: adds ``TestChangelogSpelling``.  ``AGENTS.md`` requires British
spelling in both change-history files, but no gate read them for it - the
2026-11-13 wording pass found stray American forms in the technical file alone.
A product name, a shipped option, a file name and a quoted message keep their
spelling, so each allowance carries a reason and must still match a real line.

Changed in 2.7.0: the table, the allowances and ``spelling_offences`` moved to
``tests/spelling.py``, because the shipped guides are now held to the same rule
and one implementation serves both locks (D-27).  This module re-exports the
allowances under the name its tests use.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.spelling import (
    AMERICAN_SPELLINGS,
    CHANGELOG_ALLOWANCES,
    MIN_ALLOWANCES,
    MIN_SPELLING_LINES,
    MIN_SPELLING_PATTERNS,
)
from tests.spelling import (
    spelling_offences as _changelog_offences,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
USER_CHANGELOG = REPO_ROOT / "CHANGELOG.md"
TECHNICAL_CHANGELOG = REPO_ROOT / "TECHNICAL_CHANGELOG.md"
CHANGELOGS = (USER_CHANGELOG, TECHNICAL_CHANGELOG)

#: Same column limit the Python sources use.
MAX_LINE_LENGTH = 88

#: The Keep a Changelog vocabulary, in the order a section should use it.
CATEGORIES: tuple[str, ...] = (
    "Added",
    "Changed",
    "Deprecated",
    "Removed",
    "Fixed",
    "Security",
)

#: The one legal form of a category heading.
CATEGORY_HEADINGS = frozenset(f"### {name}" for name in CATEGORIES)

#: Floors the category scan must clear, so a broken walk fails instead of
#: passing over nothing.
MIN_SECTIONS = 18
MIN_BULLETS = 100

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


def _sections_in(text: str) -> list[tuple[str, list[str]]]:
    """Return each ``## [`` section's heading and its body lines.

    Taking the text rather than a path is what lets the proof below run the
    same checks over a miniature document.
    """
    sections: list[tuple[str, list[str]]] = []
    heading: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if heading is not None:
                sections.append((heading, body))
            heading, body = line, []
        elif heading is not None:
            body.append(line)
    if heading is not None:
        sections.append((heading, body))
    return sections


def _sections(path: Path) -> list[tuple[str, list[str]]]:
    """Return *path*'s sections, heading and body."""
    return _sections_in(path.read_text(encoding="utf-8"))


def _category_headings(body: list[str]) -> set[str]:
    """Return the category headings a section body carries."""
    return {line.strip() for line in body if line.startswith("### ")}


def _unknown_headings(body: list[str]) -> set[str]:
    """Return ``###`` headings outside the Keep a Changelog vocabulary."""
    return _category_headings(body) - CATEGORY_HEADINGS


def _bullets_under_no_category(body: list[str]) -> list[str]:
    """Return bullets no heading precedes, so they belong to no category."""
    current: str | None = None
    offenders: list[str] = []
    for line in body:
        if line.startswith("### "):
            current = line.strip()
        elif line.startswith("- ") and current is None:
            offenders.append(line[:70])
    return offenders


def _empty_categories(body: list[str]) -> list[str]:
    """Return category headings that hold no bullet of their own."""
    offenders: list[str] = []
    heading: str | None = None
    holds_bullet = False
    for line in body:
        if line.startswith("### "):
            if heading is not None and not holds_bullet:
                offenders.append(heading)
            heading, holds_bullet = line.strip(), False
        elif line.startswith("- ") and heading is not None:
            holds_bullet = True
    if heading is not None and not holds_bullet:
        offenders.append(heading)
    return offenders


def _bullet_count(body: list[str]) -> int:
    """Return how many top-level bullets a section body holds."""
    return sum(1 for line in body if line.startswith("- "))


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


@pytest.mark.parametrize("path", CHANGELOGS, ids=lambda path: path.name)
class TestChangelogCategories:
    """Every section is grouped under a Keep a Changelog category heading.

    A release is read to find out whether a change is a new capability, a
    behaviour change or a repaired defect, and a flat list makes that reader
    infer it from each sentence.  The headings are therefore part of the
    format, not decoration, and the release cut promotes them unchanged.
    """

    def test_the_scan_sees_every_section(self, path: Path) -> None:
        """A broken walk must fail, not report every section as categorised."""
        sections = _sections(path)
        bullets = sum(_bullet_count(body) for _heading, body in sections)

        assert len(sections) >= MIN_SECTIONS, (
            f"{path.name} section scan collapsed: {len(sections)} sections"
        )
        assert bullets >= MIN_BULLETS, (
            f"{path.name} bullet scan collapsed: {bullets} bullets"
        )
        assert any(
            heading.startswith("## [Unreleased]") for heading, _body in sections
        ), f"{path.name} carries no [Unreleased] section"

    def test_every_section_with_bullets_carries_a_category(self, path: Path) -> None:
        """A released section that lists bullets flat has lost its headings."""
        offenders = [
            f"{heading} ({_bullet_count(body)} bullets)"
            for heading, body in _sections(path)
            if _bullet_count(body) and not _category_headings(body)
        ]
        assert not offenders, (
            f"{path.name} sections list bullets without a category heading - "
            "group each under Added/Changed/Removed/Fixed/Security:\n  "
            + "\n  ".join(offenders)
        )

    def test_every_bullet_sits_under_a_category(self, path: Path) -> None:
        """A bullet above the first heading escapes the grouping."""
        offenders = [
            f"{heading}: {bullet}"
            for heading, body in _sections(path)
            for bullet in _bullets_under_no_category(body)
        ]
        assert not offenders, (
            f"{path.name} bullets sit under no category heading:\n  "
            + "\n  ".join(offenders)
        )

    def test_only_the_six_category_names_are_used(self, path: Path) -> None:
        """The vocabulary is closed: no ``### Deleted``, no ``### Notes``."""
        offenders = [
            f"{heading}: {sorted(_unknown_headings(body))}"
            for heading, body in _sections(path)
            if _unknown_headings(body)
        ]
        assert not offenders, (
            f"{path.name} uses headings outside the six categories "
            f"({', '.join(CATEGORIES)}):\n  " + "\n  ".join(offenders)
        )

    def test_no_category_heading_is_empty(self, path: Path) -> None:
        """A heading with nothing under it reads as a category with no entries."""
        offenders = [
            f"{heading}: {_empty_categories(body)}"
            for heading, body in _sections(path)
            if _empty_categories(body)
        ]
        assert not offenders, (
            f"{path.name} category headings hold no bullet:\n  "
            + "\n  ".join(offenders)
        )

    def test_an_empty_section_is_the_unreleased_one(self, path: Path) -> None:
        """Only ``[Unreleased]`` may be empty; a released version is a record."""
        offenders = [
            heading
            for heading, body in _sections(path)
            if not _bullet_count(body) and not heading.startswith("## [Unreleased]")
        ]
        assert not offenders, (
            f"{path.name} released sections hold no bullets at all:\n  "
            + "\n  ".join(offenders)
        )


class TestChangelogCategoryLockCanFail:
    """The category lock is proved able to fail where the defect lived.

    Kept as tests rather than a one-off run: the checkers are fed the shapes
    that must be rejected, and one that must be accepted, so a rule that
    silently stopped matching cannot pass as enforcement.
    """

    def test_it_rejects_a_flat_section(self) -> None:
        """The flat shape is 2.4.2's real body, which shipped as one list."""
        flat = (
            "## [2.4.2] - 2026-11-04\n\n"
            "- **WMA files are reported as unsupported.** It is refused.\n"
        )
        heading, body = _sections_in(flat)[0]

        assert heading == "## [2.4.2] - 2026-11-04"
        assert _category_headings(body) == set()
        assert _bullets_under_no_category(body) == [
            "- **WMA files are reported as unsupported.** It is refused."
        ]

    def test_it_rejects_an_unknown_heading(self) -> None:
        """``### Deleted`` is outside the closed vocabulary."""
        assert _unknown_headings(["### Deleted", ""]) == {"### Deleted"}

    def test_it_rejects_an_empty_category(self) -> None:
        """A heading with no bullet under it is not a category."""
        assert _empty_categories(["### Added", ""]) == ["### Added"]

    def test_it_accepts_a_bullet_under_a_category(self) -> None:
        """The positive control: the checker is not simply always angry."""
        assert _bullets_under_no_category(["### Fixed", "", "- **A fix.** Ok."]) == []


#: The spelling table and the changelog allowances live in
#: ``tests/spelling.py``, because the shipped guides are held to the same rule and
#: must not carry a second copy of it.  This name is what the tests below use.
ALLOWED_SPELLINGS = CHANGELOG_ALLOWANCES


def spelling_offences(text: str) -> list[str]:
    """Return every American spelling in a change-history file.

    Args:
        text: A changelog's full source.

    Returns:
        One ``line: word - use 'british'`` report per offending word.
    """
    return _changelog_offences(text, ALLOWED_SPELLINGS)


class TestChangelogSpelling:
    """Both change-history files are written in British English.

    The rule is in ``AGENTS.md`` (*Change History Follows Its Audience*), and
    nothing read the two files for it: they are prose, so no compiler, linter or
    formatter sees them, and the 2026-11-13 wording pass found stray
    ``artifact``, ``analyzer``, ``normalized`` and ``materializes`` in the
    technical file alone.  A product name, a shipped option, a file name and a
    quoted message keep their spelling, so each is allowlisted with its reason.
    """

    def test_the_scan_sees_the_words(self) -> None:
        """A collapsed table must fail rather than report every file clean."""
        assert len(AMERICAN_SPELLINGS) >= MIN_SPELLING_PATTERNS
        assert len(ALLOWED_SPELLINGS) >= MIN_ALLOWANCES
        for path in CHANGELOGS:
            lines = _lines(path)
            assert len(lines) >= MIN_SPELLING_LINES, (
                f"{path.name} spelling scan collapsed: {len(lines)} lines"
            )

    @pytest.mark.parametrize("path", CHANGELOGS, ids=lambda path: path.name)
    def test_no_american_spelling_survives(self, path: Path) -> None:
        """Every word the table names is British, or inside an allowance."""
        offences = spelling_offences(path.read_text(encoding="utf-8"))
        assert not offences, (
            f"{path.name} uses American spellings - use the British form, or add "
            "an allowlist entry with a reason when the word is a name or a "
            "quotation:\n  " + "\n  ".join(offences)
        )

    def test_every_allowance_is_load_bearing(self) -> None:
        """A stale allowance would pre-approve the next American spelling."""
        text = "\n".join(path.read_text(encoding="utf-8") for path in CHANGELOGS)
        stale = [
            f"{snippet!r} ({reason})"
            for snippet, reason in ALLOWED_SPELLINGS
            if snippet not in text
        ]
        assert not stale, (
            "these spelling allowances match no changelog line, so they are dead "
            "weight that would let a real offence through:\n  " + "\n  ".join(stale)
        )

    def test_the_check_rejects_the_spellings_it_was_added_for(self) -> None:
        """The proof it can fail, kept as a test rather than a one-off run."""
        for line in (
            "The artifact is gone.",
            "The analyzer reported no tempo.",
            "A normalized-float path.",
            "The runner materializes a fixture.",
            "The behavior is unchanged.",
            "The license is checked.",
        ):
            assert spelling_offences(line), line

    def test_the_check_accepts_british_prose_and_allowlisted_names(self) -> None:
        """The positive control: the checker is not simply always angry."""
        accepted = (
            "The artefact is gone; the analyser reported no tempo.",
            "Normalise the behaviour before the materialised fixture.",
            "BPM Analyzer writes the tag Tempo Analyzer reads.",
            "The suite reads the `licenses\\` folder and the `LICENSE` file.",
        )
        for line in accepted:
            assert spelling_offences(line) == [], line
