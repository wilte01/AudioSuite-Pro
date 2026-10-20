"""
core/ripper.py  –  CD audio extraction for Windows via SCSI Pass-Through.

Uses IOCTL_SCSI_PASS_THROUGH_DIRECT with the MMC "READ CD" command (0xBE)
to read raw CDDA sectors. This is the method used by modern rippers on
Windows 10/11 where IOCTL_CDROM_RAW_READ is restricted.

This module re-exports all public names from its sub-modules for backward
compatibility.  See the individual sub-modules for implementation details:

    drive_handler      –  Low-level device control (TOC, SCSI, spin-down)
    track_processor    –  Read verification, C2 diagnostics, extraction
    metadata_resolver  –  Format definitions, FFmpeg probing, metadata
    encoding_pipeline  –  Per-track RipTask orchestration
    accuraterip        –  AccurateRip disc IDs, checksums, database client

Changed in 1.2.0: re-exports the new verification surface
(``DBMatch``, ``match_track``, ``VerificationMethod``,
``describe_verification``, ``TrackVerification``).
Changed in 1.4.0: a session always signals completion (an unhandled
``AudioIOError`` used to kill the thread and hang the CLI forever), records a
fatal TOC/drive error for the caller, and treats a failed spin-down as
non-fatal.
"""

import dataclasses
import logging as _logging
import os
import threading
from collections.abc import Callable
from typing import Any, cast

from audio_suite_shared.cue_generator import (
    CueFileSpec,
    TrackSpec,
    build_cue,
    write_cue,
)
from audio_suite_shared.exceptions import AudioSuiteError

# ── Re-exports from accuraterip ────────────────────────────────────────────
from cd_ripper.core.accuraterip import (  # noqa: F401
    ACCURATERIP_URL,
    DEFAULT_TIMEOUT_SECS,
    EDGE_SKIP_FRAMES,
    FRAMES_PER_SECTOR,
    AccurateRipClient,
    DBEntry,
    DBMatch,
    DBTrackEntry,
    DiscIds,
    LookupFound,
    LookupNotFound,
    LookupOffline,
    LookupResult,
    TrackChecksums,
    VerificationMethod,
    VerificationStatus,
    compute_disc_ids,
    compute_track_checksums,
    describe_verification,
    match_track,
    parse_db_entry,
    parse_db_payload,
    verify_track,
    with_gap_window,
)

# ── Re-exports from drive_handler ─────────────────────────────────────────
from cd_ripper.core.drive_handler import (  # noqa: F401
    _CDROM_TOC,
    C2_FLAG_BYTES_PER_SECTOR,
    INVALID_HANDLE_VALUE,
    SCSI_PASS_THROUGH_DIRECT,
    SECTOR_SIZE,
    _bytes_per_sector,
    _msf_to_lba,
    _open_device,
    _read_cd_scsi,
    read_toc,
    spin_down_drive,
)

# ── Re-exports from encoding_pipeline ─────────────────────────────────────
from cd_ripper.core.encoding_pipeline import RipTask  # noqa: F401

# ── Re-exports from metadata_resolver ─────────────────────────────────────
from cd_ripper.core.metadata_resolver import (  # noqa: F401
    FLAC_QUALITY_ARGS,
    FORMAT_OPTIONS,
    M4A_QUALITY_ARGS,
    MP3_QUALITY_ARGS,
    OGG_QUALITY_ARGS,
    OPUS_QUALITY_ARGS,
    _build_metadata_args,
    _run_ffmpeg_streaming,
    _safe_filename,
    get_quality_options,
    probe_ffmpeg,
)

# ── Re-exports from offset_detect ─────────────────────────────────────────
from cd_ripper.core.offset_detect import (  # noqa: F401
    ReadOffsetDetectionError,
    detect_read_offset_frames,
    run_read_offset_detection,
)

# ── Re-exports from read_offset ───────────────────────────────────────────
from cd_ripper.core.read_offset import (  # noqa: F401
    READ_OFFSET_CONFIG_KEY,
    TrackReadLayout,
    aligned_track_pcm,
    compute_track_read_layout,
    get_read_offset_frames,
    pad_tail_shortfall,
    set_read_offset_frames,
)

# ── Re-exports from track_processor ───────────────────────────────────────
from cd_ripper.core.track_processor import (  # noqa: F401
    RipVerificationConfig,
    RipVerificationMode,
    TrackVerification,
    UnresolvedSectorError,
    VerificationPlan,
    _read_verified_chunk,
    _resolve_by_majority,
    diagnose_c2_reliability,
    extract_track_scsi,
    read_track_pcm,
    read_wav_pcm,
    verify_extracted_track,
)

__all__ = [
    "ACCURATERIP_URL",
    "C2_FLAG_BYTES_PER_SECTOR",
    "DBEntry",
    "DBMatch",
    "DBTrackEntry",
    "DEFAULT_TIMEOUT_SECS",
    "DiscIds",
    "EDGE_SKIP_FRAMES",
    "FLAC_QUALITY_ARGS",
    "FORMAT_OPTIONS",
    "FRAMES_PER_SECTOR",
    "INVALID_HANDLE_VALUE",
    "AccurateRipClient",
    "LookupFound",
    "LookupNotFound",
    "LookupOffline",
    "LookupResult",
    "M4A_QUALITY_ARGS",
    "MP3_QUALITY_ARGS",
    "OGG_QUALITY_ARGS",
    "OPUS_QUALITY_ARGS",
    "RipSession",
    "RipTask",
    "RipVerificationConfig",
    "RipVerificationMode",
    "READ_OFFSET_CONFIG_KEY",
    "ReadOffsetDetectionError",
    "SCSI_PASS_THROUGH_DIRECT",
    "SECTOR_SIZE",
    "TrackChecksums",
    "TrackReadLayout",
    "TrackVerification",
    "UnresolvedSectorError",
    "VerificationMethod",
    "VerificationPlan",
    "VerificationStatus",
    "_CDROM_TOC",
    "_build_metadata_args",
    "_bytes_per_sector",
    "_msf_to_lba",
    "_open_device",
    "_read_cd_scsi",
    "_read_verified_chunk",
    "_resolve_by_majority",
    "_safe_filename",
    "aligned_track_pcm",
    "compute_disc_ids",
    "compute_track_checksums",
    "compute_track_read_layout",
    "describe_verification",
    "detect_read_offset_frames",
    "diagnose_c2_reliability",
    "extract_track_scsi",
    "get_quality_options",
    "get_read_offset_frames",
    "match_track",
    "pad_tail_shortfall",
    "parse_db_entry",
    "parse_db_payload",
    "probe_ffmpeg",
    "read_toc",
    "read_track_pcm",
    "read_wav_pcm",
    "run_read_offset_detection",
    "set_read_offset_frames",
    "spin_down_drive",
    "verify_extracted_track",
    "verify_track",
    "with_gap_window",
]

# ── RipSession (orchestration) ─────────────────────────────────────────────


class RipSession:
    """CD ripping session for multiple tracks."""

    def __init__(
        self,
        drive: str,
        tracks: list[dict[str, Any]],
        out_dir: str,
        fmt: str,
        quality_args: list[str] | None,
        progress_cb: Callable[[int, int, str], None],
        track_done_cb: Callable[[int, bool, str, str], None],
        session_done_cb: Callable[[], None],
        ffmpeg_path: str = "ffmpeg",
        log_cb: Callable[[str], None] | None = None,
        write_cue: bool = False,
        verification_config: RipVerificationConfig | None = None,
        verify_mode: str | RipVerificationMode = "off",
    ) -> None:
        self.drive = drive
        self.tracks = tracks
        self.out_dir = out_dir
        # FORMAT_OPTIONS is keyed by display name ('WAV', 'Opus') while the
        # CLI passes lowercase values ('wav', 'opus'). Resolve to the
        # canonical key so the codec_args default and the RipTask extension
        # lookup never KeyError on a valid format.
        self.fmt = next(
            (key for key in FORMAT_OPTIONS if key.lower() == fmt.lower()), fmt
        )
        # FORMAT_OPTIONS values are always list[str]; cast keeps the union honest.
        self.codec_args = (
            quality_args
            if quality_args
            else cast(list[str], FORMAT_OPTIONS[self.fmt]["codec_args"])
        )
        self.progress_cb = progress_cb
        self.track_done_cb = track_done_cb
        self.session_done_cb = session_done_cb
        self.ffmpeg = ffmpeg_path
        self.log_cb = log_cb or (lambda msg: None)
        self.write_cue = write_cue
        base_config = verification_config or RipVerificationConfig()
        stored_offset = get_read_offset_frames(self.drive)
        if stored_offset and base_config.read_offset_frames == 0:
            self.log_cb(
                f"[Offset] drive read offset {stored_offset:+d} frame(s) "
                "applied from shared config"
            )
            base_config = dataclasses.replace(
                base_config, read_offset_frames=stored_offset
            )
        self.verification_config = base_config
        if isinstance(verify_mode, RipVerificationMode):
            self.verify_mode = verify_mode
        else:
            self.verify_mode = RipVerificationMode(str(verify_mode or "off"))
        self._cancelled = False
        self._current_task: RipTask | None = None
        self._thread: threading.Thread | None = None
        #: Set when the session could not run at all (no disc, unreadable
        #: drive, missing FFmpeg).  The CLI turns this into a non-zero exit so
        #: an empty rip is never reported as success.
        self.fatal_error: str | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancelled = True
        if self._current_task:
            self._current_task.cancel()

    def _run(self) -> None:
        """Thread entry point: always signals completion, even on failure."""
        try:
            self._run_session()
        except Exception as exc:  # noqa: BLE001 - a dead thread would hang the CLI
            _logging.getLogger(__name__).error(
                "Rip session failed for drive %s: %s", self.drive, exc, exc_info=True
            )
            self.fatal_error = str(exc) or type(exc).__name__
            self.log_cb(f"[ERROR] Rip session failed: {self.fatal_error}")
        finally:
            self.session_done_cb()

    def _run_session(self) -> None:
        os.makedirs(self.out_dir, exist_ok=True)
        info = probe_ffmpeg(self.ffmpeg)
        self.log_cb(f"FFmpeg version : {info['version']}")
        self.log_cb("Extraction     : Win32 SCSI Pass-Through (READ CD 0xBE)")
        self.log_cb("\u2500" * 60)

        drive_letter = self.drive.rstrip("/\\").rstrip(":")
        try:
            toc = read_toc(drive_letter, self.log_cb)
        except (OSError, RuntimeError, AudioSuiteError) as e:
            # A missing disc or an unavailable drive is an expected outcome,
            # not a crash: log the message without a traceback, and let the
            # session finish so the caller reports "failed", never hangs.
            _logging.getLogger(__name__).warning(
                "TOC read failed for drive %s: %s", self.drive, e
            )
            self.log_cb(f"TOC read failed: {e}")
            self.fatal_error = str(e) or type(e).__name__
            toc = []

        toc_map = {e["number"]: e for e in toc}
        verification_plan = self._build_verification_plan(toc)

        done_paths: list[tuple[int, str]] = []

        def _track_done_wrap(num: int, ok: bool, path: str, msg: str) -> None:
            if ok and path:
                done_paths.append((num, path))
            self.track_done_cb(num, ok, path, msg)

        for track in self.tracks:
            if self._cancelled:
                break
            toc_entry = toc_map.get(track["number"])
            if not toc_entry:
                self.log_cb(f"[WARN] No TOC entry for track {track['number']}")
                self.track_done_cb(track["number"], False, "", "No TOC entry found")
                continue
            task = RipTask(
                drive=self.drive,
                track=track,
                toc_entry=toc_entry,
                out_dir=self.out_dir,
                fmt=self.fmt,
                codec_args=self.codec_args,
                progress_cb=self.progress_cb,
                done_cb=_track_done_wrap,
                ffmpeg_path=self.ffmpeg,
                log_cb=self.log_cb,
                verification_config=self.verification_config,
                verification=verification_plan,
            )
            self._current_task = task
            task.run()
        # Spin down the drive now ripping is complete.
        # Best-effort: a spin-down failure must not abort the session, but it
        # must never be silently swallowed -- we log it at WARNING level.
        try:
            spin_down_drive(self.drive.rstrip("/\\").rstrip(":"), self.log_cb)
        except (OSError, RuntimeError, AudioSuiteError) as _sd_exc:
            # AudioIOError is an AudioSuiteError, not an OSError: a drive that
            # has already gone away (or never opened) must not fail the
            # session after the tracks were reported.
            _logging.getLogger(__name__).warning(
                "Drive spin-down failed after rip (non-fatal): %s", _sd_exc
            )
        if self.write_cue and done_paths:
            self._write_rip_cue(done_paths)

    def _build_verification_plan(self, toc: list[dict[str, int]]) -> VerificationPlan:
        """Resolve the disc-level verification plan once per session.

        For ACCURATERIP the disc IDs are computed from the TOC and looked up
        in a single network call reused by every track. Lookup failures
        degrade to OFFLINE so ripping still proceeds; only a found but
        mismatching record blocks a write.
        """
        if self.verify_mode is RipVerificationMode.OFF or not toc:
            return VerificationPlan(mode=self.verify_mode, toc=tuple(toc))
        if self.verify_mode is RipVerificationMode.TWICE:
            return VerificationPlan(mode=self.verify_mode, toc=tuple(toc))

        starts = [entry["start_lba"] for entry in toc]
        leadout = toc[-1]["start_lba"] + toc[-1]["sectors"]
        try:
            disc_ids = compute_disc_ids(starts, leadout)
        except ValueError as exc:
            self.log_cb(f"[Verify] AccurateRip disc ID failed: {exc}")
            return VerificationPlan(
                mode=self.verify_mode,
                lookup=LookupOffline(reason=f"disc ID: {exc}"),
                toc=tuple(toc),
            )
        self.log_cb(
            f"[Verify] Disc ID ({disc_ids.track_count} tracks): "
            f"{disc_ids.disc_id1:08X} / {disc_ids.disc_id2:08X} / "
            f"CDDB {disc_ids.cddb_id:08X}"
        )
        try:
            lookup = AccurateRipClient().resolve(disc_ids.accuraterip_path)
        except Exception as exc:  # never crash a rip on a lookup bug
            _logging.getLogger(__name__).error(
                "AccurateRip lookup raised unexpectedly: %s", exc, exc_info=True
            )
            lookup = LookupOffline(reason=f"lookup error: {exc}")
        if isinstance(lookup, LookupFound):
            self.log_cb(
                f"[Verify] AccurateRip: {len(lookup.entries)} record(s) for this disc"
            )
        elif isinstance(lookup, LookupNotFound):
            self.log_cb(f"[Verify] AccurateRip: {lookup.reason}")
        else:
            reason = lookup.reason if isinstance(lookup, LookupOffline) else str(lookup)
            self.log_cb(f"[Verify] AccurateRip: offline \u2014 {reason}")
        return VerificationPlan(mode=self.verify_mode, lookup=lookup, toc=tuple(toc))

    def _write_rip_cue(self, done_paths: list[tuple[int, str]]) -> None:
        """Write one .cue sheet per album folder once all tracks succeeded.

        A track-per-file rip emits **one** ``FILE`` block per encoded track,
        each holding that track's single ``TRACK`` at ``INDEX 01 00:00:00``.
        That is the only structure a cue-aware player can resolve for this
        layout: a sheet with one ``FILE`` naming every track, all at offset
        zero, describes a single continuous image the rip never produced.

        Args:
            done_paths: ``(track_number, output_path)`` pairs for tracks whose
                encode finished successfully and produced a file.
        """
        track_by_number = {str(t.get("number")): t for t in self.tracks}
        grouped: dict[str, list[tuple[int, str]]] = {}
        for num, path in done_paths:
            grouped.setdefault(os.path.dirname(path), []).append((num, path))

        for album_dir, entries in grouped.items():
            entries.sort(key=lambda item: item[0])
            first = track_by_number.get(str(entries[0][0]), {})
            album_title = first.get("album", "") or ""
            album_artist = (
                first.get("album_artist", "") or first.get("artist", "") or ""
            )
            try:
                cue_name = os.path.join(
                    album_dir,
                    f"{_safe_filename(album_title) or 'album'}.cue",
                )
                os.makedirs(album_dir, exist_ok=True)
                files: list[CueFileSpec] = []
                for num, path in entries:
                    track = track_by_number.get(str(num), {})
                    title = track.get("title", "") or f"Track {num:02d}"
                    artist = track.get("artist", "") or ""
                    # ``path`` is captured here, inside the loop: every FILE
                    # must name its own encoded image.  ``start_ms`` is stated
                    # explicitly rather than leaning on TrackSpec's default —
                    # each file begins at its own zero.
                    files.append(
                        CueFileSpec(
                            filename=os.path.basename(path),
                            tracks=(
                                TrackSpec(
                                    number=num,
                                    title=title,
                                    performer=artist,
                                    start_ms=0,
                                ),
                            ),
                        )
                    )
                cue_text = build_cue(
                    title=album_title,
                    performer=album_artist,
                    files=tuple(files),
                )
                write_cue(cue_name, cue_text)
                self.log_cb(f"CUE sheet written: {cue_name}")
            except Exception as _cue_exc:  # never abort the session for a CUE write
                _logging.getLogger(__name__).error(
                    "Failed to write CUE sheet for %s: %s",
                    album_dir,
                    _cue_exc,
                    exc_info=True,
                )
                self.log_cb(f"[WARN] CUE sheet not written: {_cue_exc}")
