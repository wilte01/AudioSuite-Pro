"""tag_copy.py — copy one file's easy-tag fields onto another.

The rule a tag copy must obey is the one ``AGENTS.md`` records for mutagen
FLAC: an *existing* tag block is mutated in place through the destination's own
loaded object, never rebound.  The easy interface (``MutagenFile(..., easy=True)``)
writes through that object's own mapping and saves it, so a FLAC's Vorbis
comment is updated rather than replaced by a stale copy.

One implementation: the Audio Joiner and the Pitch / Time tool both rewrite a
file into a new container and both keep the source's tags, so neither keeps a
private copy of this.

Changed in 2.7.0: new module, moved out of ``audio_joiner/core/join.py`` so the
Pitch / Time tool imports it rather than growing a second copy
(PLAN_2026-11-03_2.7.0_feature_wave_3.md F-S4).
"""

from __future__ import annotations

import logging
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen import MutagenError

logger = logging.getLogger(f"audio_suite.{__name__}")

#: Containers mutagen can write through the easy interface.  A WAV or AIFF
#: written by a transform carries no tag block the suite writes, so it is
#: reported instead of tagged.
TAGGABLE_EXTENSIONS: frozenset[str] = frozenset(
    {".mp3", ".flac", ".m4a", ".mp4", ".ogg", ".opus"}
)

#: The easy-tag fields copied from the source.
EASY_TAG_FIELDS: tuple[str, ...] = (
    "title",
    "artist",
    "album",
    "albumartist",
    "date",
    "genre",
    "tracknumber",
    "discnumber",
    "comment",
)


def copy_easy_tags(source: Path, destination: Path) -> bool:
    """Copy *source*'s tags onto *destination*.

    Args:
        source: The file whose tags are the template.
        destination: The rewritten file to tag.

    Returns:
        True when the tags were written; False when the container holds no tag
        block the suite can write, or the write failed.  The caller reports
        that outcome rather than failing a run whose audio was already written.
    """
    if destination.suffix.lower() not in TAGGABLE_EXTENSIONS:
        return False
    try:
        origin = MutagenFile(str(source), easy=True)
        target = MutagenFile(str(destination), easy=True)
        if origin is None or target is None or origin.tags is None:
            return False
        if target.tags is None:
            target.add_tags()
        for field in EASY_TAG_FIELDS:
            if field in origin:
                target[field] = origin[field]
        target.save()
    except (MutagenError, OSError, ValueError) as exc:
        logger.warning("Could not copy tags onto %s: %s", destination, exc)
        return False
    return True
