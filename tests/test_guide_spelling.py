"""The shipped user guides are written in British English, and a gate reads them.

``AGENTS.md`` (*Change History Follows Its Audience*) requires British spelling in
the guides as well as in the change-history files, and nothing checked it: guides
are prose, so no compiler, linter or formatter sees them, and the spellings drifted
back in - the 2026-11-13 sweep found 77 American forms across 18 of the 35 guides,
including two section headings and the word "analyzer" used for a generic tool.

The check reuses ``tests/spelling.py`` rather than a second table, so a word added
for the changelogs is checked here too.  A fenced block and an inline code span
are code, not prose: ``--normalize-mp3`` and the colormap value ``gray`` keep the
spelling the program accepts, and a shipped caption ("BEGIN ARTWORK
NORMALIZATION"), the registered command name and the installed ``licenses``
folder keep theirs as allowances with a reason.

Changed in 2.7.0: adds ``TestGuideSpelling``, the guide half of the spelling
boundary (D-27).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.spelling import (
    AMERICAN_SPELLINGS,
    GUIDE_ROOT,
    MIN_GUIDE_PROSE_LINES,
    MIN_GUIDES,
    MIN_SPELLING_PATTERNS,
    PROSE_ALLOWANCES,
    prose_lines,
    prose_offences,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
GUIDES = sorted((REPO_ROOT / GUIDE_ROOT).rglob("*.md"))


class TestGuideSpelling:
    """Every shipped guide's prose is in British English."""

    def test_the_scan_sees_the_guides(self) -> None:
        """A walk that finds nothing must fail rather than report every file clean."""
        assert len(GUIDES) >= MIN_GUIDES, (
            f"the guide walk found {len(GUIDES)} files, expected at least "
            f"{MIN_GUIDES} under {GUIDE_ROOT}"
        )
        total_prose = sum(
            len(prose_lines(guide.read_text(encoding="utf-8"))) for guide in GUIDES
        )
        assert total_prose >= MIN_GUIDE_PROSE_LINES, (
            f"only {total_prose} prose lines survived the code fence filter"
        )
        assert len(AMERICAN_SPELLINGS) >= MIN_SPELLING_PATTERNS
        assert len(PROSE_ALLOWANCES) >= 8

    @pytest.mark.parametrize("guide", GUIDES, ids=lambda path: path.stem)
    def test_no_american_spelling_survives(self, guide: Path) -> None:
        """Every word the table names is British, or inside an allowance."""
        offences = prose_offences(guide.read_text(encoding="utf-8"))
        assert not offences, (
            f"{guide.name} uses American spellings - use the British form, or add a "
            "guide allowance with a reason when the word is a shipped name, label "
            "or command:\n  " + "\n  ".join(offences)
        )

    def test_every_allowance_is_load_bearing(self) -> None:
        """A stale allowance would pre-approve the next American spelling."""
        text = "\n".join(guide.read_text(encoding="utf-8") for guide in GUIDES)
        stale = [
            f"{snippet!r} ({reason})"
            for snippet, reason in PROSE_ALLOWANCES
            if snippet not in text
        ]
        assert not stale, (
            "these guide allowances match no guide line, so they are dead weight "
            "that would let a real offence through:\n  " + "\n  ".join(stale)
        )

    def test_an_inline_code_span_is_not_prose(self) -> None:
        """A value keeps the spelling the program accepts."""
        text = "- Run `normalise --normalize-mp3` and set the map to `gray`.\n"
        assert prose_offences(text) == []

    def test_a_fenced_block_is_not_prose(self) -> None:
        """A command in a fence is code, including a flag the tool really has."""
        text = "Run this:\n\n```bash\nnormalise --normalize-mp3 in.mp3\n```\n"
        assert prose_offences(text) == []

    def test_it_rejects_the_prose_it_was_added_for(self) -> None:
        """The proof it can fail, kept as a test rather than a one-off run."""
        for line in (
            "The analyzer uses the shared format list.",
            "## Detection Behavior",
            "Results reports analyzed files.",
            "The signal is normalized before analysis.",
            "The engine normalizes separators.",
            "The notation is recognized.",
        ):
            assert prose_offences(line), line

    def test_it_accepts_a_shipped_caption_and_command(self) -> None:
        """The positive control: a product's own wording is not a typo."""
        accepted = (
            "1. Click BEGIN ARTWORK NORMALIZATION.",
            "| Normalize Slashes (TXXX Rule) | Replaces bare separators. |",
            "The registered command is mood-analyzer.",
            "An installed build reads its licenses folder.",
            "Open Album Art Normalizer from UTIL.",
        )
        for line in accepted:
            assert prose_offences(line) == [], line

    def test_it_reports_the_line_number(self) -> None:
        """A failure has to point the reader at the line to fix."""
        offences = prose_offences("Fine.\nAlso fine.\nThe analyzer ran.\n")
        assert offences and offences[0].startswith("3:"), offences
