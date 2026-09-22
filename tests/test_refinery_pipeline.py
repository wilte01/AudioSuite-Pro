"""
tests/test_refinery_pipeline.py

Unit and integration tests for audio_refinery.core.pipeline.

Moved from tests/audio_refinery/ to tests/ to avoid pytest treating
the tests/audio_refinery directory as a package that shadows the real
audio_refinery suite package during import collection.

Run all unit tests:
    pytest tests/test_refinery_pipeline.py -m "not integration"

Run including integration tests (requires ffmpeg on PATH):
    pytest tests/test_refinery_pipeline.py
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from audio_refinery.core.models import FileResult, FileStatus, StageConfig

# ===========================================================================
# Helpers
# ===========================================================================


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
    @pytest.fixture(autouse=True)
    def _valid_integrity(self):
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

    @pytest.fixture()
    def audio_file(self, tmp_path: Path) -> Path:
        p = tmp_path / "test_track.wav"
        p.write_bytes(b"dummy audio content")
        return p

    @pytest.fixture()
    def output_file(self, tmp_path: Path) -> Path:
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
    @pytest.fixture(autouse=True)
    def require_ffmpeg(self):
        import shutil

        if not shutil.which("ffmpeg"):
            pytest.skip("ffmpeg not found on PATH — skipping integration test")

    @pytest.fixture()
    def real_wav(self, tmp_path: Path) -> Path:
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
