"""test_file_processor.py

Tests for replaygain_analyzer.core.file_processor's album-gain write phase.

Changed in 2.1.7 (backlog A1): album loudness is the integrated loudness of the
album's *combined signal*, measured in one FFmpeg pass, because the
duration-weighted formula is only an approximation of a gated measurement. The
benchmark below builds a two-track folder whose quiet track falls below the
combined signal's relative gate and pins the measured difference, so the
approximation cannot quietly come back as the primary route.
"""

from __future__ import annotations

import math
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from mutagen.flac import FLAC
from pydub import AudioSegment

from replaygain_analyzer.core.ffmpeg_metrics import (
    get_metrics,
    measure_album_loudness,
)
from replaygain_analyzer.core.file_processor import _write_worker, _WriteJob
from replaygain_analyzer.core.gain_calculator import calculate_album_gain

SAMPLE_RATE = 44100
TARGET_LUFS = -14.0

# Measured on the fixture below (20 s at -10 dBFS + 20 s at -35 dBFS): the
# weighted formula lands 3.00 dB below the combined signal's gated loudness,
# because the quiet track falls under the combined signal's relative gate and
# contributes nothing there while still dragging the mean-square average down.
# A mostly-silent-tail album measured 2.33 dB apart in the same session.
MEASURED_APPROXIMATION_ERROR_DB = 3.0


def _write_tone(path: Path, seconds: float, level_dbfs: float) -> str:
    """Write a mono 440 Hz tone at ``level_dbfs`` as a real FLAC file."""
    frames = int(SAMPLE_RATE * seconds)
    t = np.arange(frames) / SAMPLE_RATE
    amplitude = 10 ** (level_dbfs / 20.0)
    samples = np.sin(2 * np.pi * 440.0 * t) * amplitude
    pcm = (samples * 32767).astype(np.int16)
    AudioSegment(
        data=pcm.tobytes(),
        sample_width=2,
        frame_rate=SAMPLE_RATE,
        channels=1,
    ).export(str(path), format="flac")
    return str(path)


@pytest.fixture()
def album(tmp_path: Path) -> tuple[str, list[str]]:
    folder = tmp_path / "album"
    folder.mkdir()
    paths = [
        _write_tone(folder / "01 loud.flac", 20.0, -10.0),
        _write_tone(folder / "02 quiet.flac", 20.0, -35.0),
    ]
    return str(folder), paths


def _measure(paths: list[str]) -> list[dict[str, object]]:
    files_data: list[dict[str, object]] = []
    for path in paths:
        lufs, peak, duration_s = get_metrics(path)
        assert lufs is not None and duration_s is not None
        files_data.append(
            {
                "name": Path(path).name,
                "path": path,
                "lufs": lufs,
                "peak": peak,
                "duration_s": duration_s,
                "track_gain": TARGET_LUFS - lufs,
            }
        )
    return files_data


def _write(folder: str, files_data: list[dict[str, object]]) -> dict[str, object]:
    captured: dict[str, object] = {}

    def _capture(**kwargs: object) -> None:
        captured.update(kwargs)

    _write_worker(
        _WriteJob(
            folder_path=folder,
            files_data=files_data,
            target_lufs=TARGET_LUFS,
            is_dry_run=False,
            apply_lossless_gain=False,
            on_folder_complete=_capture,
            lock=None,  # type: ignore[arg-type]  # unused by the write phase
            undo_batch=None,
        )
    )
    return captured


class TestAlbumGainBenchmark:
    """A1: the weighted formula is a fallback, never the primary album measure."""

    def test_approximation_is_measurably_wrong_on_an_uneven_album(self, album):
        folder, paths = album
        files_data = _measure(paths)

        combined = measure_album_loudness(paths)
        assert combined is not None, "FFmpeg could not measure the combined album"

        weighted_gain, _, weighted_str, _ = calculate_album_gain(
            TARGET_LUFS,
            [float(f["lufs"]) for f in files_data],  # type: ignore[arg-type]
            [float(f["peak"]) for f in files_data],  # type: ignore[arg-type]
            [float(f["duration_s"]) for f in files_data],  # type: ignore[arg-type]
        )
        combined_gain, _, combined_str, _ = calculate_album_gain(
            TARGET_LUFS,
            [float(f["lufs"]) for f in files_data],  # type: ignore[arg-type]
            [float(f["peak"]) for f in files_data],  # type: ignore[arg-type]
            [float(f["duration_s"]) for f in files_data],  # type: ignore[arg-type]
            album_lufs=combined,
        )

        error = abs(weighted_gain - combined_gain)
        print(
            f"\n[A1] weighted {weighted_str} ({weighted_gain:+.2f} dB) vs "
            f"combined {combined_str} ({combined_gain:+.2f} dB) "
            f"-> {error:.2f} dB apart"
        )
        assert error == pytest.approx(MEASURED_APPROXIMATION_ERROR_DB, abs=0.3), (
            "the fixture must keep exercising the gating difference: "
            f"weighted {weighted_str} vs combined {combined_str}"
        )

        captured = _write(folder, files_data)
        assert captured["album_gain_str"] == combined_str
        assert captured["album_gain_str"] != weighted_str
        assert "measured from: combined signal" in str(captured["log_header"])

        # The tag on disk carries the combined measurement, not the approximation.
        audio = FLAC(paths[0])
        assert audio.tags is not None
        assert audio.tags["REPLAYGAIN_ALBUM_GAIN"] == [combined_str]

    def test_unreadable_combined_signal_falls_back_to_weighted_formula(self, album):
        folder, paths = album
        files_data = _measure(paths)

        weighted_gain, _, weighted_str, _ = calculate_album_gain(
            TARGET_LUFS,
            [float(f["lufs"]) for f in files_data],  # type: ignore[arg-type]
            [float(f["peak"]) for f in files_data],  # type: ignore[arg-type]
            [float(f["duration_s"]) for f in files_data],  # type: ignore[arg-type]
        )
        assert math.isfinite(weighted_gain)

        with patch(
            "replaygain_analyzer.core.file_processor.measure_album_loudness",
            return_value=None,
        ):
            captured = _write(folder, files_data)

        assert captured["album_gain_str"] == weighted_str
        assert "measured from: duration-weighted fallback" in str(
            captured["log_header"]
        )
        audio = FLAC(paths[0])
        assert audio.tags is not None
        assert audio.tags["REPLAYGAIN_ALBUM_GAIN"] == [weighted_str]
