"""duplicate_finder — local duplicate detection by Chromaprint fingerprint.

The suite could already say "these two files are the same recording according to
AcoustID"; this package answers the question a librarian asks instead — "how many
of these 400 files are really 250 recordings?" — without a network lookup.

Quarantine is the default: a live run *moves* the duplicates it identified into
a quarantine folder and records the move in the undo journal, so the kept copy
is never touched and the decision is reversible.  An opt-in run can instead
move duplicates to the operating system's Recycle Bin, or replace each one with
a verified ASX stub that the ASX Playlist Extractor can use to recreate it.
No path calls ``unlink`` on audio.

Changed in 2.4.0: adds the delete and ASX-stub dispositions
(``PLAN_duplicate_disposition_2026-11-02.md``).
"""

from __future__ import annotations

__all__ = ["__version__"]

#: Informational only; the suite version is ``audio_suite_shared.project_version``.
__version__ = "1.0.0"
