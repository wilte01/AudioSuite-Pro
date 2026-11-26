"""
tag_reader.py
Reads the TITLEGENRE custom tag from a single audio file.
Pure function — no tkinter imports, no side effects.

Changed in 2.4.1: takes ``TagHandlerFactory`` from
``audio_suite_shared.tag_handler_factory``, the leaf module that owns the
handler table (WP-2).

Changed in 2.9.0: a container with no tag handler (``.wma``, ``.aac``)
returns an unreadable-file message instead of letting ``AudioFormatError``
escape into ``run_analysis``'s decorator, where one such file aborted the
whole run. :func:`is_unreadable_container` names that outcome, so the
consolidator can leave such a file out of the coverage denominator.
"""

import logging
from typing import Optional

from mutagen import MutagenError

from audio_suite_shared.exceptions import AudioFormatError, map_to_audio_error
from audio_suite_shared.tag_handler_factory import TagHandlerFactory

logger = logging.getLogger(__name__)

#: Appended to a file's outcome when the shared tag layer has no handler for
#: its container. The consolidator reads it through
#: :func:`is_unreadable_container` to keep such a file out of the coverage
#: denominator: it can never carry TITLEGENRE, so counting it would fail a
#: fully tagged album.
NO_HANDLER_SUFFIX = "(no tag handler for this container)"


def is_unreadable_container(error: Optional[str]) -> bool:
    """Whether *error* is the no-handler outcome rather than a missing tag.

    Args:
        error: The second element :func:`read_titlegenre` returned.

    Returns:
        True when the container itself is unsupported, so the file can never
        carry TITLEGENRE and must not count toward coverage.
    """
    if not error:
        return False
    return error.endswith(NO_HANDLER_SUFFIX)


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

    except AudioFormatError as exc:
        # .wma and .aac have no handler in the shared tag layer, so this
        # error is a per-file outcome: report the file as unreadable and
        # let the run continue instead of aborting the whole album.
        logger.info("[SKIP] %s - %s", filepath, exc)
        return None, f"{exc} {NO_HANDLER_SUFFIX}"

    except (OSError, ValueError, MutagenError) as exc:
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        return None, str(exc)
