"""run_outcome.py — one-line per-tool outcome notes for the Master Driver.

Changed in 1.2.0: initial version, so a refused or offline ISRC submission is
visible in the batch report instead of only in a tool's own log.
Changed in 1.2.0: adds :func:`record_caveats` and :func:`shortfall`, the shared
half of the wire — a tool states its counts once and every surface words them
the same way.

The Master Driver runs its tools as separate processes (Audio Fingerprinter is
a standalone window), so a step's exit status is the only thing the driver can
observe about a run by itself.  A tool that finishes with a caveat — an ISRC
submission MusicBrainz rejected, one skipped for a missing token — otherwise
communicates that only in its own log file, which nobody reads while watching a
batch run.

This module is the smallest shared channel for it: a tool records one
human-readable line keyed by its **manifest id**, and the driver reads it back
for the step line it prints.

Design rules:

* A note is *not* a status.  It never changes whether a step is reported
  completed or failed, so a refused submission cannot be mistaken for a failed
  whole run (and a failed run cannot hide behind a note).
* Notes live under ``<logs>/run_outcomes/<tool_id>.json``, so they inherit the
  ``AUDIOSUITE_LOG_DIR`` override (a test run never writes into the shipped
  ``logs/`` tree) and never litter a music folder.
* The driver clears a tool's note before starting its step.  That is what makes
  a note from an earlier run impossible to display against a fresh batch;
  :func:`read_outcome` additionally treats a missing, unreadable or malformed
  file as "no note" rather than raising into the batch report.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .logging_setup import get_logs_dir

#: Namespaced like every other shared module, so its records reach the suite
#: log through the ``audio_suite`` logger hierarchy
#: (``audio_suite_shared/tests/test_logging_namespacing.py``).
logger = logging.getLogger(f"audio_suite.{__name__}")

#: Directory (under the suite logs dir) holding the per-tool note files.
OUTCOME_DIR_NAME = "run_outcomes"

#: Longest note kept.  The batch report prints one line per step, so a note that
#: grows without bound would push the step list off the panel.
MAX_NOTE_CHARS = 240

#: A manifest id, restricted to characters that cannot escape the directory.
_TOOL_ID = re.compile(r"[A-Za-z0-9_-]+\Z")


def outcome_path(tool_id: str) -> Path:
    """Return the file holding ``tool_id``'s note.

    Args:
        tool_id: The tool's manifest id (e.g. ``"fingerprinter"``).

    Returns:
        The note file's path, whether or not it exists.

    Raises:
        ValueError: if ``tool_id`` is empty or holds anything but letters,
            digits, ``_`` and ``-``.  Tool ids are manifest data, but the value
            becomes a file name, so a path separator or ``..`` is refused here
            rather than trusted.
    """
    if not _TOOL_ID.match(tool_id):
        raise ValueError(f"invalid tool id for a run outcome: {tool_id!r}")
    return get_logs_dir() / OUTCOME_DIR_NAME / f"{tool_id}.json"


def _one_line(note: str) -> str:
    """Collapse ``note`` to a single bounded line.

    Args:
        note: The note as the tool composed it (it may span lines).

    Returns:
        Whitespace-collapsed text of at most :data:`MAX_NOTE_CHARS` characters,
        with an ASCII ellipsis when it was cut.
    """
    collapsed = " ".join(note.split())
    if len(collapsed) <= MAX_NOTE_CHARS:
        return collapsed
    return collapsed[: MAX_NOTE_CHARS - 3].rstrip() + "..."


def shortfall(count: int, total: int, noun: str, outcome: str) -> str:
    """Return one caveat phrase: ``"3 of 12 tracks did not rip"``.

    Counts a run's damage the same way in every tool, so the batch report reads
    consistently and no tool has to remember the wording.  Callers pass this to
    :func:`record_caveats` alongside any other phrase.

    Args:
        count: How many of them ended this way (callers pass a non-zero count;
            a zero here means the caller should not be reporting at all).
        total: How many were attempted; omitted from the sentence when it is
            not known (0), because "3 files did not rip" beats "3 of 0".
        noun: Singular noun, pluralised to agree with the sentence's subject
            — the stated total when there is one, else the count.
        outcome: What happened to them, e.g. ``"did not rip"``.

    Returns:
        The phrase, e.g. ``"1 of 40 tracks did not rip"``.
    """
    if total <= 0:
        return f"{count} {noun if count == 1 else noun + 's'} {outcome}"
    return f"{count} of {total} {noun if total == 1 else noun + 's'} {outcome}"


def record_caveats(tool_id: str, *problems: str) -> str:
    """Record a finished run's caveats as one note, or clear them when clean.

    The call-site counterpart of :func:`shortfall`: a tool states its counts
    once and this decides whether they amount to anything worth reporting.
    Blank and whitespace-only phrases are ignored, so a caller can pass a
    phrase it computed unconditionally without an ``if`` of its own, and a run
    with nothing to report records nothing rather than an empty note.

    A note is best-effort: ``OSError`` (a read-only install, a full disk) is
    logged and swallowed, because the tool's own summary has already been shown
    and written to its log.  A ``ValueError`` for an unusable tool id is *not*
    caught — that is a defect in the caller, and the contract test on the id
    constants is what keeps it out of the tree.

    Args:
        tool_id: The tool's manifest id.
        *problems: One phrase per thing that went wrong, in the order they
            should be read.

    Returns:
        The note that now stands for ``tool_id``; ``""`` when the run was clean
        (any earlier note is cleared) or when the note could not be stored.
    """
    phrases = [problem.strip() for problem in problems if problem and problem.strip()]
    note = _one_line("; ".join(phrases))
    if not note:
        clear_outcome(tool_id)
        return ""

    try:
        record_outcome(tool_id, note)
    except OSError:
        logger.debug("Could not record the run caveats for %s", tool_id, exc_info=True)
        return ""
    return note


def record_outcome(tool_id: str, note: str) -> None:
    """Record ``note`` as ``tool_id``'s outcome for the current batch.

    The write is atomic (a temporary file replaced into position), so a driver
    reading the note while another tool records its own can never see a
    half-written document.

    Args:
        tool_id: The tool's manifest id.
        note: One line describing the outcome.  An empty (or whitespace-only)
            note clears the tool's record instead.

    Raises:
        ValueError: if ``tool_id`` is not a valid id (see :func:`outcome_path`).
        OSError: if the note cannot be written; callers report their outcome
            through their own channel first, so a failed note is not fatal.
    """
    cleaned = _one_line(note)
    if not cleaned:
        clear_outcome(tool_id)
        return

    path = outcome_path(tool_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "tool_id": tool_id,
        "note": cleaned,
        "recorded": datetime.now().isoformat(timespec="seconds"),
    }
    temp = path.with_name(f"{path.name}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)


def read_outcome(tool_id: str) -> str:
    """Return ``tool_id``'s recorded note, or ``""`` when there is none.

    Args:
        tool_id: The tool's manifest id.

    Returns:
        The note, or ``""`` when no note was recorded, the file cannot be read,
        or its content is not a note.  Never raises: this feeds a UI line, and a
        damaged file must not take the batch report down with it.
    """
    try:
        path = outcome_path(tool_id)
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    note = payload.get("note") if isinstance(payload, dict) else None
    return _one_line(note) if isinstance(note, str) else ""


def clear_outcome(tool_id: str) -> None:
    """Forget ``tool_id``'s note; safe when nothing was recorded.

    Args:
        tool_id: The tool's manifest id.
    """
    try:
        outcome_path(tool_id).unlink()
    except OSError:
        return


__all__ = [
    "MAX_NOTE_CHARS",
    "OUTCOME_DIR_NAME",
    "clear_outcome",
    "outcome_path",
    "read_outcome",
    "record_caveats",
    "record_outcome",
    "shortfall",
]
