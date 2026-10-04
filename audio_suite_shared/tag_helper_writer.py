"""
tag_helper_writer.py — Write-only facade functions for audio tag access.

Part of audio_suite_shared. All functions delegate to TagHandlerFactory
and handle errors uniformly.

When an active undo batch exists for the current thread (set via
``batch_undo.set_active_batch``), each write function automatically
snapshots the file's current tags before modification so the operation
can be reverted later.
"""

import os
from typing import Any

from audio_suite_shared.exceptions import AudioTagError, handle_audio_errors

from .batch_undo import record_tag_edit_snapshot
from .tag_helper_base import TagHandlerFactory

_ID3_BACKED_EXTENSIONS: tuple[str, ...] = (".mp3", ".wav", ".aiff", ".aif")
_MP4_BACKED_EXTENSIONS: tuple[str, ...] = (".m4a", ".mp4")


@handle_audio_errors(reraise=True, context="tag_write")
def write_bpm(path: str, bpm: int) -> None:
    """Write the BPM tag to any supported audio file.

    Args:
        path: Path to the audio file.
        bpm:  BPM value to write.
    """
    record_tag_edit_snapshot(path, "write_bpm")
    TagHandlerFactory.get_handler(path).write_bpm(bpm)


@handle_audio_errors(reraise=True, context="tag_write")
def write_key(path: str, key: str) -> None:
    """Write the musical key tag to any supported audio file.

    Args:
        path: Path to the audio file.
        key:  Key string to write.
    """
    record_tag_edit_snapshot(path, "write_key")
    TagHandlerFactory.get_handler(path).write_key(key)


@handle_audio_errors(reraise=True, context="tag_write")
def write_tempo_marking(path: str, marking: str) -> None:
    """Write the tempo-marking custom tag to any supported audio file.

    Args:
        path:    Path to the audio file.
        marking: Tempo label string to write.
    """
    record_tag_edit_snapshot(path, "write_tempo_marking")
    TagHandlerFactory.get_handler(path).write_tempo_marking(marking)


@handle_audio_errors(reraise=True, context="tag_write")
def write_mood(path: str, mood: str) -> None:
    """Write the mood tag to any supported audio file.

    Args:
        path: Path to the audio file.
        mood: Mood string to write.
    """
    record_tag_edit_snapshot(path, "write_mood")
    TagHandlerFactory.get_handler(path).write_mood(mood)


@handle_audio_errors(reraise=True, context="tag_write")
def write_mood_confidence(path: str, confidence: str) -> None:
    """Write the mood-confidence tag to any supported audio file.

    Args:
        path:       Path to the audio file.
        confidence: Confidence value string (e.g. ``'0.87'``).
    """
    record_tag_edit_snapshot(path, "write_mood_confidence")
    TagHandlerFactory.get_handler(path).write_mood_confidence(confidence)


@handle_audio_errors(reraise=True, context="tag_write")
def write_energy(path: str, energy: str | int) -> None:
    """Write the energy level tag to any supported audio file.

    Args:
        path:   Path to the audio file.
        energy: Energy level string or integer (e.g. ``'5'`` or ``5``).
    """
    record_tag_edit_snapshot(path, "write_energy")
    TagHandlerFactory.get_handler(path).write_energy(str(energy))


@handle_audio_errors(reraise=True, context="tag_write")
def write_genre(path: str, genre: str) -> None:
    """Write the genre tag to any supported audio file.

    Args:
        path:  Path to the audio file.
        genre: Genre string to write.
    """
    record_tag_edit_snapshot(path, "write_genre")
    TagHandlerFactory.get_handler(path).write_genre(genre)


@handle_audio_errors(reraise=True, context="tag_write")
def write_genre_sync_result(path: str, genre: str, derived_value: str) -> None:
    """Write genre and GENREDERIVED marker to any supported audio file.

    Args:
        path:          Path to the audio file.
        genre:         Genre string to write.
        derived_value: Value for the GENREDERIVED custom field.
    """
    record_tag_edit_snapshot(path, "write_genre_sync_result")
    TagHandlerFactory.get_handler(path).write_genre_sync_result(genre, derived_value)


@handle_audio_errors(reraise=True, context="tag_write")
def write_album_genre_result(
    path: str, album_genre: str, derived_marker: str = "Y"
) -> None:
    """Write ALBUMGENRE and ALBUMDERIVED marker to any supported audio file.

    MP3/WAV/AIFF store the pair as ``TXXX:ALBUMGENRE`` / ``TXXX:ALBUMDERIVED``
    ID3 frames; FLAC/OGG/Opus store them as Vorbis comment fields; M4A/MP4
    store them as iTunes freeform atoms.

    Args:
        path: Path to the audio file.
        album_genre: Consolidated genre string to write.
        derived_marker: Value for the album-derived marker. Defaults to "Y".

    Raises:
        AudioTagError: If the write fails.
    """
    record_tag_edit_snapshot(path, "write_album_genre_result")
    TagHandlerFactory.get_handler(path).write_album_genre_result(
        album_genre, derived_marker
    )


@handle_audio_errors(reraise=True, context="tag_write")
def write_synced_lyrics(path: str, lrc_text: str) -> None:
    """Write LRC synced lyrics to any supported audio file.

    MP3/WAV/AIFF embed an ID3 SYLT frame; FLAC/OGG/Opus store the LRC text
    in the ``SYNCEDLYRICS`` Vorbis comment field.

    Args:
        path: Path to the audio file.
        lrc_text: LRC lyrics text to embed.

    Raises:
        LrcParseError: If *lrc_text* is not valid LRC (e.g. a lyric line
            without a timestamp).
        AudioTagError: If the file's format does not support synced lyrics
            (M4A/MP4).
    """
    record_tag_edit_snapshot(path, "write_synced_lyrics")
    TagHandlerFactory.get_handler(path).write_synced_lyrics(lrc_text)


@handle_audio_errors(reraise=True, context="tag_write")
def write_plain_lyrics(path: str, text: str) -> None:
    """Write unsynced (plain text) lyrics to any supported audio file.

    MP3/WAV/AIFF embed an ID3 USLT frame; FLAC/OGG/Opus store the text in
    the ``LYRICS`` Vorbis comment field; M4A/MP4 write the ``\xa9lyr`` atom.

    Args:
        path: Path to the audio file.
        text: Plain lyric text to embed.

    Raises:
        AudioTagError: If the file's format does not support the write.
    """
    record_tag_edit_snapshot(path, "write_plain_lyrics")
    TagHandlerFactory.get_handler(path).write_plain_lyrics(text)


@handle_audio_errors(reraise=True, context="tag_write")
def write_editable_tag(path: str, field: str, value: str | None) -> None:
    """Write or clear one freeform editor field in any supported audio file.

    Args:
        path: Path to the audio file.
        field: Canonical field name from ``EDITABLE_FIELDS``.
        value: String value to store, or ``None`` to remove the field.
    """
    record_tag_edit_snapshot(path, "write_editable_tag")
    TagHandlerFactory.get_handler(path).write_editable_tag(field, value)


def write_tags_raw(path: str, tags: Any, record_snapshot: bool = True) -> None:
    """Write a raw mutagen tags object directly to a file.

    Args:
        path: Path to the audio file.
        tags: Mutagen tags object to write.
        record_snapshot: Whether to snapshot the current tags into the active
            undo batch before writing.  Set to False when *path* is a
            temporary staging file (e.g. replaced atomically afterwards), so
            the undo record points at the real output file instead.

    Raises:
        AudioTagError: If the write fails.
    """
    if record_snapshot:
        record_tag_edit_snapshot(path, "write_tags_raw")
    try:
        TagHandlerFactory.get_handler(path).set_raw_tags(tags)
    except Exception as exc:
        import logging as _logging_module

        _logging_module.getLogger(f"audio_suite.{__name__}").warning(
            "Could not write raw tags to %s: %s", path, exc, exc_info=True
        )
        raise AudioTagError(
            f"Failed to write raw tags to {path}",
            original=exc,
        ) from exc


@handle_audio_errors(reraise=True, context="tag_write")
def write_replaygain(path: str, rg_tags: dict[str, str]) -> None:
    """Write ReplayGain tags to an audio file in its native convention.

    The canonical ReplayGain fields are stored as ``TXXX`` frames for
    ID3-backed formats (MP3, WAV, AIFF), ``----:com.apple.iTunes:`` freeform
    atoms for M4A/MP4, and native VorbisComment fields for FLAC/OGG/Opus.

    Args:
        path:    Path to the audio file.
        rg_tags: Mapping of canonical ReplayGain field names (e.g.
            ``REPLAYGAIN_TRACK_GAIN``) to their formatted string values.

    Raises:
        AudioTagError: If the file cannot be opened for tagging or the write
            fails.
    """
    record_tag_edit_snapshot(path, "write_replaygain")
    import mutagen
    from mutagen.id3 import TXXX
    from mutagen.mp4 import MP4FreeForm

    audio = mutagen.File(path)
    if audio is None:
        raise AudioTagError(f"mutagen could not open file for tagging: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext in _ID3_BACKED_EXTENSIONS:
        if audio.tags is None:
            audio.add_tags()
        for desc, value in rg_tags.items():
            audio.tags.add(TXXX(encoding=3, desc=desc, text=value))
    elif ext in _MP4_BACKED_EXTENSIONS:
        if audio.tags is None:
            audio.add_tags()
        for desc, value in rg_tags.items():
            audio.tags[f"----:com.apple.iTunes:{desc}"] = [
                MP4FreeForm(value.encode("utf-8"))
            ]
    else:
        if audio.tags is None:
            audio.add_tags()
        for desc, value in rg_tags.items():
            audio.tags[desc] = value
    audio.save()


@handle_audio_errors(reraise=True, context="tag_write")
def write_musicbrainz_ids(path: str, mbids: dict[str, str]) -> None:
    """Write MusicBrainz identifier tags in each format's native convention.

    Mirrors MusicBrainz Picard: ``MUSICBRAINZ_TRACKID`` /
    ``MUSICBRAINZ_ALBUMID`` / ``MUSICBRAINZ_ARTISTID`` stored as ``TXXX``
    frames for ID3-backed formats (MP3, WAV, AIFF),
    ``----:com.apple.iTunes:`` freeform atoms for M4A/MP4, and native
    VorbisComment fields for FLAC/OGG/Opus.

    Args:
        path:  Path to the audio file.
        mbids: Mapping of canonical MBID field name to its UUID value. Empty
               values are skipped so an absent identifier is never written as
               an empty tag.

    Raises:
        AudioTagError: If the file cannot be opened for tagging or the write
            fails.
    """
    record_tag_edit_snapshot(path, "write_musicbrainz_ids")
    import mutagen
    from mutagen.id3 import TXXX
    from mutagen.mp4 import MP4FreeForm

    fields = {name: value for name, value in mbids.items() if value}
    if not fields:
        return

    audio = mutagen.File(path)
    if audio is None:
        raise AudioTagError(f"mutagen could not open file for tagging: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext in _ID3_BACKED_EXTENSIONS:
        if audio.tags is None:
            audio.add_tags()
        for desc, value in fields.items():
            audio.tags.add(TXXX(encoding=3, desc=desc, text=value))
    elif ext in _MP4_BACKED_EXTENSIONS:
        if audio.tags is None:
            audio.add_tags()
        for desc, value in fields.items():
            audio.tags[f"----:com.apple.iTunes:{desc}"] = [
                MP4FreeForm(value.encode("utf-8"))
            ]
    else:
        if audio.tags is None:
            audio.add_tags()
        for desc, value in fields.items():
            audio.tags[desc] = value
    audio.save()


@handle_audio_errors(reraise=True, context="tag_write")
def write_acoustid(path: str, fingerprint: str, acoustid_id: str) -> None:
    """Write AcoustID tags to an audio file in its native convention.

    Mirrors MusicBrainz Picard: ``Acoustid Fingerprint`` / ``Acoustid Id``
    stored as ``TXXX`` frames for ID3-backed formats (MP3, WAV, AIFF),
    ``----:com.apple.iTunes:`` freeform atoms for M4A/MP4, and native
    VorbisComment fields for FLAC/OGG/Opus.

    Args:
        path: Path to the audio file.
        fingerprint: Chromaprint fingerprint string to write.
        acoustid_id: AcoustID id of the matched lookup result.

    Raises:
        AudioTagError: If the file cannot be opened for tagging or the write
            fails.
    """
    record_tag_edit_snapshot(path, "write_acoustid")
    import mutagen
    from mutagen.id3 import TXXX
    from mutagen.mp4 import MP4FreeForm

    audio = mutagen.File(path)
    if audio is None:
        raise AudioTagError(f"mutagen could not open file for tagging: {path}")
    fields = {
        "Acoustid Fingerprint": fingerprint,
        "Acoustid Id": acoustid_id,
    }
    ext = os.path.splitext(path)[1].lower()
    if ext in _ID3_BACKED_EXTENSIONS:
        if audio.tags is None:
            audio.add_tags()
        for desc, value in fields.items():
            audio.tags.add(TXXX(encoding=3, desc=desc, text=value))
    elif ext in _MP4_BACKED_EXTENSIONS:
        if audio.tags is None:
            audio.add_tags()
        for desc, value in fields.items():
            audio.tags[f"----:com.apple.iTunes:{desc}"] = [
                MP4FreeForm(value.encode("utf-8"))
            ]
    else:
        if audio.tags is None:
            audio.add_tags()
        for desc, value in fields.items():
            audio.tags[desc] = value
    audio.save()
