"""
tests/test_pipeline_stages.py

Unit tests for the pipeline entry-points:

  process_file        — full single-file pipeline (all stages mocked)
  _run_trim           — silence trim stage (silence_trimmer mocked)
  _run_enhance        — pedalboard DSP chain (pedalboard mocked)
  _run_normalise      — FFmpeg loudnorm stage (audio_normalizer mocked)

Plus doc locks for the module's stage-order contract (the documented
pipeline chain and the numbered step comments).

Synthetic AudioSegments are built with NumPy so no real audio files or
external binaries are required.  All third-party tool imports that would
need a full suite installation are patched at the module boundary.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from pydub import AudioSegment

from audio_refinery.core.integrity import IntegrityResult, IntegrityStatus

# ── Helpers ───────────────────────────────────────────────────────────────────

FS = 44100


@pytest.fixture(autouse=True)
def _valid_integrity():
    """Pipeline tests use placeholder bytes with pydub mocked at the module
    boundary, so the real integrity checker would reject them.  Patch the
    integrity pre-flight to a passing result for these synthetic inputs."""
    fake = IntegrityResult(path=Path("fake.flac"), status=IntegrityStatus.PASS)
    fake.file_size_bytes = 1024
    fake.duration_ms = 5000.0
    fake.sample_rate = 44100
    fake.channels = 2
    with patch(
        "audio_refinery.core.pipeline.validate_file",
        return_value=fake,
    ):
        yield


def _sine(
    freq: float = 440,
    duration_ms: int = 200,
    channels: int = 1,
    amplitude: float = 0.3,
) -> AudioSegment:
    """Return a synthetic sine-wave AudioSegment (no file I/O)."""
    n = int(FS * duration_ms / 1000)
    t = np.linspace(0, duration_ms / 1000, n, endpoint=False)
    wave = amplitude * np.sin(2 * np.pi * freq * t)
    pcm = (wave * 32767).astype(np.int16)
    if channels == 2:
        raw = np.column_stack([pcm, pcm]).tobytes()
    else:
        raw = pcm.tobytes()
    return AudioSegment(raw, frame_rate=FS, sample_width=2, channels=channels)


def _silence(duration_ms: int = 200, channels: int = 1) -> AudioSegment:
    return AudioSegment.silent(duration=duration_ms, frame_rate=FS)


def _noop_emit(stage: str, msg: str) -> None:
    """Silent progress callback for tests."""


# ── Minimal StageConfig factories ─────────────────────────────────────────────


def _config_all_off():
    from audio_refinery.core.models import StageConfig

    return StageConfig(declick=False, trim=False, enhance=False, normalise=False)


def _config_enhance_only():
    from audio_refinery.core.models import StageConfig

    return StageConfig(declick=False, trim=False, enhance=True, normalise=False)


def _config_trim_only():
    from audio_refinery.core.models import StageConfig

    return StageConfig(declick=False, trim=True, enhance=False, normalise=False)


def _config_normalise_only():
    from audio_refinery.core.models import StageConfig

    return StageConfig(declick=False, trim=False, enhance=False, normalise=True)


def _config_enhance_and_normalise():
    from audio_refinery.core.models import StageConfig

    return StageConfig(declick=False, trim=False, enhance=True, normalise=True)


# ═════════════════════════════════════════════════════════════════════════════
# process_file
# ═════════════════════════════════════════════════════════════════════════════


class TestProcessFile:
    """
    All external I/O (tag read/write, pydub decode/export) is
    patched so tests run without real audio files or installed tools.
    """

    def _run(
        self,
        tmp_path: Path,
        config=None,
        audio: AudioSegment | None = None,
        *,
        source_name: str = "track.flac",
    ):
        from audio_refinery.core.pipeline import process_file

        if config is None:
            config = _config_all_off()
        if audio is None:
            audio = _sine()

        src = tmp_path / source_name
        src.write_bytes(b"\x00" * 64)  # placeholder — pydub is mocked

        with (
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={}),
            patch("audio_refinery.core.pipeline.write_tags_raw"),
            patch("audio_refinery.core.pipeline.AudioSegment") as mock_seg_cls,
        ):
            mock_seg_cls.from_file.return_value = audio
            audio.export = MagicMock()  # silence pydub export

            result = process_file(
                source_path=src,
                output_path=src,
                config=config,
                on_progress=_noop_emit,
            )
        return result

    # ── basic outcomes ────────────────────────────────────────────────────────

    def test_returns_file_result(self, tmp_path):
        from audio_refinery.core.models import FileResult

        result = self._run(tmp_path)
        assert isinstance(result, FileResult)

    def test_status_done_when_no_stages(self, tmp_path):
        from audio_refinery.core.models import FileStatus

        result = self._run(tmp_path)
        assert result.status == FileStatus.DONE

    def test_was_modified_true_on_success(self, tmp_path):
        result = self._run(tmp_path)
        assert result.was_modified is True

    def test_no_error_on_success(self, tmp_path):
        result = self._run(tmp_path)
        assert result.error is None

    def test_path_attribute_matches_source(self, tmp_path):
        src = tmp_path / "song.mp3"
        src.write_bytes(b"\x00" * 64)
        from audio_refinery.core.pipeline import process_file

        with (
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={}),
            patch("audio_refinery.core.pipeline.write_tags_raw"),
            patch("audio_refinery.core.pipeline.AudioSegment") as mock_seg_cls,
        ):
            mock_seg_cls.from_file.return_value = _sine()
            _sine().export = MagicMock()
            result = process_file(src, src, _config_all_off(), on_progress=_noop_emit)
        assert result.path == src

    def test_temp_file_created_in_output_directory(self, tmp_path):
        """Regression: the work file must share a volume with output_path.

        os.replace() cannot move across drives (WinError 17), so a temp
        file in the system TEMP dir breaks every file whose destination
        sits on another drive.
        """
        from audio_refinery.core.models import FileStatus
        from audio_refinery.core.pipeline import process_file

        src_dir = tmp_path / "source"
        out_dir = tmp_path / "output"
        src_dir.mkdir()
        out_dir.mkdir()
        src = src_dir / "track.flac"
        src.write_bytes(b"\x00" * 64)

        with (
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={}),
            patch("audio_refinery.core.pipeline.write_tags_raw"),
            patch("audio_refinery.core.pipeline.AudioSegment") as mock_seg_cls,
        ):
            mock_seg_cls.from_file.return_value = _sine()
            audio = _sine()
            audio.export = MagicMock()
            mock_seg_cls.from_file.return_value = audio

            result = process_file(
                source_path=src,
                output_path=out_dir / "track.flac",
                config=_config_all_off(),
                on_progress=_noop_emit,
            )

            exported_path = Path(audio.export.call_args[0][0])

        assert result.status == FileStatus.DONE
        assert exported_path.parent == out_dir
        assert (out_dir / "track.flac").exists()

    # ── failure handling ──────────────────────────────────────────────────────

    def test_status_error_when_tag_read_raises(self, tmp_path):
        from audio_refinery.core.models import FileStatus
        from audio_refinery.core.pipeline import process_file

        src = tmp_path / "bad.flac"
        src.write_bytes(b"\x00" * 64)

        with patch(
            "audio_refinery.core.pipeline.read_tags_raw",
            side_effect=OSError("tag read failed"),
        ):
            result = process_file(src, src, _config_all_off(), on_progress=_noop_emit)

        assert result.status == FileStatus.ERROR

    def test_error_message_populated_on_failure(self, tmp_path):
        from audio_refinery.core.pipeline import process_file

        src = tmp_path / "bad.flac"
        src.write_bytes(b"\x00" * 64)

        with patch(
            "audio_refinery.core.pipeline.read_tags_raw",
            side_effect=OSError("disk full"),
        ):
            result = process_file(src, src, _config_all_off(), on_progress=_noop_emit)

        assert result.error is not None
        assert len(result.error) > 0

    def test_original_file_not_overwritten_on_failure(self, tmp_path):
        """os.replace must NOT be called when the pipeline errors before the
        atomic-replace step."""
        from audio_refinery.core.pipeline import process_file

        src = tmp_path / "precious.flac"
        src.write_bytes(b"\xde\xad\xbe\xef")

        with (
            patch(
                "audio_refinery.core.pipeline.read_tags_raw",
                side_effect=RuntimeError("decode exploded"),
            ) as mock_read,
            patch("audio_refinery.core.pipeline.os.replace") as mock_replace,
        ):
            process_file(src, src, _config_all_off(), on_progress=_noop_emit)

        mock_read.assert_called_once()
        mock_replace.assert_not_called()
        assert src.read_bytes() == b"\xde\xad\xbe\xef"

    # ── progress callback ─────────────────────────────────────────────────────

    def test_on_progress_receives_done_stage(self, tmp_path):
        calls: list[tuple[str, str]] = []
        from audio_refinery.core.pipeline import process_file

        src = tmp_path / "song.mp3"
        src.write_bytes(b"\x00" * 64)

        with (
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={}),
            patch("audio_refinery.core.pipeline.write_tags_raw"),
            patch("audio_refinery.core.pipeline.AudioSegment") as mock_seg_cls,
        ):
            mock_seg_cls.from_file.return_value = _sine()
            _sine().export = MagicMock()
            process_file(
                src,
                src,
                _config_all_off(),
                on_progress=lambda s, m: calls.append((s, m)),
            )

        stages_seen = {s for s, _ in calls}
        assert "Done" in stages_seen

    def test_undo_records_single_snapshot_against_real_output(self, tmp_path):
        """A live run records exactly one undo snapshot per file, pointed at
        the real output path — never the temp staging file."""
        from audio_refinery.core.models import FileStatus
        from audio_refinery.core.pipeline import process_file
        from audio_suite_shared.batch_undo import (
            BatchUndoLog,
            active_batch,
            list_recent_batches,
        )

        undo_db = tmp_path / "undo.db"
        src = tmp_path / "song.mp3"
        src.write_bytes(b"\x00" * 64)

        tagged_handler = MagicMock()
        tagged_handler.get_raw_tags.return_value = {"TPE1": "Artist"}
        shared_factory = MagicMock()
        shared_factory.get_handler.return_value = tagged_handler

        audio = _sine()
        audio.export = MagicMock()

        with (
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={}),
            patch("audio_refinery.core.pipeline.write_tags_raw"),
            patch("audio_refinery.core.pipeline.AudioSegment") as mock_seg_cls,
            patch(
                "audio_suite_shared.tag_helper_base.TagHandlerFactory", shared_factory
            ),
        ):
            mock_seg_cls.from_file.return_value = audio
            with active_batch("audio_refinery", "tag_edit", db_path=undo_db):
                result = process_file(
                    source_path=src,
                    output_path=src,
                    config=_config_all_off(),
                    on_progress=_noop_emit,
                )

        assert result.status == FileStatus.DONE

        batches = list_recent_batches(limit=5, db_path=undo_db)
        assert len(batches) == 1
        assert batches[0].record_count == 1
        with BatchUndoLog(db_path=undo_db) as opened:
            records = opened.get_batch_records(batches[0].batch_id)
        assert len(records) == 1
        assert records[0].file_path == str(src)
        assert records[0].operation == "refinery_edit"

    # ── declick stage integration ─────────────────────────────────────────────

    def test_declick_stage_recorded_in_result(self, tmp_path):
        from audio_refinery.core.models import StageConfig
        from audio_refinery.core.pipeline import process_file

        config = StageConfig(declick=True, trim=False, enhance=False, normalise=False)
        src = tmp_path / "song.mp3"
        src.write_bytes(b"\x00" * 64)

        dc_result = MagicMock()
        dc_result.audio = _sine()
        dc_result.was_modified = False
        dc_result.clicks_found = 0

        with (
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={}),
            patch("audio_refinery.core.pipeline.write_tags_raw"),
            patch("audio_refinery.core.pipeline.AudioSegment") as mock_seg_cls,
            patch(
                "pop_click_remover.core.declicker.declick_audio",
                return_value=dc_result,
            ),
        ):
            mock_seg_cls.from_file.return_value = _sine()
            result = process_file(src, src, config, on_progress=_noop_emit)

        stage_names = [s.stage for s in result.stages]
        assert "Declick" in stage_names

    # ── stage failure paths ─────────────────────────────────────────────────

    def test_declick_failure_returns_error(self, tmp_path):
        from audio_refinery.core.models import FileStatus, StageConfig
        from audio_refinery.core.pipeline import process_file

        config = StageConfig(declick=True, trim=False, enhance=False, normalise=False)
        src = tmp_path / "song.mp3"
        src.write_bytes(b"\x00" * 64)

        with (
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={}),
            patch("audio_refinery.core.pipeline.write_tags_raw"),
            patch("audio_refinery.core.pipeline.AudioSegment") as mock_seg_cls,
            patch(
                "pop_click_remover.core.declicker.declick_audio",
                side_effect=RuntimeError("declick crashed"),
            ),
        ):
            mock_seg_cls.from_file.return_value = _sine()
            result = process_file(src, src, config, on_progress=_noop_emit)

        assert result.status == FileStatus.ERROR
        assert result.error is not None

    def test_trim_failure_returns_error(self, tmp_path):
        from audio_refinery.core.models import FileStatus, StageConfig
        from audio_refinery.core.pipeline import process_file

        config = StageConfig(declick=False, trim=True, enhance=False, normalise=False)
        src = tmp_path / "song.mp3"
        src.write_bytes(b"\x00" * 64)

        with (
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={}),
            patch("audio_refinery.core.pipeline.write_tags_raw"),
            patch("audio_refinery.core.pipeline.AudioSegment") as mock_seg_cls,
            patch(
                "silence_trimmer.core.trimmer.trim_and_fade",
                side_effect=RuntimeError("trim crashed"),
            ),
        ):
            mock_seg_cls.from_file.return_value = _sine()
            result = process_file(src, src, config, on_progress=_noop_emit)

        assert result.status == FileStatus.ERROR
        assert result.error is not None

    def test_enhance_failure_returns_error(self, tmp_path):
        from audio_refinery.core.models import FileStatus, StageConfig
        from audio_refinery.core.pipeline import process_file

        config = StageConfig(declick=False, trim=False, enhance=True, normalise=False)
        src = tmp_path / "song.mp3"
        src.write_bytes(b"\x00" * 64)

        with (
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={}),
            patch("audio_refinery.core.pipeline.write_tags_raw"),
            patch("audio_refinery.core.pipeline.AudioSegment") as mock_seg_cls,
            patch(
                "audio_refinery.core.pipeline._run_enhance",
                side_effect=RuntimeError("enhance crashed"),
            ),
        ):
            mock_seg_cls.from_file.return_value = _sine()
            result = process_file(src, src, config, on_progress=_noop_emit)

        assert result.status == FileStatus.ERROR
        assert result.error is not None

    def test_normalise_failure_returns_error(self, tmp_path):
        from audio_refinery.core.models import FileStatus, StageConfig
        from audio_refinery.core.pipeline import process_file

        config = StageConfig(declick=False, trim=False, enhance=False, normalise=True)
        src = tmp_path / "song.mp3"
        src.write_bytes(b"\x00" * 64)

        with (
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={}),
            patch("audio_refinery.core.pipeline.write_tags_raw"),
            patch("audio_refinery.core.pipeline.AudioSegment") as mock_seg_cls,
            patch(
                "audio_refinery.core.pipeline._run_normalise",
                side_effect=RuntimeError("normalise crashed"),
            ),
        ):
            mock_seg_cls.from_file.return_value = _sine()
            result = process_file(src, src, config, on_progress=_noop_emit)

        assert result.status == FileStatus.ERROR
        assert result.error is not None

    # ── trim stage message branches ─────────────────────────────────────────

    def test_trim_message_trimmed_branch(self, tmp_path):
        from audio_refinery.core.models import StageConfig
        from audio_refinery.core.pipeline import process_file

        config = StageConfig(declick=False, trim=True, enhance=False, normalise=False)
        src = tmp_path / "song.mp3"
        src.write_bytes(b"\x00" * 64)

        tr_result = MagicMock()
        tr_result.trimmed = _sine()
        tr_result.action = "trimmed 2.1s of silence"

        with (
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={}),
            patch("audio_refinery.core.pipeline.write_tags_raw"),
            patch("audio_refinery.core.pipeline.AudioSegment") as mock_seg_cls,
            patch(
                "silence_trimmer.core.trimmer.trim_and_fade",
                return_value=tr_result,
            ),
        ):
            mock_seg_cls.from_file.return_value = _sine()
            _sine().export = MagicMock()
            result = process_file(src, src, config, on_progress=_noop_emit)

        trim_msg = next(s.message for s in result.stages if s.stage == "Trim")
        assert "trimmed" in trim_msg.lower()

    def test_trim_message_fade_branch(self, tmp_path):
        from audio_refinery.core.models import StageConfig
        from audio_refinery.core.pipeline import process_file

        config = StageConfig(declick=False, trim=True, enhance=False, normalise=False)
        src = tmp_path / "song.mp3"
        src.write_bytes(b"\x00" * 64)

        tr_result = MagicMock()
        tr_result.trimmed = _sine()
        tr_result.action = "fade applied"

        with (
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={}),
            patch("audio_refinery.core.pipeline.write_tags_raw"),
            patch("audio_refinery.core.pipeline.AudioSegment") as mock_seg_cls,
            patch(
                "silence_trimmer.core.trimmer.trim_and_fade",
                return_value=tr_result,
            ),
        ):
            mock_seg_cls.from_file.return_value = _sine()
            _sine().export = MagicMock()
            result = process_file(src, src, config, on_progress=_noop_emit)

        trim_msg = next(s.message for s in result.stages if s.stage == "Trim")
        assert "fade" in trim_msg.lower()

    def test_trim_message_other_action_branch(self, tmp_path):
        from audio_refinery.core.models import StageConfig
        from audio_refinery.core.pipeline import process_file

        config = StageConfig(declick=False, trim=True, enhance=False, normalise=False)
        src = tmp_path / "song.mp3"
        src.write_bytes(b"\x00" * 64)

        tr_result = MagicMock()
        tr_result.trimmed = _sine()
        tr_result.action = "optimized structure"

        with (
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={}),
            patch("audio_refinery.core.pipeline.write_tags_raw"),
            patch("audio_refinery.core.pipeline.AudioSegment") as mock_seg_cls,
            patch(
                "silence_trimmer.core.trimmer.trim_and_fade",
                return_value=tr_result,
            ),
        ):
            mock_seg_cls.from_file.return_value = _sine()
            _sine().export = MagicMock()
            result = process_file(src, src, config, on_progress=_noop_emit)

        trim_msg = next(s.message for s in result.stages if s.stage == "Trim")
        assert trim_msg is not None

    def test_trim_no_silence_detected_branch(self, tmp_path):
        from audio_refinery.core.models import StageConfig
        from audio_refinery.core.pipeline import process_file

        config = StageConfig(declick=False, trim=True, enhance=False, normalise=False)
        src = tmp_path / "song.mp3"
        src.write_bytes(b"\x00" * 64)

        tr_result = MagicMock()
        tr_result.trimmed = None
        tr_result.action = ""

        with (
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={}),
            patch("audio_refinery.core.pipeline.write_tags_raw"),
            patch("audio_refinery.core.pipeline.AudioSegment") as mock_seg_cls,
            patch(
                "silence_trimmer.core.trimmer.trim_and_fade",
                return_value=tr_result,
            ),
        ):
            mock_seg_cls.from_file.return_value = _sine()
            _sine().export = MagicMock()
            result = process_file(src, src, config, on_progress=_noop_emit)

        trim_msg = next(s.message for s in result.stages if s.stage == "Trim")
        assert "No silence" in trim_msg
        assert "original length" in trim_msg

    # ── enhance stage message branches ──────────────────────────────────────

    def test_enhance_message_mild_preset(self, tmp_path):
        from audio_refinery.core.models import StageConfig
        from audio_refinery.core.pipeline import process_file

        config = StageConfig(declick=False, trim=False, enhance=True, normalise=False)
        config.enhance_params.preset = "Mild"
        src = tmp_path / "song.mp3"
        src.write_bytes(b"\x00" * 64)

        with (
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={}),
            patch("audio_refinery.core.pipeline.write_tags_raw"),
            patch("audio_refinery.core.pipeline.AudioSegment") as mock_seg_cls,
            patch(
                "audio_refinery.core.pipeline._run_enhance",
                return_value=(_sine(), -15.0, -13.0),
            ),
        ):
            mock_seg_cls.from_file.return_value = _sine()
            _sine().export = MagicMock()
            result = process_file(src, src, config, on_progress=_noop_emit)

        enhance_msg = next(s.message for s in result.stages if s.stage == "Enhance")
        assert "Mild" in enhance_msg

    def test_enhance_message_moderate_preset(self, tmp_path):
        from audio_refinery.core.models import StageConfig
        from audio_refinery.core.pipeline import process_file

        config = StageConfig(declick=False, trim=False, enhance=True, normalise=False)
        config.enhance_params.preset = "Moderate"
        src = tmp_path / "song.mp3"
        src.write_bytes(b"\x00" * 64)

        with (
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={}),
            patch("audio_refinery.core.pipeline.write_tags_raw"),
            patch("audio_refinery.core.pipeline.AudioSegment") as mock_seg_cls,
            patch(
                "audio_refinery.core.pipeline._run_enhance",
                return_value=(_sine(), -15.0, -13.0),
            ),
        ):
            mock_seg_cls.from_file.return_value = _sine()
            _sine().export = MagicMock()
            result = process_file(src, src, config, on_progress=_noop_emit)

        enhance_msg = next(s.message for s in result.stages if s.stage == "Enhance")
        assert "Moderate" in enhance_msg

    def test_enhance_message_aggressive_preset(self, tmp_path):
        from audio_refinery.core.models import StageConfig
        from audio_refinery.core.pipeline import process_file

        config = StageConfig(declick=False, trim=False, enhance=True, normalise=False)
        config.enhance_params.preset = "Aggressive"
        src = tmp_path / "song.mp3"
        src.write_bytes(b"\x00" * 64)

        with (
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={}),
            patch("audio_refinery.core.pipeline.write_tags_raw"),
            patch("audio_refinery.core.pipeline.AudioSegment") as mock_seg_cls,
            patch(
                "audio_refinery.core.pipeline._run_enhance",
                return_value=(_sine(), -15.0, -13.0),
            ),
        ):
            mock_seg_cls.from_file.return_value = _sine()
            _sine().export = MagicMock()
            result = process_file(src, src, config, on_progress=_noop_emit)

        enhance_msg = next(s.message for s in result.stages if s.stage == "Enhance")
        assert "Aggressive" in enhance_msg

    def test_enhance_message_custom_preset(self, tmp_path):
        from audio_refinery.core.models import StageConfig
        from audio_refinery.core.pipeline import process_file

        config = StageConfig(declick=False, trim=False, enhance=True, normalise=False)
        config.enhance_params.preset = "Custom"
        src = tmp_path / "song.mp3"
        src.write_bytes(b"\x00" * 64)

        with (
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={}),
            patch("audio_refinery.core.pipeline.write_tags_raw"),
            patch("audio_refinery.core.pipeline.AudioSegment") as mock_seg_cls,
            patch(
                "audio_refinery.core.pipeline._run_enhance",
                return_value=(_sine(), -15.0, -13.0),
            ),
        ):
            mock_seg_cls.from_file.return_value = _sine()
            _sine().export = MagicMock()
            result = process_file(src, src, config, on_progress=_noop_emit)

        enhance_msg = next(s.message for s in result.stages if s.stage == "Enhance")
        assert "Custom" in enhance_msg

    # ── normalise stage message branches ────────────────────────────────────

    def test_normalise_already_within_tolerance_message(self, tmp_path):
        from audio_refinery.core.models import NormaliseParams, StageConfig
        from audio_refinery.core.pipeline import process_file

        config = StageConfig(declick=False, trim=False, enhance=False, normalise=True)
        config.normalise_params = NormaliseParams(target_lufs=-16.0, tolerance=0.5)
        src = tmp_path / "song.mp3"
        src.write_bytes(b"\x00" * 64)

        with (
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={}),
            patch("audio_refinery.core.pipeline.write_tags_raw"),
            patch("audio_refinery.core.pipeline.AudioSegment") as mock_seg_cls,
            patch("audio_refinery.core.pipeline._run_normalise", return_value=False),
            patch(
                "audio_normalizer.core.loudness.measure",
                return_value={"input_i": -16.3},
            ),
        ):
            mock_seg_cls.from_file.return_value = _sine()
            _sine().export = MagicMock()
            result = process_file(src, src, config, on_progress=_noop_emit)

        norm_msg = next(s.message for s in result.stages if s.stage == "Normalise")
        assert "no adjustment needed" in norm_msg.lower()

    def test_normalise_applied_message(self, tmp_path):
        from audio_refinery.core.models import NormaliseParams, StageConfig
        from audio_refinery.core.pipeline import process_file

        config = StageConfig(declick=False, trim=False, enhance=False, normalise=True)
        config.normalise_params = NormaliseParams(target_lufs=-16.0, tolerance=0.5)
        src = tmp_path / "song.mp3"
        src.write_bytes(b"\x00" * 64)

        with (
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={}),
            patch("audio_refinery.core.pipeline.write_tags_raw"),
            patch("audio_refinery.core.pipeline.AudioSegment") as mock_seg_cls,
            patch("audio_refinery.core.pipeline._run_normalise", return_value=True),
            patch(
                "audio_normalizer.core.loudness.measure",
                return_value={"input_i": -23.0},
            ),
        ):
            mock_seg_cls.from_file.return_value = _sine()
            _sine().export = MagicMock()
            result = process_file(src, src, config, on_progress=_noop_emit)

        norm_msg = next(s.message for s in result.stages if s.stage == "Normalise")
        assert "Adjusted" in norm_msg

    def test_normalise_measurement_failed_fallback_message(self, tmp_path):
        from audio_refinery.core.models import NormaliseParams, StageConfig
        from audio_refinery.core.pipeline import process_file

        config = StageConfig(declick=False, trim=False, enhance=False, normalise=True)
        config.normalise_params = NormaliseParams(target_lufs=-16.0, tolerance=0.5)
        src = tmp_path / "song.mp3"
        src.write_bytes(b"\x00" * 64)

        with (
            patch("audio_refinery.core.pipeline.read_tags_raw", return_value={}),
            patch("audio_refinery.core.pipeline.write_tags_raw"),
            patch("audio_refinery.core.pipeline.AudioSegment") as mock_seg_cls,
            patch("audio_refinery.core.pipeline._run_normalise", return_value=False),
            patch(
                "audio_normalizer.core.loudness.measure",
                return_value=None,
            ),
        ):
            mock_seg_cls.from_file.return_value = _sine()
            _sine().export = MagicMock()
            result = process_file(src, src, config, on_progress=_noop_emit)

        norm_msg = next(s.message for s in result.stages if s.stage == "Normalise")
        assert "failed" in norm_msg.lower()


# ═════════════════════════════════════════════════════════════════════════════
# _run_trim
# ═════════════════════════════════════════════════════════════════════════════


class TestRunTrim:
    """The trim stage message must be derived from silence_trimmer's
    *structured* result, never by substring-matching its human ``action``
    text.

    ``action`` is display copy, not an interface: the real values are
    ``"No silence detected"``, ``"Would trim ..."`` and ``"-Xms / -Yms"``
    (optionally ``" + Fades"``).  The previous implementation looked for
    ``"trimmed"``/``"removed"`` in that string, neither of which ever
    occurs, so every non-fade trim silently degraded to the generic
    "audio structure optimized" wording.  These tests pin the structured
    contract so a wording change can never re-break the branch selection.
    """

    @staticmethod
    def _result(**overrides: object) -> MagicMock:
        """A TrimResult stand-in whose `action` deliberately contains none
        of the words the old code searched for ("trimmed", "removed",
        "fade"), so message selection can only come from the fields.
        """
        base: dict[str, object] = {
            "start_trim_ms": 120,
            "end_trim_ms": 340,
            "total_trim_ms": 460,
            "has_silence": True,
            "trimmed": AudioSegment(
                np.full(1000, 0.5, dtype=np.float32),
                frame_rate=44100,
                sample_width=2,
                channels=2,
            ),
            "status": "TRIMMED",
            # Opaque, wording-agnostic telemetry - no "trim"/"removed"/"fade".
            "action": "-120ms / -340ms (opaque-9f2c telemetry)",
            "apply_fade": False,
        }
        base.update(overrides)
        return MagicMock(**base)

    def test_plain_trim_message_comes_from_status_not_action_text(self) -> None:
        """A structured trim with no matching action substrings must still
        produce the trim-specific wording, not the generic fallback.
        """
        from audio_refinery.core.pipeline import _run_trim_stage

        with patch(
            "silence_trimmer.core.trimmer.trim_and_fade", return_value=self._result()
        ):
            _, msg = _run_trim_stage(
                AudioSegment.silent(duration=2000), _config_trim_only(), MagicMock()
            )

        assert msg == (
            "-120ms / -340ms (opaque-9f2c telemetry), improved flow between sections"
        )

    def test_fade_message_reads_structured_field_not_action_text(self) -> None:
        """The fade wording is selected by the structured `apply_fade`
        field even when `action` never mentions fades.
        """
        from audio_refinery.core.pipeline import _run_trim_stage

        with patch(
            "silence_trimmer.core.trimmer.trim_and_fade",
            return_value=self._result(apply_fade=True),
        ):
            _, msg = _run_trim_stage(
                AudioSegment.silent(duration=2000), _config_trim_only(), MagicMock()
            )

        assert msg.endswith(", smooth transitions applied")

    def test_trimmed_audio_replaces_the_input_segment(self) -> None:
        from audio_refinery.core.pipeline import _run_trim_stage

        result = self._result()
        with patch("silence_trimmer.core.trimmer.trim_and_fade", return_value=result):
            audio, _ = _run_trim_stage(
                AudioSegment.silent(duration=2000), _config_trim_only(), MagicMock()
            )

        assert audio is result.trimmed

    def test_no_silence_reports_original_length_maintained(self) -> None:
        """has_silence=False yields trimmed=None and the skip message."""
        from audio_refinery.core.pipeline import _run_trim_stage

        with patch(
            "silence_trimmer.core.trimmer.trim_and_fade",
            return_value=self._result(
                has_silence=False,
                trimmed=None,
                status="SKIP",
                action="No silence detected",
            ),
        ):
            audio, msg = _run_trim_stage(
                AudioSegment.silent(duration=2000), _config_trim_only(), MagicMock()
            )

        assert msg == "No silence detected - original length maintained"
        assert len(audio) == 2000

    def test_trim_failure_is_wrapped_with_stage_context(self) -> None:
        from audio_refinery.core.pipeline import _run_trim_stage
        from audio_suite_shared.exceptions import AudioProcessingError

        with patch(
            "silence_trimmer.core.trimmer.trim_and_fade", side_effect=ValueError("boom")
        ):
            with pytest.raises(AudioProcessingError) as exc_info:
                _run_trim_stage(
                    AudioSegment.silent(duration=2000), _config_trim_only(), MagicMock()
                )

        assert exc_info.value.context["stage"] == "trim"


class TestPipelineChainDocs:
    """Locks the documented stage order against the executed order.

    The module docstring and the UI subtitle both omitted Noise Reduction
    while the pipeline really runs declick → trim → noise reduction →
    enhance, and two step comments were both numbered "5".  These tests
    pin the contract so the docs cannot drift again silently.
    """

    def test_docstring_chain_matches_executed_stage_order(self) -> None:
        from audio_refinery.core import pipeline

        doc = pipeline.__doc__ or ""
        # Collapse the wrapped continuation line into one chain string.
        chain = " ".join(
            line.strip()
            for line in doc.splitlines()
            if "\u2192" in line or "normalise (FFmpeg)" in line
        )
        positions = [
            chain.index(word)
            for word in (
                "Decode once",
                "declick",
                "trim",
                "noise reduction",
                "enhance",
                "encode once",
                "normalise",
            )
        ]
        assert positions == sorted(positions), (
            f"docstring chain is out of executed order: {chain!r}"
        )

    def test_numbered_step_comments_are_unique_and_increasing(self) -> None:
        import re

        from audio_refinery.core import pipeline

        source = inspect.getsource(pipeline)
        steps = [
            int(m)
            for m in re.findall(
                r"^\s*# \u2500\u2500 (\d+)\. ", source, flags=re.MULTILINE
            )
        ]
        assert steps == list(range(len(steps))), (
            f"step comments must be numbered 0..{len(steps) - 1} without "
            f"duplicates, got {steps}"
        )


# ═════════════════════════════════════════════════════════════════════════════
# _run_enhance
# ═════════════════════════════════════════════════════════════════════════════


class TestRunEnhance:
    """
    Pedalboard and audio_enhancer models are patched.  The focus is on the
    segment→numpy→segment round-trip and output gain suppression logic.
    """

    def _make_pedalboard_patch(self):
        """Return a context-manager stack that replaces pedalboard with
        an identity chain (passes audio through unchanged)."""

        # A chain callable that returns the input array unmodified
        def _identity_chain(audio_np, sample_rate):
            return audio_np.copy()

        mock_board = MagicMock()
        mock_board.return_value = MagicMock(side_effect=lambda a, sr: a.copy())

        mock_pb_module = MagicMock()
        mock_pb_module.Pedalboard.return_value = mock_board.return_value
        for cls_name in (
            "NoiseGate",
            "Compressor",
            "LowShelfFilter",
            "PeakFilter",
            "HighShelfFilter",
            "Gain",
            "Limiter",
        ):
            setattr(mock_pb_module, cls_name, MagicMock(return_value=MagicMock()))

        return mock_pb_module

    def _run(self, audio: AudioSegment, config=None) -> AudioSegment:
        from audio_refinery.core.pipeline import _run_enhance

        if config is None:
            config = _config_enhance_only()

        mock_ep = MagicMock()
        mock_ep.noise_gate_threshold_db = -65.0
        mock_ep.compressor_threshold_db = -22.0
        mock_ep.compressor_ratio = 3.5
        mock_ep.compressor_attack_ms = 8.0
        mock_ep.compressor_release_ms = 120.0
        mock_ep.low_shelf_gain_db = 2.5
        mock_ep.low_shelf_freq_hz = 100.0
        mock_ep.presence_gain_db = 2.5
        mock_ep.presence_freq_hz = 3500.0
        mock_ep.high_shelf_gain_db = 4.0
        mock_ep.high_shelf_freq_hz = 7000.0
        mock_ep.output_gain_db = 2.0
        mock_ep.limiter_threshold_db = -0.5

        mock_preset_enum = MagicMock()
        mock_preset_enum.CUSTOM = "Custom"

        # pedalboard chain simply passes audio_np through unmodified
        mock_chain = MagicMock()
        mock_chain.side_effect = lambda audio_np, sr: audio_np.copy()

        mock_pedalboard_cls = MagicMock(return_value=mock_chain)
        mock_enhancement_params_cls = MagicMock(return_value=mock_ep)

        with (
            patch.dict(
                "sys.modules",
                {
                    "pedalboard": MagicMock(
                        Pedalboard=mock_pedalboard_cls,
                        NoiseGate=MagicMock(return_value=MagicMock()),
                        Compressor=MagicMock(return_value=MagicMock()),
                        LowShelfFilter=MagicMock(return_value=MagicMock()),
                        PeakFilter=MagicMock(return_value=MagicMock()),
                        HighShelfFilter=MagicMock(return_value=MagicMock()),
                        Gain=MagicMock(return_value=MagicMock()),
                        Limiter=MagicMock(return_value=MagicMock()),
                    )
                },
            ),
            patch(
                "audio_enhancer.core.models.PRESETS",
                {mock_preset_enum: mock_ep},
                create=True,
            ),
            patch(
                "audio_enhancer.core.models.PresetName",
                MagicMock(return_value=mock_preset_enum, CUSTOM="Custom"),
                create=True,
            ),
            patch(
                "audio_enhancer.core.models.EnhancementParams",
                mock_enhancement_params_cls,
                create=True,
            ),
        ):
            audio_out, _rms_b, _rms_a = _run_enhance(audio, config, _noop_emit)
            return audio_out

    def test_returns_audio_segment(self):
        result = self._run(_sine())
        assert isinstance(result, AudioSegment)

    def test_output_sample_rate_preserved(self):
        audio = _sine()
        result = self._run(audio)
        assert result.frame_rate == audio.frame_rate

    def test_output_channel_count_preserved_mono(self):
        result = self._run(_sine(channels=1))
        assert result.channels == 1

    def test_output_channel_count_preserved_stereo(self):
        result = self._run(_sine(channels=2))
        assert result.channels == 2

    def test_output_sample_width_preserved(self):
        audio = _sine()
        result = self._run(audio)
        assert result.sample_width == audio.sample_width

    def test_silence_in_produces_silence_out(self):
        """An all-zeros input through an identity chain must remain silence."""
        silence = _silence()
        result = self._run(silence)
        raw = np.frombuffer(result.raw_data, dtype=np.int16)
        assert np.all(raw == 0)

    def test_non_custom_preset_loads_from_presets_dict(self):
        """When config.enhance_params.preset is not CUSTOM, _run_enhance
        should look up PRESETS[preset_enum] instead of using config values."""
        config = _config_enhance_only()
        config.enhance_params.preset = "Moderate"

        mock_presets = {
            "Moderate": MagicMock(
                noise_gate_threshold_db=-60.0,
                compressor_threshold_db=-20.0,
                compressor_ratio=4.0,
                compressor_attack_ms=10.0,
                compressor_release_ms=150.0,
                low_shelf_gain_db=3.0,
                low_shelf_freq_hz=120.0,
                presence_gain_db=3.0,
                presence_freq_hz=3000.0,
                high_shelf_gain_db=5.0,
                high_shelf_freq_hz=6000.0,
                output_gain_db=2.5,
                limiter_threshold_db=-1.0,
            ),
        }

        mock_preset_name_cls = MagicMock()
        mock_preset_name_cls.return_value = "Moderate"
        mock_preset_name_cls.CUSTOM = "Custom"
        mock_preset_name_cls.MODERATE = "Moderate"

        captured_kwargs = []

        def capture_ep(**kwargs):
            captured_kwargs.append(kwargs)
            ep = MagicMock()
            for k, v in kwargs.items():
                setattr(ep, k, v)
            return ep

        mock_chain = MagicMock()
        mock_chain.side_effect = lambda audio_np, sr: audio_np.copy()

        with (
            patch.dict(
                "sys.modules",
                {
                    "pedalboard": MagicMock(
                        Pedalboard=MagicMock(return_value=mock_chain),
                        NoiseGate=MagicMock(return_value=MagicMock()),
                        Compressor=MagicMock(return_value=MagicMock()),
                        LowShelfFilter=MagicMock(return_value=MagicMock()),
                        PeakFilter=MagicMock(return_value=MagicMock()),
                        HighShelfFilter=MagicMock(return_value=MagicMock()),
                        Gain=MagicMock(return_value=MagicMock()),
                        Limiter=MagicMock(return_value=MagicMock()),
                    )
                },
            ),
            patch(
                "audio_enhancer.core.models.PRESETS",
                mock_presets,
                create=True,
            ),
            patch(
                "audio_enhancer.core.models.PresetName",
                mock_preset_name_cls,
                create=True,
            ),
            patch(
                "audio_enhancer.core.models.EnhancementParams",
                side_effect=capture_ep,
                create=True,
            ),
        ):
            from audio_refinery.core.pipeline import _run_enhance

            result_audio, _rms_b, _rms_a = _run_enhance(_sine(), config, _noop_emit)

        assert len(captured_kwargs) == 1
        # noise_gate_threshold_db should come from presets
        # dict (-60.0), not config (-65.0)
        assert captured_kwargs[0]["noise_gate_threshold_db"] == -60.0
        # output_gain should come from presets (normalise is False)
        assert captured_kwargs[0]["output_gain_db"] == 2.5
        assert isinstance(result_audio, AudioSegment)

    def test_output_gain_suppressed_when_normalise_active(self):
        """When config.normalise=True, output_gain_db passed to EnhancementParams
        must be 0.0 regardless of the preset's own output_gain_db value.

        Strategy: force the CUSTOM preset path so _run_enhance uses
        config.enhance_params (p) directly as the source, bypassing the
        PRESETS dict lookup.  A non-zero output_gain_db is set on the source
        params; we assert the value reaching EnhancementParams is 0.0.
        """
        config = _config_enhance_and_normalise()

        # Give the enhance_params a non-zero output gain so we can confirm
        # the suppression overrides it.
        config.enhance_params.output_gain_db = 3.5

        captured_kwargs: list[dict] = []

        # EnhancementParams capture: records kwargs, returns a usable mock
        mock_built_ep = MagicMock()
        mock_built_ep.noise_gate_threshold_db = -65.0
        mock_built_ep.compressor_threshold_db = -22.0
        mock_built_ep.compressor_ratio = 3.5
        mock_built_ep.compressor_attack_ms = 8.0
        mock_built_ep.compressor_release_ms = 120.0
        mock_built_ep.low_shelf_gain_db = 2.5
        mock_built_ep.low_shelf_freq_hz = 100.0
        mock_built_ep.presence_gain_db = 2.5
        mock_built_ep.presence_freq_hz = 3500.0
        mock_built_ep.high_shelf_gain_db = 4.0
        mock_built_ep.high_shelf_freq_hz = 7000.0
        mock_built_ep.output_gain_db = 0.0
        mock_built_ep.limiter_threshold_db = -0.5

        def capture_ep(**kwargs):
            captured_kwargs.append(kwargs)
            return mock_built_ep

        mock_chain = MagicMock()
        mock_chain.side_effect = lambda audio_np, sr: audio_np.copy()

        # Use a real sentinel for CUSTOM so equality checks work reliably.
        CUSTOM_SENTINEL = "Custom"

        # PresetName(value) must return CUSTOM_SENTINEL so that
        # `preset_enum != PresetName.CUSTOM` is False → PRESETS dict is skipped.
        mock_preset_name_cls = MagicMock(
            return_value=CUSTOM_SENTINEL,  # PresetName(p.preset) → CUSTOM_SENTINEL
            CUSTOM=CUSTOM_SENTINEL,
            MODERATE=CUSTOM_SENTINEL,
        )

        with (
            patch.dict(
                "sys.modules",
                {
                    "pedalboard": MagicMock(
                        Pedalboard=MagicMock(return_value=mock_chain),
                        NoiseGate=MagicMock(return_value=MagicMock()),
                        Compressor=MagicMock(return_value=MagicMock()),
                        LowShelfFilter=MagicMock(return_value=MagicMock()),
                        PeakFilter=MagicMock(return_value=MagicMock()),
                        HighShelfFilter=MagicMock(return_value=MagicMock()),
                        Gain=MagicMock(return_value=MagicMock()),
                        Limiter=MagicMock(return_value=MagicMock()),
                    )
                },
            ),
            patch(
                "audio_enhancer.core.models.PRESETS",
                {},  # Empty — should never be accessed on CUSTOM path
                create=True,
            ),
            patch(
                "audio_enhancer.core.models.PresetName",
                mock_preset_name_cls,
                create=True,
            ),
            patch(
                "audio_enhancer.core.models.EnhancementParams",
                side_effect=capture_ep,
                create=True,
            ),
        ):
            from audio_refinery.core.pipeline import _run_enhance

            _run_enhance(_sine(), config, _noop_emit)

        assert len(captured_kwargs) == 1, (
            "EnhancementParams should be called exactly once"
        )
        assert captured_kwargs[0]["output_gain_db"] == 0.0, (
            f"Expected output_gain_db=0.0 (suppressed),"
            f" got {captured_kwargs[0]['output_gain_db']}"
        )


# ═════════════════════════════════════════════════════════════════════════════
# _run_normalise
# ═════════════════════════════════════════════════════════════════════════════


class TestRunNormalise:
    """
    audio_normalizer.core.loudness.measure and .normalizer.apply are patched
    so no real FFmpeg binary is required.
    """

    def _run(
        self,
        tmp_path: Path,
        *,
        loudness_data: dict | None,
        current_lufs: float = -20.0,
        target_lufs: float = -16.0,
        tolerance: float = 0.5,
    ) -> bool:
        from audio_refinery.core.models import NormaliseParams, StageConfig
        from audio_refinery.core.pipeline import _run_normalise

        config = StageConfig(declick=False, trim=False, enhance=False, normalise=True)
        config.normalise_params = NormaliseParams(
            target_lufs=target_lufs, tolerance=tolerance
        )

        fake_file = tmp_path / "audio.flac"
        fake_file.write_bytes(b"\x00" * 64)

        with (
            patch(
                "audio_normalizer.core.loudness.measure",
                return_value=loudness_data,
            ),
            patch("audio_normalizer.core.normalizer.apply"),
        ):
            result = _run_normalise(fake_file, config, _noop_emit)

        return result

    # ── measure() returns None ────────────────────────────────────────────────

    def test_returns_false_when_measure_returns_none(self, tmp_path):
        result = self._run(tmp_path, loudness_data=None)
        assert result is False

    # ── already within tolerance ──────────────────────────────────────────────

    def test_returns_false_when_already_within_tolerance(self, tmp_path):
        # current = -16.3 LUFS, target = -16.0, tolerance = 0.5 → |delta| = 0.3 ≤ 0.5
        result = self._run(
            tmp_path,
            loudness_data={"input_i": -16.3},
            target_lufs=-16.0,
            tolerance=0.5,
        )
        assert result is False

    def test_apply_not_called_when_within_tolerance(self, tmp_path):
        from audio_refinery.core.models import NormaliseParams, StageConfig
        from audio_refinery.core.pipeline import _run_normalise

        config = StageConfig(declick=False, trim=False, enhance=False, normalise=True)
        config.normalise_params = NormaliseParams(target_lufs=-16.0, tolerance=0.5)
        fake_file = tmp_path / "audio.flac"
        fake_file.write_bytes(b"\x00" * 64)

        with (
            patch(
                "audio_normalizer.core.loudness.measure",
                return_value={"input_i": -16.2},
            ) as mock_measure,
            patch("audio_normalizer.core.normalizer.apply") as mock_apply,
        ):
            _run_normalise(fake_file, config, _noop_emit)

        mock_measure.assert_called_once()
        mock_apply.assert_not_called()

    # ── normalisation applied ─────────────────────────────────────────────────

    def test_returns_true_when_normalisation_applied(self, tmp_path):
        # current = -23.0 LUFS, target = -16.0 → |delta| = 7.0 > 0.5
        result = self._run(
            tmp_path,
            loudness_data={"input_i": -23.0},
            target_lufs=-16.0,
            tolerance=0.5,
        )
        assert result is True

    def test_apply_called_when_normalisation_needed(self, tmp_path):
        from audio_refinery.core.models import NormaliseParams, StageConfig
        from audio_refinery.core.pipeline import _run_normalise

        config = StageConfig(declick=False, trim=False, enhance=False, normalise=True)
        config.normalise_params = NormaliseParams(target_lufs=-16.0, tolerance=0.5)
        fake_file = tmp_path / "audio.flac"
        fake_file.write_bytes(b"\x00" * 64)
        loudness = {"input_i": -23.0}

        with (
            patch(
                "audio_normalizer.core.loudness.measure",
                return_value=loudness,
            ),
            patch("audio_normalizer.core.normalizer.apply") as mock_apply,
        ):
            _run_normalise(fake_file, config, _noop_emit)

        mock_apply.assert_called_once()

    def test_apply_receives_correct_target(self, tmp_path):
        from audio_refinery.core.models import NormaliseParams, StageConfig
        from audio_refinery.core.pipeline import _run_normalise

        target = -14.0
        config = StageConfig(declick=False, trim=False, enhance=False, normalise=True)
        config.normalise_params = NormaliseParams(target_lufs=target, tolerance=0.5)
        fake_file = tmp_path / "audio.flac"
        fake_file.write_bytes(b"\x00" * 64)
        loudness = {"input_i": -23.0}

        with (
            patch(
                "audio_normalizer.core.loudness.measure",
                return_value=loudness,
            ),
            patch("audio_normalizer.core.normalizer.apply") as mock_apply,
        ):
            _run_normalise(fake_file, config, _noop_emit)

        call_args = mock_apply.call_args
        # apply(str(tmp_path), target, loudness_data) — target is second positional arg
        assert call_args[0][1] == target

    def test_apply_receives_record_snapshot_false(self, tmp_path):
        """The pipeline owns the undo snapshot, so apply() must not record
        one against the temp staging path."""
        from audio_refinery.core.models import NormaliseParams, StageConfig
        from audio_refinery.core.pipeline import _run_normalise

        config = StageConfig(declick=False, trim=False, enhance=False, normalise=True)
        config.normalise_params = NormaliseParams(target_lufs=-16.0, tolerance=0.5)
        fake_file = tmp_path / "audio.flac"
        fake_file.write_bytes(b"\x00" * 64)
        loudness = {"input_i": -23.0}

        with (
            patch("audio_normalizer.core.loudness.measure", return_value=loudness),
            patch("audio_normalizer.core.normalizer.apply") as mock_apply,
        ):
            _run_normalise(fake_file, config, _noop_emit)

        mock_apply.assert_called_once()
        assert mock_apply.call_args.kwargs["record_snapshot"] is False

    # ── boundary: exactly at tolerance edge ──────────────────────────────────

    def test_exactly_at_tolerance_boundary_is_skipped(self, tmp_path):
        # |(-16.5) - (-16.0)| == 0.5 == tolerance → should skip
        result = self._run(
            tmp_path,
            loudness_data={"input_i": -16.5},
            target_lufs=-16.0,
            tolerance=0.5,
        )
        assert result is False

    def test_just_outside_tolerance_is_applied(self, tmp_path):
        # |(-16.51) - (-16.0)| = 0.51 > 0.5 → should apply
        result = self._run(
            tmp_path,
            loudness_data={"input_i": -16.51},
            target_lufs=-16.0,
            tolerance=0.5,
        )
        assert result is True
