"""
Tests for music_format_converter.core.ffmpeg_params (G-29 params matrix)
         music_format_converter.core.file_processor (G-29 pipeline)
"""

import contextlib
import json
import os
import subprocess
import threading
from queue import Queue
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydub import AudioSegment

from audio_suite_shared.error_recovery import RecoveryAction
from music_format_converter.core.ffmpeg_params import get_ffmpeg_params
from music_format_converter.core.file_processor import (
    _wav_params_for,
    process_single_file,
    run_conversion,
)
from music_format_converter.core.formats import LOSSY_FORMATS

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_audio(tmp_path, name="track.mp3"):
    path = tmp_path / name
    AudioSegment.silent(duration=100).export(str(path), format=name.split(".")[-1])
    return str(path)


def _make_slot_fixtures(n=4):
    slot_vars = [MagicMock() for _ in range(n)]
    slot_q = Queue()
    for i in range(n):
        slot_q.put(i)
    return slot_vars, slot_q


# ═════════════════════════════════════════════════════════════════════════════
# G-29a — get_ffmpeg_params
# ═════════════════════════════════════════════════════════════════════════════


class TestGetFfmpegParams:
    def test_returns_list(self):
        result = get_ffmpeg_params("/in/track.mp3", "/out/track.ogg", "ogg")
        assert isinstance(result, list)

    def test_all_elements_are_strings(self):
        result = get_ffmpeg_params("/in/track.mp3", "/out/track.ogg", "ogg")
        assert all(isinstance(s, str) for s in result)

    def test_starts_with_ffmpeg(self):
        result = get_ffmpeg_params("/in/t.mp3", "/out/t.ogg", "ogg")
        assert result[0] == "ffmpeg"

    def test_input_path_in_command(self):
        result = get_ffmpeg_params("/music/track.mp3", "/out/track.ogg", "ogg")
        assert "/music/track.mp3" in result

    def test_output_path_last_element(self):
        result = get_ffmpeg_params("/in/t.mp3", "/out/t.ogg", "ogg")
        assert result[-1] == "/out/t.ogg"

    def test_hides_banner(self):
        result = get_ffmpeg_params("/in/t.mp3", "/out/t.ogg", "ogg")
        assert "-hide_banner" in result

    def test_overwrite_flag_present(self):
        result = get_ffmpeg_params("/in/t.mp3", "/out/t.ogg", "ogg")
        assert "-y" in result

    @pytest.mark.parametrize(
        "fmt,expected_codec",
        [
            ("mp3", "libmp3lame"),
            ("aac", "aac"),
            ("m4a", "aac"),
            ("ogg", "libvorbis"),
            ("opus", "libopus"),
            ("flac", "flac"),
            ("wav", "pcm_s16le"),
            ("alac", "alac"),
            ("wma", "wmav2"),
            ("wv", "wavpack"),
            ("mp4", "aac"),
            ("aiff", "pcm_s24be"),
            ("aif", "pcm_s24be"),
        ],
    )
    def test_correct_codec_per_format(self, fmt, expected_codec):
        result = get_ffmpeg_params("/in/t.flac", f"/out/t.{fmt}", fmt)
        assert expected_codec in result

    @pytest.mark.parametrize(
        "depth,expected",
        [
            ("16", "pcm_s16le"),
            ("24", "pcm_s24le"),
            ("32", "pcm_s32le"),
            ("float", "pcm_f32le"),
        ],
    )
    def test_wav_depth_override(self, depth, expected):
        """Explicit wav_depth override wins regardless of the source."""
        result = get_ffmpeg_params("/in/t.flac", "/out/t.wav", "wav", wav_depth=depth)
        assert expected in result

    @pytest.mark.parametrize(
        "sample_fmt,bits,expected",
        [
            ("s32", 24, "pcm_s24le"),  # 24-bit FLAC decodes to s32, raw 24
            ("s32", 32, "pcm_s32le"),
            ("s16", 16, "pcm_s16le"),
            ("flt", 32, "pcm_f32le"),
            ("fltp", 0, "pcm_f32le"),
            ("dblp", 64, "pcm_f64le"),
            (None, 0, "pcm_s16le"),  # unprobed/unknown -> historical default
        ],
    )
    def test_wav_auto_preserves_source_depth(self, sample_fmt, bits, expected):
        result = get_ffmpeg_params(
            "/in/t.flac",
            "/out/t.wav",
            "wav",
            wav_depth="auto",
            source_sample_fmt=sample_fmt,
            source_bits_per_sample=bits,
        )
        assert expected in result

    @pytest.mark.parametrize(
        "quality,expected",
        [
            ("highest", "0"),  # VBR V0 for mp3
            ("high", "2"),  # VBR V2
            ("medium", "192k"),
        ],
    )
    def test_mp3_quality_settings(self, quality, expected):
        result = get_ffmpeg_params("/in/t.flac", "/out/t.mp3", "mp3", quality=quality)
        assert expected in result

    @pytest.mark.parametrize(
        "quality,expected_bitrate",
        [
            ("highest", "256k"),
            ("high", "192k"),
            ("medium", "128k"),
        ],
    )
    def test_opus_quality_settings(self, quality, expected_bitrate):
        result = get_ffmpeg_params("/in/t.flac", "/out/t.opus", "opus", quality=quality)
        assert expected_bitrate in result

    @pytest.mark.parametrize(
        "quality,expected_bitrate",
        [
            ("highest", "320k"),
            ("high", "256k"),
            ("medium", "192k"),
        ],
    )
    def test_wma_quality_settings(self, quality, expected_bitrate):
        result = get_ffmpeg_params("/in/t.flac", "/out/t.wma", "wma", quality=quality)
        assert expected_bitrate in result
        assert "wmav2" in result

    @pytest.mark.parametrize(
        "quality,expected_bitrate",
        [
            ("highest", "320k"),
            ("high", "256k"),
            ("medium", "192k"),
        ],
    )
    def test_aac_quality_settings(self, quality, expected_bitrate):
        result = get_ffmpeg_params("/in/t.flac", "/out/t.aac", "aac", quality=quality)
        assert expected_bitrate in result
        assert "-strict" in result
        assert "experimental" in result

    @pytest.mark.parametrize(
        "quality,expected_bitrate",
        [
            ("highest", "320k"),
            ("high", "256k"),
            ("medium", "192k"),
        ],
    )
    def test_m4a_quality_settings(self, quality, expected_bitrate):
        result = get_ffmpeg_params("/in/t.flac", "/out/t.m4a", "m4a", quality=quality)
        assert expected_bitrate in result
        assert "-vn" in result
        assert "-strict" in result
        assert "experimental" in result

    @pytest.mark.parametrize(
        "quality,expected_q",
        [
            ("highest", "10"),
            ("high", "8"),
            ("medium", "6"),
        ],
    )
    def test_ogg_quality_settings(self, quality, expected_q):
        result = get_ffmpeg_params("/in/t.flac", "/out/t.ogg", "ogg", quality=quality)
        assert expected_q in result
        assert "libvorbis" in result

    @pytest.mark.parametrize(
        "quality,expected_bitrate",
        [
            ("highest", "320k"),
            ("high", "256k"),
            ("medium", "192k"),
        ],
    )
    def test_mp4_quality_settings(self, quality, expected_bitrate):
        result = get_ffmpeg_params("/in/t.flac", "/out/t.mp4", "mp4", quality=quality)
        assert expected_bitrate in result
        assert "-vn" in result
        assert "-strict" in result
        assert "experimental" in result

    @pytest.mark.parametrize(
        "quality,expected_codec",
        [
            ("highest", "pcm_s24be"),
            ("high", "pcm_s24be"),
            ("medium", "pcm_s16be"),
        ],
    )
    def test_aiff_quality_settings(self, quality, expected_codec):
        """AIFF uses big-endian PCM: s24be at the best tiers, s16be below."""
        result = get_ffmpeg_params("/in/t.flac", "/out/t.aiff", "aiff", quality=quality)
        assert expected_codec in result

    @pytest.mark.parametrize(
        "fmt",
        ["aiff", "aif"],
    )
    def test_aiff_extensions_share_codec_policy(self, fmt):
        result = get_ffmpeg_params("/in/t.flac", f"/out/t.{fmt}", fmt, quality="high")
        assert "pcm_s24be" in result
        assert result[-1].endswith(f".{fmt}")

    def test_low_quality_equals_medium(self):
        """'low' falls to the else-branch in every format, same as 'medium'."""
        for fmt in ("mp3", "aac", "m4a", "ogg", "opus", "wma", "mp4", "aiff", "aif"):
            r_low = get_ffmpeg_params("/in/t.flac", f"/out/t.{fmt}", fmt, quality="low")
            r_med = get_ffmpeg_params(
                "/in/t.flac", f"/out/t.{fmt}", fmt, quality="medium"
            )
            assert r_low == r_med

    def test_wv_has_no_bitrate_flag(self):
        """WavPack is lossless; -b:a is meaningless for it and must not appear."""
        result = get_ffmpeg_params("/in/t.flac", "/out/t.wv", "wv")
        assert "wavpack" in result
        assert "-b:a" not in result

    def test_mp3_has_id3v2_version_flag(self):
        result = get_ffmpeg_params("/in/t.flac", "/out/t.mp3", "mp3")
        assert "-id3v2_version" in result

    def test_flac_has_compression_level(self):
        result = get_ffmpeg_params("/in/t.mp3", "/out/t.flac", "flac")
        assert "-compression_level" in result

    @pytest.mark.parametrize(
        "sample_rate",
        ["44100", "48000", "88200", "96000", "176400", "192000"],
    )
    def test_sample_rate_override_injects_ar(self, sample_rate):
        """A numeric sample rate must produce `-ar <rate>` in every format."""
        for fmt in ("mp3", "flac", "wav", "ogg", "opus"):
            result = get_ffmpeg_params(
                "/in/t.flac", f"/out/t.{fmt}", fmt, sample_rate=sample_rate
            )
            assert sample_rate in result
            assert "-ar" in result

    def test_sample_rate_default_source_omits_ar(self):
        """Default 'source' keeps the input rate — no `-ar` flag."""
        for fmt in ("mp3", "flac", "wav", "ogg"):
            result = get_ffmpeg_params("/in/t.flac", f"/out/t.{fmt}", fmt)
            assert "-ar" not in result

    def test_sample_rate_source_explicit_omits_ar(self):
        result = get_ffmpeg_params(
            "/in/t.flac", "/out/t.flac", "flac", sample_rate="source"
        )
        assert "-ar" not in result

    def test_sample_rate_with_wav_keeps_s16_codec(self):
        """Sample rate and bit depth are independent flags — a sample-rate
        override must not disturb the WAV PCM codec selection."""
        result = get_ffmpeg_params(
            "/in/t.flac", "/out/t.wav", "wav", sample_rate="48000"
        )
        assert "pcm_s16le" in result
        assert "48000" in result

    def test_map_metadata_flags_present(self):
        result = get_ffmpeg_params("/in/t.mp3", "/out/t.ogg", "ogg")
        assert "-map_metadata" in result

    def test_truly_unknown_format_uses_copy_codec(self):
        """Formats with no dedicated branch (and not wma/wv, which now have
        real encoders) still fall back to stream copy."""
        result = get_ffmpeg_params("/in/t.xyz", "/out/t.xyz", "xyz")
        assert "copy" in result

    def test_default_quality_is_highest(self):
        r_default = get_ffmpeg_params("/in/t.flac", "/out/t.mp3", "mp3")
        r_highest = get_ffmpeg_params(
            "/in/t.flac", "/out/t.mp3", "mp3", quality="highest"
        )
        assert r_default == r_highest


# ═════════════════════════════════════════════════════════════════════════════
# G-29b — process_single_file
# ═════════════════════════════════════════════════════════════════════════════


class TestProcessSingleFile:
    def _call(
        self,
        tmp_path,
        filename,
        output_format="ogg",
        is_dry_run=True,
        delete_original=False,
        on_progress=None,
    ):
        slot_vars, slot_q = _make_slot_fixtures()
        lock = threading.Lock()
        results = []
        cb = on_progress or (lambda **kw: results.append(kw))

        process_single_file(
            filename=filename,
            input_dir=str(tmp_path),
            output_dir=str(tmp_path / "out"),
            output_format=output_format,
            quality="highest",
            delete_original=delete_original,
            is_dry_run=is_dry_run,
            lossy_formats=LOSSY_FORMATS,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            lock=lock,
            on_progress=cb,
        )
        return results, slot_q

    def test_slot_returned_after_dry_run(self, tmp_path):
        _make_audio(tmp_path, "track.mp3")
        _, slot_q = self._call(tmp_path, "track.mp3", is_dry_run=True)
        assert slot_q.qsize() == 4

    def test_dry_run_reports_dry_run_status(self, tmp_path):
        _make_audio(tmp_path, "track.mp3")
        results, _ = self._call(tmp_path, "track.mp3", is_dry_run=True)
        assert any("DRY RUN" in r.get("display_text", "") for r in results)

    def test_dry_run_converted_count_one(self, tmp_path):
        _make_audio(tmp_path, "track.mp3")
        results, _ = self._call(tmp_path, "track.mp3", is_dry_run=True)
        assert any(r.get("n_converted") == 1 for r in results)

    def test_lossy_to_lossless_skipped(self, tmp_path):
        _make_audio(tmp_path, "track.mp3")
        results, _ = self._call(
            tmp_path, "track.mp3", output_format="flac", is_dry_run=True
        )
        assert any(r.get("n_skipped") == 1 for r in results)

    def test_same_format_skipped(self, tmp_path):
        """Same-format 'conversion' must be cleanly skipped, not attempted
        via FFmpeg (which fails with 'Output same as Input' when the
        output directory defaults to the input directory)."""
        _make_audio(tmp_path, "track.mp3")
        results, _ = self._call(
            tmp_path, "track.mp3", output_format="mp3", is_dry_run=True
        )
        assert any(r.get("n_skipped") == 1 for r in results)
        assert any(r.get("n_converted", 0) == 0 for r in results)

    def test_unsupported_extension_reports_error(self, tmp_path):
        (tmp_path / "file.xyz").write_bytes(b"x")
        results, _ = self._call(tmp_path, "file.xyz", is_dry_run=True)
        assert any(r.get("n_errors", 0) == 1 for r in results)

    def test_slot_returned_on_skip(self, tmp_path):
        _make_audio(tmp_path, "track.mp3")
        _, slot_q = self._call(
            tmp_path, "track.mp3", output_format="flac", is_dry_run=True
        )
        assert slot_q.qsize() == 4

    def test_live_conversion_calls_ffmpeg(self, tmp_path):
        (tmp_path / "out").mkdir()
        _make_audio(tmp_path, "track.flac")
        results = []
        mock_result = MagicMock()
        mock_result.returncode = 0

        def fake_run(executable, args, **kw):
            # Create dummy output file
            cmd = [executable, *args]
            out_path = cmd[-1]
            open(out_path, "wb").close()
            return mock_result

        with patch(
            "music_format_converter.core.file_processor.run_secure_subprocess", fake_run
        ):
            self._call(
                tmp_path,
                "track.flac",
                output_format="mp3",
                is_dry_run=False,
                on_progress=lambda **kw: results.append(kw),
            )

        assert any("CONVERTED" in r.get("display_text", "") for r in results)

    def _run_live_wav(
        self,
        tmp_path,
        filename,
        probe_stream=None,
        probe_ok=True,
        override=None,
        on_progress=None,
    ):
        """Convert filename to WAV live, mocking ffprobe + ffmpeg.

        Returns (seen_commands, progress_results).
        """
        (tmp_path / "out").mkdir(exist_ok=True)
        _make_audio(tmp_path, filename)
        seen: dict[str, list[object]] = {"cmds": []}
        result_ok = MagicMock()
        result_ok.returncode = 0

        def fake_run(executable, args, **kw):
            cmd = [executable, *args]
            seen["cmds"].append(cmd)
            if cmd[0] == "ffprobe":
                probe = MagicMock()
                probe.returncode = 0 if probe_ok else 1
                probe.stdout = (
                    json.dumps({"streams": [probe_stream]})
                    if probe_ok and probe_stream
                    else ""
                )
                return probe
            open(cmd[-1], "wb").close()
            return result_ok

        patches: list[Any] = [
            patch(
                "music_format_converter.core.file_processor.run_secure_subprocess",
                fake_run,
            )
        ]
        if override is not None:
            patches.append(
                patch(
                    "music_format_converter.core.file_processor.load_value",
                    return_value=override,
                )
            )

        results = []
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            self._call(
                tmp_path,
                filename,
                output_format="wav",
                is_dry_run=False,
                on_progress=on_progress or (lambda **kw: results.append(kw)),
            )
        return seen, results

    def test_wav_preserves_24bit_flac_depth(self, tmp_path):
        """24-bit FLAC source -> pcm_s24le on WAV output (plan's core case)."""
        seen, results = self._run_live_wav(
            tmp_path,
            "track.flac",
            probe_stream={"sample_fmt": "s32", "bits_per_raw_sample": 24},
        )
        ffmpeg_cmd = next(c for c in seen["cmds"] if c[0] == "ffmpeg")
        assert "pcm_s24le" in ffmpeg_cmd
        assert any("CONVERTED" in r.get("display_text", "") for r in results)

    def test_wav_params_lossy_source_keeps_16_bit_default(self):
        """Lossy sources (rejected for WAV output live) yield no hint kwargs."""
        with patch(
            "music_format_converter.core.file_processor.run_secure_subprocess"
        ) as mock_run:
            kwargs = _wav_params_for("/in/track.mp3", "mp3", "wav")
        mock_run.assert_not_called()
        assert kwargs == {}
        cmd = get_ffmpeg_params("/in/track.mp3", "/out/track.wav", "wav", **kwargs)
        assert "pcm_s16le" in cmd

    def test_wav_params_explicit_bit_depth_wins(self):
        """A user-chosen explicit bit depth beats lossy short-circuit and
        config override, with no probe."""
        with (
            patch(
                "music_format_converter.core.file_processor.run_secure_subprocess"
            ) as mock_run,
            patch(
                "music_format_converter.core.file_processor.load_value",
                return_value="24",
            ),
        ):
            kwargs = _wav_params_for("/in/track.mp3", "mp3", "wav", bit_depth="16")
        mock_run.assert_not_called()
        assert kwargs == {"wav_depth": "16"}

    def test_wav_params_auto_still_reads_config_override(self):
        """'auto' keeps legacy behaviour: a config override still wins."""
        with (
            patch(
                "music_format_converter.core.file_processor.run_secure_subprocess"
            ) as mock_run,
            patch(
                "music_format_converter.core.file_processor.load_value",
                return_value="24",
            ),
        ):
            kwargs = _wav_params_for("/in/track.flac", "flac", "wav")
        mock_run.assert_not_called()
        assert kwargs == {"wav_depth": "24"}

    def test_wav_params_override_beats_lossy_short_circuit(self):
        """A concrete override wins even for a lossy source, with no probe."""
        with (
            patch(
                "music_format_converter.core.file_processor.run_secure_subprocess"
            ) as mock_run,
            patch(
                "music_format_converter.core.file_processor.load_value",
                return_value="24",
            ),
        ):
            kwargs = _wav_params_for("/in/track.mp3", "mp3", "wav")
        mock_run.assert_not_called()
        assert kwargs == {"wav_depth": "24"}

    def test_wav_override_respected_for_lossless_source(self, tmp_path):
        """Shared-config wav_bit_depth override beats a 24-bit FLAC probe."""
        seen, _ = self._run_live_wav(
            tmp_path,
            "track.flac",
            probe_stream={"sample_fmt": "s32", "bits_per_raw_sample": 24},
            override="16",
        )
        assert len(seen["cmds"]) == 1  # override short-circuits the probe
        assert "pcm_s16le" in seen["cmds"][0]

    def test_wav_probe_failure_falls_back_to_16bit(self, tmp_path):
        """Unreadable source must not fail the job; WAV falls back to 16-bit."""
        seen, results = self._run_live_wav(tmp_path, "track.flac", probe_ok=False)
        ffmpeg_cmd = next(c for c in seen["cmds"] if c[0] == "ffmpeg")
        assert "pcm_s16le" in ffmpeg_cmd
        assert any("CONVERTED" in r.get("display_text", "") for r in results)

    def _run_live(
        self, tmp_path, filename, output_format, sample_rate="source", bit_depth="auto"
    ):
        """Convert filename live, mocking subprocess.run; captures the ffmpeg cmd."""
        (tmp_path / "out").mkdir(exist_ok=True)
        _make_audio(tmp_path, filename)
        seen: dict[str, list[object]] = {"cmds": []}
        result_ok = MagicMock()
        result_ok.returncode = 0

        def fake_run(executable, args, **kw):
            cmd = [executable, *args]
            seen["cmds"].append(cmd)
            open(cmd[-1], "wb").close()
            return result_ok

        results = []
        slot_vars, slot_q = _make_slot_fixtures()
        lock = threading.Lock()
        with patch(
            "music_format_converter.core.file_processor.run_secure_subprocess", fake_run
        ):
            process_single_file(
                filename=filename,
                input_dir=str(tmp_path),
                output_dir=str(tmp_path / "out"),
                output_format=output_format,
                quality="highest",
                delete_original=False,
                is_dry_run=False,
                lossy_formats=LOSSY_FORMATS,
                slot_vars=slot_vars,
                slot_queue=slot_q,
                lock=lock,
                on_progress=lambda **kw: results.append(kw),
                sample_rate=sample_rate,
                bit_depth=bit_depth,
            )
        return seen, results

    def test_live_conversion_passes_sample_rate(self, tmp_path):
        """The `-ar` flag must reach the real ffmpeg command."""
        seen, results = self._run_live(
            tmp_path, "track.flac", "mp3", sample_rate="48000"
        )
        ffmpeg_cmd = next(c for c in seen["cmds"] if c[0] == "ffmpeg")
        assert "48000" in ffmpeg_cmd
        assert "-ar" in ffmpeg_cmd
        assert any("CONVERTED" in r.get("display_text", "") for r in results)

    def test_live_conversion_source_rate_no_ar(self, tmp_path):
        seen, results = self._run_live(
            tmp_path, "track.flac", "mp3", sample_rate="source"
        )
        ffmpeg_cmd = next(c for c in seen["cmds"] if c[0] == "ffmpeg")
        assert "-ar" not in ffmpeg_cmd
        assert any("CONVERTED" in r.get("display_text", "") for r in results)

    def test_live_conversion_bit_depth_applies_to_wav(self, tmp_path):
        """WAV + explicit bit depth 24 → pcm_s24le in the real command."""
        seen, results = self._run_live(tmp_path, "track.flac", "wav", bit_depth="24")
        ffmpeg_cmd = next(c for c in seen["cmds"] if c[0] == "ffmpeg")
        assert "pcm_s24le" in ffmpeg_cmd
        assert any("CONVERTED" in r.get("display_text", "") for r in results)

    def test_ffmpeg_failure_reports_error(self, tmp_path):
        (tmp_path / "out").mkdir()
        _make_audio(tmp_path, "track.flac")
        results = []
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error: codec not found"

        with patch(
            "music_format_converter.core.file_processor.run_secure_subprocess",
            return_value=mock_result,
        ):
            self._call(
                tmp_path,
                "track.flac",
                output_format="mp3",
                is_dry_run=False,
                on_progress=lambda **kw: results.append(kw),
            )

        assert any(r.get("n_errors", 0) >= 1 for r in results)

    def test_timeout_reports_error(self, tmp_path):
        (tmp_path / "out").mkdir()
        _make_audio(tmp_path, "track.flac")
        results = []
        with patch(
            "music_format_converter.core.file_processor.run_secure_subprocess",
            side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=300),
        ):
            self._call(
                tmp_path,
                "track.flac",
                output_format="mp3",
                is_dry_run=False,
                on_progress=lambda **kw: results.append(kw),
            )
        assert any(r.get("n_errors", 0) >= 1 for r in results)

    def test_delete_original_on_success(self, tmp_path):
        (tmp_path / "out").mkdir()
        _make_audio(tmp_path, "track.flac")
        src_path = os.path.join(str(tmp_path), "track.flac")
        results = []
        mock_result = MagicMock()
        mock_result.returncode = 0

        def fake_run(executable, args, **kw):
            cmd = [executable, *args]
            out_path = cmd[-1]
            open(out_path, "wb").close()
            return mock_result

        with patch(
            "music_format_converter.core.file_processor.run_secure_subprocess", fake_run
        ):
            self._call(
                tmp_path,
                "track.flac",
                output_format="mp3",
                is_dry_run=False,
                delete_original=True,
                on_progress=lambda **kw: results.append(kw),
            )

        assert not os.path.exists(src_path)
        assert any("ORIGINAL DELETED" in r.get("display_text", "") for r in results)

    def test_delete_original_failure_reported(self, tmp_path):
        (tmp_path / "out").mkdir()
        _make_audio(tmp_path, "track.flac")
        results = []
        mock_result = MagicMock()
        mock_result.returncode = 0

        def fake_run(executable, args, **kw):
            cmd = [executable, *args]
            out_path = cmd[-1]
            open(out_path, "wb").close()
            return mock_result

        with (
            patch(
                "music_format_converter.core.file_processor.run_secure_subprocess",
                fake_run,
            ),
            patch(
                "music_format_converter.core.file_processor.os.remove",
                side_effect=PermissionError("Access denied"),
            ),
        ):
            self._call(
                tmp_path,
                "track.flac",
                output_format="mp3",
                is_dry_run=False,
                delete_original=True,
                on_progress=lambda **kw: results.append(kw),
            )

        assert any("DELETE FAILED" in r.get("display_text", "") for r in results)

    def test_recovery_action_skip_on_error(self, tmp_path):
        (tmp_path / "out").mkdir()
        _make_audio(tmp_path, "track.flac")
        results = []

        with (
            patch(
                "music_format_converter.core.file_processor.run_secure_subprocess",
                side_effect=OSError("ffmpeg crash"),
            ),
            patch(
                "music_format_converter.core.file_processor.get_recovery_action",
                return_value=RecoveryAction.SKIP,
            ),
        ):
            self._call(
                tmp_path,
                "track.flac",
                output_format="mp3",
                is_dry_run=False,
                on_progress=lambda **kw: results.append(kw),
            )

        assert any(r.get("n_skipped", 0) >= 1 for r in results)
        assert any("SKIP" in r.get("display_text", "") for r in results)


# ═════════════════════════════════════════════════════════════════════════════
# G-29b — run_conversion
# ═════════════════════════════════════════════════════════════════════════════


class TestRunConversion:
    def _run(self, tmp_path, output_format="ogg", is_dry_run=True):
        slot_vars, slot_q = _make_slot_fixtures()
        progress, complete, errors = [], [], []
        (tmp_path / "out").mkdir(exist_ok=True)

        run_conversion(
            input_dir=str(tmp_path),
            output_dir=str(tmp_path / "out"),
            output_format=output_format,
            quality="highest",
            delete_originals=False,
            is_dry_run=is_dry_run,
            lossy_formats=LOSSY_FORMATS,
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

    def test_on_complete_called_with_total(self, tmp_path):
        for i in range(3):
            _make_audio(tmp_path, f"t{i}.flac")
        _, complete, _ = self._run(tmp_path, output_format="mp3")
        assert len(complete) == 1
        assert complete[0]["total"] == 3

    def test_on_progress_called_per_file(self, tmp_path):
        for i in range(3):
            _make_audio(tmp_path, f"t{i}.flac")
        progress, _, _ = self._run(tmp_path, output_format="mp3")
        assert len(progress) == 3

    def test_lossy_to_lossless_counted_as_skipped(self, tmp_path):
        for i in range(2):
            _make_audio(tmp_path, f"t{i}.mp3")
        _, complete, _ = self._run(tmp_path, output_format="flac")
        assert complete[0]["skipped"] == 2

    def test_duration_in_complete(self, tmp_path):
        _make_audio(tmp_path, "t.flac")
        _, complete, _ = self._run(tmp_path, output_format="mp3")
        assert complete[0]["duration_secs"] >= 0

    def test_output_dir_in_complete(self, tmp_path):
        _make_audio(tmp_path, "t.flac")
        _, complete, _ = self._run(tmp_path, output_format="mp3")
        assert "output_dir" in complete[0]

    def test_non_audio_files_excluded(self, tmp_path):
        (tmp_path / "cover.jpg").write_bytes(b"x")
        (tmp_path / "notes.txt").write_bytes(b"x")
        _make_audio(tmp_path, "t.flac")
        _, complete, _ = self._run(tmp_path, output_format="mp3")
        assert complete[0]["total"] == 1

    def test_output_directory_created_when_different(self, tmp_path):
        out_dir = tmp_path / "custom_out"
        _make_audio(tmp_path, "t.flac")
        slot_vars, slot_q = _make_slot_fixtures()
        progress, complete, errors = [], [], []

        run_conversion(
            input_dir=str(tmp_path),
            output_dir=str(out_dir),
            output_format="mp3",
            quality="highest",
            delete_originals=False,
            is_dry_run=False,
            lossy_formats=LOSSY_FORMATS,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            on_progress=lambda **kw: progress.append(kw),
            on_complete=lambda **kw: complete.append(kw),
            on_error=lambda msg: errors.append(msg),
        )

        assert out_dir.exists()

    def test_directory_scan_error_calls_on_error(self, tmp_path):
        slot_vars, slot_q = _make_slot_fixtures()
        errors = []

        with patch(
            "music_format_converter.core.file_processor.os.scandir",
            side_effect=PermissionError("access denied"),
        ):
            run_conversion(
                input_dir=str(tmp_path),
                output_dir=str(tmp_path / "out"),
                output_format="mp3",
                quality="highest",
                delete_originals=False,
                is_dry_run=False,
                lossy_formats=LOSSY_FORMATS,
                slot_vars=slot_vars,
                slot_queue=slot_q,
                on_progress=lambda **kw: None,
                on_complete=lambda **kw: None,
                on_error=lambda msg: errors.append(msg),
            )

        assert len(errors) == 1


# ═════════════════════════════════════════════════════════════════════════════
# Lossless gain post-conversion
# ═════════════════════════════════════════════════════════════════════════════


class TestNormalizeMp3PostConversion:
    def _call(
        self,
        tmp_path,
        filename,
        output_format="mp3",
        is_dry_run=False,
        normalize_mp3=True,
        on_progress=None,
        measure_result="-20.0",
    ):
        (tmp_path / "out").mkdir(exist_ok=True)
        _make_audio(tmp_path, filename)
        slot_vars, slot_q = _make_slot_fixtures()
        lock = threading.Lock()
        results = []
        cb = on_progress or (lambda **kw: results.append(kw))
        result_ok = MagicMock()
        result_ok.returncode = 0

        def fake_run(executable, args, **kw):
            cmd = [executable, *args]
            if cmd[0] == "ffmpeg" and cmd[-1] == "-":
                # loudnorm measurement pass
                data = {
                    "input_i": measure_result,
                    "input_tp": -2.0,
                    "input_lra": 11.0,
                    "input_thresh": -30.0,
                }
                probe = MagicMock()
                probe.returncode = 0
                probe.stderr = json.dumps(data)
                return probe
            open(cmd[-1], "wb").close()
            return result_ok

        with patch(
            "music_format_converter.core.file_processor.run_secure_subprocess", fake_run
        ):
            process_single_file(
                filename=filename,
                input_dir=str(tmp_path),
                output_dir=str(tmp_path / "out"),
                output_format=output_format,
                quality="highest",
                delete_original=False,
                is_dry_run=is_dry_run,
                lossy_formats=LOSSY_FORMATS,
                slot_vars=slot_vars,
                slot_queue=slot_q,
                lock=lock,
                on_progress=cb,
                normalize_mp3=normalize_mp3,
                target_lufs=-16.0,
            )
        return results

    def test_mp3_gain_applied(self, tmp_path, monkeypatch):
        applied = []

        def fake_apply(path, delta):
            applied.append((path, delta))
            return 100

        monkeypatch.setattr(
            "music_format_converter.core.file_processor.apply_track_gain", fake_apply
        )
        results = self._call(tmp_path, "track.flac", measure_result="-20.0")
        assert len(applied) == 1
        assert applied[0][1] == pytest.approx(4.0, abs=0.1)
        assert any("GAIN APPLIED" in r.get("display_text", "") for r in results)

    def test_non_mp3_output_no_gain(self, tmp_path, monkeypatch):
        applied = []
        monkeypatch.setattr(
            "music_format_converter.core.file_processor.apply_track_gain",
            lambda path, delta: applied.append((path, delta)),
        )
        self._call(tmp_path, "track.flac", output_format="ogg", measure_result="-20.0")
        assert applied == []

    def test_flag_off_no_gain(self, tmp_path, monkeypatch):
        applied = []
        monkeypatch.setattr(
            "music_format_converter.core.file_processor.apply_track_gain",
            lambda path, delta: applied.append((path, delta)),
        )
        results = self._call(
            tmp_path, "track.flac", normalize_mp3=False, measure_result="-20.0"
        )
        assert applied == []
        assert not any("GAIN" in r.get("display_text", "") for r in results)

    def test_within_tolerance_no_gain(self, tmp_path, monkeypatch):
        applied = []
        monkeypatch.setattr(
            "music_format_converter.core.file_processor.apply_track_gain",
            lambda path, delta: applied.append((path, delta)),
        )
        results = self._call(tmp_path, "track.flac", measure_result="-16.2")
        assert applied == []
        assert any("ALREADY AT" in r.get("display_text", "") for r in results)

    def test_measurement_failure_reports_gain_failed(self, tmp_path, monkeypatch):
        applied = []
        monkeypatch.setattr(
            "music_format_converter.core.file_processor.apply_track_gain",
            lambda path, delta: applied.append((path, delta)),
        )
        results = self._call(tmp_path, "track.flac", measure_result="__no_json__")
        assert applied == []
        assert any("GAIN FAILED" in r.get("display_text", "") for r in results)
        assert any(r.get("n_converted", 0) == 1 for r in results)

    def test_dry_run_reports_would_normalize(self, tmp_path, monkeypatch):
        applied = []
        monkeypatch.setattr(
            "music_format_converter.core.file_processor.apply_track_gain",
            lambda path, delta: applied.append((path, delta)),
        )
        results = self._call(tmp_path, "track.flac", is_dry_run=True)
        assert applied == []
        assert any("WOULD NORMALIZE MP3" in r.get("display_text", "") for r in results)

    def test_gain_error_reported_but_conversion_kept(self, tmp_path, monkeypatch):
        from audio_suite_shared.exceptions import AudioFormatError

        def boom(path, delta):
            raise AudioFormatError("no frames")

        monkeypatch.setattr(
            "music_format_converter.core.file_processor.apply_track_gain", boom
        )
        results = self._call(tmp_path, "track.flac", measure_result="-20.0")
        assert any("GAIN FAILED" in r.get("display_text", "") for r in results)
        assert any(r.get("n_converted", 0) == 1 for r in results)


# ═════════════════════════════════════════════════════════════════════════════
# E1 (decision D1 option A) — TPDF dither + soxr resampling
# ═════════════════════════════════════════════════════════════════════════════


def _filter_for(**kwargs) -> str | None:
    """Return the -af value of the built command, or None when absent."""
    cmd = get_ffmpeg_params("/in/t.flac", "/out/t.wav", **kwargs)
    return cmd[cmd.index("-af") + 1] if "-af" in cmd else None


class TestAresampleFilterPolicy:
    """The four dither/resampler combinations, plus the stream-copy guard.

    Measured rationale (plan E1 Decision Log): a bare 24->16 bit reduction
    leaves a correlated quantisation spur ~12 dB above the noise floor, while
    `dither_method=triangular` flattens it; and a bare `-ar` leaks only ~10 dB
    down at 22 kHz into a 44.1 kHz target, while `resampler=soxr` suppresses
    the same tone by ~99 dB.
    """

    def test_dither_and_resample_combined(self):
        assert (
            _filter_for(output_format="wav", wav_depth="16", sample_rate="48000")
            == "aresample=resampler=soxr:dither_method=triangular"
        )

    def test_resample_only_when_dither_disabled(self):
        assert (
            _filter_for(
                output_format="wav", wav_depth="16", sample_rate="48000", dither=False
            )
            == "aresample=resampler=soxr"
        )

    def test_dither_only_at_source_sample_rate(self):
        assert (
            _filter_for(output_format="wav", wav_depth="16", sample_rate="source")
            == "aresample=dither_method=triangular"
        )

    def test_no_filter_at_source_rate_without_dither(self):
        """--no-dither at the source rate must add no filter at all."""
        assert (
            _filter_for(
                output_format="wav", wav_depth="16", sample_rate="source", dither=False
            )
            is None
        )

    def test_dither_applies_to_aiff_both_depth_tiers(self):
        for quality in ("highest", "high", "medium", "low"):
            assert _filter_for(output_format="aiff", quality=quality) == (
                "aresample=dither_method=triangular"
            )

    def test_dither_applies_to_aif_alias(self):
        assert _filter_for(output_format="aif", quality="medium") == (
            "aresample=dither_method=triangular"
        )

    def test_resample_applies_to_lossy_targets(self):
        """soxr is a rate conversion, not a depth policy: every target gets it."""
        for fmt in ("mp3", "aac", "m4a", "ogg", "opus", "flac", "wma", "wv"):
            assert _filter_for(output_format=fmt, sample_rate="96000") == (
                "aresample=resampler=soxr"
            ), fmt

    def test_no_dither_filter_for_lossy_targets(self):
        """Lossy targets have no selectable PCM depth, so no dither term."""
        for fmt in ("mp3", "flac", "ogg"):
            assert _filter_for(output_format=fmt, sample_rate="source") is None, fmt

    def test_no_filter_for_stream_copy_even_with_rate_change(self):
        """A copied stream cannot be filtered; -af there would fail the run."""
        assert _filter_for(output_format="ape", sample_rate="48000") is None

    def test_dither_true_is_the_default(self):
        assert _filter_for(output_format="wav", wav_depth="16") == _filter_for(
            output_format="wav", wav_depth="16", dither=True
        )

    def test_no_dither_reproduces_the_pre_e1_command_line(self):
        """The documented opt-out must be byte-for-byte the old command."""
        legacy = get_ffmpeg_params(
            "/in/t.flac", "/out/t.wav", "wav", wav_depth="16", dither=False
        )
        expected = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "/in/t.flac",
            "-y",
            "-codec:a",
            "pcm_s16le",
            "-map",
            "0:a",
            "-map_metadata",
            "0",
            "-map_metadata:s:a",
            "0:s:a",
            "/out/t.wav",
        ]
        assert legacy == expected

    def test_filter_precedes_the_output_path(self):
        cmd = get_ffmpeg_params("/in/t.flac", "/out/t.wav", "wav", wav_depth="16")
        assert cmd.index("-af") < cmd.index("/out/t.wav")
        assert cmd.index("-af") < len(cmd) - 1


class TestDitherMeasuredOutcome:
    """Decode-and-measure tests: the artefact, not the flag spelling.

    A 1 kHz tone at -60 dBFS quantised 24->16 bits without dither shows a
    correlated second harmonic sitting above the residual noise floor; TPDF
    dither trades that tonal spur for a flat, slightly higher floor.
    """

    F0 = 1000.0
    SR = 44100
    SEG_N = 28224  # exactly 640 cycles of F0 at SR: no spectral leakage
    SECS = 2  # long enough to centre SEG_N without clipping the tone

    def _sine_power(self, samples, freq):
        """Goertzel magnitude-squared of ``samples`` at ``freq``."""
        import math

        n = len(samples)
        w = 2.0 * math.pi * (freq * n / self.SR) / n
        coeff = 2.0 * math.cos(w)
        s1 = s2 = 0.0
        for v in samples:
            s0 = v + coeff * s1 - s2
            s2 = s1
            s1 = s0
        return s1 * s1 + s2 * s2 - coeff * s1 * s2

    def _spur_db(self, path):
        """2nd-harmonic-to-noise-floor ratio in dB, from a decoded WAV.

        The floor is measured at 4500 Hz, far from both the tone and any
        harmonic. Negative means the harmonic sits below the floor, i.e. no
        correlated spur.
        """
        import math

        import numpy as np

        dec = path.with_suffix(".decoded.wav")
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-y",
                "-c:a",
                "pcm_f32le",
                str(dec),
            ],
            check=True,
            capture_output=True,
        )
        # stdlib `wave` rejects WAVE_FORMAT_IEEE_FLOAT (tag 3), so walk RIFF.
        blob = dec.read_bytes()
        samples = np.empty(0)
        pos = 12
        while pos + 8 <= len(blob):
            cid = blob[pos : pos + 4]
            size = int.from_bytes(blob[pos + 4 : pos + 8], "little")
            body = blob[pos + 8 : pos + 8 + size]
            if cid == b"data":
                samples = np.frombuffer(body[: len(body) // 4 * 4], dtype="<f4").astype(
                    np.float64
                )
            pos += 8 + size + (size & 1)
        dec.unlink()
        assert samples.size, f"no audio decoded from {path}"
        mid = samples.size // 2
        seg = samples[mid - self.SEG_N // 2 : mid + self.SEG_N // 2]
        p2 = self._sine_power(seg, 2 * self.F0)
        pn = self._sine_power(seg, 4500.0)
        return 10 * math.log10(p2 / pn)

    def _convert(self, tmp_path, dither):
        """Run the real chain once and return the produced WAV path."""
        out_dir = tmp_path / "out"
        run_conversion(
            input_dir=str(tmp_path),
            output_dir=str(out_dir),
            output_format="wav",
            quality="highest",
            delete_originals=False,
            is_dry_run=False,
            lossy_formats=[],
            slot_vars=[MagicMock()],
            slot_queue=_make_slot_fixtures(1)[1],
            on_progress=lambda **kw: None,
            on_complete=lambda **kw: None,
            on_error=lambda m: pytest.fail(f"conversion error: {m}"),
            sample_rate="source",
            bit_depth="16",
            dither=dither,
        )
        out = out_dir / "tone.wav"
        assert out.exists(), "conversion produced no output"
        return out

    def _make_24bit_flac(self, tmp_path):
        """A 24-bit 1 kHz FLAC, i.e. a source whose depth really is reduced.

        FLAC rather than WAV because a wav->wav run is skipped as a no-op by
        can_convert(), and the source must be deeper than the 16-bit target
        for the quantisation spur to exist at all.
        """
        import numpy as np

        t = np.arange(self.SR * self.SECS) / self.SR
        sig = (10 ** (-60 / 20)) * np.sin(2 * np.pi * self.F0 * t)
        ints = np.round(sig * 8388607).astype(np.int32)
        src = tmp_path / "tone.flac"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "s32le",
                "-ar",
                str(self.SR),
                "-ac",
                "1",
                "-i",
                "-",
                "-c:a",
                "flac",
                "-sample_fmt",
                "s32",
                "-y",
                str(src),
            ],
            input=ints.tobytes(),
            check=True,
            capture_output=True,
        )
        return src

    def test_dither_reduces_the_correlated_quantisation_spur(self, tmp_path):
        self._make_24bit_flac(tmp_path)
        without = self._spur_db(self._convert(tmp_path, False))
        with_dither = self._spur_db(self._convert(tmp_path, True))
        assert with_dither < without - 3.0, (
            f"dither did not lower the spur: {without:.2f} dB -> {with_dither:.2f} dB"
        )

    def test_dither_leaves_the_output_bit_identical_in_shape(self, tmp_path):
        """Dither adds noise, not a different signal: level must be preserved."""
        import wave as wave_mod

        self._make_24bit_flac(tmp_path)
        out = self._convert(tmp_path, True)
        with wave_mod.open(str(out), "rb") as w:
            assert w.getsampwidth() == 2
            assert w.getframerate() == self.SR
            assert w.getnchannels() == 1

    def test_no_dither_preserves_the_correlated_spur(self, tmp_path):
        """Locks the negative control: without dither the spur is still there,
        so the improvement above cannot be an artefact of the measurement."""
        self._make_24bit_flac(tmp_path)
        assert self._spur_db(self._convert(tmp_path, False)) > -8.0


class TestResamplerMeasuredOutcome:
    """96 -> 44.1 kHz: the shipped chain must suppress what the old one aliased.

    The fixture is a 96 kHz source carrying a 1 kHz passband reference plus a
    23 kHz partial. 23 kHz sits above the 44.1 kHz output's Nyquist (22.05 kHz),
    so it folds to 44100-23000 = 21100 Hz unless an anti-alias filter removes
    it first. Measuring the *alias* is what makes this a real outcome test —
    probing 23 kHz on a 44.1 kHz output would read zero for either command.

    Declared floor from the E1 Decision Log probe: on this two-tone fixture the
    legacy bare ``-ar`` folded the partial in at only -19.94 dB relative to the
    passband, while ``resampler=soxr`` reached -59.42 dB. The threshold sits at
    -50 dB, i.e. ~10 dB of margin below the measured value and ~30 dB clear of
    the legacy control. Raising soxr's precision to 28 measured -59.41 dB, so
    the default precision 20 is kept (nothing to gain from pinning it).
    """

    SRC_RATE = 96000
    OUT_RATE = 44100
    PASSBAND_HZ = 1000.0
    PARTIAL_HZ = 23000.0
    ALIAS_HZ = float(OUT_RATE - PARTIAL_HZ)  # 21100.0

    def _decode_f32(self, path):
        import numpy as np

        dec = path.with_suffix(".decoded.wav")
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-y",
                "-c:a",
                "pcm_f32le",
                str(dec),
            ],
            check=True,
            capture_output=True,
        )
        blob = dec.read_bytes()
        samples = np.empty(0)
        pos = 12
        while pos + 8 <= len(blob):
            cid = blob[pos : pos + 4]
            size = int.from_bytes(blob[pos + 4 : pos + 8], "little")
            body = blob[pos + 8 : pos + 8 + size]
            if cid == b"data":
                samples = np.frombuffer(body[: len(body) // 4 * 4], dtype="<f4").astype(
                    np.float64
                )
            pos += 8 + size + (size & 1)
        dec.unlink()
        assert samples.size, f"no audio decoded from {path}"
        return samples

    @staticmethod
    def _power(samples, freq, rate):
        """Goertzel power of ``samples`` at ``freq`` (whole-cycle window)."""
        import math

        n = rate  # exactly one second: whole cycles at every tone used here
        seg = samples[:n]
        w = 2.0 * math.pi * freq / rate
        coeff = 2.0 * math.cos(w)
        s1 = s2 = 0.0
        for v in seg:
            s0 = v + coeff * s1 - s2
            s2 = s1
            s1 = s0
        return s1 * s1 + s2 * s2 - coeff * s1 * s2

    def _make_source(self, tmp_path):
        """96 kHz FLAC: 1 kHz reference + 23 kHz partial, both at -60 dBFS."""
        import numpy as np

        t = np.arange(self.SRC_RATE) / self.SRC_RATE
        sig = (10 ** (-60 / 20)) * (
            np.sin(2 * np.pi * self.PASSBAND_HZ * t)
            + np.sin(2 * np.pi * self.PARTIAL_HZ * t)
        )
        ints = np.round(sig * 8388607).astype(np.int32)
        src = tmp_path / "wide.flac"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "s32le",
                "-ar",
                str(self.SRC_RATE),
                "-ac",
                "1",
                "-i",
                "-",
                "-c:a",
                "flac",
                "-sample_fmt",
                "s32",
                "-y",
                str(src),
            ],
            input=ints.tobytes(),
            check=True,
            capture_output=True,
        )
        return src

    def _run(self, tmp_path, extra_filter):
        """Convert to 44.1 kHz, optionally adding a filter; return the file."""
        src = tmp_path / "wide.flac"
        out = tmp_path / f"out_{'fixed' if extra_filter else 'legacy'}.wav"
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-y",
            "-c:a",
            "pcm_s24le",
        ]
        if extra_filter:
            cmd += ["-af", extra_filter]
        cmd += ["-ar", str(self.OUT_RATE), str(out)]
        subprocess.run(cmd, check=True, capture_output=True)
        return out

    def _alias_db(self, path):
        """Alias level relative to the 1 kHz passband reference, in dB."""
        import math

        s = self._decode_f32(path)
        ref = self._power(s, self.PASSBAND_HZ, self.OUT_RATE)
        alias = self._power(s, self.ALIAS_HZ, self.OUT_RATE)
        return 10 * math.log10((alias + 1e-30) / (ref + 1e-30))

    def test_shipped_chain_suppresses_the_aliased_partial(self, tmp_path):
        self._make_source(tmp_path)
        fixed = self._alias_db(self._run(tmp_path, "aresample=resampler=soxr"))
        # Declared floor: soxr measured -59.42 dB on this fixture.
        assert fixed < -50.0, f"alias only {fixed:.1f} dB down, need < -50 dB"

    def test_legacy_bare_ar_command_aliases_the_partial(self, tmp_path):
        """Negative control for the assertion above: the pre-E1 command (bare
        ``-ar``, no filter) folds the 23 kHz partial into audible aliasing, so
        the previous test is measuring a real improvement."""
        self._make_source(tmp_path)
        legacy = self._alias_db(self._run(tmp_path, None))
        assert legacy > -30.0, (
            f"legacy command aliased by only {legacy:.1f} dB — the control "
            "no longer demonstrates the defect"
        )

    def test_run_conversion_reaches_44k_output(self, tmp_path):
        """The sample-rate plumbing must actually take effect end to end."""
        import wave as wave_mod

        self._make_source(tmp_path)
        run_conversion(
            input_dir=str(tmp_path),
            output_dir=str(tmp_path / "out"),
            output_format="wav",
            quality="highest",
            delete_originals=False,
            is_dry_run=False,
            lossy_formats=[],
            slot_vars=[MagicMock()],
            slot_queue=_make_slot_fixtures(1)[1],
            on_progress=lambda **kw: None,
            on_complete=lambda **kw: None,
            on_error=lambda m: pytest.fail(f"conversion error: {m}"),
            sample_rate="44100",
            bit_depth="24",
        )
        out = tmp_path / "out" / "wide.wav"
        assert out.exists(), "conversion produced no output"
        with wave_mod.open(str(out), "rb") as w:
            assert w.getframerate() == self.OUT_RATE

    def test_rate_change_through_the_chain_carries_the_soxr_filter(self, tmp_path):
        """End-to-end wiring lock.

        The two measured tests above invoke ffmpeg directly, so on their own
        they would stay green even if the converter stopped emitting the
        filter. This records the command the real chain actually runs (the
        subprocess is delegated to, so the output file is really produced).
        """
        self._make_source(tmp_path)
        seen = self._record_commands(tmp_path, "44100")
        assert seen, "no ffmpeg command was issued"
        assert any("resampler=soxr" in " ".join(c) for c in seen), seen

    def test_no_rate_change_through_the_chain_emits_no_resampler(self, tmp_path):
        self._make_source(tmp_path)
        seen = self._record_commands(tmp_path, "source")
        assert seen, "no ffmpeg command was issued"
        assert not any("resampler=soxr" in " ".join(c) for c in seen), seen

    def _record_commands(self, tmp_path, sample_rate):
        """Run the real chain, recording each ffmpeg argv it issues."""
        import audio_suite_shared.secure_subprocess as secure_subprocess

        real = secure_subprocess.run_secure_subprocess
        seen: list[list[str]] = []

        def _spy(program, args, **kwargs):
            seen.append([program, *args])
            return real(program, args, **kwargs)

        with patch(
            "music_format_converter.core.file_processor.run_secure_subprocess",
            side_effect=_spy,
        ):
            run_conversion(
                input_dir=str(tmp_path),
                output_dir=str(tmp_path / "out"),
                output_format="wav",
                quality="highest",
                delete_originals=False,
                is_dry_run=False,
                lossy_formats=[],
                slot_vars=[MagicMock()],
                slot_queue=_make_slot_fixtures(1)[1],
                on_progress=lambda **kw: None,
                on_complete=lambda **kw: None,
                on_error=lambda m: pytest.fail(f"conversion error: {m}"),
                sample_rate=sample_rate,
                bit_depth="24",
            )
        return seen
