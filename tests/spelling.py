"""The suite's one British-spelling checker, shared by its three prose locks.

``AGENTS.md`` (*Change History Follows Its Audience*) requires British spelling in
the change-history files and in the shipped prose - the guides and the Sphinx
pages. Prose is invisible to every other gate - no compiler, linter or formatter
reads it - so this module holds the table once and every lock imports it, and a
word added here is added everywhere instead of in three drifting copies.

The exception this module exists to make mechanical: a product name, a shipped
label, a command name and a file or folder name keep their spelling, because
renaming one is a product change rather than a correction. Those are
``(snippet, reason)`` allowances, a match is excused only when it lies *inside*
an allowance, and each lock asserts its own allowances still match a real line so
a stale entry cannot pre-approve the next offence.

Changed in 2.7.0: the table, the allowances and ``spelling_offences`` moved here
from ``tests/test_changelog_format.py`` so the guide lock
(``tests/test_guide_spelling.py``) reads the same implementation (D-27).

Changed in 2.7.0: the prose extraction is named for prose rather than for guides,
because the Sphinx pages under ``documentation/docs`` are checked by the same
walk and the same allowances (D-28). They were clean on the first run, which is
the point of locking them: nothing else reads that prose either.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

#: American spellings the locks must not use, with the British form to use.
#: ``licensed`` is deliberately absent: it is the British verb, while the noun is
#: ``licence``.  A word that already ends in ``-ise`` never matches these.
AMERICAN_SPELLINGS: tuple[tuple[str, str], ...] = (
    (r"\bbehavior(s|al)?\b", "behaviour"),
    (r"\bcolors?\b", "colour"),
    (r"\bcolored\b", "coloured"),
    (r"\bcenters?\b", "centre"),
    (r"\bcentered\b", "centred"),
    (r"\bgray(ed)?\b", "grey"),
    (r"\bdefense\b", "defence"),
    (r"\bfulfill\w*\b", "fulfil"),
    (r"\benroll\w*\b", "enrol"),
    (r"\bcanceled\b", "cancelled"),
    (r"\btraveled\b", "travelled"),
    (r"\bmodeled\b", "modelled"),
    (r"\blabeled\b", "labelled"),
    (r"\bfavors?\b", "favour"),
    (r"\bfavored\b", "favoured"),
    (r"\bhonors?\b", "honour"),
    (r"\bhonored\b", "honoured"),
    (r"\bskeptic\w*\b", "sceptic"),
    (r"\bjudgment\b", "judgement"),
    (r"\backnowledgment\b", "acknowledgement"),
    (r"\baluminum\b", "aluminium"),
    (r"\bmaneuver\w*\b", "manoeuvre"),
    (r"\bpracticing\b", "practising"),
    (r"\banalyz(e|ed|es|ing)\b", "analyse"),
    (r"\banalyzers?\b", "analyser"),
    (r"\bnormaliz(e|ed|es|ing|ation)\b", "normalise"),
    (r"\bnormalizers?\b", "normaliser"),
    (r"\borganiz(e|ed|es|ing|ation)\b", "organise"),
    (r"\borganizers?\b", "organiser"),
    (r"\brecogniz\w*\b", "recognise"),
    (r"\bserializ\w*\b", "serialise"),
    (r"\bsynchroniz\w*\b", "synchronise"),
    (r"\binitializ\w*\b", "initialise"),
    (r"\bcustomiz\w*\b", "customise"),
    (r"\bcategoriz\w*\b", "categorise"),
    (r"\bprioritiz\w*\b", "prioritise"),
    (r"\bsummariz\w*\b", "summarise"),
    (r"\butiliz\w*\b", "utilise"),
    (r"\bmaterializ\w*\b", "materialise"),
    (r"\bartifact(s)?\b", "artefact"),
    (r"\bcatalog\b", "catalogue"),
    (r"\blicense\b", "licence (the noun)"),
    (r"\blicenses\b", "licences (the noun)"),
)

#: The tool names that ship with an American spelling.  Their labels are part of
#: the product, so the prose quotes them as they are; changing one would be a
#: rename, not a correction.
SHIPPED_NAMES: tuple[tuple[str, str], ...] = (
    ("File Reorganizer", "the tool's shipped name"),
    ("Audio Normalizer", "the tool's shipped name"),
    ("Album Art Normalizer", "the tool's shipped name"),
    ("BPM Analyzer", "the tool's shipped name"),
    ("Mood Analyzer", "the tool's shipped name"),
    ("Tempo Analyzer", "the tool's shipped name"),
    ("ReplayGain Analyzer", "the tool's shipped name"),
)

#: ``(snippet, reason)`` pairs that legitimately carry an American form in the two
#: change-history files.  A match is allowed only when it lies *inside* one of
#: these snippets, so a line that names a tool cannot hide a real American
#: spelling beside it, and every entry must still match a line or it is dead
#: weight.
CHANGELOG_ALLOWANCES: tuple[tuple[str, str], ...] = SHIPPED_NAMES + (
    ("Analyzer:", "the batch-verdict example wraps 'BPM Analyzer' over a line"),
    ("Error initializing the muxer", "a quoted FFmpeg error message"),
    ("LICENSE", "the licence file's name"),
    ("licenses\\", "the installed licences folder's name"),
    ("packaging/licenses", "the source-checkout licences folder's name"),
    ("--normalize-mp3", "the shipped command-line option"),
    ("partially initialized module", "a quoted interpreter error message"),
)

#: The same idea for shipped prose - the user guides and the Sphinx pages: a
#: button caption, a bulk-operation caption, the registered command name, the
#: shipped flag and the installed folder's name.  The guides use every entry, so
#: ``TestGuideSpelling`` proves each one still matches a line; the docs pages
#: quote the same shipped text and add no allowance of their own.
PROSE_ALLOWANCES: tuple[tuple[str, str], ...] = SHIPPED_NAMES + (
    ("BEGIN ARTWORK NORMALIZATION", "the button caption the tool ships"),
    ("Normalize Slashes", "the bulk-operation caption the Tag Editor ships"),
    ("mood-analyzer", "the registered command name"),
    ("--normalize-mp3", "the shipped command-line option"),
    ("licenses folder", "the installed folder's name"),
)

#: Floors the scans must clear, so a broken table cannot pass quietly.
MIN_SPELLING_PATTERNS = 25
MIN_ALLOWANCES = 8
MIN_SPELLING_LINES = 1000
MIN_GUIDES = 30
MIN_GUIDE_PROSE_LINES = 1000
MIN_DOCS_PAGES = 6
MIN_DOCS_PROSE_LINES = 600

#: The two prose corpora, relative to the repository root.
GUIDE_ROOT = Path("documentation/user_guides")
DOCS_ROOT = Path("documentation/docs")

#: A fenced code block, and an inline code span, are code rather than prose: a
#: command or a value keeps the spelling the program accepts.
_FENCE = re.compile(r"^\s*(```|~~~)")
_INLINE_CODE = re.compile(r"`[^`]*`")


def allowed_spelling(
    line: str, start: int, end: int, allowances: Iterable[tuple[str, str]]
) -> bool:
    """Whether the match at *start*:*end* lies inside an allowlisted snippet.

    Args:
        line: The line the match was found on.
        start: Match start offset in *line*.
        end: Match end offset in *line*.
        allowances: ``(snippet, reason)`` pairs excused in this corpus.

    Returns:
        True when the match sits wholly inside one of the snippets.
    """
    for snippet, _reason in allowances:
        at = line.find(snippet)
        while at != -1:
            if at <= start and end <= at + len(snippet):
                return True
            at = line.find(snippet, at + 1)
    return False


def spelling_offences(
    text: str, allowances: Iterable[tuple[str, str]] = CHANGELOG_ALLOWANCES
) -> list[str]:
    """Return every American spelling in *text* that no allowance covers.

    Args:
        text: A document's full source.
        allowances: The ``(snippet, reason)`` pairs excused in this corpus.

    Returns:
        One ``line: word - use 'british'`` report per offending word.
    """
    offences: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for pattern, british in AMERICAN_SPELLINGS:
            for match in re.finditer(pattern, line, re.IGNORECASE):
                if allowed_spelling(line, match.start(), match.end(), allowances):
                    continue
                offences.append(
                    f"{number}: {match.group(0)!r} should be {british!r} - "
                    f"{line.strip()[:60]}"
                )
    return offences


def prose_lines(text: str) -> list[tuple[int, str]]:
    """Return ``(line number, prose)`` for a page, with its code removed.

    A fenced block is dropped whole, and an inline span is blanked in place, so a
    command such as ``--normalize-mp3`` or a value such as ``gray`` is not prose
    and cannot be spelled wrong.

    Args:
        text: A page's full Markdown source.

    Returns:
        Every remaining line with its original line number.
    """
    out: list[tuple[int, str]] = []
    fence: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if fence is not None:
            if stripped.startswith(fence):
                fence = None
            continue
        if _FENCE.match(line):
            fence = "```" if stripped.startswith("```") else "~~~"
            continue
        out.append((number, _INLINE_CODE.sub(" ", line)))
    return out


def prose_offences(
    text: str, allowances: Iterable[tuple[str, str]] = PROSE_ALLOWANCES
) -> list[str]:
    """Return every American spelling in a page's prose.

    Args:
        text: A page's full Markdown source.
        allowances: The ``(snippet, reason)`` pairs excused in shipped prose.

    Returns:
        One ``line: word - use 'british'`` report per offending word.
    """
    offences: list[str] = []
    for number, prose in prose_lines(text):
        for pattern, british in AMERICAN_SPELLINGS:
            for match in re.finditer(pattern, prose, re.IGNORECASE):
                if allowed_spelling(prose, match.start(), match.end(), allowances):
                    continue
                offences.append(
                    f"{number}: {match.group(0)!r} should be {british!r} - "
                    f"{prose.strip()[:60]}"
                )
    return offences
