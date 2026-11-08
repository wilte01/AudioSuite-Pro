"""
tag_prefs.py
Persist the user's "tags to keep" selection across sessions.

The selection is a flat list of TXXX descriptions, so it lives in the shared
``audio_suite_config.json`` under the single key
``metadata_scrubber_kept_tags`` - the same store every other tool preference
uses - and no file is written into the package folder.

Changed in 2.5.0: this module used to keep ``metadata_scrubber/tag_prefs.json``
beside the package, which a LIVE run rewrote inside the tracked tree and which
was not gitignored. A flat list fits one shared key, so the file moved to the
suite config; the old file is imported once on first use and then deleted.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from audio_suite_shared import suite_config
from audio_suite_shared.suite_paths import package_path

logger = logging.getLogger(__name__)

#: Shared-config key holding the sorted list of kept TXXX descriptions.
_KEY_KEPT_TAGS = "metadata_scrubber_kept_tags"

#: The pre-2.5.0 file. One canonical location, module-level so a test can point
#: it at a temporary directory - never a path argument a caller could vary.
LEGACY_PREFS_PATH: Path = package_path(__file__, "tag_prefs.json")


def _migrate_legacy() -> None:
    """Import a pre-2.5.0 ``tag_prefs.json`` once, then delete it.

    The shared key wins whenever it is already set, so a user who has saved a
    selection since upgrading never sees an old file reappear after clearing
    every tag. A malformed legacy file is logged and left in place: it is not
    this function's job to destroy data it cannot read.
    """
    legacy = LEGACY_PREFS_PATH
    if not legacy.is_file() or suite_config.load_value(_KEY_KEPT_TAGS) is not None:
        return
    try:
        data = json.loads(legacy.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Could not read legacy tag prefs %s: %s", legacy, exc)
        return
    tags = data.get("kept_tags") if isinstance(data, dict) else None
    if not isinstance(tags, list):
        logger.warning("Legacy tag prefs %s hold no kept_tags list", legacy)
        return
    suite_config.save_value(_KEY_KEPT_TAGS, [str(tag) for tag in tags])
    try:
        legacy.unlink()
    except OSError as exc:
        logger.warning("Could not delete migrated tag prefs %s: %s", legacy, exc)
    logger.info(
        "Migrated %d kept-tag preference(s) from %s to the suite config",
        len(tags),
        legacy,
    )


def load_kept_tags() -> set[str]:
    """Return the TXXX descriptions that were kept last time.

    Returns:
        The stored set, or an empty set when nothing has been saved yet (the
        normal first-run condition). A stored value that is not a list, or a
        list holding non-letter entries, degrades to what can be used rather
        than raising: a preference must never stop the tool starting.
    """
    _migrate_legacy()
    stored = suite_config.load_value(_KEY_KEPT_TAGS, [])
    if not isinstance(stored, list):
        return set()
    return {tag for tag in stored if isinstance(tag, str)}


def save_kept_tags(kept: list[str]) -> None:
    """Persist the sorted list of kept TXXX descriptions.

    Args:
        kept: The ticked descriptions from the setup tab. Stored sorted so the
            config file's diff is stable between runs.
    """
    _migrate_legacy()
    suite_config.save_value(_KEY_KEPT_TAGS, sorted(kept))
