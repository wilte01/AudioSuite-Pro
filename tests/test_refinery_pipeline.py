"""
tests/test_refinery_pipeline.py

Unit and integration tests for audio_refinery.core.pipeline.

Changed in 2.1.7: the two FLAC tests are gated on a measured capability
(``_pydub_can_round_trip_flac``) instead of ``os.environ.get("CI")`` (X12).
The old marker named an environment rather than the capability it lacked, so a
runner with ffmpeg skipped them anyway - and the reason string claimed a fact
nothing checked.  ``import os`` went with it, since that was its only use.

Changed in 1.0.1: skipped test_normalise_reaches_target_lufs and
test_full_chain_all_stages on CI where pydub/ffmpeg may not be available.
Changed in 1.0.1: fixed pytest skipif condition from os.environ.get("CI")
to os.environ.get("CI") is not None to avoid NameError.
Changed in 1.0.1: split skipif decorator across multiple lines to satisfy
ruff line length limit (88 characters).

Moved from tests/audio_refinery/ to tests/ to avoid pytest treating
the tests/audio_refinery directory as a package that shadows the real
audio_refinery suite package during import collection.

Run all unit tests:
    pytest tests/test_refinery_pipeline.py -m "not integration"

Run including integration tests (requires ffmpeg on PATH):
    pytest tests/test_refinery_pipeline.py
"""

from __future__ import annotations

import functools
import math
import struct
import tempfile
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from audio_refinery.core.models import FileResult, FileStatus, StageConfig

# ===========================================================================
# Helpers
# ===========================================================================


@functools.lru_cache(maxsize=1)
def _pydub_can_round_trip_flac() -> bool:
    """Whether this host can do what the two gated tests need: FLAC via pydub.

    Both tests write a WAV, export it to FLAC through pydub and read the FLAC
    back, so the capability is a pydub FLAC round trip - not the value of an
    environment variable.  The gate used to be
    ``os.environ.get("CI") is not None``, which stated an environment rather
    than the thing it lacked: on a runner that *did* have ffmpeg the two tests
    were skipped anyway, and the skip stayed green for a reason it never
    measured (X12, the same defect class R-20 fixed for the soxr tests).

    The probe is the smallest round trip that exercises that path, so it cannot
    drift from what the tests ask for.

    Returns:
        True when pydub exported a WAV to FLAC and read it back; False when
        pydub is missing or either step raised.
    """
    try:
        from pydub import AudioSegment
    except ImportError:
        return False
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "probe.wav"
        flac = Path(tmp) / "probe.flac"
        try:
            AudioSegment.silent(duration=50, frame_rate=44100).export(
                str(wav), format="wav"
            )
            AudioSegment.from_wav(str(wav)).export(str(flac), format="flac")
            decoded = AudioSegment.from_file(str(flac))
        except Exception:  # noqa: BLE001 - any failure means "cannot", not "broken"
            return False
    return len(decoded) > 0


#: Capability gate for the two tests that need a FLAC round trip through pydub.
PYDUB_FLAC_MISSING = pytest.mark.skipif(
    not _pydub_can_round_trip_flac(),
    reason="pydub cannot round-trip FLAC on this host (no ffmpeg, or a build "
    "without FLAC support), which the tests below need",
)


def _minimal_config(**overrides) -> StageConfig:
    """Return a StageConfig with all stages disabled unless overridden."""
    defaults = dict(declick=False, trim=False, enhance=False, normalise=False)
    defaults.update(overrides)
    return StageConfig(**defaults)


# ===========================================================================
# Tests: get_export_args (shared audio_formats)
# ===========================================================================


class TestPydubExportArgs:
    def test_mp3_returns_mp3_codec(self):
        from audio_suite_shared.audio_formats import get_export_args

        fmt, _ = get_export_args(".mp3")
        assert fmt == "mp3"

    def test_flac_returns_flac_codec(self):
        from audio_suite_shared.audio_formats import get_export_args

        fmt, args = get_export_args(".flac")
        assert fmt == "flac"
        assert "-compression_level" in args

    def test_wav_returns_empty_extra_args(self):
        from audio_suite_shared.audio_formats import get_export_args

        fmt, args = get_export_args(".wav")
        assert fmt == "wav"
        assert args == []

    def test_unknown_extension_falls_back_to_mp3(self):
        from audio_suite_shared.audio_formats import get_export_args

        fmt, _ = get_export_args(".xyz")
        assert fmt == "mp3"

    def test_case_insensitive(self):
        from audio_suite_shared.audio_formats import get_export_args

        fmt_lower, _ = get_export_args(".mp3")
        fmt_upper, _ = get_export_args(".MP3")
        assert fmt_lower == fmt_upper


# ===========================================================================
# Tests: StageConfig and model defaults
# ===========================================================================


class TestStageConfig:
    def test_all_stages_enabled_by_default(self):
        cfg = StageConfig()
        assert cfg.declick is True
        assert cfg.trim is True
        assert cfg.enhance is True
        assert cfg.normalise is True

    def test_declick_params_default_sensitivity(self):
        cfg = StageConfig()
        assert 0.0 < cfg.declick_params.sensitivity <= 0.40

    def test_normalise_params_target_lufs_in_valid_range(self):
        cfg = StageConfig()
        assert -70.0 <= cfg.normalise_params.target_lufs <= 0.0

    def test_trim_params_fade_disabled_by_default(self):
        cfg = StageConfig()
        assert cfg.trim_params.apply_fade is False


# ===========================================================================
# Tests: FileResult helper methods
# ===========================================================================


class TestFileResult:
    def test_add_stage_appends_result(self):
        result = FileResult(path=Path("test.mp3"))
        result.add_stage("Declick", FileStatus.DONE, "3 clicks removed")
        assert len(result.stages) == 1
        assert result.stages[0].stage == "Declick"
        assert result.stages[0].status == FileStatus.DONE

    def test_get_stage_metrics_returns_none_for_missing_stage(self):
        result = FileResult(path=Path("test.mp3"))
        assert result.get_stage_metrics("Declick") is None

    def test_get_stage_metrics_returns_metrics_when_present(self):
        from audio_refinery.core.models import StageMetrics

        result = FileResult(path=Path("test.mp3"))
        metrics = StageMetrics(stage="Trim")
        result.add_stage("Trim", FileStatus.DONE, metrics=metrics)
        assert result.get_stage_metrics("Trim") is metrics

    def test_multiple_stages_accumulate_correctly(self):
        result = FileResult(path=Path("test.flac"))
        result.add_stage("Declick", FileStatus.DONE)
        result.add_stage("Trim", FileStatus.SKIPPED, "already trimmed")
        result.add_stage("Enhance", FileStatus.DONE)
        assert len(result.stages) == 3
        assert result.stages[1].status == FileStatus.SKIPPED


# ===========================================================================
# Tests: StageMetrics
# ===========================================================================


class TestStageMetrics:
    def test_get_change_returns_difference(self):
        from audio_refinery.core.models import StageMetrics

        sm = StageMetrics(
            stage="Trim",
            before_values={"duration_seconds": 10.0},
            after_values={"duration_seconds": 8.5},
        )
        assert sm.get_change("duration_seconds") == -1.5

    def test_get_change_returns_none_for_missing_before(self):
        from audio_refinery.core.models import StageMetrics

        sm = StageMetrics(stage="Trim", after_values={"duration_seconds": 8.5})
        assert sm.get_change("duration_seconds") is None

    def test_get_change_returns_none_for_missing_after(self):
        from audio_refinery.core.models import StageMetrics

        sm = StageMetrics(stage="Trim", before_values={"duration_seconds": 10.0})
        assert sm.get_change("duration_seconds") is None

    def test_get_change_returns_none_for_unknown_metric(self):
        from audio_refinery.core.models import StageMetrics

        sm = StageMetrics(stage="Trim")
        assert sm.get_change("nonexistent") is None


# ===========================================================================
# Tests: process_file — unit level (mocked pydub + stage functions)
# ===========================================================================


class TestProcessFile:
    @staticmethod
    @pytest.fixture(autouse=True)
    def _valid_integrity():
        """Unit tests use placeholder bytes with pydub mocked at the module
        boundary, so the real integrity checker would reject them.  Patch the
        integrity pre-flight to a passing result for these synthetic inputs."""
        from audio_refinery.core.integrity import IntegrityResult, IntegrityStatus

        fake = IntegrityResult(path=Path("fake.wav"), status=IntegrityStatus.PASS)
        fake.file_size_bytes = 1024
        fake.duration_ms = 10000.0
        fake.sample_rate = 44100
        fake.channels = 2
        with patch(
            "audio_refinery.core.pipeline.validate_file",
            return_value=fake,
        ):
            yield

    @staticmethod
    @pytest.fixture()
    def audio_file(tmp_path: Path) -> Path:
        p = tmp_path / "test_track.wav"
        p.write_bytes(b"dummy audio content")
        return p

    @staticmethod
    @pytest.fixture()
    def output_file(tmp_path: Path) -> Path:
        return tmp_path / "output_track.wav"

    def _mock_segment(self) -> MagicMock:
        seg = MagicMock()
        seg.__len__ = MagicMock(return_value=44100 * 10)
        seg.frame_rate = 44100
        seg.channels = 2
        seg.sample_width = 2
        return seg

    @patch("audio_refinery.core.pipeline.read_tags_raw", return_value={})
    @patch("audio_refinery.core.pipeline.write_tags_raw")
    @patch("audio_refinery.core.pipeline.AudioSegment")
    def test_all_stages_disabled_writes_output(
        self,
        mock_audioseg,
        mock_write_tags,
        mock_read_tags,
        audio_file: Path,
        output_file: Path,
    ):
        from audio_refinery.core.pipeline import process_file

        mock_audioseg.from_file.return_value = self._mock_segment()
        config = _minimal_config()
        result = process_file(audio_file, output_file, config)
        assert result.status != FileStatus.ERROR, result.error

    @patch(
        "audio_refinery.core.pipeline.read_tags_raw",
        side_effect=Exception("tag read failed"),
    )
    def test_tag_read_failure_returns_error_result(
        self, mock_read_tags, audio_file: Path, output_file: Path
    ):
        from audio_refinery.core.pipeline import process_file

        config = _minimal_config()
        result = process_file(audio_file, output_file, config)
        assert result.status == FileStatus.ERROR
        assert result.error is not None

    @patch("audio_refinery.core.pipeline.read_tags_raw", return_value={})
    @patch("audio_refinery.core.pipeline.write_tags_raw")
    @patch("audio_refinery.core.pipeline.AudioSegment")
    def test_original_file_unchanged_on_success(
        self,
        mock_audioseg,
        mock_write_tags,
        mock_read_tags,
        audio_file: Path,
        output_file: Path,
    ):
        from audio_refinery.core.pipeline import process_file

        original_content = audio_file.read_bytes()
        mock_audioseg.from_file.return_value = self._mock_segment()
        config = _minimal_config()
        process_file(audio_file, output_file, config)
        assert audio_file.read_bytes() == original_content

    @patch(
        "audio_refinery.core.pipeline.read_tags_raw",
        return_value={"title": "Test Track"},
    )
    @patch("audio_refinery.core.pipeline.write_tags_raw")
    @patch("audio_refinery.core.pipeline.AudioSegment")
    def test_tags_read_once_written_once(
        self,
        mock_audioseg,
        mock_write_tags,
        mock_read_tags,
        audio_file: Path,
        output_file: Path,
    ):
        from audio_refinery.core.pipeline import process_file

        mock_audioseg.from_file.return_value = self._mock_segment()
        config = _minimal_config()
        process_file(audio_file, output_file, config)
        assert mock_read_tags.call_count == 1
        assert mock_write_tags.call_count == 1

    @patch("audio_refinery.core.pipeline.read_tags_raw", return_value={})
    @patch("audio_refinery.core.pipeline.write_tags_raw")
    @patch("audio_refinery.core.pipeline.AudioSegment")
    def test_progress_callback_is_called(
        self,
        mock_audioseg,
        mock_write_tags,
        mock_read_tags,
        audio_file: Path,
        output_file: Path,
    ):
        from audio_refinery.core.pipeline import process_file

        mock_audioseg.from_file.return_value = self._mock_segment()
        on_progress = MagicMock()
        config = _minimal_config()
        process_file(audio_file, output_file, config, on_progress=on_progress)
        assert on_progress.call_count > 0


# ===========================================================================
# Integration tests — require real ffmpeg + audio file
# ===========================================================================


@pytest.mark.integration
class TestProcessFileIntegration:
    @staticmethod
    @pytest.fixture(autouse=True)
    def require_ffmpeg():
        import shutil

        if not shutil.which("ffmpeg"):
            pytest.skip("ffmpeg not found on PATH — skipping integration test")

    @staticmethod
    @pytest.fixture()
    def real_wav(tmp_path: Path) -> Path:
        import struct
        import wave

        path = tmp_path / "silence.wav"
        with wave.open(str(path), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            wf.writeframes(struct.pack("<" + "h" * 44100, *([0] * 44100)))
        return path

    def test_pipeline_processes_wav_without_error(self, real_wav: Path, tmp_path: Path):
        from audio_refinery.core.pipeline import process_file

        output = tmp_path / "output.wav"
        config = StageConfig(declick=False, trim=True, enhance=False, normalise=False)
        result = process_file(real_wav, output, config)
        assert result.status != FileStatus.ERROR, f"Pipeline error: {result.error}"
        assert output.exists()

    def test_in_place_processing_preserves_file(self, real_wav: Path):
        from audio_refinery.core.pipeline import process_file

        config = StageConfig(declick=False, trim=False, enhance=False, normalise=False)
        result = process_file(real_wav, real_wav, config)
        assert result.status != FileStatus.ERROR
        assert real_wav.exists()
        assert real_wav.stat().st_size > 0


# ===========================================================================
# Tests: process_file — real-audio outcome locks (iteration-7 C3)
#
# These tests are the behaviour lock the decomposition must not change: every
# test decodes the pipeline OUTPUT and measures it (per-channel RMS, duration,
# sample rate, or integrated loudness via the shared loudness module) instead
# of reading back written state.  Tolerances were measured against the
# pre-decomposition function and are declared here per the F1 rule.
# ===========================================================================


def _write_wav(path: Path, segments: list[tuple[float, float]]) -> dict[str, float]:
    """Write a 16-bit stereo 44.1 kHz WAV built from (duration_s, amplitude) parts.

    Each part is a 440 Hz sine at the given peak amplitude (0.0 = silence).
    Returns the measured source RMS per channel in dBFS.
    """
    rate = 44100
    frames: list[tuple[int, int]] = []
    for duration_s, amplitude in segments:
        n = int(duration_s * rate)
        for i in range(n):
            v = int(amplitude * 32767 * math.sin(2 * math.pi * 440.0 * (i / rate)))
            frames.append((v, v))
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        for pair in frames:
            wf.writeframes(struct.pack("<hh", *pair))
    return _decode_wav(path)[0]


def _decode_wav(path: Path) -> tuple[dict[str, float], dict[str, float]]:
    """Decode a WAV and measure it.

    Returns:
        ``(signal, format)`` where *signal* carries per-channel RMS in dBFS
        and *format* carries ``duration_s``, ``sample_rate`` and ``channels``.
    """
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        rate = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)
    count = len(raw) // 2
    samples = struct.unpack("<" + "h" * count, raw)
    per_channel_rms: dict[str, float] = {}
    for ch in range(channels):
        ch_samples = samples[ch::channels]
        rms = math.sqrt(sum(s * s for s in ch_samples) / len(ch_samples))
        per_channel_rms[f"ch{ch}_rms_dbfs"] = (
            20 * math.log10(rms / 32768.0) if rms else -120.0
        )
    fmt = {
        "duration_s": n_frames / rate,
        "sample_rate": float(rate),
        "channels": float(channels),
    }
    return per_channel_rms, fmt


@pytest.mark.integration
class TestProcessFileOutcomes:
    """Real-audio decode-and-measure locks for the pipeline stages."""

    @staticmethod
    @pytest.fixture()
    def tone_wav(tmp_path: Path) -> Path:
        p = tmp_path / "tone.wav"
        _write_wav(p, [(2.0, 0.25)])
        return p

    def test_passthrough_preserves_signal(self, tone_wav: Path, tmp_path: Path) -> None:
        from audio_refinery.core.pipeline import process_file

        src_rms, _ = _decode_wav(tone_wav)
        out = tmp_path / "out.wav"
        result = process_file(tone_wav, out, _minimal_config())
        assert result.status is FileStatus.DONE, result.error

        out_rms, fmt = _decode_wav(out)
        assert fmt["sample_rate"] == 44100.0
        assert fmt["channels"] == 2.0
        assert fmt["duration_s"] == pytest.approx(2.0, abs=0.02)
        for ch in src_rms:
            assert out_rms[ch] == pytest.approx(src_rms[ch], abs=0.1), ch

    def test_declick_on_clean_audio_preserves_signal(
        self, tone_wav: Path, tmp_path: Path
    ) -> None:
        from audio_refinery.core.pipeline import process_file

        src_rms, _ = _decode_wav(tone_wav)
        out = tmp_path / "out.wav"
        result = process_file(tone_wav, out, _minimal_config(declick=True))
        assert result.status is FileStatus.DONE, result.error

        out_rms, fmt = _decode_wav(out)
        assert fmt["duration_s"] == pytest.approx(2.0, abs=0.02)
        for ch in src_rms:
            assert out_rms[ch] == pytest.approx(src_rms[ch], abs=0.1), ch

    def test_trim_removes_leading_and_trailing_silence(self, tmp_path: Path) -> None:
        from audio_refinery.core.pipeline import process_file

        src = tmp_path / "padded.wav"
        _write_wav(src, [(0.5, 0.0), (1.0, 0.25), (0.5, 0.0)])

        out = tmp_path / "out.wav"
        result = process_file(src, out, _minimal_config(trim=True))
        assert result.status is FileStatus.DONE, result.error

        _, fmt = _decode_wav(out)
        assert fmt["duration_s"] == pytest.approx(1.0, abs=0.05)
        out_rms, _ = _decode_wav(out)
        # The padded source's RMS sits ~3 dB below the tone's because half its
        # samples are silence; the trimmed output contains only tone. The
        # expected value is the measured RMS of a 0.25-peak sine, which equals
        # the analytic 20*log10(0.25/sqrt(2)) = -15.05 dBFS.
        expected_tone_rms = 20 * math.log10(0.25 / math.sqrt(2))
        for ch in out_rms:
            assert out_rms[ch] == pytest.approx(expected_tone_rms, abs=0.3), ch

    def test_enhance_mild_gain_within_measured_band(
        self, tone_wav: Path, tmp_path: Path
    ) -> None:
        from audio_refinery.core.pipeline import process_file

        src_rms, _ = _decode_wav(tone_wav)
        out = tmp_path / "out.wav"
        config = StageConfig(declick=False, trim=False, enhance=True, normalise=False)
        config.enhance_params.preset = "Mild"
        result = process_file(tone_wav, out, config)
        assert result.status is FileStatus.DONE, result.error

        out_rms, fmt = _decode_wav(out)
        assert fmt["duration_s"] == pytest.approx(2.0, abs=0.02)
        gains = [out_rms[ch] - src_rms[ch] for ch in src_rms]
        # Measured pre-decomposition: the Mild preset yields +3.79 dB on this
        # fixture (stereo-identical). The band is the F1 lock: decomposition
        # must not shift the measured output beyond it.
        for gain in gains:
            assert 3.2 <= gain <= 4.4, gain

    @staticmethod
    @pytest.fixture()
    def quiet_flac(tmp_path: Path) -> Path:
        """A FLAC source at ≈ -30 dBFS (the normaliser refuses .wav by design)."""
        from pydub import AudioSegment

        wav = tmp_path / "quiet.wav"
        _write_wav(wav, [(2.0, 0.03)])
        flac = tmp_path / "quiet.flac"
        AudioSegment.from_wav(str(wav)).export(str(flac), format="flac")
        return flac

    @PYDUB_FLAC_MISSING
    def test_normalise_reaches_target_lufs(
        self, quiet_flac: Path, tmp_path: Path
    ) -> None:
        from pydub import AudioSegment

        from audio_refinery.core.pipeline import process_file

        out = tmp_path / "out.flac"
        config = StageConfig(
            declick=False,
            trim=False,
            enhance=False,
            normalise=True,
        )
        config.normalise_params.target_lufs = -16.0
        result = process_file(quiet_flac, out, config)
        assert result.status is FileStatus.DONE, result.error

        from audio_normalizer.core.loudness import measure

        loudness = measure(str(out), -16.0)
        assert loudness is not None
        assert loudness["input_i"] == pytest.approx(-16.0, abs=0.7)
        # The FLAC output is decoded with pydub (ffmpeg-backed); the stdlib
        # wave reader used by _decode_wav cannot read it.
        duration = AudioSegment.from_file(str(out)).duration_seconds
        assert duration == pytest.approx(2.0, abs=0.05)

    @PYDUB_FLAC_MISSING
    def test_full_chain_all_stages(self, tmp_path: Path) -> None:
        from pydub import AudioSegment

        from audio_refinery.core.pipeline import process_file

        wav = tmp_path / "full.wav"
        _write_wav(wav, [(0.4, 0.0), (1.0, 0.25), (0.4, 0.0)])
        src = tmp_path / "full.flac"
        AudioSegment.from_wav(str(wav)).export(str(src), format="flac")

        out = tmp_path / "out.flac"
        config = StageConfig(declick=True, trim=True, enhance=True, normalise=True)
        config.normalise_params.target_lufs = -16.0
        result = process_file(src, out, config)
        assert result.status is FileStatus.DONE, result.error
        assert result.was_modified is True

        duration = AudioSegment.from_file(str(out)).duration_seconds
        assert duration == pytest.approx(1.0, abs=0.05)

        from audio_normalizer.core.loudness import measure

        loudness = measure(str(out), -16.0)
        assert loudness is not None
        assert loudness["input_i"] == pytest.approx(-16.0, abs=0.7)

    def test_corrupt_input_fails_integrity_gate(self, tmp_path: Path) -> None:
        from audio_refinery.core.pipeline import process_file

        src = tmp_path / "corrupt.wav"
        src.write_bytes(b"this is not audio at all" * 100)
        original = src.read_bytes()
        out = tmp_path / "out.wav"

        result = process_file(src, out, StageConfig())

        assert result.status is FileStatus.ERROR
        assert result.error is not None
        assert "integrity" in result.error.lower()
        assert not out.exists()
        assert src.read_bytes() == original

    def test_in_place_replaces_source_with_processed_audio(
        self, tmp_path: Path
    ) -> None:
        from audio_refinery.core.pipeline import process_file

        src = tmp_path / "inplace.wav"
        _write_wav(src, [(0.5, 0.0), (1.0, 0.25), (0.5, 0.0)])
        result = process_file(src, src, _minimal_config(trim=True))
        assert result.status is FileStatus.DONE, result.error
        _, fmt = _decode_wav(src)
        assert fmt["duration_s"] == pytest.approx(1.0, abs=0.05)


class TestPipelineShape:
    """Structural lock guarding the C3 decomposition against re-inlining."""

    def test_stage_helpers_have_declared_signatures(self) -> None:
        import inspect

        from audio_refinery.core import pipeline

        expected = {
            "_check_integrity": ["source_path", "emit"],
            "_load_source": ["source_path", "emit"],
            "_run_declick_stage": ["audio", "config", "emit"],
            "_run_trim_stage": ["audio", "config", "emit"],
            "_run_noise_reduction_stage": ["audio", "config", "emit"],
            "_run_enhance_stage": ["audio", "config", "emit"],
            "_write_output": ["audio", "tmp_path", "source_path", "ext", "emit"],
            "_run_normalise_stage": ["tmp_path", "config", "emit"],
        }
        for name, params in expected.items():
            fn = getattr(pipeline, name, None)
            assert fn is not None, name
            assert list(inspect.signature(fn).parameters) == params, name

    def test_process_file_signature_unchanged(self) -> None:
        import inspect

        from audio_refinery.core.pipeline import process_file

        assert list(inspect.signature(process_file).parameters) == [
            "source_path",
            "output_path",
            "config",
            "on_progress",
        ]
