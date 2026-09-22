"""
tag_prefs.py
Persist the user's "tags to keep" selection across sessions.

JSON layout:
    { "kept_tags": ["REPLAYGAIN_TRACK_GAIN", "TEMPO", ...] }

Stored as  metadata_scrubber/tag_prefs.json  alongside the package root,
so it travels with the tool if the folder is moved.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

_FILENAME = "tag_prefs.json"


def _prefs_path(package_dir: str) -> str:
    """Resolve the path to tag_prefs.json relative to the package root."""
    return os.path.join(package_dir, _FILENAME)


def load_kept_tags(package_dir: str) -> set[str]:
    """
    Return the set of TXXX descriptions that were kept last time.
    Returns an empty set if the file does not exist or is unreadable.

    OSError (missing / permissions) is expected and handled silently —
    the absence of a prefs file is a normal first-run condition.
    JSON parse errors are logged as warnings so malformed files surface
    in the log without interrupting startup.
    """
    path = _prefs_path(package_dir)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        tags = data.get("kept_tags", [])
        if isinstance(tags, list):
            return set(tags)
    except FileNotFoundError:
        pass  # Normal first-run — no prefs yet
    except OSError as exc:
        logger.warning("Could not read tag prefs (%s): %s", path, exc, exc_info=True)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Malformed tag prefs file (%s): %s", path, exc, exc_info=True)
    return set()


def save_kept_tags(package_dir: str, kept: list[str]) -> None:
    """
    Save the list of kept TXXX descriptions to tag_prefs.json.

    OSError is logged as a warning but never re-raised — a permissions
    problem must not interrupt the processing completion flow.
    """
    path = _prefs_path(package_dir)
    try:
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"kept_tags": sorted(kept)}, f, indent=2)
        os.replace(tmp_path, path)
    except OSError as exc:
        logger.warning("Could not save tag prefs (%s): %s", path, exc, exc_info=True)
