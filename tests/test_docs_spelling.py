"""The Sphinx documentation pages are written in British English, and a gate reads them.

``AGENTS.md`` (*Change History Follows Its Audience*) applies the spelling rule to
the suite's prose, and the pages under ``documentation/docs`` are the half nobody
read: they are Markdown rendered by MyST, so no compiler, linter or formatter sees
them either.  They were clean when this lock was added - measured, not assumed:
965 prose lines across 8 pages, no offence - which is exactly why it exists, since
nothing else would notice the first one that appeared.

The check reuses ``tests/spelling.py``, so the table and the shipped-text
allowances are the ones ``TestGuideSpelling`` already asserts load-bearing.  A
fenced block and an inline code span are code rather than prose: a flag, a module
path or a value keeps the spelling the program accepts, and a page quotes a
shipped tool name as it ships.

Changed in 2.7.0: adds ``TestDocsSpelling``, the third prose corpus (D-28).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.spelling import (
    AMERICAN_SPELLINGS,
    DOCS_ROOT,
    MIN_DOCS_PAGES,
    MIN_DOCS_PROSE_LINES,
    MIN_SPELLING_PATTERNS,
    prose_lines,
    prose_offences,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PAGES = sorted((REPO_ROOT / DOCS_ROOT).rglob("*.md"))

#: Every page has to hold some prose, or the walk is reading the wrong files.
MIN_LINES_PER_PAGE = 20


class TestDocsSpelling:
    """Every Sphinx page's prose is in British English."""

    def test_the_scan_sees_the_pages(self) -> None:
        """A walk that finds nothing must fail rather than report every page clean."""
        assert len(PAGES) >= MIN_DOCS_PAGES, (
            f"the docs walk found {len(PAGES)} pages, expected at least "
            f"{MIN_DOCS_PAGES} under {DOCS_ROOT}"
        )
        prose_lines_total = sum(
            len(prose_lines(page.read_text(encoding="utf-8"))) for page in PAGES
        )
        assert prose_lines_total >= MIN_DOCS_PROSE_LINES, (
            f"only {prose_lines_total} prose lines survived the code fence filter"
        )
        assert len(AMERICAN_SPELLINGS) >= MIN_SPELLING_PATTERNS

    @pytest.mark.parametrize("page", PAGES, ids=lambda path: path.stem)
    def test_no_american_spelling_survives(self, page: Path) -> None:
        """Every word the table names is British, or inside a shipped allowance."""
        offences = prose_offences(page.read_text(encoding="utf-8"))
        assert not offences, (
            f"{page.name} uses American spellings - use the British form, or add a "
            "shipped-prose allowance with a reason when the word is a name, a "
            "label or a command:\n  " + "\n  ".join(offences)
        )

    def test_each_page_is_really_prose(self) -> None:
        """A page stripped to nothing would pass every check above vacuously."""
        thin = [
            page.name
            for page in PAGES
            if len(prose_lines(page.read_text(encoding="utf-8"))) < MIN_LINES_PER_PAGE
        ]
        assert not thin, (
            "these pages hold almost no prose after the code filter, so the "
            "spelling check reads nothing on them:\n  " + "\n  ".join(thin)
        )

    def test_it_rejects_the_prose_it_was_added_for(self) -> None:
        """The proof it can fail, kept as a test rather than a one-off run."""
        for line in (
            "The analyzer reads every module.",
            "## Error behavior",
            "The page is generated, not normalized.",
        ):
            assert prose_offences(line), line

    def test_it_accepts_a_shipped_name_and_a_code_span(self) -> None:
        """The positive control: a product's own wording is not a typo."""
        accepted = (
            "Mood Analyzer writes the tag Tempo Analyzer reads.",
            "Run `--normalize-mp3` on the converted file.",
            "| Colour map | magma | plasma or `gray`. |",
        )
        for line in accepted:
            assert prose_offences(line) == [], line
