"""
transformation_rules.py — Per-format audio tag processing functions.

Each ``process_*_file`` function encapsulates the Mutagen-specific logic
for one audio format.  They are pure in the sense that they accept a file
path, return a :class:`ProcessingResult`, and handle their own I/O errors.
No mutable processor state is touched — that responsibility lives in
:mod:`tag_field_updater.core.processor`.

All Mutagen imports are performed lazily (inside each function body) so
that external patches on ``tag_field_updater.core.processor.MP3`` etc.
are correctly picked up at call time.

Every rule takes a ``dry_run`` flag and gates **both** persisted effects on
it: the undo snapshot (:func:`~audio_suite_shared.batch_undo.record_tag_edit_snapshot`)
and ``audio.save()``.  The in-memory tag rewrite still happens and the
returned :class:`ProcessingResult` still reports ``updated=True``, so a dry
run reports what *would* change without touching the file on disk.
"""

import logging
from pathlib import Path

from audio_suite_shared.batch_undo import record_tag_edit_snapshot
from audio_suite_shared.exceptions import map_to_audio_error, user_message_for

from .mapping_engine import (
    TAG_MAPPINGS,
    ProcessingResult,
    should_update_value,
    update_value,
)

logger = logging.getLogger(__name__)


class _SkipFile(Exception):
    """Internal signal: file should be counted as skipped upstream.

    Raised inside a ``process_*_file`` function for conditions such as
    "no ID3 tags found".  The calling delegate method catches this to
    increment ``skipped_files`` and return an empty result.
    """

    def __init__(self, reason: str = "") -> None:
        self.reason = reason
        super().__init__(reason)


def process_mp3_file(file_path: Path, dry_run: bool = False) -> ProcessingResult:
    """Process an MP3 file and rewrite qualifying ID3 tags.

    Preserves the original ID3 version encoding (Latin-1 for v2.3,
    UTF-8 for v2.4).  Handles TXXX, TIT1, and TCON frames individually
    because each requires a distinct mutagen constructor call.

    Args:
        file_path: Path to the ``.mp3`` file.
        dry_run: When True, compute the rewrite and report it but neither
            snapshot the undo log nor save the file.

    Returns:
        A :class:`ProcessingResult` indicating which tags were updated.

    Raises:
        :class:`mutagen.id3.ID3NoHeaderError`: Re-raised for the caller to
            handle the skip/stats logic.
        :class:`_SkipFile`: Raised when the file has no ID3 tags at all.
    """
    from tag_field_updater.core.processor import (
        MP3,
        TCON,
        TIT1,
        TXXX,
        ID3NoHeaderError,
    )

    result = ProcessingResult(file_path=file_path)

    try:
        audio = MP3(file_path)
        if audio.tags is None:
            raise _SkipFile("no ID3 tags found")

        original_version = getattr(audio.tags, "version", (2, 3))
        encoding = 3 if original_version >= (2, 4) else 1

        tags_updated: list[str] = []
        tag_keys = TAG_MAPPINGS["mp3"]["txxx"] + TAG_MAPPINGS["mp3"]["standard"]

        for tag_key in tag_keys:
            if tag_key in audio.tags:
                original_value = str(audio.tags[tag_key])
                if should_update_value(original_value):
                    new_value = update_value(original_value)
                    if new_value != original_value:
                        if tag_key == "TIT1":
                            del audio.tags[tag_key]
                            audio.tags.add(TIT1(encoding=encoding, text=new_value))
                        elif tag_key == "TCON":
                            del audio.tags[tag_key]
                            audio.tags.add(TCON(encoding=encoding, text=new_value))
                        elif tag_key.startswith("TXXX:"):
                            txxx_name = tag_key[5:]
                            del audio.tags[tag_key]
                            audio.tags.add(
                                TXXX(
                                    encoding=encoding,
                                    desc=txxx_name,
                                    text=new_value,
                                )
                            )
                        else:
                            audio.tags[tag_key] = new_value

                        tags_updated.append(tag_key)
                        logger.info(
                            "Updated %s in %s: '%s' -> '%s'",
                            tag_key,
                            file_path.name,
                            original_value,
                            new_value,
                        )

        if tags_updated:
            if dry_run:
                logger.info(
                    "Dry run: %s not written (would update %s)",
                    file_path.name,
                    ", ".join(tags_updated),
                )
            else:
                record_tag_edit_snapshot(str(file_path), "tag_field_update")
                audio.save()
            result = ProcessingResult(
                file_path=file_path,
                updated=True,
                tags_updated=tuple(tags_updated),
            )
        else:
            logger.info("Skipped %s: no target tags found to update", file_path.name)

    except ID3NoHeaderError:
        raise
    except _SkipFile:
        raise
    except Exception as exc:
        mapped = map_to_audio_error(
            exc, context={"file": str(file_path), "format": "mp3"}
        )
        logger.error(
            "[%s] MP3 processing error for %s: %s",
            type(mapped).__name__,
            file_path.name,
            mapped,
            exc_info=True,
        )
        result = ProcessingResult(file_path=file_path, error=user_message_for(mapped))

    return result


def process_flac_file(file_path: Path, dry_run: bool = False) -> ProcessingResult:
    """Process a FLAC file and rewrite qualifying Vorbis comment fields.

    Args:
        file_path: Path to the ``.flac`` file.
        dry_run: When True, compute the rewrite and report it but neither
            snapshot the undo log nor save the file.

    Returns:
        A :class:`ProcessingResult` indicating which tags were updated.
    """
    from tag_field_updater.core.processor import FLAC

    result = ProcessingResult(file_path=file_path)

    try:
        audio = FLAC(file_path)
        tags_updated: list[str] = []
        tag_keys = TAG_MAPPINGS["flac"]["txxx"] + TAG_MAPPINGS["flac"]["standard"]

        for tag_key in tag_keys:
            if tag_key in audio:
                original_value = str(audio[tag_key])
                if should_update_value(original_value):
                    new_value = update_value(original_value)
                    if new_value != original_value:
                        audio[tag_key] = new_value
                        tags_updated.append(tag_key)
                        logger.info(
                            "Updated %s in %s: '%s' -> '%s'",
                            tag_key,
                            file_path.name,
                            original_value,
                            new_value,
                        )

        if tags_updated:
            if dry_run:
                logger.info(
                    "Dry run: %s not written (would update %s)",
                    file_path.name,
                    ", ".join(tags_updated),
                )
            else:
                record_tag_edit_snapshot(str(file_path), "tag_field_update")
                audio.save()
            result = ProcessingResult(
                file_path=file_path,
                updated=True,
                tags_updated=tuple(tags_updated),
            )

    except Exception as exc:
        mapped = map_to_audio_error(
            exc, context={"file": str(file_path), "format": "flac"}
        )
        logger.error(
            "[%s] FLAC processing error for %s: %s",
            type(mapped).__name__,
            file_path.name,
            mapped,
            exc_info=True,
        )
        result = ProcessingResult(file_path=file_path, error=user_message_for(mapped))

    return result


def process_mp4_file(file_path: Path, dry_run: bool = False) -> ProcessingResult:
    """Process an MP4/M4A file and rewrite qualifying atom tag fields.

    Args:
        file_path: Path to the ``.mp4`` or ``.m4a`` file.
        dry_run: When True, compute the rewrite and report it but neither
            snapshot the undo log nor save the file.

    Returns:
        A :class:`ProcessingResult` indicating which tags were updated.
    """
    from tag_field_updater.core.processor import MP4

    result = ProcessingResult(file_path=file_path)

    try:
        audio = MP4(file_path)
        tags_updated: list[str] = []
        tag_keys = TAG_MAPPINGS["mp4"]["txxx"] + TAG_MAPPINGS["mp4"]["standard"]

        for tag_key in tag_keys:
            if tag_key in audio:
                original_value = str(audio[tag_key])
                if should_update_value(original_value):
                    new_value = update_value(original_value)
                    if new_value != original_value:
                        audio[tag_key] = new_value
                        tags_updated.append(tag_key)
                        logger.info(
                            "Updated %s in %s: '%s' -> '%s'",
                            tag_key,
                            file_path.name,
                            original_value,
                            new_value,
                        )

        if tags_updated:
            if dry_run:
                logger.info(
                    "Dry run: %s not written (would update %s)",
                    file_path.name,
                    ", ".join(tags_updated),
                )
            else:
                record_tag_edit_snapshot(str(file_path), "tag_field_update")
                audio.save()
            result = ProcessingResult(
                file_path=file_path,
                updated=True,
                tags_updated=tuple(tags_updated),
            )

    except Exception as exc:
        mapped = map_to_audio_error(
            exc, context={"file": str(file_path), "format": "mp4"}
        )
        logger.error(
            "[%s] MP4 processing error for %s: %s",
            type(mapped).__name__,
            file_path.name,
            mapped,
            exc_info=True,
        )
        result = ProcessingResult(file_path=file_path, error=user_message_for(mapped))

    return result


def process_ogg_file(file_path: Path, dry_run: bool = False) -> ProcessingResult:
    """Process an OGG Vorbis file and rewrite qualifying comment fields.

    Args:
        file_path: Path to the ``.ogg`` file.
        dry_run: When True, compute the rewrite and report it but neither
            snapshot the undo log nor save the file.

    Returns:
        A :class:`ProcessingResult` indicating which tags were updated.
    """
    from tag_field_updater.core.processor import OggVorbis

    result = ProcessingResult(file_path=file_path)

    try:
        audio = OggVorbis(file_path)
        tags_updated: list[str] = []
        tag_keys = TAG_MAPPINGS["ogg"]["txxx"] + TAG_MAPPINGS["ogg"]["standard"]

        for tag_key in tag_keys:
            if tag_key in audio:
                original_value = str(audio[tag_key])
                if should_update_value(original_value):
                    new_value = update_value(original_value)
                    if new_value != original_value:
                        audio[tag_key] = new_value
                        tags_updated.append(tag_key)
                        logger.info(
                            "Updated %s in %s: '%s' -> '%s'",
                            tag_key,
                            file_path.name,
                            original_value,
                            new_value,
                        )

        if tags_updated:
            if dry_run:
                logger.info(
                    "Dry run: %s not written (would update %s)",
                    file_path.name,
                    ", ".join(tags_updated),
                )
            else:
                record_tag_edit_snapshot(str(file_path), "tag_field_update")
                audio.save()
            result = ProcessingResult(
                file_path=file_path,
                updated=True,
                tags_updated=tuple(tags_updated),
            )

    except Exception as exc:
        mapped = map_to_audio_error(
            exc, context={"file": str(file_path), "format": "ogg"}
        )
        logger.error(
            "[%s] OGG processing error for %s: %s",
            type(mapped).__name__,
            file_path.name,
            mapped,
            exc_info=True,
        )
        result = ProcessingResult(file_path=file_path, error=user_message_for(mapped))

    return result


def process_opus_file(file_path: Path, dry_run: bool = False) -> ProcessingResult:
    """Process an Opus file and rewrite qualifying Vorbis comment fields.

    Args:
        file_path: Path to the ``.opus`` file.
        dry_run: When True, compute the rewrite and report it but neither
            snapshot the undo log nor save the file.

    Returns:
        A :class:`ProcessingResult` indicating which tags were updated.
    """
    from tag_field_updater.core.processor import OggOpus

    result = ProcessingResult(file_path=file_path)

    try:
        audio = OggOpus(file_path)
        tags_updated: list[str] = []
        tag_keys = TAG_MAPPINGS["opus"]["txxx"] + TAG_MAPPINGS["opus"]["standard"]

        for tag_key in tag_keys:
            if tag_key in audio:
                original_value = str(audio[tag_key])
                if should_update_value(original_value):
                    new_value = update_value(original_value)
                    if new_value != original_value:
                        audio[tag_key] = new_value
                        tags_updated.append(tag_key)
                        logger.info(
                            "Updated %s in %s: '%s' -> '%s'",
                            tag_key,
                            file_path.name,
                            original_value,
                            new_value,
                        )

        if tags_updated:
            if dry_run:
                logger.info(
                    "Dry run: %s not written (would update %s)",
                    file_path.name,
                    ", ".join(tags_updated),
                )
            else:
                record_tag_edit_snapshot(str(file_path), "tag_field_update")
                audio.save()
            result = ProcessingResult(
                file_path=file_path,
                updated=True,
                tags_updated=tuple(tags_updated),
            )

    except Exception as exc:
        mapped = map_to_audio_error(
            exc, context={"file": str(file_path), "format": "opus"}
        )
        logger.error(
            "[%s] Opus processing error for %s: %s",
            type(mapped).__name__,
            file_path.name,
            mapped,
            exc_info=True,
        )
        result = ProcessingResult(file_path=file_path, error=user_message_for(mapped))

    return result


def process_wav_file(file_path: Path, dry_run: bool = False) -> ProcessingResult:
    """Process a WAV file and rewrite qualifying ID3 tags.

    WAV files with ID3 tags use the same frame structure as MP3.

    Args:
        file_path: Path to the ``.wav`` file.
        dry_run: When True, compute the rewrite and report it but neither
            snapshot the undo log nor save the file.

    Returns:
        A :class:`ProcessingResult` indicating which tags were updated.
    """
    from tag_field_updater.core.processor import (
        TCON,
        TIT1,
        TXXX,
        WAVE,
        ID3NoHeaderError,
    )

    result = ProcessingResult(file_path=file_path)

    try:
        audio = WAVE(file_path)
        if audio.tags is None:
            raise _SkipFile("no ID3 tags found")

        tags_updated: list[str] = []
        tag_keys = TAG_MAPPINGS["wav"]["txxx"] + TAG_MAPPINGS["wav"]["standard"]

        for tag_key in tag_keys:
            if tag_key in audio.tags:
                original_value = str(audio.tags[tag_key])
                if should_update_value(original_value):
                    new_value = update_value(original_value)
                    if new_value != original_value:
                        if tag_key == "TIT1":
                            del audio.tags[tag_key]
                            audio.tags.add(TIT1(encoding=1, text=new_value))
                        elif tag_key == "TCON":
                            del audio.tags[tag_key]
                            audio.tags.add(TCON(encoding=1, text=new_value))
                        elif tag_key.startswith("TXXX:"):
                            txxx_name = tag_key[5:]
                            del audio.tags[tag_key]
                            audio.tags.add(
                                TXXX(
                                    encoding=1,
                                    desc=txxx_name,
                                    text=new_value,
                                )
                            )
                        else:
                            audio.tags[tag_key] = new_value

                        tags_updated.append(tag_key)
                        logger.info(
                            "Updated %s in %s: '%s' -> '%s'",
                            tag_key,
                            file_path.name,
                            original_value,
                            new_value,
                        )

        if tags_updated:
            if dry_run:
                logger.info(
                    "Dry run: %s not written (would update %s)",
                    file_path.name,
                    ", ".join(tags_updated),
                )
            else:
                record_tag_edit_snapshot(str(file_path), "tag_field_update")
                audio.save()
            result = ProcessingResult(
                file_path=file_path,
                updated=True,
                tags_updated=tuple(tags_updated),
            )
        else:
            logger.info("Skipped %s: no target tags found to update", file_path.name)

    except ID3NoHeaderError:
        raise
    except _SkipFile:
        raise
    except Exception as exc:
        mapped = map_to_audio_error(
            exc, context={"file": str(file_path), "format": "wav"}
        )
        logger.error(
            "[%s] WAV processing error for %s: %s",
            type(mapped).__name__,
            file_path.name,
            mapped,
            exc_info=True,
        )
        result = ProcessingResult(file_path=file_path, error=user_message_for(mapped))

    return result


def process_aiff_file(file_path: Path, dry_run: bool = False) -> ProcessingResult:
    """Process an AIFF file and rewrite qualifying ID3 tags.

    AIFF files with ID3 tags use the same frame structure as MP3.

    Args:
        file_path: Path to the ``.aiff`` or ``.aif`` file.
        dry_run: When True, compute the rewrite and report it but neither
            snapshot the undo log nor save the file.

    Returns:
        A :class:`ProcessingResult` indicating which tags were updated.
    """
    from tag_field_updater.core.processor import (
        AIFF,
        TCON,
        TIT1,
        TXXX,
        ID3NoHeaderError,
    )

    result = ProcessingResult(file_path=file_path)

    try:
        audio = AIFF(file_path)
        if audio.tags is None:
            raise _SkipFile("no ID3 tags found")

        tags_updated: list[str] = []
        tag_keys = TAG_MAPPINGS["aiff"]["txxx"] + TAG_MAPPINGS["aiff"]["standard"]

        for tag_key in tag_keys:
            if tag_key in audio.tags:
                original_value = str(audio.tags[tag_key])
                if should_update_value(original_value):
                    new_value = update_value(original_value)
                    if new_value != original_value:
                        if tag_key == "TIT1":
                            del audio.tags[tag_key]
                            audio.tags.add(TIT1(encoding=1, text=new_value))
                        elif tag_key == "TCON":
                            del audio.tags[tag_key]
                            audio.tags.add(TCON(encoding=1, text=new_value))
                        elif tag_key.startswith("TXXX:"):
                            txxx_name = tag_key[5:]
                            del audio.tags[tag_key]
                            audio.tags.add(
                                TXXX(
                                    encoding=1,
                                    desc=txxx_name,
                                    text=new_value,
                                )
                            )
                        else:
                            audio.tags[tag_key] = new_value

                        tags_updated.append(tag_key)
                        logger.info(
                            "Updated %s in %s: '%s' -> '%s'",
                            tag_key,
                            file_path.name,
                            original_value,
                            new_value,
                        )

        if tags_updated:
            if dry_run:
                logger.info(
                    "Dry run: %s not written (would update %s)",
                    file_path.name,
                    ", ".join(tags_updated),
                )
            else:
                record_tag_edit_snapshot(str(file_path), "tag_field_update")
                audio.save()
            result = ProcessingResult(
                file_path=file_path,
                updated=True,
                tags_updated=tuple(tags_updated),
            )
        else:
            logger.info("Skipped %s: no target tags found to update", file_path.name)

    except ID3NoHeaderError:
        raise
    except _SkipFile:
        raise
    except Exception as exc:
        mapped = map_to_audio_error(
            exc, context={"file": str(file_path), "format": "aiff"}
        )
        logger.error(
            "[%s] AIFF processing error for %s: %s",
            type(mapped).__name__,
            file_path.name,
            mapped,
            exc_info=True,
        )
        result = ProcessingResult(file_path=file_path, error=user_message_for(mapped))

    return result


def process_wma_file(file_path: Path, dry_run: bool = False) -> ProcessingResult:
    """Process a WMA file and rewrite qualifying ASF metadata fields.

    Args:
        file_path: Path to the ``.wma`` file.
        dry_run: When True, compute the rewrite and report it but neither
            snapshot the undo log nor save the file.

    Returns:
        A :class:`ProcessingResult` indicating which tags were updated.
    """
    from tag_field_updater.core.processor import ASF

    result = ProcessingResult(file_path=file_path)

    try:
        audio = ASF(file_path)
        tags_updated: list[str] = []
        tag_keys = TAG_MAPPINGS["wma"]["txxx"] + TAG_MAPPINGS["wma"]["standard"]

        for tag_key in tag_keys:
            if tag_key in audio:
                original_value = str(audio[tag_key])
                if should_update_value(original_value):
                    new_value = update_value(original_value)
                    if new_value != original_value:
                        audio[tag_key] = new_value
                        tags_updated.append(tag_key)
                        logger.info(
                            "Updated %s in %s: '%s' -> '%s'",
                            tag_key,
                            file_path.name,
                            original_value,
                            new_value,
                        )

        if tags_updated:
            if dry_run:
                logger.info(
                    "Dry run: %s not written (would update %s)",
                    file_path.name,
                    ", ".join(tags_updated),
                )
            else:
                record_tag_edit_snapshot(str(file_path), "tag_field_update")
                audio.save()
            result = ProcessingResult(
                file_path=file_path,
                updated=True,
                tags_updated=tuple(tags_updated),
            )

    except Exception as exc:
        mapped = map_to_audio_error(
            exc, context={"file": str(file_path), "format": "wma"}
        )
        logger.error(
            "[%s] WMA processing error for %s: %s",
            type(mapped).__name__,
            file_path.name,
            mapped,
            exc_info=True,
        )
        result = ProcessingResult(file_path=file_path, error=user_message_for(mapped))

    return result
