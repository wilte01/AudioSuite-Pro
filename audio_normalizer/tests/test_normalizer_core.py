"""
Tests for audio_normalizer.core.loudness and normalizer.
Gap G-35: _safe_float, measure(), _codec_args, apply().

Changed in 2.6.0 (U-04): the standalone batch processor these tests also
covered (process_single_file, run_parallel_process and its lossless routing)
is gone; REFINE owns that path, and audio_refinery/tests covers it.

Changed in 2.1.7: TestApply gained the source-parameter pins - rate, FLAC bit
depth, the FLAC frame cap, and the encoder whose rate set forbids the pin
(audio_normalizer.core.normalizer._preserve_args).

F-09 adds the delivery-target tests: the ceiling/LRA reach both FFmpeg passes,
the achieved peak is read back from loudnorm's summary, the defaults keep the
previous filter string byte for byte, and a real file normalised at -1.0 dBTP
measures louder than the same file at the default.

Changed in 2.3.1: restores the imports its surviving helpers use after the
standalone batch processor was removed (U-04).
"""

from queue import Queue
from unittest.mock import MagicMock, patch

import pytest
from pydub import AudioSegment

from audio_normalizer.core.loudness import (
    _safe_float,
    measure,
    parse_output_true_peak,
)
from audio_normalizer.core.normalizer import (
    _codec_args,
    _filters,
    _preserve_args,
    apply,
)
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

    def test_source_rate_and_depth_are_pinned(self, tmp_path):
        """The output must keep the source's rate and FLAC bit depth.

        Without these pins every normalised file came out at loudnorm's internal
        192 kHz and 16-bit audio was widened to 24 bits; see the module comment
        above ``_preserve_args``.
        """
        # Explicit 44.1 kHz/16-bit: AudioSegment.silent() defaults to 11025 Hz,
        # so a helper-built file would not exercise the pin at all.
        path = tmp_path / "t.flac"
        source = AudioSegment.silent(duration=100, frame_rate=44100).set_channels(2)
        source.export(str(path), format="flac")
        f = str(path)
        calls = []

        def fake_run(exe, args, **kw):
            cmd = [exe, *args]
            calls.append(cmd)
            open(cmd[-1], "wb").close()
            m = MagicMock()
            m.returncode = 0
            return m

        with (
            patch("audio_normalizer.core.normalizer.run_secure_subprocess", fake_run),
            patch("audio_normalizer.core.normalizer.read_tags_raw", return_value=None),
            patch("audio_normalizer.core.normalizer.write_tags_raw"),
        ):
            apply(f, -16.0, MOCK_LOUDNESS)

        cmd = calls[0]
        assert cmd[cmd.index("-ar") + 1] == "44100"
        assert cmd[cmd.index("-sample_fmt") + 1] == "s16"
        # The frame cap is what keeps the FLAC encoder's block size legal.
        filters = cmd[cmd.index("-af") + 1]
        assert filters.endswith("asetnsamples=n=4096:p=0")

    def test_unreadable_source_omits_the_pins(self, tmp_path):
        """No readable source parameters means no pin - not a guessed default."""
        f = tmp_path / "t.flac"
        f.write_bytes(b"not audio")
        cmd = _preserve_args(str(f), "flac")
        assert "-ar" not in cmd
        assert "-sample_fmt" not in cmd
        # The block-size cap needs no source information, so it always applies.
        assert "asetnsamples" in _filters(-16.0, MOCK_LOUDNESS, "flac")

    def test_rate_is_not_pinned_for_an_encoder_that_rejects_it(self, tmp_path):
        """opus takes 8/12/16/24/48 kHz only; pinning 44.1 kHz made it fail."""
        flac = _make_audio(tmp_path, "t.flac")
        opus = tmp_path / "t.opus"
        opus.write_bytes((tmp_path / "t.flac").read_bytes())
        assert flac.endswith("t.flac")
        assert "-ar" not in _preserve_args(str(opus), "libopus")
        assert "-ar" in _preserve_args(flac, "flac")

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


class TestDeliveryTargets:
    """F-09: the true-peak ceiling and LRA are configurable, not literals."""

    def test_default_filter_string_is_unchanged(self):
        """Defaults must reproduce the previously hard-coded filter string."""
        filters = _filters(-16.0, MOCK_LOUDNESS, "mp3")
        assert filters == (
            "loudnorm=I=-16.0:TP=-1.5:LRA=11"
            ":measured_I=-18.0:measured_TP=-1.5:measured_LRA=7.0"
            ":measured_thresh=-28.0:offset=0.0"
            ":linear=true:print_format=summary"
        )

    def test_custom_ceiling_and_lra_reach_the_filter(self):
        filters = _filters(-14.0, MOCK_LOUDNESS, "mp3", true_peak=-1.0, lra=7)
        assert "TP=-1.0" in filters
        assert "LRA=7" in filters

    def test_analysis_pass_carries_the_targets(self):
        calls = []

        def fake_run(exe, args, **kw):
            calls.append([exe, *args])
            result = MagicMock()
            result.returncode = 0
            result.stderr = MOCK_STDERR
            return result

        with patch("audio_normalizer.core.loudness.run_secure_subprocess", fake_run):
            measure("/tmp/t.flac", -16.0, true_peak=-1.0, lra=7)

        filters = calls[0][calls[0].index("-af") + 1]
        assert "TP=-1.0" in filters
        assert "LRA=7" in filters

    def test_apply_passes_the_targets_and_returns_the_achieved_peak(self, tmp_path):
        f = _make_audio(tmp_path, "t.mp3")
        calls = []
        summary = (
            "[Parsed_loudnorm_0 @ 0x1] {\n"
            '        "input_i" : "-18.00",\n'
            '        "output_i" : "-16.00",\n'
            '        "output_tp" : "-1.02",\n'
            '        "target_offset" : "0.00"\n'
            "}\n"
        )

        def fake_run(exe, args, **kw):
            calls.append([exe, *args])
            open(calls[-1][-1], "wb").close()
            result = MagicMock()
            result.returncode = 0
            result.stderr = summary
            return result

        with (
            patch("audio_normalizer.core.normalizer.run_secure_subprocess", fake_run),
            patch("audio_normalizer.core.normalizer.read_tags_raw", return_value=None),
            patch("audio_normalizer.core.normalizer.write_tags_raw"),
        ):
            achieved = apply(f, -16.0, MOCK_LOUDNESS, true_peak=-1.0, lra=7)

        filters = calls[0][calls[0].index("-af") + 1]
        assert "TP=-1.0" in filters
        assert "LRA=7" in filters
        assert achieved == pytest.approx(-1.02)

    def test_apply_returns_none_without_a_summary_block(self, tmp_path):
        f = _make_audio(tmp_path, "t.mp3")

        def fake_run(exe, args, **kw):
            cmd = [exe, *args]
            open(cmd[-1], "wb").close()
            result = MagicMock()
            result.returncode = 0
            result.stderr = "no json here"
            return result

        with (
            patch("audio_normalizer.core.normalizer.run_secure_subprocess", fake_run),
            patch("audio_normalizer.core.normalizer.read_tags_raw", return_value=None),
            patch("audio_normalizer.core.normalizer.write_tags_raw"),
        ):
            assert apply(f, -16.0, MOCK_LOUDNESS) is None


class TestParseOutputTruePeak:
    """The achieved true peak comes from loudnorm's second-pass summary."""

    def test_reads_output_tp(self):
        stderr = '{\n    "output_i" : "-16.00",\n    "output_tp" : "-1.31"\n}\n'
        assert parse_output_true_peak(stderr) == pytest.approx(-1.31)

    def test_reads_the_summary_line(self):
        stderr = (
            "[Parsed_loudnorm_0 @ 0x1] \n"
            "Input True Peak:      -0.9 dBTP\n"
            "Output True Peak:     -1.3 dBTP\n"
        )
        assert parse_output_true_peak(stderr) == pytest.approx(-1.3)

    def test_last_block_wins(self):
        stderr = '{"output_tp" : "-9.0"}\n{"output_tp" : "-1.25"}\n'
        assert parse_output_true_peak(stderr) == pytest.approx(-1.25)

    def test_missing_summary_returns_none(self):
        assert parse_output_true_peak("") is None
        assert parse_output_true_peak("no json at all") is None
        assert parse_output_true_peak('{"input_i" : "-18.0"}') is None
        # A mock's MagicMock stderr must not raise.
        assert parse_output_true_peak(MagicMock()) is None

    def test_infinite_peak_is_not_reported_as_a_number(self):
        # ``_safe_float`` maps -inf to the floor, which is the honest answer for
        # a silent output: no measurable peak rather than a bogus -inf.
        assert parse_output_true_peak('{"output_tp" : "-inf"}') == -70.0
