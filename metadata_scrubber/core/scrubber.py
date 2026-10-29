"""
scrubber.py
Per-file scrubbing worker and thread-pool orchestration loop.
No tkinter imports — all UI interaction via injected callbacks.

Changed in 1.4.0: the docstring no longer claims a fixed 4-worker pool; the
count resolves from ``default_max_workers()`` (D56, D67).
Changed in 2.1.3: discovery and loading share one ``_LOADERS`` table, so the
scrubber can no longer advertise a container it cannot open (R-05).
Changed in 2.1.7: APEv2 (.wv/.ape/.mpc), Ogg Speex (.spx) and DSF (.dsf) join
the table, with a container-aware preserve/restore path (B2). APEv2 items are
kept as the raw ``APEValue`` objects the loaded container holds; ``.spx`` uses
the Vorbis-comment path and ``.dsf`` the ID3 path.
"""

import logging
import os
import threading
import time
from queue import Queue
from typing import Any, Callable, Optional, cast

from mutagen.aiff import AIFF
from mutagen.dsf import DSF
from mutagen.flac import FLAC
from mutagen.id3 import APIC, ID3, SYLT, TPE2, TXXX, USLT
from mutagen.monkeysaudio import MonkeysAudio
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.musepack import Musepack
from mutagen.oggopus import OggOpus
from mutagen.oggspeex import OggSpeex
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE
from mutagen.wavpack import WavPack

from audio_suite_shared.batch_undo import (
    get_active_batch_id,
    record_tag_edit_snapshot,
    use_batch,
)
from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from audio_suite_shared.exceptions import (
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.file_processor_base import BaseFileProcessor
from audio_suite_shared.tag_helper_base import TagHandlerFactory

#: Extension -> mutagen loader. This table is the *only* source of truth for
#: what the scrubber advertises: ``SUPPORTED_EXTENSIONS`` is derived from it and
#: ``_load_audio`` looks the same entry up, so discovery cannot offer a container
#: the loader cannot open (R-05 - ``.wv/.ape/.mpc/.spx/.dsf`` came from the
#: suite-wide list and were then reported ``[UNREADABLE]`` at run time).
#: A plain class is a valid callable; an explicit lambda appears only where the
#: constructor takes keyword arguments.
#:
#: ``TagHandlerFactory`` is deliberately not used as the loader here: scrubbing
#: needs the *raw* mutagen object, because ``_collect_tags_to_preserve`` captures
#: actual ``APIC``/``SYLT``/``USLT``/``TPE2``/``TXXX`` frames and restores those
#: same frame objects. APEv2 containers are supported on the same terms: the
#: preserved items are the raw ``APEValue`` objects (text, binary artwork or
#: multi-value), and ``_restore_tags`` writes them back into a freshly loaded
#: container before ``set_raw_tags`` persists it.
_LOADERS: dict[str, Callable[[str], Any]] = {
    ".mp3": lambda path: MP3(path, ID3=ID3),
    ".flac": FLAC,
    ".ogg": OggVorbis,
    ".opus": OggOpus,
    ".spx": OggSpeex,
    ".m4a": MP4,
    ".mp4": MP4,
    ".wav": WAVE,
    ".aiff": AIFF,
    ".aif": AIFF,
    ".wv": WavPack,
    ".ape": MonkeysAudio,
    ".mpc": Musepack,
    ".dsf": DSF,
}

#: Containers whose tags are APEv2 items (WavPack, Monkey's Audio, Musepack).
_APEV2_EXTENSIONS: frozenset[str] = frozenset({".wv", ".ape", ".mpc"})

#: Vorbis-comment containers, including Ogg Speex.
_VORBIS_EXTENSIONS: frozenset[str] = frozenset({".flac", ".ogg", ".opus", ".spx"})

#: ID3-backed containers, including DSF's ID3 chunk.
_ID3_EXTENSIONS: frozenset[str] = frozenset({".wav", ".aiff", ".aif", ".dsf"})

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(_LOADERS)

logger = logging.getLogger(__name__)


def _get_frame_safe(audio: Any, field_id: str) -> Optional[Any]:
    """
    Safely retrieve an ID3 tag frame object for later restoration.

    Returns the frame itself (not a derived string) so that multi-value
    text frames (e.g. a TPE1 storing several artists as separate values)
    and the frame's original text encoding survive a delete/restore cycle
    unchanged. Returns None if the field is absent, empty, or unreadable.
    """
    try:
        field = audio.tags.get(field_id)
        if field and hasattr(field, "text") and field.text:
            return field
    except Exception as exc:  # mutagen can raise various internals here
        logger.debug("Could not read tag field %s: %s", field_id, exc, exc_info=True)
    return None


def _load_audio(full_path: str) -> Any:
    """Load an audio file with the handler ``_LOADERS`` maps to its extension.

    Raises:
        ValueError: when the extension has no loader. Discovery only offers what
            this table contains, so the raise is a direct-call guard rather than
            a reachable run-time path.
    """
    ext = os.path.splitext(full_path)[1].lower()
    loader = _LOADERS.get(ext)
    if loader is None:
        raise ValueError(f"Unsupported audio format: {ext}")
    return loader(full_path)


def _matching_key(mapping: Any, wanted: str) -> Optional[str]:
    """Return the stored key matching *wanted* case-insensitively.

    APEv2 (and Vorbis comments) match keys case-insensitively but remember the
    casing they were written with, so restoring through the stored key keeps
    the file's own canonical spelling instead of lower-casing it.
    """
    for key in mapping.keys():
        if str(key).lower() == wanted.lower():
            return str(key)
    return None


def _has_tags(audio: Any) -> bool:
    """Check whether the loaded audio object has any tags."""
    if hasattr(audio, "tags"):
        return audio.tags is not None and len(audio.tags) > 0
    return False


def _collect_tags_to_preserve(
    audio: Any,
    preserve_list: list[str],
    preserve_lyrics: bool,
    preserve_album_artist: bool,
    preserve_embedded_art: bool,
) -> dict[str, Any]:
    """
    Collect tags that should be preserved across a wipe/restore cycle.

    Returns a dict keyed by tag identifier (format-specific) -> raw tag value.
    """
    ext = os.path.splitext(str(getattr(audio, "filename", "")))[1].lower()
    preserved: dict[str, Any] = {}

    if ext == ".mp3":
        # Always preserve artist, album, title (essential tags)
        for fid in ("TPE1", "TALB", "TIT2"):
            frame = _get_frame_safe(audio, fid)
            if frame is not None:
                preserved[f"id3:{fid}"] = frame
        for frame in audio.tags.values():
            try:
                # mutagen stubs omit Frame.desc; it is always a str at runtime.
                if preserve_lyrics and isinstance(frame, (USLT, SYLT)):
                    preserved[f"id3:{frame.FrameID}"] = frame
                elif preserve_album_artist and isinstance(frame, TPE2):
                    preserved["id3:TPE2"] = frame
                elif preserve_embedded_art and isinstance(frame, APIC):
                    desc = cast(Any, frame).desc
                    preserved[f"id3:APIC:{desc}"] = frame
                elif isinstance(frame, TXXX):
                    txxx_desc = cast(Any, frame).desc
                    if txxx_desc in preserve_list:
                        preserved[f"id3:TXXX:{txxx_desc}"] = frame
            except Exception as exc:
                logger.debug("Skipping unreadable ID3 frame: %s", exc)
    elif ext in _VORBIS_EXTENSIONS:
        # Always preserve artist, album, title (essential tags)
        for key in ("artist", "album", "title"):
            vals = audio.tags.get(key)
            if vals:
                preserved[key] = list(vals)
        for key in list(audio.tags.keys()):
            try:
                vals = audio.tags.get(key, [])
                if not vals:
                    continue
                if preserve_lyrics and key.lower() in ("lyrics", "syncedlyrics"):
                    preserved[key] = list(vals)
                elif preserve_album_artist and key.lower() in (
                    "albumartist",
                    "album artist",
                ):
                    preserved[key] = list(vals)
                elif preserve_embedded_art and key.lower() in (
                    "metadata_block_picture",
                ):
                    preserved[key] = list(vals)
                elif key.lower() in {p.lower() for p in preserve_list}:
                    preserved[key] = list(vals)
            except Exception as exc:
                logger.debug("Skipping unreadable Vorbis tag %s: %s", key, exc)
    elif ext in _APEV2_EXTENSIONS:
        # Essentials first, then the flagged/preserved items. The raw APEValue
        # is kept (not a list of strings): a multi-value text item round-trips
        # as one item, and a Cover Art (Front) binary item stays binary.
        wanted_preserve = {p.lower() for p in preserve_list}
        for wanted in ("artist", "album", "title"):
            match_key = _matching_key(audio.tags, wanted)
            if match_key is not None and audio.tags.get(match_key):
                preserved[match_key] = audio.tags.get(match_key)
        kept = {str(key).lower() for key in preserved}
        for key in list(audio.tags.keys()):
            try:
                value = audio.tags.get(key)
                if not value or str(key).lower() in kept:
                    continue
                lower = key.lower()
                if preserve_lyrics and lower in ("lyrics", "syncedlyrics"):
                    preserved[key] = value
                elif preserve_album_artist and lower in (
                    "albumartist",
                    "album artist",
                ):
                    preserved[key] = value
                elif preserve_embedded_art and lower == "cover art (front)":
                    preserved[key] = value
                elif lower in wanted_preserve:
                    preserved[key] = value
            except Exception as exc:
                logger.debug("Skipping unreadable APEv2 item %s: %s", key, exc)
    elif ext in (".m4a", ".mp4"):
        # Always preserve artist, album, title (essential tags)
        for key in ("\xa9ART", "\xa9alb", "\xa9nam"):
            vals = audio.tags.get(key)
            if vals:
                preserved[key] = vals
        for key in list(audio.tags.keys()):
            try:
                vals = audio.tags.get(key)
                if vals is None:
                    continue
                if preserve_lyrics and key.lower() in ("\xa9lyr",):
                    preserved[key] = vals
                elif preserve_embedded_art and key == "covr":
                    preserved[key] = vals
                elif key.lower() in {p.lower() for p in preserve_list}:
                    preserved[key] = vals
            except Exception as exc:
                logger.debug("Skipping unreadable MP4 atom %s: %s", key, exc)
    elif ext in _ID3_EXTENSIONS:
        # WAV/AIFF and DSF use ID3 tags, same structure as MP3
        for fid in ("TPE1", "TALB", "TIT2"):
            frame = _get_frame_safe(audio, fid)
            if frame is not None:
                preserved[f"id3:{fid}"] = frame
        if audio.tags:
            for frame in audio.tags.values():
                try:
                    if preserve_lyrics and isinstance(frame, (USLT, SYLT)):
                        preserved[f"id3:{frame.FrameID}"] = frame
                    elif preserve_album_artist and isinstance(frame, TPE2):
                        preserved["id3:TPE2"] = frame
                    elif preserve_embedded_art and isinstance(frame, APIC):
                        desc = cast(Any, frame).desc
                        preserved[f"id3:APIC:{desc}"] = frame
                    elif isinstance(frame, TXXX):
                        txxx_desc = cast(Any, frame).desc
                        if txxx_desc in preserve_list:
                            preserved[f"id3:TXXX:{txxx_desc}"] = frame
                except Exception as exc:
                    logger.debug("Skipping unreadable ID3 frame: %s", exc)

    return preserved


def _wipe_tags(audio: Any) -> None:
    """Delete all tags from the loaded audio object."""
    audio.delete()


def _restore_tags(audio: Any, preserved: dict[str, Any]) -> None:
    """Re-add preserved tags after a wipe."""
    ext = os.path.splitext(str(getattr(audio, "filename", "")))[1].lower()

    if ext == ".mp3":
        for _key, frame in preserved.items():
            try:
                audio.tags.add(frame)
            except Exception as exc:
                logger.debug("Could not restore ID3 frame: %s", exc)
    elif ext in _VORBIS_EXTENSIONS or ext in (".m4a", ".mp4"):
        for key, vals in preserved.items():
            audio.tags[key] = vals
    elif ext in _APEV2_EXTENSIONS:
        for key, value in preserved.items():
            try:
                audio.tags[key] = value
            except Exception as exc:
                logger.debug("Could not restore APEv2 item %s: %s", key, exc)
    elif ext in _ID3_EXTENSIONS:
        for _key, frame in preserved.items():
            try:
                audio.tags.add(frame)
            except Exception as exc:
                logger.debug("Could not restore ID3 frame: %s", exc)


def process_single_file(
    name: str,
    dir_path: str,
    is_dry_run: bool,
    preserve_list: list[str],
    preserve_lyrics: bool,
    preserve_album_artist: bool,
    preserve_embedded_art: bool,
    slot_vars: list[Any],
    slot_queue: Queue[Any],
    lock: threading.Lock,
    on_progress: Callable[..., Any],
) -> None:
    """
    Acquire a worker slot, scrub one audio file, release the slot.

    Supports MP3, FLAC, OGG, Opus, Speex, M4A, MP4, WAV, AIFF/AIF, WavPack,
    Monkey's Audio, Musepack, and DSF.

    on_progress signature:
        on_progress(n_skipped=0, n_errors=0, display_text="", log_text="")
    """
    slot_idx = slot_queue.get()
    full_path = os.path.join(dir_path, name)

    try:
        slot_vars[slot_idx].set(f"Processing: {name[:25]}...")

        if is_dry_run:
            status = "DRY RUN"
            action: Optional[str] = "Would scrub metadata"
        else:
            # ── Stage 1: Load ─────────────────────────────────────────────────
            try:
                audio = _load_audio(full_path)
            except Exception as exc:
                mapped = map_to_audio_error(exc)
                logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
                with lock:
                    on_progress(
                        n_errors=1,
                        display_text=f"[UNREADABLE] {name} \u2192 could not open file",
                        log_text=f"[UNREADABLE] {name} | {exc}\n",
                    )
                return

            # ── Stage 2: Check tags exist ─────────────────────────────────────
            if not _has_tags(audio):
                with lock:
                    on_progress(
                        n_errors=1,
                        display_text=f"[NO TAGS] {name} \u2192 no tags present",
                        log_text=f"[NO TAGS] {name} | no tags found\n",
                    )
                return

            # ── Stage 3: Collect tags to preserve ─────────────────────────────
            preserved = _collect_tags_to_preserve(
                audio,
                preserve_list,
                preserve_lyrics,
                preserve_album_artist,
                preserve_embedded_art,
            )

            # ── Stage 4: Wipe tags ────────────────────────────────────────────
            slot_vars[slot_idx].set(f"Scrubbing: {name[:25]}...")
            try:
                record_tag_edit_snapshot(full_path, "scrub_wipe")
                _wipe_tags(audio)
                audio.save()
            except Exception as exc:
                mapped = map_to_audio_error(exc)
                logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
                with lock:
                    on_progress(
                        n_errors=1,
                        display_text=f"[CORRUPT TAGS] {name} \u2192 could "
                        f"not wipe tags",
                        log_text=f"[CORRUPT TAGS] {name} | {exc}\n",
                    )
                return

            # Allow filesystem to flush the deleted file before re-reading.
            # On Windows NTFS a brief pause avoids FILE_NOT_FOUND when the
            # re-read races the OS-level unlink; 50 ms is sufficient.
            time.sleep(0.05)

            # ── Stage 5: Restore essential tags ──────────────────────────────
            slot_vars[slot_idx].set(f"Restoring: {name[:25]}...")
            try:
                audio = _load_audio(full_path)
                if audio.tags is None:
                    audio.add_tags()
                _restore_tags(audio, preserved)
                TagHandlerFactory.get_handler(full_path).set_raw_tags(audio.tags)
            except Exception as exc:
                mapped = map_to_audio_error(exc)
                logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
                with lock:
                    on_progress(
                        n_errors=1,
                        display_text=f"[WRITE FAILED] {name} \u2192 could "
                        f"not restore tags",
                        log_text=f"[WRITE FAILED] {name} | {exc}\n",
                    )
                return

            status = "CLEANED"
            action = f"Preserved: {len(preserved)} tags"

        display = f"[{status}] {name}"
        if action:
            display += f" \u2192 {action}"
        log = f"[{status}] {name}"
        if action:
            log += f" | {action}"
        log += "\n"

        with lock:
            on_progress(display_text=display, log_text=log)

    except Exception as exc:
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        with lock:
            on_progress(
                n_errors=1,
                display_text=f"[ERROR] {name}",
                log_text=f"[ERROR] {name}: {exc}\n",
            )
    finally:
        slot_vars[slot_idx].set("IDLE")
        slot_queue.put(slot_idx)


@handle_audio_errors(reraise=False, context="metadata_scrubber_run_scrubbing")
def run_scrubbing(
    dir_path: str,
    is_dry_run: bool,
    preserve_list: list[str],
    preserve_lyrics: bool,
    preserve_album_artist: bool,
    preserve_embedded_art: bool,
    slot_vars: list[Any],
    slot_queue: Queue[Any],
    on_progress: Callable[..., Any],
    on_complete: Callable[..., Any],
    on_error: Callable[..., Any],
) -> None:
    """
    Scan directory for supported audio files, process all with a worker pool
    then invoke on_complete with summary data.
    """
    try:
        files = [
            e.name
            for e in os.scandir(dir_path)
            if e.is_file()
            and os.path.splitext(e.name)[1].lower() in SUPPORTED_EXTENSIONS
        ]
    except OSError as exc:
        mapped = map_to_audio_error(exc)
        logger.error("Directory scan failed: %s", mapped, exc_info=True)
        on_error(user_message_for(mapped))
        return

    if not files:
        on_error("No supported audio files found in the selected directory.")
        return

    lock = threading.Lock()
    processed = [0]
    skipped = [0]
    errors = [0]
    log_entries: list[str] = []

    def _on_progress(
        n_skipped: int = 0,
        n_errors: int = 0,
        display_text: str = "",
        log_text: str = "",
    ) -> None:
        processed[0] += 1
        skipped[0] += n_skipped
        errors[0] += n_errors
        log_entries.append(log_text)
        on_progress(
            processed=processed[0],
            total=len(files),
            skipped=skipped[0],
            errors=errors[0],
            display_text=display_text,
        )

    start = time.monotonic()

    undo_batch = get_active_batch_id()

    def _scrub_worker(*args: Any, **kwargs: Any) -> None:
        with use_batch(undo_batch):
            process_single_file(*args, **kwargs)

    processor = BaseFileProcessor(
        max_workers=DEFAULT_MAX_WORKERS, operation_type="metadata_scrubber"
    )

    def _worker(name: str) -> None:
        _scrub_worker(
            name,
            dir_path,
            is_dry_run,
            preserve_list,
            preserve_lyrics,
            preserve_album_artist,
            preserve_embedded_art,
            slot_vars,
            slot_queue,
            lock,
            _on_progress,
        )

    processor.process_batch(files, _worker, max_workers=processor.max_workers)

    on_complete(
        total=len(files),
        processed=processed[0],
        skipped=skipped[0],
        errors=errors[0],
        duration_secs=time.monotonic() - start,
        log_entries=log_entries,
    )
