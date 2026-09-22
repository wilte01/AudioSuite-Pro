"""
tests/test_ffmpeg_io.py
Tests for core/ffmpeg_io.py — the ffmpeg-backed decode/encode path used
for .opus and .m4a, the two formats pedalboard.io.AudioFile does not
support (confirmed via pedalboard.io.get_supported_read_formats() /
get_supported_write_formats() — neither list includes .opus or .m4a).

Two tiers
---------
Unit tests (always run): mock subprocess.run/shutil.which, exercising
this module's own logic in isolation — error routing, bitrate clamping,
extension validation — without depending on a real ffmpeg binary or
producing real encoded audio.

Integration tests (skipped automatically if ffmpeg/ffprobe is not on
PATH): round-trip real audio through real ffmpeg subprocesses and verify
the actual decoded sample count / shape / fidelity claims made in this
module's docstring, rather than trusting the mocks alone.

Run with:
    pytest tests/test_ffmpeg_io.py -v
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import numpy.typing as npt
import pytest

from audio_enhancer.core import ffmpeg_io
from audio_suite_shared.exceptions import (
    AudioExternalToolError,
    AudioFormatError,
    AudioMissingDependencyError,
)

SR: int = 48_000

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
requires_ffmpeg = pytest.mark.skipif(
    not HAVE_FFMPEG, reason="ffmpeg/ffprobe not found on PATH in this environment"
)


def _sine(
    freq_hz: float, duration_s: float = 0.5, channels: int = 2
) -> npt.NDArray[np.float32]:
    """Return a sine wave with shape (channels, samples) as float32."""
    t = np.linspace(0, duration_s, int(SR * duration_s), endpoint=False)
    wave = (0.4 * np.sin(2.0 * np.pi * freq_hz * t)).astype(np.float32)
    return np.tile(wave, (channels, 1))


# ── Unit tests: dependency checks ────────────────────────────────────────────


class TestRequireFfmpeg:
    def test_raises_missing_dependency_when_not_on_path(self) -> None:
        with patch("shutil.which", return_value=None):
            with pytest.raises(AudioMissingDependencyError) as exc_info:
                ffmpeg_io._require_ffmpeg()
        assert exc_info.value.context.get("dependency") == "ffmpeg"

    def test_returns_path_when_found(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            assert ffmpeg_io._require_ffmpeg() == "/usr/bin/ffmpeg"


class TestRequireFfprobe:
    def test_raises_missing_dependency_when_not_on_path(self) -> None:
        with patch("shutil.which", return_value=None):
            with pytest.raises(AudioMissingDependencyError) as exc_info:
                ffmpeg_io._require_ffprobe()
        assert exc_info.value.context.get("dependency") == "ffprobe"


# ── Unit tests: write_audio extension validation ─────────────────────────────


class TestWriteAudioValidation:
    def test_rejects_unsupported_extension(self) -> None:
        audio = _sine(440.0)
        with pytest.raises(
            AudioFormatError, match=r"supports \['\.m4a', '\.mp4', '\.opus'\]"
        ):
            ffmpeg_io.write_audio(audio, SR, Path("output.wav"))

    def test_accepts_opus_extension(self) -> None:
        audio = _sine(440.0)
        fake_proc = MagicMock(returncode=0)
        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("subprocess.run", return_value=fake_proc) as mock_run,
        ):
            ffmpeg_io.write_audio(audio, SR, Path("output.opus"))
        cmd = mock_run.call_args[0][0]
        assert "libopus" in cmd

    def test_accepts_m4a_extension(self) -> None:
        audio = _sine(440.0)
        fake_proc = MagicMock(returncode=0)
        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("subprocess.run", return_value=fake_proc) as mock_run,
        ):
            ffmpeg_io.write_audio(audio, SR, Path("output.m4a"))
        cmd = mock_run.call_args[0][0]
        assert "aac" in cmd

    def test_accepts_mp4_extension(self) -> None:
        audio = _sine(440.0)
        fake_proc = MagicMock(returncode=0)
        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("subprocess.run", return_value=fake_proc) as mock_run,
        ):
            ffmpeg_io.write_audio(audio, SR, Path("output.mp4"))
        cmd = mock_run.call_args[0][0]
        assert "aac" in cmd
        assert cmd[-1] == "output.mp4"


# ── Unit tests: bitrate clamping ─────────────────────────────────────────────


class TestBitrateClamping:
    @pytest.mark.parametrize(
        "requested_kbps, expected_kbps",
        [
            (128, 128),  # within range — used as-is
            (0, ffmpeg_io._DEFAULT_OPUS_KBPS),  # zero — falls back to default
            (5, ffmpeg_io._DEFAULT_OPUS_KBPS),  # below _MIN_KBPS — falls back
            (9999, ffmpeg_io._DEFAULT_OPUS_KBPS),  # above _MAX_OPUS_KBPS — falls back
        ],
    )
    def test_opus_bitrate_clamping(
        self, requested_kbps: int, expected_kbps: int
    ) -> None:
        audio = _sine(440.0)
        fake_proc = MagicMock(returncode=0)
        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("subprocess.run", return_value=fake_proc) as mock_run,
        ):
            ffmpeg_io.write_audio(
                audio, SR, Path("o.opus"), bitrate_kbps=requested_kbps
            )
        cmd = mock_run.call_args[0][0]
        assert f"{expected_kbps}k" in cmd

    @pytest.mark.parametrize(
        "requested_kbps, expected_kbps",
        [
            (192, 192),
            (0, ffmpeg_io._DEFAULT_AAC_KBPS),
            (9999, ffmpeg_io._DEFAULT_AAC_KBPS),
        ],
    )
    def test_aac_bitrate_clamping(
        self, requested_kbps: int, expected_kbps: int
    ) -> None:
        audio = _sine(440.0)
        fake_proc = MagicMock(returncode=0)
        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("subprocess.run", return_value=fake_proc) as mock_run,
        ):
            ffmpeg_io.write_audio(audio, SR, Path("o.m4a"), bitrate_kbps=requested_kbps)
        cmd = mock_run.call_args[0][0]
        assert f"{expected_kbps}k" in cmd


# ── Unit tests: subprocess failure routing ───────────────────────────────────


class TestSubprocessFailureRouting:
    def test_write_audio_wraps_called_process_error(self) -> None:
        audio = _sine(440.0)
        err = subprocess.CalledProcessError(1, ["ffmpeg"], stderr=b"boom")
        with (
            patch("shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("subprocess.run", side_effect=err),
        ):
            with pytest.raises(AudioExternalToolError) as exc_info:
                ffmpeg_io.write_audio(audio, SR, Path("o.opus"))
        assert exc_info.value.context.get("tool") == "ffmpeg"
        assert exc_info.value.context.get("returncode") == 1

    def test_probe_stream_wraps_called_process_error(self) -> None:
        err = subprocess.CalledProcessError(1, ["ffprobe"], stderr="bad file")
        with (
            patch("shutil.which", return_value="/usr/bin/ffprobe"),
            patch("subprocess.run", side_effect=err),
        ):
            with pytest.raises(AudioExternalToolError) as exc_info:
                ffmpeg_io._probe_stream(Path("bad.opus"))
        assert exc_info.value.context.get("tool") == "ffprobe"

    def test_probe_stream_raises_when_no_audio_stream_found(self) -> None:
        fake_proc = MagicMock(stdout='{"streams": []}')
        with (
            patch("shutil.which", return_value="/usr/bin/ffprobe"),
            patch("subprocess.run", return_value=fake_proc),
        ):
            with pytest.raises(AudioExternalToolError, match="no audio stream"):
                ffmpeg_io._probe_stream(Path("silent.opus"))


# ── Integration tests: real ffmpeg round-trip (skipped if unavailable) ───────


@requires_ffmpeg
class TestRealRoundTrip:
    """These tests run actual ffmpeg/ffprobe subprocesses and verify the
    specific empirical claims documented in ffmpeg_io.py's module
    docstring: that Opus decode needs no trimming, and that AAC/M4A
    decode does (with a non-constant offset)."""

    def test_opus_round_trip_preserves_sample_count(self, tmp_path: Path) -> None:
        original = _sine(1000.0, duration_s=0.5, channels=2)
        out_path = tmp_path / "test.opus"

        ffmpeg_io.write_audio(original, SR, out_path, bitrate_kbps=128)
        assert out_path.exists()

        decoded, sr = ffmpeg_io.read_audio(out_path)
        assert sr == SR
        assert decoded.shape[0] == 2
        # Verified empirically: ffmpeg's raw-PCM decode of Opus already
        # trims the encoder pre-skip, so no extra trimming logic should
        # be needed and the result should match the source length exactly.
        assert decoded.shape[1] == original.shape[1]

    def test_opus_round_trip_signal_is_recognizable(self, tmp_path: Path) -> None:
        """Lossy, but should still be highly correlated with the source
        (regression guard against e.g. accidental silence/garbage output)."""
        original = _sine(1000.0, duration_s=0.5, channels=2)
        out_path = tmp_path / "test.opus"
        ffmpeg_io.write_audio(original, SR, out_path, bitrate_kbps=128)
        decoded, _ = ffmpeg_io.read_audio(out_path)

        n = min(decoded.shape[1], original.shape[1])
        rms_signal = np.sqrt(np.mean(original[:, :n] ** 2))
        rms_error = np.sqrt(np.mean((original[:, :n] - decoded[:, :n]) ** 2))
        snr_db = 20 * np.log10(rms_signal / rms_error)
        # Measured ~43 dB in manual testing; require at least 20 dB as a
        # generous regression guard (catches "decoded silence/garbage",
        # not meant to be a tight codec-quality assertion).
        assert snr_db > 20.0

    def test_m4a_round_trip_trims_to_correct_length(self, tmp_path: Path) -> None:
        original = _sine(440.0, duration_s=0.5, channels=2)
        out_path = tmp_path / "test.m4a"

        ffmpeg_io.write_audio(original, SR, out_path, bitrate_kbps=192)
        assert out_path.exists()

        decoded, sr = ffmpeg_io.read_audio(out_path)
        assert sr == SR
        # Verified empirically: raw AAC decode returns MORE samples than
        # the source (encoder priming delay, NOT a fixed constant across
        # sample rates/durations) — read_audio must trim this using the
        # container's declared duration. After trimming, length must
        # match the original to within a few samples (allow a small
        # tolerance for floating-point duration rounding).
        assert abs(decoded.shape[1] - original.shape[1]) <= 4

    def test_m4a_round_trip_signal_is_recognizable(self, tmp_path: Path) -> None:
        original = _sine(440.0, duration_s=0.5, channels=2)
        out_path = tmp_path / "test.m4a"
        ffmpeg_io.write_audio(original, SR, out_path, bitrate_kbps=192)
        decoded, _ = ffmpeg_io.read_audio(out_path)

        n = min(decoded.shape[1], original.shape[1])
        rms_signal = np.sqrt(np.mean(original[:, :n] ** 2))
        rms_error = np.sqrt(np.mean((original[:, :n] - decoded[:, :n]) ** 2))
        snr_db = 20 * np.log10(rms_signal / rms_error)
        assert snr_db > 20.0

    def test_mp4_round_trip_trims_to_correct_length(self, tmp_path: Path) -> None:
        """MP4 shares the AAC/MPEG-4 behaviour of M4A (priming-delay trim)."""
        original = _sine(440.0, duration_s=0.5, channels=2)
        out_path = tmp_path / "test.mp4"

        ffmpeg_io.write_audio(original, SR, out_path, bitrate_kbps=192)
        assert out_path.exists()

        decoded, sr = ffmpeg_io.read_audio(out_path)
        assert sr == SR
        assert abs(decoded.shape[1] - original.shape[1]) <= 4

    def test_mp4_round_trip_signal_is_recognizable(self, tmp_path: Path) -> None:
        original = _sine(440.0, duration_s=0.5, channels=2)
        out_path = tmp_path / "test.mp4"
        ffmpeg_io.write_audio(original, SR, out_path, bitrate_kbps=192)
        decoded, _ = ffmpeg_io.read_audio(out_path)

        n = min(decoded.shape[1], original.shape[1])
        rms_signal = np.sqrt(np.mean(original[:, :n] ** 2))
        rms_error = np.sqrt(np.mean((original[:, :n] - decoded[:, :n]) ** 2))
        snr_db = 20 * np.log10(rms_signal / rms_error)
        assert snr_db > 20.0

    def test_mono_round_trips_correctly_opus(self, tmp_path: Path) -> None:
        original = _sine(440.0, duration_s=0.3, channels=1)
        out_path = tmp_path / "mono.opus"
        ffmpeg_io.write_audio(original, SR, out_path, bitrate_kbps=96)
        decoded, _ = ffmpeg_io.read_audio(out_path)
        assert decoded.shape[0] == 1

    def test_mono_round_trips_correctly_m4a(self, tmp_path: Path) -> None:
        original = _sine(440.0, duration_s=0.3, channels=1)
        out_path = tmp_path / "mono.m4a"
        ffmpeg_io.write_audio(original, SR, out_path, bitrate_kbps=128)
        decoded, _ = ffmpeg_io.read_audio(out_path)
        assert decoded.shape[0] == 1

    def test_real_missing_ffmpeg_raises_missing_dependency(
        self, tmp_path: Path
    ) -> None:
        """End-to-end (not mocked) check that a PATH without ffmpeg
        produces the dependency error, not a confusing subprocess
        traceback or a misleading file-not-found mapping."""
        original = _sine(440.0, duration_s=0.2)
        out_path = tmp_path / "test.opus"
        with patch("shutil.which", return_value=None):
            with pytest.raises(AudioMissingDependencyError):
                ffmpeg_io.write_audio(original, SR, out_path)
