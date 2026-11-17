"""The auto-profile prose names what the detector actually measures.

The Refinery guide, ``CHANGELOG.md`` and ``TECHNICAL_CHANGELOG.md`` describe the
spectral gate's noise-profile search in words: a candidate window sits within a
number of decibels of the quietest, the flattest few of those are shortlisted,
the trial drops a candidate that removes more than a ceiling from the file's
loudest stretch, the report names that trial reading in decibels, and a tie at
zero falls to flatness.  Every number
there is a constant in :mod:`noise_reduction.core.noise_reducer`, so prose can
keep repeating a value the detector no longer uses and tell a reader what the
code stopped doing.  These locks read both sides together.

Each lock asks for the clause around its number, not the number on its own: the
window length, the consequence the range implies ("anything louder is content,
not a floor"), the ceiling a candidate is dropped for.  A bare ``12 dB``
somewhere in a 2,000-line changelog would satisfy a substring check and tell a
reader nothing.

The zero tie is the case worth spelling out: the trial is a guard, not a
ranking, so a musical rest and a hiss both pass it at 0.00 dB and flatness
decides between them.  A doc that says the trial *ranks* would describe a
detector that could pick a rest as the floor.  So that claim is locked to one
sentence at a time: a measurement in one paragraph and a decision in another
read as two facts, not as the tie falling to flatness.

Changed in 2.8.0: added with the auto profile's trial-ceiling guard.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from noise_reduction.core.models import NoiseWindow
from noise_reduction.core.noise_reducer import (
    _PROFILE_CANDIDATE_RANGE_DB,
    _PROFILE_CANDIDATES,
    _PROFILE_TRIAL_MAX_DB,
    _PROFILE_WINDOW_MS,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

REFINERY_GUIDE = (
    REPO_ROOT
    / "documentation"
    / "user_guides"
    / "individual_programs"
    / "audio_refinery"
    / "Audio_Refinery_User_Guide.md"
)
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
TECHNICAL_CHANGELOG = REPO_ROOT / "TECHNICAL_CHANGELOG.md"

#: The clause the three documents share, both numbers built from the detector:
#: the window length and how far from the quietest a candidate may sit.
_QUIETEST_WINDOW = (
    f"every {_PROFILE_WINDOW_MS} ms window within "
    f"{_PROFILE_CANDIDATE_RANGE_DB:g} dB of the quietest"
)
_LOUDER_IS_CONTENT = "anything louder is content, not a floor"

#: The reading the trial shows when a candidate takes nothing out of the loudest
#: stretch - the case where the guard has no opinion and flatness decides.
_ZERO_TIE_DB = "0.00 dB"


@dataclass(frozen=True)
class Prose:
    """One document, and the phrases each of its claims must still carry."""

    document: Path
    quietest: tuple[str, ...]
    shortlist: tuple[str, ...]
    trial: tuple[str, ...]
    tie: tuple[str, ...]


#: The documents that describe the search, in the order a reader meets them: the
#: guide, the release note, then the technical record behind it.
PROSE: tuple[Prose, ...] = (
    Prose(
        REFINERY_GUIDE,
        (_QUIETEST_WINDOW + " - " + _LOUDER_IS_CONTENT,),
        (
            f"trials the flattest {_PROFILE_CANDIDATES} of them against the "
            "file's loudest stretch",
        ),
        (
            "drops any window whose profile would take more than "
            f"{_PROFILE_TRIAL_MAX_DB:g} dB out of it",
        ),
        ("the tie at zero falls to flatness",),
    ),
    Prose(
        CHANGELOG,
        (_QUIETEST_WINDOW + " stretch in the file - " + _LOUDER_IS_CONTENT,),
        (f"trials the flattest {_PROFILE_CANDIDATES} against its loudest stretch",),
        (
            "drops any whose profile would take more than "
            f"{_PROFILE_TRIAL_MAX_DB:g} dB out of it",
        ),
        ("trial ties at zero there and flatness", "picks the hiss, not the trial"),
    ),
    Prose(
        TECHNICAL_CHANGELOG,
        (_QUIETEST_WINDOW + " as a candidate - " + _LOUDER_IS_CONTENT,),
        (f"The flattest {_PROFILE_CANDIDATES} are the shortlist",),
        (
            "a candidate that would remove more than `_PROFILE_TRIAL_MAX_DB` "
            f"({_PROFILE_TRIAL_MAX_DB:.1f} dB) there is dropped as content-derived",
        ),
        ("the tie at zero falls to flatness",),
    ),
)

_DOCUMENT_IDS = [prose.document.name for prose in PROSE]

#: Punctuation that ends a sentence, followed by something that starts one: a
#: capital, a markup marker or an opening bracket.  A stop inside a number is
#: followed by a digit or by a lowercase word, so ``0.00 dB`` and ``12.4-12.8 s``
#: stay inside their sentence.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z`*_(\[])")


def _text(path: Path) -> str:
    """Return a document's text with one line-ending and wrapping convention.

    Sentences are asserted whole, and Markdown wraps them mid-phrase; collapsing
    every run of whitespace to one space compares the prose, not the layout.
    """
    text = re.sub(r"\s+", " ", path.read_text(encoding="utf-8").replace("\r\n", "\n"))

    assert text, f"{path.name} is empty - the lock would pass vacuously"
    return text


def _sentences_stating(path: Path, phrases: tuple[str, ...]) -> list[str]:
    """Return the document's sentences that contain every one of the phrases."""
    return [
        sentence
        for sentence in _SENTENCE_END.split(_text(path))
        if sentence and all(phrase in sentence for phrase in phrases)
    ]


@pytest.mark.parametrize("prose", PROSE, ids=_DOCUMENT_IDS)
def test_every_document_names_the_detectors_quietest_window(prose: Prose) -> None:
    """Each document states the window, the range and what lies outside it."""
    assert _sentences_stating(prose.document, prose.quietest), (
        f"{prose.document.relative_to(REPO_ROOT)} no longer says, in one "
        f"sentence, {prose.quietest[0]!r}; _PROFILE_WINDOW_MS is "
        f"{_PROFILE_WINDOW_MS} and _PROFILE_CANDIDATE_RANGE_DB is "
        f"{_PROFILE_CANDIDATE_RANGE_DB:g} today"
    )


@pytest.mark.parametrize("prose", PROSE, ids=_DOCUMENT_IDS)
def test_every_document_shortlists_the_flattest_candidates(prose: Prose) -> None:
    """Each document trials the flattest ``_PROFILE_CANDIDATES`` windows."""
    assert _sentences_stating(prose.document, prose.shortlist), (
        f"{prose.document.relative_to(REPO_ROOT)} no longer trials the "
        f"flattest {_PROFILE_CANDIDATES} candidates "
        f"({prose.shortlist[0]!r} is the wording that says so); the shortlist "
        "size is _PROFILE_CANDIDATES"
    )


@pytest.mark.parametrize("prose", PROSE, ids=_DOCUMENT_IDS)
def test_every_document_guards_the_trial_ceiling(prose: Prose) -> None:
    """Each document drops a candidate that removes more than the ceiling."""
    assert _sentences_stating(prose.document, prose.trial), (
        f"{prose.document.relative_to(REPO_ROOT)} no longer drops a candidate "
        f"for removing more than {_PROFILE_TRIAL_MAX_DB:g} dB "
        f"({prose.trial[0]!r} is the wording that says so); the constant is "
        "_PROFILE_TRIAL_MAX_DB"
    )


@pytest.mark.parametrize("prose", PROSE, ids=_DOCUMENT_IDS)
def test_the_zero_tie_falls_to_flatness_in_one_sentence(prose: Prose) -> None:
    """One sentence carries both the 0.00 dB reading and flatness deciding."""
    assert _sentences_stating(prose.document, (*prose.tie, _ZERO_TIE_DB)), (
        f"{prose.document.relative_to(REPO_ROOT)} no longer says in one sentence "
        f"that a trial tying at {_ZERO_TIE_DB} falls to flatness "
        f"({', '.join(map(repr, prose.tie))}); the reading and the decision "
        "belong to the same claim - the trial is a guard, not a ranking"
    )


@pytest.mark.parametrize("prose", PROSE, ids=_DOCUMENT_IDS)
def test_the_documented_trial_reading_is_the_windows_report(prose: Prose) -> None:
    """The example line each document quotes is ``NoiseWindow.describe()``."""
    window = NoiseWindow(
        start_ms=12_400,
        end_ms=12_800,
        rms_dbfs=-62.0,
        flatness=0.85,
        trial_db=0.0,
    )
    reported = window.describe()

    assert reported == "auto 12.4-12.8 s at -62 dBFS, trial 0.0 dB", (
        "the report form changed; the documents' example lines and this lock "
        "must move with it"
    )
    assert reported in _text(prose.document), (
        f"{prose.document.relative_to(REPO_ROOT)} no longer quotes the report "
        f"form {reported!r}, so a reader cannot match a run's line to the guide"
    )
