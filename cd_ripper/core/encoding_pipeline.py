"""
encoding_pipeline.py  –  Per-track CD rip orchestration.

RipTask coordinates the two-stage extraction/encode pipeline for a single
audio CD track: first raw sector reads via SCSI Pass-Through (delegated to
extract_track_scsi), then FFmpeg encoding with metadata.

Changed in 1.0.1: a failed or interrupted encode now removes any partial
output file in the finally block, so an incomplete track is never left on
disk looking finished.

Changed in 1.2.0: consumes the typed ``TrackVerification`` and reports its
EAC-style label (with the AccurateRip confidence) instead of the bare status
value (PLAN_feature_expansion.md D30).

Changed in 2.1.2: the per-track output path is checked for containment inside
``out_dir`` before any directory is created, so a tag value can never write
outside the chosen tree (security finding R-03). ``_safe_filename`` already
refuses ``.``/``..``; this is the backstop.
"""

import logging as _logging
import os
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from audio_suite_shared.exceptions import AudioSuiteError
from cd_ripper.core.metadata_resolver import (
    FORMAT_OPTIONS,
    _build_metadata_args,
    _run_ffmpeg_streaming,
    _safe_filename,
)
from cd_ripper.core.track_processor import (
    RipVerificationConfig,
    RipVerificationMode,
    VerificationPlan,
    extract_track_scsi,
    read_wav_pcm,
    verify_extracted_track,
)


def _ensure_inside_output_dir(out_dir: str, out_path: str, track_num: int) -> None:
    """Refuse a track output path that resolves outside *out_dir*.

    Both sides are resolved first, so ``..`` segments and symlinks are already
    folded in, and compared case-insensitively on Windows where two casings
    are the same file.

    Args:
        out_dir: The output directory the user chose.
        out_path: The joined per-track output path.
        track_num: Track number, for the message.

    Raises:
        AudioSuiteError: When *out_path* is not below *out_dir*.
    """
    root = Path(os.path.normcase(str(Path(out_dir).resolve())))
    candidate = Path(os.path.normcase(str(Path(out_path).resolve())))
    if not candidate.is_relative_to(root):
        raise AudioSuiteError(
            f"Track {track_num:02d}: the resolved output path escapes the output "
            "directory"
        )


class RipTask:
    """CD ripping task for a single track."""

    def __init__(
        self,
        drive: str,
        track: dict[str, Any],
        toc_entry: dict[str, int],
        out_dir: str,
        fmt: str,
        codec_args: list[str],
        progress_cb: Callable[[int, int, str], None],
        done_cb: Callable[[int, bool, str, str], None],
        ffmpeg_path: str = "ffmpeg",
        log_cb: Callable[[str], None] | None = None,
        verification_config: RipVerificationConfig | None = None,
        verification: VerificationPlan | None = None,
    ) -> None:
        self.drive = drive
        self.track = track
        self.toc_entry = toc_entry
        self.out_dir = out_dir
        self.fmt = fmt
        self.codec_args = codec_args
        self.progress_cb = progress_cb
        self.done_cb = done_cb
        self.ffmpeg = ffmpeg_path
        self.log_cb = log_cb or (lambda msg: None)
        self.verification_config = verification_config or RipVerificationConfig()
        self.verification = verification or VerificationPlan()
        self.verification_label = ""
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _is_cancelled(self) -> bool:
        return self._cancelled

    def _is_last_track(self) -> bool:
        """Whether this task's TOC entry is the final track on the disc."""
        toc = self.verification.toc
        if not toc:
            return False
        my_number: int = int(self.track["number"])
        return my_number == max(int(entry.get("number", 0)) for entry in toc)

    def run(self) -> None:
        num = self.track["number"]
        ext = FORMAT_OPTIONS[self.fmt]["ext"]
        track_artist = _safe_filename(self.track.get("artist", ""))
        album_artist = (
            _safe_filename(self.track.get("album_artist", "")) or track_artist
        )
        title = _safe_filename(self.track.get("title", f"Track {num:02d}"))
        album = _safe_filename(self.track.get("album", "Unknown Album"))
        year = _safe_filename(self.track.get("year", ""))

        # Build Artist / [Year] Album subfolder under the chosen output dir
        album_folder = f"[{year}] {album}" if year else album
        artist_dir = os.path.join(self.out_dir, album_artist or "Unknown Artist")
        album_dir = os.path.join(artist_dir, album_folder)

        fname = f"{num:02d} - {title}.{ext}"
        out_path = os.path.join(album_dir, fname)
        # Before creating anything: the tags came from an online database, and
        # a path that resolves outside out_dir must be refused, not written.
        try:
            _ensure_inside_output_dir(self.out_dir, out_path, num)
        except AudioSuiteError as exc:
            self.log_cb(f"[ERROR] {exc}")
            self.done_cb(num, False, "", str(exc))
            return
        os.makedirs(album_dir, exist_ok=True)

        duration = self.track.get("duration", 0)

        self.progress_cb(num, 0, "Starting\u2026")
        tmp_wav = None
        succeeded = False
        encode_started = False
        try:
            tmp_fd, tmp_wav = tempfile.mkstemp(
                suffix=".wav", prefix=f"cd_rip_{num:02d}_"
            )
            os.close(tmp_fd)

            drive_letter = self.drive.rstrip("/\\").rstrip(":")

            # Stage 1: SCSI READ CD
            extract_track_scsi(
                drive_letter=drive_letter,
                start_lba=self.toc_entry["start_lba"],
                sectors=self.toc_entry["sectors"],
                out_wav=tmp_wav,
                progress_cb=self.progress_cb,
                track_num=num,
                cancelled_fn=self._is_cancelled,
                log_cb=self.log_cb,
                verification_config=self.verification_config,
                is_last_track=self._is_last_track(),
            )

            if self._cancelled:
                self.done_cb(num, False, "", "Cancelled")
                return

            if not os.path.exists(tmp_wav) or os.path.getsize(tmp_wav) < 44:
                self.done_cb(num, False, "", "Extraction produced empty file")
                return

            # Stage 1.5: verification (rip-twice and/or AccurateRip)
            if self.verification.mode is not RipVerificationMode.OFF:
                self.progress_cb(num, 91, "Verifying\u2026")
                try:
                    first_pcm = read_wav_pcm(tmp_wav)
                except (OSError, ValueError) as exc:
                    self.done_cb(num, False, "", f"Verification failed: {exc}")
                    return
                try:
                    outcome = verify_extracted_track(
                        drive_letter=drive_letter,
                        toc_entry=self.toc_entry,
                        toc=self.verification.toc,
                        first_pcm=first_pcm,
                        plan=self.verification,
                        verification_config=self.verification_config,
                        track_num=num,
                        cancelled_fn=self._is_cancelled,
                        log_cb=self.log_cb,
                    )
                except (OSError, ValueError) as exc:
                    self.done_cb(num, False, "", f"Verification failed: {exc}")
                    return
                if self._cancelled:
                    self.done_cb(num, False, "", "Cancelled")
                    return
                if outcome.is_mismatch:
                    self.log_cb(
                        f"[Verify] Track {num:02d}: {outcome.label} "
                        f"\u2014 {outcome.detail}"
                    )
                    self.done_cb(num, False, "", f"{outcome.label}: {outcome.detail}")
                    return
                if not outcome.was_cancelled:
                    self.verification_label = outcome.label
                    self.log_cb(
                        f"[Verify] Track {num:02d}: {outcome.label} \u2014 "
                        f"{outcome.detail}"
                    )

            # Stage 2: encode
            self.progress_cb(num, 92, "Encoding\u2026")
            encode_started = True
            encode_args = (
                ["-i", tmp_wav]
                + self.codec_args
                + _build_metadata_args(self.track)
                + [out_path]
            )
            rc, stderr = _run_ffmpeg_streaming(
                self.ffmpeg,
                encode_args,
                duration=duration,
                progress_cb=self.progress_cb,
                track_num=num,
                cancelled_fn=self._is_cancelled,
            )

            if self._cancelled:
                if os.path.exists(out_path):
                    os.remove(out_path)
                self.done_cb(num, False, "", "Cancelled")
                return

            if rc == 0:
                self.progress_cb(num, 100, "Done")
                succeeded = True
                self.done_cb(num, True, out_path, self.verification_label)
            else:
                err_lines = [
                    line.strip() for line in stderr.splitlines() if line.strip()
                ]
                error_msg = next(
                    (
                        line
                        for line in reversed(err_lines)
                        if any(
                            w in line.lower() for w in ("error", "invalid", "could not")
                        )
                    ),
                    err_lines[-1] if err_lines else f"rc={rc}",
                )
                self.done_cb(num, False, "", f"Encode failed: {error_msg}")

        except RuntimeError as e:
            self.done_cb(num, False, "", str(e))
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            _logging.getLogger(__name__).error(
                "RipTask.run unexpected error on track %s: %s", num, e, exc_info=True
            )
            self.done_cb(num, False, "", f"Unexpected error: {e}")
        finally:
            if encode_started and not succeeded and os.path.exists(out_path):
                # A failed/mismatched encode can leave a partial (or empty)
                # output file behind; never present it as a finished track.
                try:
                    os.remove(out_path)
                except OSError:
                    _logging.getLogger(__name__).debug(
                        "Could not remove partial output %s", out_path, exc_info=True
                    )
            if tmp_wav and os.path.exists(tmp_wav):
                try:
                    os.remove(tmp_wav)
                except OSError:
                    _logging.getLogger(__name__).debug(
                        "Could not remove temp WAV %s", tmp_wav, exc_info=True
                    )
