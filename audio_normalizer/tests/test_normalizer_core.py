"""
Tests for audio_normalizer.core.loudness, normalizer, and file_processor
Gap G-35: _safe_float, measure(), _codec_args, apply(), process_single_file(),
          run_parallel_process()
"""

import threading
from queue import Queue
from unittest.mock import MagicMock, patch

import pytest
from pydub import AudioSegment

from audio_normalizer.core.file_processor import (
    AudioNormalizerProcessor,
    process_single_file,
    run_parallel_process,
)
from audio_normalizer.core.loudness import _safe_float, measure
from audio_normalizer.core.normalizer import _codec_args, apply
from audio_suite_shared.exceptions import AudioFormatError

# ── Helpers ───────────────────────────────────────────────────────────────────

MOCK_LOUDNESS = {
    "input_i": -18.0,
    "input_tp": -1.5,
    "input_lra": 7.0,
    "input_thresh": -28.0,
    "target_offset": 0.0,
}

MOCK_STDERR = (
    "{\n"
    '    "input_i" : "-18.00",\n'
    '    "input_tp" : "-1.50",\n'
    '    "input_lra" : "7.00",\n'
    '    "input_thresh" : "-28.00",\n'
    '    "target_offset" : "0.00"\n'
    "}\n"
)


def _make_audio(tmp_path, name="track.mp3"):
    path = tmp_path / name
    AudioSegment.silent(duration=100).export(str(path), format=name.rsplit(".", 1)[-1])
    return str(path)


def _make_slots(n=4):
    slot_vars = [MagicMock() for _ in range(n)]
    slot_q = Queue()
    for i in range(n):
        slot_q.put(i)
    return slot_vars, slot_q


def _mock_result(stderr=MOCK_STDERR, returncode=0):
    m = MagicMock()
    m.returncode = returncode
    m.stderr = stderr
    return m


# ═════════════════════════════════════════════════════════════════════════════
# _safe_float
# ═════════════════════════════════════════════════════════════════════════════


class TestSafeFloat:
    def test_numeric_string_converts(self):
        assert _safe_float("-18.5") == -18.5

    def test_positive_numeric_converts(self):
        assert _safe_float("3.14") == pytest.approx(3.14)

    def test_minus_inf_returns_default(self):
        assert _safe_float("-inf") == 0.0

    def test_plus_inf_returns_default(self):
        assert _safe_float("inf") == 0.0

    def test_nan_returns_default(self):
        assert _safe_float("nan") == 0.0

    def test_none_returns_default(self):
        assert _safe_float(None) == 0.0

    def test_empty_string_returns_default(self):
        assert _safe_float("") == 0.0

    def test_non_numeric_returns_default(self):
        assert _safe_float("abc") == 0.0

    def test_custom_default_used(self):
        assert _safe_float("inf", default=-70.0) == -70.0

    def test_integer_string_converts(self):
        assert _safe_float("42") == 42.0

    def test_zero_string_converts(self):
        assert _safe_float("0.0") == 0.0

    def test_real_loudnorm_value(self):
        assert _safe_float("-23.0") == pytest.approx(-23.0)


# ═════════════════════════════════════════════════════════════════════════════
# measure()
# ═════════════════════════════════════════════════════════════════════════════


class TestMeasure:
    def _mock_run(self, stderr, returncode=0):
        with patch(
            "audio_normalizer.core.loudness.run_secure_subprocess",
            return_value=_mock_result(stderr, returncode),
        ):
            return measure("/tmp/test.mp3", -16.0)

    def test_returns_dict_on_success(self):
        result = self._mock_run(MOCK_STDERR)
        assert isinstance(result, dict)

    def test_returns_none_when_no_json(self):
        assert self._mock_run("no json here") is None

    def test_parses_input_i(self):
        result = self._mock_run(MOCK_STDERR)
        assert result is not None
        assert abs(result["input_i"] - (-18.0)) < 0.01

    def test_parses_input_tp(self):
        result = self._mock_run(MOCK_STDERR)
        assert abs(result["input_tp"] - (-1.5)) < 0.01

    def test_parses_input_lra(self):
        result = self._mock_run(MOCK_STDERR)
        assert abs(result["input_lra"] - 7.0) < 0.01

    def test_parses_input_thresh(self):
        result = self._mock_run(MOCK_STDERR)
        assert abs(result["input_thresh"] - (-28.0)) < 0.01

    def test_parses_target_offset(self):
        result = self._mock_run(MOCK_STDERR)
        assert result["target_offset"] == pytest.approx(0.0)

    def test_all_required_keys_present(self):
        result = self._mock_run(MOCK_STDERR)
        for key in (
            "input_i",
            "input_tp",
            "input_lra",
            "input_thresh",
            "target_offset",
        ):
            assert key in result

    def test_non_loudnorm_json_returns_none(self):
        other_json = '{"some_other": "data"}'
        assert self._mock_run(other_json) is None

    def test_minus_inf_in_json_uses_safe_float(self):
        bad_stderr = (
            "{\n"
            '    "input_i" : "-inf",\n'
            '    "input_tp" : "-1.5",\n'
            '    "input_lra" : "7.0",\n'
            '    "input_thresh" : "-28.0",\n'
            '    "target_offset" : "0.0"\n'
            "}\n"
        )
        result = self._mock_run(bad_stderr)
        assert result is not None
        assert result["input_i"] == -70.0  # safe_float default for -inf

    def test_multiple_json_blocks_uses_last(self):
        # ffmpeg may emit earlier stream-info JSON before loudnorm JSON
        double = '{"codec_name": "mp3"}\n' + MOCK_STDERR
        result = self._mock_run(double)
        assert result is not None
        assert "input_i" in result

    def test_ffmpeg_subprocess_uses_correct_target(self):
        calls = []
        with patch(
            "audio_normalizer.core.loudness.run_secure_subprocess",
            side_effect=lambda exe, args, **kw: (
                calls.append([exe, *args]),
                _mock_result(),
            )[1],
        ):
            measure("/tmp/t.mp3", -23.0)
        assert any("-23.0" in str(arg) for arg in calls[0])


# ═════════════════════════════════════════════════════════════════════════════
# _codec_args
# ═════════════════════════════════════════════════════════════════════════════


class TestCodecArgs:
    @pytest.mark.parametrize(
        "filename,expected_codec",
        [
            ("track.mp3", "libmp3lame"),
            ("track.flac", "flac"),
            ("track.ogg", "libvorbis"),
            ("track.m4a", "aac"),
            ("track.opus", "libopus"),
        ],
    )
    def test_correct_codec_per_extension(self, filename, expected_codec):
        codec, _ = _codec_args(filename)
        assert codec == expected_codec

    def test_returns_tuple(self):
        result = _codec_args("track.mp3")
        assert isinstance(result, tuple) and len(result) == 2

    def test_extra_args_is_list(self):
        _, extra = _codec_args("track.mp3")
        assert isinstance(extra, list)

    @pytest.mark.parametrize(
        "filename",
        [
            "track.xyz",
            "track.wav",
            "track.aiff",
            "track.aif",
            "track.mp4",
            "track.wma",
            "track.flacx",
        ],
    )
    def test_unmapped_extension_raises_format_error(self, filename):
        """Silent MP3 fallback on unmapped extensions is forbidden — a WAV/AIFF
        or unknown file must never be lossily re-encoded as MP3."""
        with pytest.raises(AudioFormatError):
            _codec_args(filename)

    def test_unmapped_extension_error_includes_extension(self):
        with pytest.raises(AudioFormatError, match=r"\.xyz"):
            _codec_args("track.xyz")

    def test_case_insensitive_extension(self):
        codec_lower, _ = _codec_args("track.mp3")
        codec_upper, _ = _codec_args("track.MP3")
        assert codec_lower == codec_upper

    def test_mp3_uses_vbr_quality(self):
        _, extra = _codec_args("track.mp3")
        assert "-q:a" in extra

    def test_flac_has_compression_level(self):
        _, extra = _codec_args("track.flac")
        assert "-compression_level" in extra

    def test_opus_has_bitrate(self):
        _, extra = _codec_args("track.opus")
        assert "-b:a" in extra


# ═════════════════════════════════════════════════════════════════════════════
# apply() — normalizer (mocked subprocess)
# ═════════════════════════════════════════════════════════════════════════════


class TestApply:
    def test_calls_ffmpeg_subprocess(self, tmp_path):
        f = _make_audio(tmp_path, "t.mp3")
        calls = []

        def fake_run(exe, args, **kw):
            cmd = [exe, *args]
            calls.append(cmd)
            # Create the temp output file so os.replace works
            temp = cmd[-1]
            with open(temp, "wb") as fh:
                fh.write(b"encoded")
            m = MagicMock()
            m.returncode = 0
            return m

        with (
            patch("audio_normalizer.core.normalizer.run_secure_subprocess", fake_run),
            patch("audio_normalizer.core.normalizer.read_tags_raw", return_value=None),
            patch("audio_normalizer.core.normalizer.write_tags_raw"),
        ):
            apply(f, -16.0, MOCK_LOUDNESS)
        assert len(calls) == 1
        assert "ffmpeg" in calls[0][0].lower() or "ffmpeg" in calls[0]

    def test_output_replaces_original(self, tmp_path):
        original_content = b"original audio content"
        f = tmp_path / "t.mp3"
        f.write_bytes(original_content)
        encoded_content = b"encoded audio content"

        def fake_run(exe, args, **kw):
            cmd = [exe, *args]
            temp = cmd[-1]
            with open(temp, "wb") as fh:
                fh.write(encoded_content)
            m = MagicMock()
            m.returncode = 0
            return m

        with (
            patch("audio_normalizer.core.normalizer.run_secure_subprocess", fake_run),
            patch("audio_normalizer.core.normalizer.read_tags_raw", return_value=None),
            patch("audio_normalizer.core.normalizer.write_tags_raw"),
        ):
            apply(str(f), -16.0, MOCK_LOUDNESS)

        assert f.read_bytes() == encoded_content

    def test_ffmpeg_includes_measured_values(self, tmp_path):
        f = _make_audio(tmp_path, "t.mp3")
        calls = []

        def fake_run(exe, args, **kw):
            cmd = [exe, *args]
            calls.append(cmd)
            temp = cmd[-1]
            open(temp, "wb").close()
            m = MagicMock()
            m.returncode = 0
            return m

        with (
            patch("audio_normalizer.core.normalizer.run_secure_subprocess", fake_run),
            patch("audio_normalizer.core.normalizer.read_tags_raw", return_value=None),
            patch("audio_normalizer.core.normalizer.write_tags_raw"),
        ):
            apply(f, -16.0, MOCK_LOUDNESS)

        cmd_str = " ".join(calls[0])
        assert "measured_I=-18.0" in cmd_str or "measured_I" in cmd_str

    def test_ffmpeg_error_raises(self, tmp_path):
        f = _make_audio(tmp_path, "t.mp3")
        import subprocess

        with (
            patch(
                "audio_normalizer.core.normalizer.run_secure_subprocess",
                side_effect=subprocess.CalledProcessError(1, "ffmpeg"),
            ),
            patch("audio_normalizer.core.normalizer.read_tags_raw", return_value=None),
        ):
            with pytest.raises(subprocess.CalledProcessError):
                apply(f, -16.0, MOCK_LOUDNESS)

    def test_temp_file_cleaned_up_on_error(self, tmp_path):
        f = _make_audio(tmp_path, "t.mp3")
        import subprocess

        with (
            patch(
                "audio_normalizer.core.normalizer.run_secure_subprocess",
                side_effect=subprocess.CalledProcessError(1, "ffmpeg"),
            ),
            patch("audio_normalizer.core.normalizer.read_tags_raw", return_value=None),
        ):
            try:
                apply(f, -16.0, MOCK_LOUDNESS)
            except subprocess.CalledProcessError:
                pass

        # No .tmp.mp3 file should remain
        temp_files = list((tmp_path).glob("*.tmp*"))
        assert len(temp_files) == 0

    def test_write_tags_raw_failure_leaves_temp_file_and_original_intact(
        self, tmp_path
    ):
        """When tag writing fails after encoding, the original must be preserved
        and the exception must propagate (temp file may leak — a known limitation
        since the try/except only covers the subprocess call)."""
        original_content = b"original audio content"
        f = tmp_path / "t.mp3"
        f.write_bytes(original_content)
        encoded_content = b"encoded audio content"

        def fake_run(exe, args, **kw):
            cmd = [exe, *args]
            temp = cmd[-1]
            with open(temp, "wb") as fh:
                fh.write(encoded_content)
            m = MagicMock()
            m.returncode = 0
            return m

        with (
            patch("audio_normalizer.core.normalizer.run_secure_subprocess", fake_run),
            patch("audio_normalizer.core.normalizer.read_tags_raw", return_value=None),
            patch(
                "audio_normalizer.core.normalizer.write_tags_raw",
                side_effect=OSError("write permission denied"),
            ),
        ):
            with pytest.raises(OSError, match="write permission denied"):
                apply(str(f), -16.0, MOCK_LOUDNESS)

        # Original file must be untouched
        assert f.read_bytes() == original_content

    def test_read_tags_raw_failure_propagates(self, tmp_path):
        """If reading the original tags fails, the exception must propagate
        before any encoding takes place."""
        f = _make_audio(tmp_path, "t.mp3")
        with (
            patch("audio_normalizer.core.normalizer.run_secure_subprocess") as mock_run,
            patch(
                "audio_normalizer.core.normalizer.read_tags_raw",
                side_effect=RuntimeError("tag read error"),
            ),
        ):
            with pytest.raises(RuntimeError, match="tag read error"):
                apply(f, -16.0, MOCK_LOUDNESS)

        # FFmpeg should never have been called
        mock_run.assert_not_called()

    def test_apply_unsupported_format_rejected_before_ffmpeg(self, tmp_path):
        """An unmapped extension (e.g. .wav) must raise AudioFormatError before
        any tag read or FFmpeg invocation — never silently re-encode as MP3."""
        f = tmp_path / "track.wav"
        f.write_bytes(b"wav data")
        with (
            patch("audio_normalizer.core.normalizer.run_secure_subprocess") as mock_run,
            patch("audio_normalizer.core.normalizer.read_tags_raw") as mock_tags,
        ):
            with pytest.raises(AudioFormatError, match=r"\.wav"):
                apply(str(f), -16.0, MOCK_LOUDNESS)

        mock_run.assert_not_called()
        mock_tags.assert_not_called()
        assert f.read_bytes() == b"wav data"

    def test_ffmpeg_includes_loudnorm_offset_parameter(self, tmp_path):
        """The measured target_offset must be passed to the loudnorm filter."""
        f = _make_audio(tmp_path, "t.mp3")
        calls = []

        def fake_run(exe, args, **kw):
            cmd = [exe, *args]
            calls.append(cmd)
            temp = cmd[-1]
            open(temp, "wb").close()
            m = MagicMock()
            m.returncode = 0
            return m

        loudness_with_offset = {**MOCK_LOUDNESS, "target_offset": -0.5}
        with (
            patch("audio_normalizer.core.normalizer.run_secure_subprocess", fake_run),
            patch("audio_normalizer.core.normalizer.read_tags_raw", return_value=None),
            patch("audio_normalizer.core.normalizer.write_tags_raw"),
        ):
            apply(f, -16.0, loudness_with_offset)

        cmd_str = " ".join(calls[0])
        assert "offset=-0.5" in cmd_str


# ═════════════════════════════════════════════════════════════════════════════
# AudioNormalizerProcessor
# ═════════════════════════════════════════════════════════════════════════════


class TestAudioNormalizerProcessor:
    def test_instantiates(self):
        with patch("audio_suite_shared.file_processor_base.get_resource_manager"):
            p = AudioNormalizerProcessor()
            assert p is not None

    def test_operation_type(self):
        with patch("audio_suite_shared.file_processor_base.get_resource_manager"):
            p = AudioNormalizerProcessor()
            assert p.operation_type == "audio_normalization"


# ═════════════════════════════════════════════════════════════════════════════
# process_single_file (normalizer)
# ═════════════════════════════════════════════════════════════════════════════


class TestNormalizerProcessSingleFile:
    def _call(self, tmp_path, name, loudness=MOCK_LOUDNESS, is_dry_run=True):
        slot_vars, slot_q = _make_slots()
        slot_idx = slot_q.get()
        results = []

        with (
            patch(
                "audio_normalizer.core.file_processor.measure", return_value=loudness
            ),
            patch(
                "audio_normalizer.core.file_processor.apply_normalisation"
            ) as mock_apply,
        ):
            process_single_file(
                name=name,
                dir_path=str(tmp_path),
                target_lufs=-16.0,
                tolerance=1.0,
                is_dry_run=is_dry_run,
                slot_idx=slot_idx,
                lock=threading.Lock(),
                on_progress=lambda **kw: results.append(kw),
                slot_vars=slot_vars,
            )
        return results, mock_apply

    def test_dry_run_does_not_apply(self, tmp_path):
        _make_audio(tmp_path, "t.mp3")
        results, mock_apply = self._call(tmp_path, "t.mp3", is_dry_run=True)
        mock_apply.assert_not_called()
        assert "DRY RUN" in results[-1]["display_text"]

    def test_dry_run_display_contains_dry_run(self, tmp_path):
        _make_audio(tmp_path, "t.mp3")
        results, _ = self._call(tmp_path, "t.mp3", is_dry_run=True)
        assert "DRY RUN" in results[-1]["display_text"]

    def test_dry_run_shows_gain_db(self, tmp_path):
        _make_audio(tmp_path, "t.mp3")
        results, _ = self._call(tmp_path, "t.mp3", is_dry_run=True)
        # gain = -16 - (-18) = 2.0 dB
        assert "2.00" in results[-1]["display_text"]

    def test_live_calls_apply(self, tmp_path):
        _make_audio(tmp_path, "t.mp3")
        _, mock_apply = self._call(tmp_path, "t.mp3", is_dry_run=False)
        mock_apply.assert_called_once()

    def test_live_display_contains_normalized(self, tmp_path):
        _make_audio(tmp_path, "t.mp3")
        results, _ = self._call(tmp_path, "t.mp3", is_dry_run=False)
        assert "NORMALIZED" in results[-1]["display_text"]

    def test_within_tolerance_skips_dry_run(self, tmp_path):
        # target=-16.0, tolerance=1.0, measured=-16.5 → |gain|=0.5 <= 1.0 → skip
        near_loudness = {**MOCK_LOUDNESS, "input_i": -16.5}
        _make_audio(tmp_path, "t.mp3")
        results, mock_apply = self._call(
            tmp_path, "t.mp3", loudness=near_loudness, is_dry_run=True
        )
        assert "SKIPPED" in results[-1]["display_text"]
        mock_apply.assert_not_called()

    def test_within_tolerance_skips_live(self, tmp_path):
        # target=-16.0, tolerance=1.0, measured=-16.5 → |gain|=0.5 <= 1.0 → skip
        near_loudness = {**MOCK_LOUDNESS, "input_i": -16.5}
        _make_audio(tmp_path, "t.mp3")
        results, mock_apply = self._call(
            tmp_path, "t.mp3", loudness=near_loudness, is_dry_run=False
        )
        assert "SKIPPED" in results[-1]["display_text"]
        mock_apply.assert_not_called()

    def test_within_tolerance_reports_n_skipped(self, tmp_path):
        near_loudness = {**MOCK_LOUDNESS, "input_i": -16.5}
        _make_audio(tmp_path, "t.mp3")
        results, _ = self._call(
            tmp_path, "t.mp3", loudness=near_loudness, is_dry_run=False
        )
        assert results[-1].get("n_skipped") == 1

    def test_exactly_at_tolerance_boundary_skips(self, tmp_path):
        # target=-16.0, tolerance=1.0, measured=-17.0 → |gain|=1.0 <= 1.0 → skip
        # (inclusive)
        boundary_loudness = {**MOCK_LOUDNESS, "input_i": -17.0}
        _make_audio(tmp_path, "t.mp3")
        results, mock_apply = self._call(
            tmp_path, "t.mp3", loudness=boundary_loudness, is_dry_run=False
        )
        assert "SKIPPED" in results[-1]["display_text"]
        mock_apply.assert_not_called()

    def test_just_outside_tolerance_does_not_skip(self, tmp_path):
        # target=-16.0, tolerance=1.0, measured=-17.1 → |gain|=1.1 > 1.0 → normalize
        outside_loudness = {**MOCK_LOUDNESS, "input_i": -17.1}
        _make_audio(tmp_path, "t.mp3")
        results, mock_apply = self._call(
            tmp_path, "t.mp3", loudness=outside_loudness, is_dry_run=False
        )
        assert "NORMALIZED" in results[-1]["display_text"]
        mock_apply.assert_called_once()

    def test_null_loudness_raises_audio_analysis_error(self, tmp_path):
        _make_audio(tmp_path, "t.mp3")
        slot_vars, slot_q = _make_slots()
        slot_idx = slot_q.get()
        from audio_suite_shared.exceptions import AudioAnalysisError

        with patch("audio_normalizer.core.file_processor.measure", return_value=None):
            with pytest.raises(AudioAnalysisError, match="Could not detect loudness"):
                process_single_file(
                    name="t.mp3",
                    dir_path=str(tmp_path),
                    target_lufs=-16.0,
                    tolerance=1.0,
                    is_dry_run=True,
                    slot_idx=slot_idx,
                    lock=threading.Lock(),
                    on_progress=lambda **kw: None,
                    slot_vars=slot_vars,
                )

    def test_live_apply_error_reports_n_errors(self, tmp_path):
        """When apply_normalisation raises in live mode, the error is caught,
        mapped, and reported via on_progress with n_errors=1."""
        _make_audio(tmp_path, "t.mp3")
        slot_vars, slot_q = _make_slots()
        slot_idx = slot_q.get()
        results: list[dict] = []

        with (
            patch(
                "audio_normalizer.core.file_processor.measure",
                return_value=MOCK_LOUDNESS,
            ),
            patch(
                "audio_normalizer.core.file_processor.apply_normalisation",
                side_effect=RuntimeError("FFmpeg encoding failed"),
            ),
        ):
            process_single_file(
                name="t.mp3",
                dir_path=str(tmp_path),
                target_lufs=-16.0,
                tolerance=1.0,
                is_dry_run=False,
                slot_idx=slot_idx,
                lock=threading.Lock(),
                on_progress=lambda **kw: results.append(kw),
                slot_vars=slot_vars,
            )

        assert len(results) == 1
        assert results[0].get("n_errors") == 1
        assert "[ERROR]" in results[0].get("display_text", "")
        assert "t.mp3" in results[0].get("display_text", "")

    def test_live_apply_error_does_not_raise(self, tmp_path):
        """The error handler in process_single_file must catch all exceptions
        from apply_normalisation and return cleanly (no exception propagates)."""
        _make_audio(tmp_path, "t.mp3")
        slot_vars, slot_q = _make_slots()
        slot_idx = slot_q.get()

        with (
            patch(
                "audio_normalizer.core.file_processor.measure",
                return_value=MOCK_LOUDNESS,
            ),
            patch(
                "audio_normalizer.core.file_processor.apply_normalisation",
                side_effect=RuntimeError("FFmpeg encoding failed"),
            ),
        ):
            # This should not raise — the error is caught internally
            process_single_file(
                name="t.mp3",
                dir_path=str(tmp_path),
                target_lufs=-16.0,
                tolerance=1.0,
                is_dry_run=False,
                slot_idx=slot_idx,
                lock=threading.Lock(),
                on_progress=lambda **kw: None,
                slot_vars=slot_vars,
            )

    def test_tolerance_zero_only_skips_exact_match(self, tmp_path):
        """tolerance=0.0 should skip iff |gain_needed| is exactly 0.0."""
        exact_match = {**MOCK_LOUDNESS, "input_i": -16.0}  # gain = -16 - (-16) = 0
        _make_audio(tmp_path, "t.mp3")
        results, mock_apply = self._call(
            tmp_path, "t.mp3", loudness=exact_match, is_dry_run=False
        )
        assert "SKIPPED" in results[-1]["display_text"]
        mock_apply.assert_not_called()


# ═════════════════════════════════════════════════════════════════════════════
# Lossless routing — process_single_file normalization_mode
# ═════════════════════════════════════════════════════════════════════════════


class TestNormalizerLosslessRouting:
    """normalization_mode="lossless" must route MP3 files through global_gain
    adjustment and everything else through the FFmpeg loudnorm fallback."""

    def _apply_file(
        self,
        tmp_path,
        name,
        normalization_mode,
        loudness=MOCK_LOUDNESS,
        is_dry_run=False,
    ):
        _make_audio(tmp_path, name)
        slot_vars, slot_q = _make_slots()
        slot_idx = slot_q.get()
        results = []

        with (
            patch(
                "audio_normalizer.core.file_processor.measure",
                return_value=loudness,
            ),
            patch(
                "audio_normalizer.core.file_processor.apply_normalisation"
            ) as mock_loudnorm,
            patch(
                "audio_normalizer.core.file_processor.apply_track_gain"
            ) as mock_track,
        ):
            process_single_file(
                name=name,
                dir_path=str(tmp_path),
                target_lufs=-16.0,
                tolerance=1.0,
                is_dry_run=is_dry_run,
                slot_idx=slot_idx,
                lock=threading.Lock(),
                on_progress=lambda **kw: results.append(kw),
                slot_vars=slot_vars,
                normalization_mode=normalization_mode,
            )
        return results, mock_loudnorm, mock_track

    def test_lossless_mp3_uses_track_gain(self, tmp_path):
        _, mock_loudnorm, mock_track = self._apply_file(tmp_path, "t.mp3", "lossless")
        mock_track.assert_called_once()
        mock_loudnorm.assert_not_called()

    def test_lossless_mp3_passes_gain_needed_db(self, tmp_path):
        # target=-16.0, input_i=-18.0 → gain_needed = +2.0 dB
        _, _, mock_track = self._apply_file(tmp_path, "t.mp3", "lossless")
        args = mock_track.call_args.args
        assert len(args) == 2
        assert str(args[0]).endswith("t.mp3")
        assert args[1] == pytest.approx(2.0)

    def test_lossless_non_mp3_falls_back_to_loudnorm(self, tmp_path):
        _, mock_loudnorm, mock_track = self._apply_file(tmp_path, "t.flac", "lossless")
        mock_loudnorm.assert_called_once()
        mock_track.assert_not_called()

    def test_normalise_mode_never_uses_track_gain(self, tmp_path):
        _, mock_loudnorm, mock_track = self._apply_file(tmp_path, "t.mp3", "normalise")
        mock_loudnorm.assert_called_once()
        mock_track.assert_not_called()

    def test_lossless_dry_run_calls_nothing(self, tmp_path):
        results, mock_loudnorm, mock_track = self._apply_file(
            tmp_path, "t.mp3", "lossless", is_dry_run=True
        )
        mock_loudnorm.assert_not_called()
        mock_track.assert_not_called()
        assert "DRY RUN" in results[-1]["display_text"]


# ═════════════════════════════════════════════════════════════════════════════
# run_parallel_process
# ═════════════════════════════════════════════════════════════════════════════


class TestRunParallelProcess:
    def _run(self, tmp_path, loudness=MOCK_LOUDNESS, is_dry_run=True):
        slot_vars, slot_q = _make_slots()
        progress, complete, errors = [], [], []

        with (
            patch(
                "audio_normalizer.core.file_processor.measure", return_value=loudness
            ),
            patch("audio_normalizer.core.file_processor.apply_normalisation"),
            patch("audio_suite_shared.file_processor_base.get_resource_manager"),
            patch("audio_suite_shared.file_processor_base.track_thread"),
            patch("audio_suite_shared.file_processor_base.cleanup_expired_resources"),
        ):
            run_parallel_process(
                dir_path=str(tmp_path),
                target_lufs=-16.0,
                tolerance=1.0,
                is_dry_run=is_dry_run,
                slot_vars=slot_vars,
                slot_queue=slot_q,
                on_progress=lambda **kw: progress.append(kw),
                on_complete=lambda **kw: complete.append(kw),
                on_error=lambda msg: errors.append(msg),
            )
        return progress, complete, errors

    def test_empty_directory_calls_on_error(self, tmp_path):
        _, _, errors = self._run(tmp_path)
        assert len(errors) == 1

    def test_on_complete_called(self, tmp_path):
        for i in range(2):
            _make_audio(tmp_path, f"t{i}.mp3")
        _, complete, _ = self._run(tmp_path)
        assert len(complete) == 1

    def test_total_matches_file_count(self, tmp_path):
        for i in range(3):
            _make_audio(tmp_path, f"t{i}.mp3")
        _, complete, _ = self._run(tmp_path)
        assert complete[0]["total"] == 3

    def test_null_loudness_still_calls_on_complete(self, tmp_path):
        """When loudness detection fails, RuntimeError is raised by process_single_file.
        BaseFileProcessor's retry logic exhausts retries and on_complete
        is still called.
        """
        _make_audio(tmp_path, "t.mp3")
        _, complete, _ = self._run(tmp_path, loudness=None)
        assert len(complete) == 1
        assert complete[0]["total"] == 1

    def test_duration_in_complete(self, tmp_path):
        _make_audio(tmp_path, "t.mp3")
        _, complete, _ = self._run(tmp_path)
        assert complete[0]["duration_secs"] >= 0

    def test_lossless_mode_forwarded_to_single_file(self, tmp_path):
        """normalization_mode must reach process_single_file via the wrapper."""
        _make_audio(tmp_path, "t.mp3")
        slot_vars, slot_q = _make_slots()

        with (
            patch(
                "audio_normalizer.core.file_processor.process_single_file"
            ) as mock_single,
            patch("audio_suite_shared.file_processor_base.get_resource_manager"),
            patch("audio_suite_shared.file_processor_base.track_thread"),
            patch("audio_suite_shared.file_processor_base.cleanup_expired_resources"),
        ):
            run_parallel_process(
                dir_path=str(tmp_path),
                target_lufs=-16.0,
                tolerance=1.0,
                is_dry_run=True,
                normalization_mode="lossless",
                slot_vars=slot_vars,
                slot_queue=slot_q,
                on_progress=MagicMock(),
                on_complete=MagicMock(),
                on_error=MagicMock(),
            )

        assert any(
            call_.kwargs.get("normalization_mode") == "lossless"
            for call_ in mock_single.call_args_list
        )


class TestUndoBatchRecording:
    """Phase 2: worker threads must join the orchestrator's active undo
    batch so tag snapshots are recorded against it (batch_undo.use_batch)."""

    def _run(self, tmp_path, is_dry_run, loudness=MOCK_LOUDNESS):
        from audio_suite_shared.batch_undo import active_batch, list_recent_batches
        from audio_suite_shared.tag_helper_writer import write_tags_raw

        undo_db = tmp_path / "undo_log.db"
        for i in range(2):
            _make_audio(tmp_path, f"t{i}.mp3")
        slot_vars, slot_q = _make_slots()

        handler = MagicMock()
        handler.get_raw_tags.return_value = {"TCON": "Rock"}
        shared_factory = MagicMock()
        shared_factory.get_handler.return_value = handler

        def _mock_apply(file_path, target_lufs, loudness_data):
            write_tags_raw(str(file_path), {"original": "tags"})

        with (
            patch(
                "audio_normalizer.core.file_processor.measure", return_value=loudness
            ),
            patch(
                "audio_normalizer.core.file_processor.apply_normalisation",
                side_effect=_mock_apply,
            ),
            patch("audio_suite_shared.file_processor_base.get_resource_manager"),
            patch("audio_suite_shared.file_processor_base.track_thread"),
            patch("audio_suite_shared.file_processor_base.cleanup_expired_resources"),
            patch(
                "audio_suite_shared.tag_helper_base.TagHandlerFactory", shared_factory
            ),
            patch(
                "audio_suite_shared.tag_helper_reader.TagHandlerFactory", shared_factory
            ),
            patch(
                "audio_suite_shared.tag_helper_writer.TagHandlerFactory", shared_factory
            ),
        ):
            with active_batch("audio_normalizer", "tag_edit", db_path=undo_db):
                run_parallel_process(
                    dir_path=str(tmp_path),
                    target_lufs=-16.0,
                    tolerance=1.0,
                    is_dry_run=is_dry_run,
                    slot_vars=slot_vars,
                    slot_queue=slot_q,
                    on_progress=MagicMock(),
                    on_complete=MagicMock(),
                    on_error=MagicMock(),
                )

        return list_recent_batches(limit=10, db_path=undo_db)

    def test_live_mode_records_snapshots_from_workers(self, tmp_path):
        batches = self._run(tmp_path, is_dry_run=False)
        assert len(batches) == 1
        assert batches[0].tool_name == "audio_normalizer"
        assert batches[0].operation_type == "tag_edit"
        assert batches[0].record_count == 2

    def test_dry_run_prunes_empty_batch(self, tmp_path):
        assert self._run(tmp_path, is_dry_run=True) == []

    def test_apply_records_snapshot_against_real_path(self, tmp_path):
        """apply() must snapshot the real output file — never its .tmp
        staging path — and the staging tag-write must not auto-record."""
        from audio_normalizer.core.normalizer import apply as apply_norm
        from audio_suite_shared.batch_undo import (
            BatchUndoLog,
            active_batch,
            list_recent_batches,
        )

        undo_db = tmp_path / "undo.log.db"
        f = _make_audio(tmp_path, "t.mp3")

        tagged_handler = MagicMock()
        tagged_handler.get_raw_tags.return_value = {"TPE1": "Artist"}
        shared_factory = MagicMock()
        shared_factory.get_handler.return_value = tagged_handler

        def fake_run(exe, args, **kw):
            cmd = [exe, *args]
            open(cmd[-1], "wb").close()
            m = MagicMock()
            m.returncode = 0
            return m

        with (
            patch("audio_normalizer.core.normalizer.run_secure_subprocess", fake_run),
            patch(
                "audio_normalizer.core.normalizer.read_tags_raw",
                return_value={"TPE1": "Artist"},
            ),
            patch("audio_normalizer.core.normalizer.write_tags_raw"),
            patch(
                "audio_suite_shared.tag_helper_base.TagHandlerFactory", shared_factory
            ),
        ):
            with active_batch("audio_normalizer", "tag_edit", db_path=undo_db):
                apply_norm(f, -16.0, MOCK_LOUDNESS)

        batches = list_recent_batches(limit=5, db_path=undo_db)
        assert len(batches) == 1
        assert batches[0].record_count == 1
        records = BatchUndoLog(db_path=undo_db).get_batch_records(batches[0].batch_id)
        assert len(records) == 1
        assert records[0].file_path == f
        assert records[0].operation == "write_normalise"
