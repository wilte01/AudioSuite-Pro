"""duplicate_finder — local duplicate detection by Chromaprint fingerprint.

The suite could already say "these two files are the same recording according to
AcoustID"; this package answers the question a librarian asks instead — "how many
of these 400 files are really 250 recordings?" — without a network lookup.

Nothing here deletes audio.  A live run *moves* the duplicates it identified into
a quarantine folder and records the move in the undo journal, so the kept copy is
never touched and the decision is reversible.

Changed in 2.3.0: initial package (``PLAN_functional_backlog.md`` item F-02).
"""

from __future__ import annotations

__all__ = ["__version__"]

#: Informational only; the suite version is ``audio_suite_shared.project_version``.
__version__ = "1.0.0"
