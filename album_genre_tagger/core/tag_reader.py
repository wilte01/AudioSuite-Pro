"""
tag_reader.py
Reads the TITLEGENRE custom tag from a single audio file.
Pure function — no tkinter imports, no side effects.
"""

import logging
from typing import Optional

from mutagen import MutagenError

from audio_suite_shared.exceptions import map_to_audio_error
from audio_suite_shared.tag_helper import TagHandlerFactory

logger = logging.getLogger(__name__)


def read_titlegenre(filepath: str) -> tuple[Optional[str], Optional[str]]:
    """
    Extract the TITLEGENRE custom tag from an audio file.

    Returns:
        (genre_string, None)        on success
        (None, error_message)       if the tag is absent or the file errors
    """
    try:
        handler = TagHandlerFactory.get_handler(filepath)
        if handler.get_raw_tags() is None:
            return None, "No tags"

        fields = handler.read_custom_genre_fields()
        value = fields.get("TITLEGENRE")
        if value is None:
            return None, "No TITLEGENRE tag"
        return value, None

    except (OSError, ValueError, MutagenError) as exc:
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        return None, str(exc)
