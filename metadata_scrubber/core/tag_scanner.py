"""
tag_scanner.py
Scans a directory for custom tags, filtering out known system tags.
Pure logic — no tkinter imports.

Changed in 2.1.3: discovery uses the scrubber's ``SUPPORTED_EXTENSIONS`` (the
``_LOADERS`` keys), not the suite-wide list, so the preserve checklist cannot
be built from a container the scrubber is unable to open (R-05).
Changed in 2.1.7: APEv2 items (``.wv``/``.ape``/``.mpc``), Speex comments
(``.spx``) and DSF's ID3 frames (``.dsf``) are offered in the checklist; before
B2 those containers were not discovered at all, and their keys were never read.
"""

import logging
import os
from typing import Any, Callable, Optional, cast

from audio_suite_shared.exceptions import map_to_audio_error, user_message_for
from audio_suite_shared.tag_helper_base import TagHandlerFactory

from .scrubber import SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)

# Tags that are system/technical and should never appear in the preserve list
_IGNORED_KEYWORDS = frozenset(
    [
        "replaygain",
        "bpm",
        "tempo",
        "initial key",
        "musicbrainz",
        "acousticid",
        "barcode",
        "mediatype",
        "originaldate",
    ]
)


def is_ignored(desc: str) -> bool:
    """Return True if a tag description is a known system tag."""
    desc_lower = desc.lower()
    return any(kw in desc_lower for kw in _IGNORED_KEYWORDS)


def _extract_tag_descriptions(handler: Any) -> list[str]:
    """Extract custom tag description strings from a loaded handler.

    For ID3-based formats (MP3, WAV, AIFF, DSF), returns TXXX frame descriptions.
    For Vorbis-based formats (FLAC, OGG, Opus, Speex), returns Vorbis comment keys.
    For MP4-based formats (M4A, MP4), returns freeform atom keys.
    For APEv2 containers (WavPack, Monkey's Audio, Musepack), returns item keys.
    """
    raw = handler.get_raw_tags()
    if raw is None:
        return []

    ext = os.path.splitext(handler.path)[1].lower()

    if ext in (".mp3", ".wav", ".aiff", ".aif", ".dsf"):
        from mutagen.id3 import TXXX

        descriptions: list[str] = []
        for frame in raw.values():
            if isinstance(frame, TXXX):
                descriptions.append(cast(Any, frame).desc)
        return descriptions

    if ext in (".flac", ".ogg", ".opus", ".spx", ".wv", ".ape", ".mpc"):
        return list(raw.keys())

    if ext in (".m4a", ".mp4"):
        keys: list[str] = []
        for key in raw.keys():
            if key.startswith("----:com.apple.iTunes:"):
                keys.append(key.split(":", 3)[-1])
        return keys

    return []


def scan_custom_tags(
    folder: str,
    sample_size: int = 100,
    on_error: Optional[Callable[[str], None]] = None,
) -> set[str]:
    """
    Scan up to *sample_size* audio files for custom tag descriptions.

    Returns:
        Set of unique, non-ignored custom tag description strings.
    """
    try:
        files = [
            e.name
            for e in os.scandir(folder)
            if e.is_file()
            and os.path.splitext(e.name)[1].lower() in SUPPORTED_EXTENSIONS
        ]
    except OSError as exc:
        mapped = map_to_audio_error(exc)
        logger.error("Directory scan failed: %s", mapped, exc_info=True)
        if on_error:
            on_error(user_message_for(mapped))
        return set()

    discovered: set[str] = set()
    for filename in files[:sample_size]:
        try:
            full_path = os.path.join(folder, filename)
            handler = TagHandlerFactory.get_handler(full_path)
            for desc in _extract_tag_descriptions(handler):
                if not is_ignored(desc):
                    discovered.add(desc)
        except Exception as exc:
            logger.debug("Skipping unreadable tag during scan: %s", exc, exc_info=True)
            continue

    return discovered
