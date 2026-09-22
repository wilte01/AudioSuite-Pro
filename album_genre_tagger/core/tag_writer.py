"""
tag_writer.py
Writes ALBUMGENRE and ALBUMDERIVED tags to a single audio file.
Pure function — no tkinter imports, no side effects beyond the file write.
"""

import logging

from audio_suite_shared.exceptions import AudioSuiteError, map_to_audio_error
from audio_suite_shared.tag_helper import write_album_genre_result

logger = logging.getLogger(__name__)


def write_album_genre(
    filepath: str,
    album_genre_string: str,
    is_dry_run: bool,
) -> tuple[bool, str]:
    """
    Write the consolidated genre string to ALBUMGENRE and flag ALBUMDERIVED=Y.

    Args:
        filepath:           Absolute path to the audio file.
        album_genre_string: Semicolon-separated sorted genre string.
        is_dry_run:         If True, validates the operation but makes no changes.

    Returns:
        (True, message)   on success or dry run
        (False, message)  on error
    """
    if is_dry_run:
        return True, "Dry run - no changes made"

    try:
        write_album_genre_result(filepath, album_genre_string)
        return True, "Updated"

    except (OSError, ValueError, AudioSuiteError) as exc:
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        return False, str(exc)
