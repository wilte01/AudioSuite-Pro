"""
encoding_pipeline.py  –  Per-track CD rip orchestration.

RipTask coordinates the two-stage extraction/encode pipeline for a single
audio CD track: first raw sector reads via SCSI Pass-Through (delegated to
extract_track_scsi), then FFmpeg encoding with metadata.
"""

import logging as _logging
import os
import subprocess
import tempfile
from collections.abc import Callable
from typing import Any

from cd_ripper.core.metadata_resolver import (
    FORMAT_OPTIONS,
    _build_metadata_args,
    _run_ffmpeg_streaming,
    _safe_filename,
)
from cd_ripper.core.track_processor import (
    RipVerificationConfig,
    extract_track_scsi,
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
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _is_cancelled(self) -> bool:
        return self._cancelled

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
        os.makedirs(album_dir, exist_ok=True)

        fname = f"{num:02d} - {title}.{ext}"
        out_path = os.path.join(album_dir, fname)
        duration = self.track.get("duration", 0)

        self.progress_cb(num, 0, "Starting\u2026")
        tmp_wav = None
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
            )

            if self._cancelled:
                self.done_cb(num, False, "", "Cancelled")
                return

            if not os.path.exists(tmp_wav) or os.path.getsize(tmp_wav) < 44:
                self.done_cb(num, False, "", "Extraction produced empty file")
                return

            # Stage 2: encode
            self.progress_cb(num, 92, "Encoding\u2026")
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
                self.done_cb(num, True, out_path, "")
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
            if tmp_wav and os.path.exists(tmp_wav):
                try:
                    os.remove(tmp_wav)
                except OSError:
                    _logging.getLogger(__name__).debug(
                        "Could not remove temp WAV %s", tmp_wav, exc_info=True
                    )
