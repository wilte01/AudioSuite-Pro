"""analysis.py — the example plugin's custom-analysis contribution.

``audiosuite stats`` runs every enabled analysis contribution once per file it
scans, handing it the tags the host already read (so a contribution never pays
for a second decode).  A contribution returns a mapping of metric name to
``int``, ``float`` or ``str``; the host counts how many files produced each
value (a value→file-count distribution, whatever the value's type) and
publishes the result under ``plugin_analysis`` in the JSON payload and the JSON
export.

Changed in 2.1.0: new module — the example analysis contribution (Item 7.2).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any


def analyse(path: Path, tags: Mapping[str, Any]) -> dict[str, int | str]:
    """Measure the file's title.

    Args:
        path: The audio file being scanned (unused, kept for the contract).
        tags: The tags the host read for this file.

    Returns:
        ``title_words`` (a number, aggregated as a mean) and ``title_state``
        (a category, aggregated as a histogram).
    """
    title = tags.get("title")
    words = str(title).split() if title else []
    return {
        "title_words": len(words),
        "title_state": "present" if words else "missing",
    }
