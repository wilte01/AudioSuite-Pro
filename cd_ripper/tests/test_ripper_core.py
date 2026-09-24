"""
Tests for cd_ripper.core.ripper (G-38)

Coverage strategy
-----------------
Pure-function / subprocess-backed units are tested directly.
The Windows SCSI / ctypes layer (ctypes.windll, CreateFileW, DeviceIoControl)
is patched at the ctypes.windll level so tests run on any OS.

Hardware-dependent paths (extract_track_scsi, spin_down_drive, read_toc) are
tested with the Win32 API fully mocked; they carry a ``hardware`` marker to
allow targeted exclusion in environments that want to skip OS-layer tests.

RipSession.start() launches a background thread; integration-style tests that
exercise the full session are kept under the ``integration`` marker and avoid
real ffmpeg/SCSI calls.
"""

import ctypes
import os
import struct
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from audio_suite_shared.exceptions import AudioConfigurationError, AudioIOError

# ---------------------------------------------------------------------------
# Ensure ctypes.windll exists on non-Windows so the module can be imported
# ---------------------------------------------------------------------------
if not hasattr(ctypes, "windll"):
    ctypes.windll = MagicMock()


# ---------------------------------------------------------------------------
# Ensure ctypes.wintypes.DWORD exists on non-Windows so functions that build
# a DWORD(0) byte-count output param (e.g. _read_cd_scsi) can be exercised
# directly in tests, not just through fully-mocked higher-level functions.
# ---------------------------------------------------------------------------
class _FakeWintypes:
    DWORD = ctypes.c_uint32
    HANDLE = ctypes.c_void_p


if not hasattr(ctypes, "wintypes"):
    ctypes.wintypes = _FakeWintypes()


# ---------------------------------------------------------------------------
# Ensure ctypes.get_last_error/set_last_error exist on non-Windows. Production
# code now uses these (not the bare, unreliable ctypes.GetLastError()) per
# the use_last_error=True fix -- see cd_ripper.core.drive_handler._kernel32.
# ---------------------------------------------------------------------------
if not hasattr(ctypes, "get_last_error"):
    ctypes.get_last_error = lambda: 0
if not hasattr(ctypes, "set_last_error"):
    ctypes.set_last_error = lambda value: 0

# The module imports run_secure_subprocess from audio_suite_shared; keep real
# implementation if available, otherwise stub it so import succeeds in CI.
try:
    from audio_suite_shared.secure_subprocess import (
        SubprocessSecurityError,  # noqa: F401
        run_secure_subprocess,  # noqa: F401
    )
except Exception:
    _stub_mod = MagicMock()
    _stub_mod.SubprocessSecurityError = type(
        "SubprocessSecurityError", (Exception,), {}
    )
    _stub_mod.run_secure_subprocess = MagicMock()
    sys.modules.setdefault("audio_suite_shared", MagicMock())
    sys.modules.setdefault("audio_suite_shared.secure_subprocess", _stub_mod)

from cd_ripper.core.ripper import (  # noqa: E402
    C2_FLAG_BYTES_PER_SECTOR,
    FLAC_QUALITY_ARGS,
    FORMAT_OPTIONS,  # noqa: E402
    M4A_QUALITY_ARGS,
    MP3_QUALITY_ARGS,
    OGG_QUALITY_ARGS,
    OPUS_QUALITY_ARGS,
    SCSI_PASS_THROUGH_DIRECT,
    SECTOR_SIZE,
    DBEntry,
    DBTrackEntry,
    LookupFound,
    LookupNotFound,
    LookupOffline,
    RipSession,
    RipTask,
    RipVerificationConfig,
    RipVerificationMode,
    UnresolvedSectorError,
    VerificationPlan,
    _build_metadata_args,
    _bytes_per_sector,
    _msf_to_lba,
    _read_cd_scsi,
    _read_verified_chunk,
    _resolve_by_majority,
    _run_ffmpeg_streaming,
    _safe_filename,
    compute_disc_ids,
    compute_track_checksums,
    diagnose_c2_reliability,
    extract_track_scsi,
    get_quality_options,
    probe_ffmpeg,
    read_toc,
    read_track_pcm,
    read_wav_pcm,
    spin_down_drive,
    verify_extracted_track,
    with_gap_window,
)

# ===========================================================================
# Helpers
# ===========================================================================


def _noop(*_, **__):
    pass


def _make_track(**kwargs):
    base = {
        "number": 1,
        "title": "Song Title",
        "artist": "Artist",
        "album": "Album",
        "album_artist": "Album Artist",
        "year": "2024",
        "genre": "Rock",
        "duration": 240.0,
    }
    base.update(kwargs)
    return base


def _make_toc_entry(**kwargs):
    base = {"number": 1, "start_lba": 0, "end_lba": 16874, "sectors": 16875}
    base.update(kwargs)
    return base


# ===========================================================================
# _safe_filename
# ===========================================================================


class TestSafeFilename:
    @pytest.mark.parametrize("char", ["\\", "/", "*", "?", ":", '"', "<", ">", "|"])
    def test_illegal_chars_replaced(self, char):
        result = _safe_filename(f"Track{char}01")
        assert char not in result
        assert "_" in result

    def test_clean_string_unchanged(self):
        assert _safe_filename("Normal Track Title") == "Normal Track Title"

    def test_leading_trailing_whitespace_stripped(self):
        assert _safe_filename("  Title  ") == "Title"

    def test_empty_string(self):
        assert _safe_filename("") == ""

    def test_all_illegal(self):
        result = _safe_filename('\\/*?:"<>|')
        assert all(c == "_" for c in result)

    def test_unicode_preserved(self):
        assert _safe_filename("Ångström") == "Ångström"

    def test_multiple_illegal_chars(self):
        result = _safe_filename("A:B/C*D")
        assert ":" not in result
        assert "/" not in result
        assert "*" not in result


# ===========================================================================
# _build_metadata_args
# ===========================================================================


class TestBuildMetadataArgs:
    def test_full_track_produces_all_fields(self):
        track = _make_track()
        args = _build_metadata_args(track)
        # Rebuild as dict from -metadata key=val triples
        meta = {}
        i = 0
        while i < len(args):
            if args[i] == "-metadata":
                k, v = args[i + 1].split("=", 1)
                meta[k] = v
                i += 2
            else:
                i += 1
        assert meta["title"] == "Song Title"
        assert meta["artist"] == "Artist"
        assert meta["album"] == "Album"
        assert meta["date"] == "2024"
        assert meta["genre"] == "Rock"
        assert meta["track"] == "1"

    def test_missing_title_omitted(self):
        track = _make_track(title="")
        args = _build_metadata_args(track)
        keys_present = [
            args[i + 1].split("=")[0]
            for i in range(0, len(args) - 1, 3)
            if i < len(args) and args[i] == "-metadata"
        ]
        assert "title" not in keys_present

    def test_album_artist_falls_back_to_artist(self):
        track = _make_track(album_artist="", artist="Solo Artist")
        args = _build_metadata_args(track)
        meta = {}
        i = 0
        while i < len(args):
            if args[i] == "-metadata":
                k, v = args[i + 1].split("=", 1)
                meta[k] = v
                i += 2
            else:
                i += 1
        assert meta["album_artist"] == "Solo Artist"

    def test_empty_track_produces_no_args(self):
        track = {
            "number": 1,
            "title": "",
            "artist": "",
            "album_artist": "",
            "album": "",
            "year": "",
            "genre": "",
        }
        args = _build_metadata_args(track)
        # track number is cast to str; if number is present and non-empty
        # str it should appear
        # But number=1 → str "1" which is truthy
        meta_keys = [
            args[i + 1].split("=")[0]
            for i in range(0, len(args) - 1)
            if i < len(args) and args[i] == "-metadata"
        ]
        # Only "track" should be present (number=1 is always truthy)
        assert meta_keys == ["track"]

    def test_output_is_list_of_strings(self):
        args = _build_metadata_args(_make_track())
        assert all(isinstance(a, str) for a in args)

    def test_no_metadata_flag_for_zero_number(self):
        track = _make_track(
            number=0, title="", artist="", album="", album_artist="", year="", genre=""
        )
        args = _build_metadata_args(track)
        # number=0 → str "0" which is falsy after `if val`… wait, "0" is truthy
        # number str(0) == "0" which IS truthy; confirm track meta is present
        assert "-metadata" in args


# ===========================================================================
# get_quality_options
# ===========================================================================


class TestGetQualityOptions:
    @pytest.mark.parametrize(
        "fmt,expected",
        [
            ("MP3", MP3_QUALITY_ARGS),
            ("FLAC", FLAC_QUALITY_ARGS),
            ("OGG", OGG_QUALITY_ARGS),
            ("M4A", M4A_QUALITY_ARGS),
            ("Opus", OPUS_QUALITY_ARGS),
        ],
    )
    def test_known_formats_return_correct_dict(self, fmt, expected):
        assert get_quality_options(fmt) is expected

    def test_unknown_format_returns_none(self):
        assert get_quality_options("WAV") is None

    def test_case_sensitive(self):
        assert get_quality_options("mp3") is None
        assert get_quality_options("flac") is None

    def test_empty_string_returns_none(self):
        assert get_quality_options("") is None

    def test_returned_dicts_contain_lists(self):
        for fmt in ("MP3", "FLAC", "OGG", "M4A", "Opus"):
            opts = get_quality_options(fmt)
            assert isinstance(opts, dict)
            for v in opts.values():
                assert isinstance(v, list)
                assert len(v) >= 2


# ===========================================================================
# FORMAT_OPTIONS
# ===========================================================================


class TestFormatOptions:
    @pytest.mark.parametrize("fmt", ["FLAC", "MP3", "OGG", "M4A", "WAV", "Opus"])
    def test_known_format_options_present(self, fmt):
        assert fmt in FORMAT_OPTIONS

    @pytest.mark.parametrize("fmt", ["FLAC", "MP3", "OGG", "M4A", "WAV", "Opus"])
    def test_format_options_have_ext_and_codec_args(self, fmt):
        entry = FORMAT_OPTIONS[fmt]
        assert "ext" in entry
        assert "codec_args" in entry
        assert isinstance(entry["ext"], str)
        assert isinstance(entry["codec_args"], list)


# ===========================================================================
# _msf_to_lba
# ===========================================================================


class TestMsfToLba:
    def test_known_value(self):
        # Standard audio CD lead-in offset: MSF 00:02:00 → LBA 0
        assert _msf_to_lba(0, 2, 0) == 0

    def test_two_minute_offset(self):
        # 00:02:00 in MSF = LBA 0; 00:03:00 = LBA 75
        assert _msf_to_lba(0, 3, 0) == 75

    def test_large_value(self):
        # 74:00:00 → (74*60+0)*75 + 0 - 150 = 333000 - 150 = 332850
        assert _msf_to_lba(74, 0, 0) == 332850

    def test_frame_offset(self):
        # 00:02:01 → (0*60+2)*75 + 1 - 150 = 150 + 1 - 150 = 1
        assert _msf_to_lba(0, 2, 1) == 1


# ===========================================================================
# probe_ffmpeg
# ===========================================================================


class TestProbeFfmpeg:
    def test_successful_probe_extracts_version(self):
        mock_result = MagicMock()
        mock_result.stdout = "ffmpeg version 6.1.0 Copyright (c) 2000-2023\nmore info"
        with patch(
            "cd_ripper.core.metadata_resolver.run_secure_subprocess",
            return_value=mock_result,
        ):
            info = probe_ffmpeg("ffmpeg")
        assert info["version"] == "6.1.0"

    def test_security_error_returns_error_string(self):
        from audio_suite_shared.secure_subprocess import (
            SubprocessSecurityError,  # noqa: F811
        )

        with patch(
            "cd_ripper.core.metadata_resolver.run_secure_subprocess",
            side_effect=SubprocessSecurityError("bad path"),
        ):
            info = probe_ffmpeg("bad_ffmpeg")
        assert "security error" in info["version"].lower()

    def test_generic_exception_returns_probe_error(self):
        with patch(
            "cd_ripper.core.metadata_resolver.run_secure_subprocess",
            side_effect=OSError("oops"),
        ):
            info = probe_ffmpeg("ffmpeg")
        assert "probe error" in info["version"].lower()

    def test_no_version_line_returns_unknown(self):
        mock_result = MagicMock()
        mock_result.stdout = "some other output\nno version here"
        with patch(
            "cd_ripper.core.metadata_resolver.run_secure_subprocess",
            return_value=mock_result,
        ):
            info = probe_ffmpeg("ffmpeg")
        assert info["version"] == "unknown"

    def test_returns_dict_always(self):
        with patch(
            "cd_ripper.core.metadata_resolver.run_secure_subprocess",
            side_effect=OSError("probe error"),
        ):
            result = probe_ffmpeg("ffmpeg")
        assert isinstance(result, dict)
        assert "version" in result


# ===========================================================================
# _run_ffmpeg_streaming — subprocess-based ffmpeg encode with progress
# ===========================================================================


class TestRunFfmpegStreaming:
    def test_successful_encode_parses_progress(self):
        progress_events = []
        stderr_lines = [
            "frame=  100 fps=25\n",
            "  time=00:00:30.00  bitrate=128.0kbits/s\n",
            "  time=00:01:00.00  bitrate=128.0kbits/s\n",
        ]
        mock_proc = MagicMock()
        mock_proc.stderr = iter(stderr_lines)
        mock_proc.returncode = 0
        mock_proc.wait.return_value = 0

        with patch(
            "cd_ripper.core.metadata_resolver.run_secure_popen", return_value=mock_proc
        ):
            rc, _ = _run_ffmpeg_streaming(
                "ffmpeg",
                ["-i", "in.wav"],
                duration=120.0,
                progress_cb=lambda num, pct, msg: progress_events.append(
                    (num, pct, msg)
                ),
                track_num=1,
                cancelled_fn=lambda: False,
            )

        assert rc == 0
        assert any(pct > 0 for _, pct, _ in progress_events)

    def test_security_error_returns_minus_two(self):
        from audio_suite_shared.secure_subprocess import SubprocessSecurityError

        with patch(
            "cd_ripper.core.metadata_resolver.run_secure_popen",
            side_effect=SubprocessSecurityError("bad path"),
        ):
            rc, msg = _run_ffmpeg_streaming("ffmpeg", [], 0, _noop, 1, lambda: False)

        assert rc == -2
        assert "Security error" in msg

    def test_file_not_found_returns_minus_one(self):
        with patch(
            "cd_ripper.core.metadata_resolver.run_secure_popen",
            side_effect=FileNotFoundError("ffmpeg not found on PATH"),
        ):
            rc, msg = _run_ffmpeg_streaming("ffmpeg", [], 0, _noop, 1, lambda: False)

        assert rc == -1
        assert "FFmpeg executable not found" in msg

    def test_generic_exception_returns_minus_one(self):
        with patch(
            "cd_ripper.core.metadata_resolver.run_secure_popen",
            side_effect=OSError("subprocess crashed"),
        ):
            rc, _ = _run_ffmpeg_streaming("ffmpeg", [], 0, _noop, 1, lambda: False)

        assert rc == -1

    def test_zero_duration_skips_progress_callback(self):
        progress_events = []
        mock_proc = MagicMock()
        mock_proc.stderr = iter(["no time line here\n"])
        mock_proc.returncode = 0
        mock_proc.wait.return_value = 0

        with patch(
            "cd_ripper.core.metadata_resolver.run_secure_popen", return_value=mock_proc
        ):
            rc, _ = _run_ffmpeg_streaming(
                "ffmpeg",
                ["-i", "in.wav"],
                duration=0,
                progress_cb=lambda num, pct, msg: progress_events.append(
                    (num, pct, msg)
                ),
                track_num=1,
                cancelled_fn=lambda: False,
            )

        assert rc == 0
        assert not any(pct > 0 for _, pct, _ in progress_events)

    def test_returns_tuple_of_int_and_str(self):
        mock_proc = MagicMock()
        mock_proc.stderr = iter([])
        mock_proc.returncode = 0
        mock_proc.wait.return_value = 0
        with patch(
            "cd_ripper.core.metadata_resolver.run_secure_popen", return_value=mock_proc
        ):
            result = _run_ffmpeg_streaming("ffmpeg", [], 0, _noop, 1, lambda: False)

        assert isinstance(result, tuple)
        assert isinstance(result[0], int)
        assert isinstance(result[1], str)


# ===========================================================================
# RipTask — unit tests with all I/O mocked
# ===========================================================================


class TestRipTask:
    def _make_task(self, tmp_path, track=None, fmt="FLAC", **kwargs):
        track = track or _make_track()
        toc_entry = _make_toc_entry()
        progress_events = []
        done_events = []

        task = RipTask(
            drive="D:",
            track=track,
            toc_entry=toc_entry,
            out_dir=str(tmp_path),
            fmt=fmt,
            codec_args=FORMAT_OPTIONS[fmt]["codec_args"],
            progress_cb=lambda num, pct, msg: progress_events.append((num, pct, msg)),
            done_cb=lambda num, ok, path, err: done_events.append((num, ok, path, err)),
            ffmpeg_path="ffmpeg",
            log_cb=_noop,
            **kwargs,
        )
        return task, progress_events, done_events

    def test_cancel_before_run_stops_immediately(self, tmp_path):
        task, _, done = self._make_task(tmp_path)
        task.cancel()

        with patch(
            "cd_ripper.core.encoding_pipeline.extract_track_scsi"
        ) as mock_extract:
            # Even if we somehow call run after cancel, extract should not be called
            # We simulate the cancel flag being set; run() checks it post-extract
            mock_extract.side_effect = lambda **kw: None
            with patch(
                "cd_ripper.core.encoding_pipeline.tempfile.mkstemp"
            ) as mock_mkstemp:
                mock_mkstemp.return_value = (-1, str(tmp_path / "fake.wav"))
                with patch("os.close"), patch("os.path.exists", return_value=False):
                    task.run()

        # done_cb should signal cancellation or extraction failure
        assert len(done) == 1

    def test_successful_rip_calls_done_with_ok_true(self, tmp_path):
        task, progress, done = self._make_task(tmp_path)
        out_wav = str(tmp_path / "track.wav")

        # Write a minimal real WAV so size check passes (>44 bytes)
        Path(out_wav).write_bytes(b"RIFF" + b"\x00" * 44)

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = iter([])
        mock_proc.wait.return_value = 0

        with (
            patch("cd_ripper.core.encoding_pipeline.extract_track_scsi"),
            patch(
                "cd_ripper.core.encoding_pipeline.tempfile.mkstemp",
                return_value=(0, out_wav),
            ),
            patch("os.close"),
            patch("os.path.exists", return_value=True),
            patch("os.path.getsize", return_value=1000),
            patch(
                "cd_ripper.core.metadata_resolver.run_secure_popen",
                return_value=mock_proc,
            ),
            patch("os.makedirs"),
        ):
            task.run()

        assert len(done) == 1
        num, ok, path, err = done[0]
        assert ok is True
        assert num == 1

    def test_ffmpeg_failure_calls_done_with_ok_false(self, tmp_path):
        task, _, done = self._make_task(tmp_path)
        out_wav = str(tmp_path / "track.wav")
        Path(out_wav).write_bytes(b"RIFF" + b"\x00" * 44)

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = iter(["Error: invalid codec\n"])
        mock_proc.wait.return_value = 1

        with (
            patch("cd_ripper.core.encoding_pipeline.extract_track_scsi"),
            patch(
                "cd_ripper.core.encoding_pipeline.tempfile.mkstemp",
                return_value=(0, out_wav),
            ),
            patch("os.close"),
            patch("os.path.exists", return_value=True),
            patch("os.path.getsize", return_value=1000),
            patch(
                "cd_ripper.core.metadata_resolver.run_secure_popen",
                return_value=mock_proc,
            ),
            patch("os.makedirs"),
        ):
            task.run()

        num, ok, path, err = done[0]
        assert ok is False
        assert "Encode failed" in err or err

    def test_runtime_error_from_scsi_handled(self, tmp_path):
        task, _, done = self._make_task(tmp_path)

        with (
            patch(
                "cd_ripper.core.encoding_pipeline.extract_track_scsi",
                side_effect=RuntimeError("SCSI pass-through failed"),
            ),
            patch(
                "cd_ripper.core.encoding_pipeline.tempfile.mkstemp",
                return_value=(0, str(tmp_path / "t.wav")),
            ),
            patch("os.close"),
            patch("os.makedirs"),
        ):
            task.run()

        num, ok, path, err = done[0]
        assert ok is False
        assert "SCSI" in err

    def test_progress_callback_called_at_start(self, tmp_path):
        task, progress, done = self._make_task(tmp_path)

        out_wav = str(tmp_path / "t.wav")
        Path(out_wav).write_bytes(b"RIFF" + b"\x00" * 44)
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = iter([])
        mock_proc.wait.return_value = 0

        with (
            patch("cd_ripper.core.encoding_pipeline.extract_track_scsi"),
            patch(
                "cd_ripper.core.encoding_pipeline.tempfile.mkstemp",
                return_value=(0, out_wav),
            ),
            patch("os.close"),
            patch("os.path.exists", return_value=True),
            patch("os.path.getsize", return_value=1000),
            patch(
                "cd_ripper.core.metadata_resolver.run_secure_popen",
                return_value=mock_proc,
            ),
            patch("os.makedirs"),
        ):
            task.run()

        assert any(pct == 0 and "Start" in msg for _, pct, msg in progress)

    def test_output_path_uses_safe_filename(self, tmp_path):
        track = _make_track(
            title='Track: "Bad" Name', album="My/Album", artist="Art*ist"
        )
        task, _, done = self._make_task(tmp_path, track=track)

        out_wav = str(tmp_path / "t.wav")
        Path(out_wav).write_bytes(b"RIFF" + b"\x00" * 44)

        created_dirs = []

        def fake_makedirs(path, **kw):
            created_dirs.append(path)

        captured_encode_args = []

        def fake_popen(ffmpeg, args, **kw):
            captured_encode_args.extend(args)
            proc = MagicMock()
            proc.returncode = 0
            proc.stderr = iter([])
            proc.wait.return_value = 0
            return proc

        with (
            patch("cd_ripper.core.encoding_pipeline.extract_track_scsi"),
            patch(
                "cd_ripper.core.encoding_pipeline.tempfile.mkstemp",
                return_value=(0, out_wav),
            ),
            patch("os.close"),
            patch("os.path.exists", return_value=True),
            patch("os.path.getsize", return_value=1000),
            patch(
                "cd_ripper.core.metadata_resolver.run_secure_popen",
                side_effect=fake_popen,
            ),
            patch("os.makedirs", side_effect=fake_makedirs),
        ):
            task.run()

        # The final output path argument to ffmpeg must not contain illegal chars
        # (it's the last non-flag arg in encode_args — i.e., the out_path)
        # Extract just the filename portion from the last arg passed to ffmpeg
        if captured_encode_args:
            out_file = os.path.basename(captured_encode_args[-1])
            for bad_char in [":", '"', "*", "?", "<", ">", "|"]:
                assert bad_char not in out_file, (
                    f"Illegal char {bad_char!r} in filename: {out_file}"
                )

    def test_cancel_flag_propagates(self, tmp_path):
        task, _, done = self._make_task(tmp_path)
        out_wav = str(tmp_path / "t.wav")
        Path(out_wav).write_bytes(b"RIFF" + b"\x00" * 44)

        def fake_extract(**kw):
            task.cancel()  # cancel mid-extraction

        with (
            patch(
                "cd_ripper.core.encoding_pipeline.extract_track_scsi",
                side_effect=fake_extract,
            ),
            patch(
                "cd_ripper.core.encoding_pipeline.tempfile.mkstemp",
                return_value=(0, out_wav),
            ),
            patch("os.close"),
            patch("os.path.exists", return_value=True),
            patch("os.path.getsize", return_value=1000),
            patch("os.makedirs"),
        ):
            task.run()

        num, ok, path, err = done[0]
        assert ok is False
        assert "Cancelled" in err

    def test_temp_wav_cleaned_up_in_finally_block(self, tmp_path):
        """The temp .wav file must be removed in the finally block of
        RipTask.run() regardless of success or failure."""
        task, _, done = self._make_task(tmp_path)
        out_wav = str(tmp_path / "track.wav")
        Path(out_wav).write_bytes(b"RIFF" + b"\x00" * 44)

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = iter([])
        mock_proc.wait.return_value = 0
        removed_files = []

        def fake_remove(path):
            removed_files.append(path)

        with (
            patch("cd_ripper.core.encoding_pipeline.extract_track_scsi"),
            patch(
                "cd_ripper.core.encoding_pipeline.tempfile.mkstemp",
                return_value=(0, out_wav),
            ),
            patch("os.close"),
            patch("os.path.exists", return_value=True),
            patch("os.path.getsize", return_value=1000),
            patch(
                "cd_ripper.core.metadata_resolver.run_secure_popen",
                return_value=mock_proc,
            ),
            patch("os.makedirs"),
            patch("os.remove", side_effect=fake_remove),
        ):
            task.run()

        assert out_wav in removed_files, "temp WAV was not cleaned up"

    def test_temp_wav_cleaned_up_on_scsi_failure(self, tmp_path):
        """Even if extract_track_scsi raises, the temp file must be removed."""
        task, _, done = self._make_task(tmp_path)
        out_wav = str(tmp_path / "track.wav")
        Path(out_wav).write_bytes(b"RIFF" + b"\x00" * 44)

        removed_files = []

        def fake_remove(path):
            removed_files.append(path)

        with (
            patch(
                "cd_ripper.core.encoding_pipeline.extract_track_scsi",
                side_effect=RuntimeError("SCSI failed"),
            ),
            patch(
                "cd_ripper.core.encoding_pipeline.tempfile.mkstemp",
                return_value=(0, out_wav),
            ),
            patch("os.close"),
            patch("os.path.exists", return_value=True),
            patch("os.remove", side_effect=fake_remove),
            patch("os.makedirs"),
        ):
            task.run()

        assert out_wav in removed_files, "temp WAV was not cleaned up on failure"
        num, ok, path, err = done[0]
        assert ok is False


# ===========================================================================
# RipSession — unit tests
# ===========================================================================


class TestRipSession:
    def _make_session(self, tmp_path, tracks=None, fmt="FLAC"):
        tracks = tracks or [_make_track(number=i + 1) for i in range(2)]
        done_tracks = []
        session_done = threading.Event()

        session = RipSession(
            drive="D:",
            tracks=tracks,
            out_dir=str(tmp_path),
            fmt=fmt,
            quality_args=None,
            progress_cb=_noop,
            track_done_cb=lambda num, ok, path, err: done_tracks.append(
                (num, ok, path, err)
            ),
            session_done_cb=session_done.set,
            ffmpeg_path="ffmpeg",
            log_cb=_noop,
        )
        return session, done_tracks, session_done

    def test_init_uses_format_options_when_quality_args_is_none(self, tmp_path):
        session, _, _ = self._make_session(tmp_path, fmt="MP3")
        assert session.codec_args == FORMAT_OPTIONS["MP3"]["codec_args"]

    @pytest.mark.parametrize(
        "lowercase_key,display_key",
        [("flac", "FLAC"), ("mp3", "MP3"), ("wav", "WAV"), ("opus", "Opus")],
    )
    def test_lowercase_fmt_resolves_to_display_key(
        self, tmp_path, lowercase_key, display_key
    ):
        """The CLI passes lowercase format values ('wav', 'opus'); RipSession
        must resolve them to the FORMAT_OPTIONS display key so the codec_args
        default and RipTask extension lookup never KeyError."""
        session, _, _ = self._make_session(tmp_path, fmt=lowercase_key)
        assert session.fmt == display_key
        assert session.codec_args == FORMAT_OPTIONS[display_key]["codec_args"]

    def test_wav_fmt_uses_pcm_s16le(self, tmp_path):
        session, _, _ = self._make_session(tmp_path, fmt="WAV")
        assert session.codec_args == ["-c:a", "pcm_s16le"]

    def test_init_uses_supplied_quality_args(self, tmp_path):
        custom_args = ["-c:a", "libmp3lame", "-b:a", "256k"]
        tracks = [_make_track()]
        session = RipSession(
            drive="D:",
            tracks=tracks,
            out_dir=str(tmp_path),
            fmt="MP3",
            quality_args=custom_args,
            progress_cb=_noop,
            track_done_cb=_noop,
            session_done_cb=_noop,
            ffmpeg_path="ffmpeg",
        )
        assert session.codec_args == custom_args

    def test_cancel_sets_flag(self, tmp_path):
        session, _, _ = self._make_session(tmp_path)
        assert not session._cancelled
        session.cancel()
        assert session._cancelled

    def test_session_calls_done_cb_for_missing_toc_entry(self, tmp_path):
        """Track has no matching TOC entry → track_done_cb called with ok=False."""
        tracks = [_make_track(number=1)]
        done_tracks = []
        session_done = threading.Event()

        session = RipSession(
            drive="D:",
            tracks=tracks,
            out_dir=str(tmp_path),
            fmt="FLAC",
            quality_args=None,
            progress_cb=_noop,
            track_done_cb=lambda num, ok, path, err: done_tracks.append(
                (num, ok, path, err)
            ),
            session_done_cb=session_done.set,
            ffmpeg_path="ffmpeg",
            log_cb=_noop,
        )

        # read_toc returns empty list → toc_map is empty
        with (
            patch(
                "cd_ripper.core.ripper.probe_ffmpeg", return_value={"version": "test"}
            ),
            patch("cd_ripper.core.ripper.read_toc", return_value=[]),
            patch("cd_ripper.core.ripper.spin_down_drive"),
        ):
            session._run()

        assert len(done_tracks) == 1
        num, ok, path, err = done_tracks[0]
        assert ok is False
        assert "TOC" in err

    def test_session_runs_spin_down_on_completion(self, tmp_path):
        tracks = [_make_track(number=1)]
        session_done = threading.Event()

        session = RipSession(
            drive="D:",
            tracks=tracks,
            out_dir=str(tmp_path),
            fmt="FLAC",
            quality_args=None,
            progress_cb=_noop,
            track_done_cb=_noop,
            session_done_cb=session_done.set,
            ffmpeg_path="ffmpeg",
        )

        with (
            patch(
                "cd_ripper.core.ripper.probe_ffmpeg", return_value={"version": "test"}
            ),
            patch("cd_ripper.core.ripper.read_toc", return_value=[]),
            patch("cd_ripper.core.ripper.spin_down_drive") as mock_spin,
        ):
            session._run()

        mock_spin.assert_called_once()

    def test_session_calls_session_done_cb(self, tmp_path):
        session_done = threading.Event()
        session = RipSession(
            drive="D:",
            tracks=[],
            out_dir=str(tmp_path),
            fmt="FLAC",
            quality_args=None,
            progress_cb=_noop,
            track_done_cb=_noop,
            session_done_cb=session_done.set,
            ffmpeg_path="ffmpeg",
        )

        with (
            patch("cd_ripper.core.ripper.probe_ffmpeg", return_value={"version": "0"}),
            patch("cd_ripper.core.ripper.read_toc", return_value=[]),
            patch("cd_ripper.core.ripper.spin_down_drive"),
        ):
            session._run()

        assert session_done.is_set()

    @pytest.mark.integration
    def test_session_start_launches_thread(self, tmp_path):
        """start() must create and start a daemon thread."""
        session_done = threading.Event()
        session = RipSession(
            drive="D:",
            tracks=[],
            out_dir=str(tmp_path),
            fmt="FLAC",
            quality_args=None,
            progress_cb=_noop,
            track_done_cb=_noop,
            session_done_cb=session_done.set,
            ffmpeg_path="ffmpeg",
        )

        with (
            patch("cd_ripper.core.ripper.probe_ffmpeg", return_value={"version": "0"}),
            patch("cd_ripper.core.ripper.read_toc", return_value=[]),
            patch("cd_ripper.core.ripper.spin_down_drive"),
        ):
            session.start()
            session._thread.join(timeout=5)

        assert session._thread is not None
        assert session._thread.daemon

    def test_toc_read_exception_is_handled_gracefully(self, tmp_path):
        """
        When read_toc() raises an exception, RipSession._run() must catch it,
        log the failure, set toc=[], and continue so individual tracks still
        get reported (with a "No TOC entry found" error).
        """
        tracks = [_make_track(number=1), _make_track(number=2)]
        done_tracks = []
        session_done = threading.Event()
        log_lines = []

        session = RipSession(
            drive="D:",
            tracks=tracks,
            out_dir=str(tmp_path),
            fmt="FLAC",
            quality_args=None,
            progress_cb=_noop,
            track_done_cb=lambda num, ok, path, err: done_tracks.append(
                (num, ok, path, err)
            ),
            session_done_cb=session_done.set,
            ffmpeg_path="ffmpeg",
            log_cb=log_lines.append,
        )

        with (
            patch(
                "cd_ripper.core.ripper.probe_ffmpeg", return_value={"version": "test"}
            ),
            patch(
                "cd_ripper.core.ripper.read_toc",
                side_effect=RuntimeError("Drive not ready"),
            ),
            patch("cd_ripper.core.ripper.spin_down_drive"),
        ):
            session._run()

        assert any("TOC read failed" in line for line in log_lines)
        # Both tracks should have been processed with failure (no TOC entry)
        assert len(done_tracks) == 2
        for num, ok, path, err in done_tracks:
            assert ok is False
            assert "TOC" in err or "No TOC entry" in err
        assert session_done.is_set()


# ===========================================================================
# RipSession — CUE sheet output
# ===========================================================================


class _FakeRipTask:
    """Stands in for RipTask and reports every track as successfully encoded."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def run(self):
        track = self.kwargs["track"]
        num = int(track["number"])
        out_dir = self.kwargs["out_dir"]
        out_path = os.path.join(
            out_dir,
            "Album Artist",
            "[2024] Hits",
            f"{num:02d} - {track.get('title')}.flac",
        )
        self.kwargs["done_cb"](num, True, out_path, "")


class TestRipSessionCueWrite:
    def _run_session(self, tmp_path, write_cue):
        tracks = [_make_track(number=i + 1) for i in range(2)]
        session_done = threading.Event()
        log_lines = []
        session = RipSession(
            drive="D:",
            tracks=tracks,
            out_dir=str(tmp_path),
            fmt="FLAC",
            quality_args=None,
            progress_cb=_noop,
            track_done_cb=_noop,
            session_done_cb=session_done.set,
            ffmpeg_path="ffmpeg",
            log_cb=log_lines.append,
            write_cue=write_cue,
        )
        toc = [_make_toc_entry(number=i + 1) for i in range(2)]
        with (
            patch(
                "cd_ripper.core.ripper.probe_ffmpeg", return_value={"version": "test"}
            ),
            patch("cd_ripper.core.ripper.read_toc", return_value=toc),
            patch("cd_ripper.core.ripper.spin_down_drive"),
            patch("cd_ripper.core.ripper.RipTask", _FakeRipTask),
        ):
            session._run()
        assert session_done.is_set()
        return session, log_lines

    def test_write_cue_defaults_to_false(self, tmp_path):
        session, _ = self._run_session(tmp_path, write_cue=False)
        assert session.write_cue is False

    def test_write_cue_true_is_stored(self, tmp_path):
        session, _ = self._run_session(tmp_path, write_cue=True)
        assert session.write_cue is True

    def test_no_cue_written_when_disabled(self, tmp_path):
        self._run_session(tmp_path, write_cue=False)
        assert list(tmp_path.rglob("*.cue")) == []

    def test_cue_written_after_successful_rip(self, tmp_path):
        self._run_session(tmp_path, write_cue=True)
        cues = list(tmp_path.rglob("*.cue"))
        assert len(cues) == 1
        text = cues[0].read_text(encoding="utf-8")
        assert 'TITLE "Album"' in text
        assert 'PERFORMER "Album Artist"' in text
        assert "  TRACK 01 AUDIO" in text
        assert "  TRACK 02 AUDIO" in text
        assert "FILE " in text
        assert text.count("INDEX 01") == 2

    def test_cue_write_failure_is_non_fatal(self, tmp_path):
        with patch(
            "cd_ripper.core.ripper.write_cue",
            side_effect=OSError("disk full"),
        ):
            session, log_lines = self._run_session(tmp_path, write_cue=True)
        assert any("CUE sheet not written" in line for line in log_lines)
        assert session.write_cue is True


# ===========================================================================
# SCSI / OS layer — mocked hardware tests
# ===========================================================================


@pytest.mark.hardware
class TestHardwareLayer:
    """
    Tests that exercise the ctypes/Win32 layer by mocking ctypes.windll.
    These tests verify the logic around the OS calls without needing real
    hardware. Mark with ``-m 'not hardware'`` to exclude from CI.
    """

    def test_open_device_raises_on_invalid_handle(self):
        from cd_ripper.core.ripper import INVALID_HANDLE_VALUE, _open_device

        mock_kernel32 = MagicMock()
        mock_kernel32.CreateFileW.return_value = INVALID_HANDLE_VALUE

        with (
            patch("sys.platform", "win32"),
            patch("cd_ripper.core.drive_handler._kernel32", mock_kernel32),
            patch("ctypes.get_last_error", return_value=5),
        ):  # 5 = Access denied
            with pytest.raises(AudioIOError, match="Cannot open CD device"):
                _open_device("D")

    def test_open_device_success_returns_handle(self):
        from cd_ripper.core.ripper import _open_device

        fake_handle = 42
        mock_kernel32 = MagicMock()
        mock_kernel32.CreateFileW.return_value = fake_handle  # not INVALID_HANDLE_VALUE

        with (
            patch("sys.platform", "win32"),
            patch("cd_ripper.core.drive_handler._kernel32", mock_kernel32),
        ):
            handle = _open_device("D")

        assert handle == fake_handle

    def test_open_device_retries_with_read_only_on_write_access_denied(self):
        """
        When GENERIC_READ|GENERIC_WRITE returns INVALID_HANDLE_VALUE,
        _open_device must retry with GENERIC_READ before raising.
        """
        from cd_ripper.core.ripper import INVALID_HANDLE_VALUE, _open_device

        mock_kernel32 = MagicMock()
        mock_kernel32.CreateFileW.side_effect = [INVALID_HANDLE_VALUE, 42]

        with (
            patch("sys.platform", "win32"),
            patch("cd_ripper.core.drive_handler._kernel32", mock_kernel32),
            patch("ctypes.get_last_error", return_value=5),
        ):
            handle = _open_device("D")

        assert handle == 42
        assert mock_kernel32.CreateFileW.call_count == 2

    def test_open_device_fails_after_both_attempts(self):
        """
        If both GENERIC_READ|GENERIC_WRITE and GENERIC_READ retry return
        INVALID_HANDLE_VALUE, _open_device must raise RuntimeError.
        """
        from cd_ripper.core.ripper import INVALID_HANDLE_VALUE, _open_device

        mock_kernel32 = MagicMock()
        mock_kernel32.CreateFileW.return_value = INVALID_HANDLE_VALUE

        with (
            patch("sys.platform", "win32"),
            patch("cd_ripper.core.drive_handler._kernel32", mock_kernel32),
            patch("ctypes.get_last_error", return_value=5),
        ):
            with pytest.raises(AudioIOError, match="Cannot open CD device"):
                _open_device("D")

        assert mock_kernel32.CreateFileW.call_count == 2


# ===========================================================================
# read_toc — TOC parsing via IOCTL_CDROM_READ_TOC
# ===========================================================================


@pytest.mark.hardware
class TestReadToc:
    """Direct tests of the TOC-reading code path with mocked Win32 API."""

    def _populate_toc(
        self, toc_ptr: ctypes.pointer, track_addresses: list[tuple[int, int, int, int]]
    ) -> None:
        """Fill a _CDROM_TOC struct given list of (track_number, m, s, f) tuples.
        The last entry should be the lead-out (0xAA).
        """
        from cd_ripper.core.ripper import _CDROM_TOC

        toc = ctypes.cast(toc_ptr, ctypes.POINTER(_CDROM_TOC)).contents
        # FirstTrack/LastTrack must be data track numbers, NOT lead-out (0xAA)
        data_tracks = [t for t in track_addresses if t[0] != 0xAA]
        toc.FirstTrack = data_tracks[0][0] if data_tracks else track_addresses[0][0]
        toc.LastTrack = data_tracks[-1][0] if data_tracks else 1
        for i, (num, m, s, f) in enumerate(track_addresses):
            toc.TrackData[i].TrackNumber = num
            toc.TrackData[i].Address = (ctypes.c_uint8 * 4)(0, m, s, f)

    def _fake_ioctl(self, expected_tracks: list[tuple[int, int, int, int]]):
        """Return a side_effect for DeviceIoControl that writes a TOC."""

        def fake_ioctl(
            handle, code, in_buf, in_len, out_buf, out_len, bytes_ret, overlapped
        ):
            self._populate_toc(out_buf, expected_tracks)
            return 1

        return fake_ioctl

    def test_single_track(self):

        log_lines = []
        mock_k32 = MagicMock()
        mock_k32.DeviceIoControl.side_effect = self._fake_ioctl(
            [(1, 0, 2, 0), (0xAA, 0, 3, 0)]
        )
        mock_k32.CloseHandle = MagicMock()

        with (
            patch("cd_ripper.core.drive_handler._open_device", return_value=1),
            patch("cd_ripper.core.drive_handler._kernel32", mock_k32),
            patch("sys.platform", "win32"),
        ):
            result = read_toc("D", log_lines.append)

        assert len(result) == 1
        assert result[0]["number"] == 1
        assert result[0]["start_lba"] == 0
        assert result[0]["end_lba"] == 74
        assert result[0]["sectors"] == 75

    def test_two_tracks(self):

        log_lines = []
        mock_k32 = MagicMock()
        # Track 1 at MSF 00:02:00 (LBA 0), Track 2 at MSF 03:47:00 (LBA 16875),
        # Lead-out at MSF 05:00:00 (LBA 22350)
        mock_k32.DeviceIoControl.side_effect = self._fake_ioctl(
            [(1, 0, 2, 0), (2, 3, 47, 0), (0xAA, 5, 0, 0)]
        )
        mock_k32.CloseHandle = MagicMock()

        with (
            patch("cd_ripper.core.drive_handler._open_device", return_value=1),
            patch("cd_ripper.core.drive_handler._kernel32", mock_k32),
            patch("sys.platform", "win32"),
        ):
            result = read_toc("D", log_lines.append)

        assert len(result) == 2
        assert result[0]["number"] == 1
        assert result[0]["start_lba"] == 0
        assert result[0]["end_lba"] == 16874
        assert result[0]["sectors"] == 16875
        assert result[1]["number"] == 2
        assert result[1]["start_lba"] == 16875
        assert result[1]["end_lba"] == 22349
        assert result[1]["sectors"] == 5475

    def test_log_lines_contain_track_info(self):
        log_lines = []
        mock_k32 = MagicMock()
        mock_k32.DeviceIoControl.side_effect = self._fake_ioctl(
            [(1, 0, 2, 0), (0xAA, 0, 3, 0)]
        )
        mock_k32.CloseHandle = MagicMock()

        with (
            patch("cd_ripper.core.drive_handler._open_device", return_value=1),
            patch("cd_ripper.core.drive_handler._kernel32", mock_k32),
            patch("sys.platform", "win32"),
        ):
            read_toc("D", log_lines.append)

        assert any("[TOC]" in line for line in log_lines)
        assert any("Track 01" in line for line in log_lines)

    def test_close_handle_called_on_success(self):
        log_lines = []
        mock_k32 = MagicMock()
        mock_k32.DeviceIoControl.side_effect = self._fake_ioctl(
            [(1, 0, 2, 0), (0xAA, 0, 3, 0)]
        )
        mock_k32.CloseHandle = MagicMock()

        with (
            patch("cd_ripper.core.drive_handler._open_device", return_value=1),
            patch("cd_ripper.core.drive_handler._kernel32", mock_k32),
            patch("sys.platform", "win32"),
        ):
            read_toc("D", log_lines.append)

        mock_k32.CloseHandle.assert_called_once_with(1)

    def test_ioctl_failure_raises_runtime_error(self):
        log_lines = []
        mock_k32 = MagicMock()
        mock_k32.DeviceIoControl.return_value = 0  # falsy == failure
        mock_k32.CloseHandle = MagicMock()

        with (
            patch("cd_ripper.core.drive_handler._open_device", return_value=1),
            patch("cd_ripper.core.drive_handler._kernel32", mock_k32),
            patch("sys.platform", "win32"),
            patch("ctypes.get_last_error", return_value=6),
        ):
            with pytest.raises(AudioIOError, match="IOCTL_CDROM_READ_TOC"):
                read_toc("D", log_lines.append)

        mock_k32.CloseHandle.assert_called_once_with(1)

    def test_device_identifiers_reported_in_first_toc_log(self):
        log_lines = []
        mock_k32 = MagicMock()
        mock_k32.DeviceIoControl.side_effect = self._fake_ioctl(
            [(1, 0, 2, 0), (2, 3, 0, 0), (0xAA, 5, 0, 0)]
        )
        mock_k32.CloseHandle = MagicMock()

        with (
            patch("cd_ripper.core.drive_handler._open_device", return_value=1),
            patch("cd_ripper.core.drive_handler._kernel32", mock_k32),
            patch("sys.platform", "win32"),
        ):
            read_toc("D", log_lines.append)

        assert any("Tracks 1\u20132" in line for line in log_lines) or any(
            "Tracks 1-2" in line for line in log_lines
        )


# ===========================================================================
# Read verification: jitter/error-detection feature (multi-read + C2 hint)
# ===========================================================================


def _sptd_from_ioctl_call(out_buf_arg) -> "SCSI_PASS_THROUGH_DIRECT":
    """Recover the SCSI_PASS_THROUGH_DIRECT struct from a mocked
    DeviceIoControl call."""
    return ctypes.cast(out_buf_arg, ctypes.POINTER(SCSI_PASS_THROUGH_DIRECT)).contents


@pytest.mark.hardware
class TestReadCdScsiC2Request:
    """Confirms the CDB flags byte and transfer length change only when
    C2 is requested."""

    def _run_with_fake_ioctl(self, count, request_c2):
        captured = {}

        def fake_ioctl(
            handle, code, in_buf, in_len, out_buf, out_len, bytes_ret, overlapped
        ):
            sptd = _sptd_from_ioctl_call(out_buf)
            captured["flags_byte"] = sptd.Cdb[9]
            captured["transfer_len"] = sptd.DataTransferLength
            sptd.ScsiStatus = 0
            return 1

        mock_kernel32 = MagicMock()
        mock_kernel32.DeviceIoControl.side_effect = fake_ioctl
        buf = ctypes.create_string_buffer(
            count * (SECTOR_SIZE + C2_FLAG_BYTES_PER_SECTOR)
        )

        with patch("cd_ripper.core.drive_handler._kernel32", mock_kernel32):
            _read_cd_scsi(1, 0, count, buf, _noop, request_c2=request_c2)

        return captured

    def test_default_call_uses_original_0xF8_flags_and_length(self):
        captured = self._run_with_fake_ioctl(count=5, request_c2=False)
        assert captured["flags_byte"] == 0xF8
        assert captured["transfer_len"] == 5 * SECTOR_SIZE

    def test_c2_request_uses_0xFA_flags_and_larger_length(self):
        captured = self._run_with_fake_ioctl(count=5, request_c2=True)
        assert captured["flags_byte"] == 0xFA
        assert captured["transfer_len"] == 5 * (SECTOR_SIZE + C2_FLAG_BYTES_PER_SECTOR)

    def test_failure_reports_error_code_via_reliable_get_last_error(self):
        """
        Regression for the reported 'IOCTL_CDROM_READ_TOC failed: Win32
        error 6' bug: ctypes.windll.kernel32 does not reliably preserve the
        true last-error code for a later bare ctypes.GetLastError() call --
        any intervening ctypes/CPython internal Win32 call can clobber it.
        The fix loads kernel32 with use_last_error=True and reads via
        ctypes.get_last_error(); this proves the failure path actually uses
        that reliable mechanism, not the unreliable bare one.
        """
        mock_kernel32 = MagicMock()
        mock_kernel32.DeviceIoControl.return_value = 0  # falsy == failure
        buf = ctypes.create_string_buffer(SECTOR_SIZE)

        with (
            patch("cd_ripper.core.drive_handler._kernel32", mock_kernel32),
            patch("ctypes.get_last_error", return_value=6),
        ):
            with pytest.raises(AudioIOError, match="Win32 error 6"):
                _read_cd_scsi(1, 0, 1, buf, _noop)

    def test_non_zero_scsi_status_raises_error(self):
        """
        When the SCSI pass-through succeeds (DeviceIoControl returns 1)
        but the SCSI status byte is non-zero, _read_cd_scsi must raise
        RuntimeError with the status code.
        """
        mock_kernel32 = MagicMock()
        buf = ctypes.create_string_buffer(SECTOR_SIZE)

        def fake_ioctl(
            handle, code, in_buf, in_len, out_buf, out_len, bytes_ret, overlapped
        ):
            sptd = _sptd_from_ioctl_call(out_buf)
            sptd.ScsiStatus = 2  # Check Condition
            return 1

        mock_kernel32.DeviceIoControl.side_effect = fake_ioctl

        with (
            patch("cd_ripper.core.drive_handler._kernel32", mock_kernel32),
            patch("sys.platform", "win32"),
        ):
            with pytest.raises(AudioIOError, match="SCSI status 2"):
                _read_cd_scsi(1, 0, 1, buf, _noop)


class TestBytesPerSector:
    def test_without_c2(self):
        assert _bytes_per_sector(False) == SECTOR_SIZE

    def test_with_c2(self):
        assert _bytes_per_sector(True) == SECTOR_SIZE + C2_FLAG_BYTES_PER_SECTOR


class TestRipVerificationConfig:
    def test_defaults(self):
        config = RipVerificationConfig()
        assert config.max_read_attempts == 3
        assert config.use_c2_hint is False

    def test_rejects_max_attempts_below_two(self):
        with pytest.raises(AudioConfigurationError):
            RipVerificationConfig(max_read_attempts=1)

    def test_is_frozen(self):
        config = RipVerificationConfig()
        with pytest.raises(Exception):
            config.max_read_attempts = 5


@pytest.mark.hardware
class TestDiagnoseC2Reliability:
    """
    Verifies the C2-honesty diagnostic's three distinguishable outcomes.
    Per the Data Premise Verification Rule, this drive's forum-reported C2
    support cannot be trusted without an empirical check like this one.
    """

    def _patched_read(self, sectors, audio_first, audio_second, c2_block):
        bytes_per_sector = SECTOR_SIZE + C2_FLAG_BYTES_PER_SECTOR
        state = {"calls": 0}

        def _fake_read(handle, lba, count, buf, log_cb, request_c2=False):
            audio = audio_first if state["calls"] == 0 else audio_second
            state["calls"] += 1
            payload = bytearray()
            for _ in range(sectors):
                payload += audio
                payload += c2_block
            buf[: len(payload)] = bytes(payload)
            return len(payload)

        return _fake_read, bytes_per_sector

    def _run_diagnostic(self, sectors, audio_first, audio_second, c2_block):
        fake_read, bytes_per_sector = self._patched_read(
            sectors, audio_first, audio_second, c2_block
        )
        with (
            patch("sys.platform", "win32"),
            patch("cd_ripper.core.track_processor._open_device", return_value=1),
            patch(
                "cd_ripper.core.track_processor._read_cd_scsi", side_effect=fake_read
            ),
            patch("ctypes.windll") as mock_windll,
        ):
            mock_windll.kernel32 = MagicMock()
            return diagnose_c2_reliability(
                "D", start_lba=0, log_cb=_noop, sectors=sectors
            )

    def test_audio_mismatch_between_reads_is_flagged_not_honest(self):
        audio_a = bytes([1]) * SECTOR_SIZE
        audio_b = bytes([2]) * SECTOR_SIZE
        c2_zero = bytes(C2_FLAG_BYTES_PER_SECTOR)
        result = self._run_diagnostic(2, audio_a, audio_b, c2_zero)
        assert result.audio_data_matched is False
        assert result.c2_appears_honest is False

    def test_all_zero_c2_is_never_treated_as_honest(self):
        audio = bytes([3]) * SECTOR_SIZE
        c2_zero = bytes(C2_FLAG_BYTES_PER_SECTOR)
        result = self._run_diagnostic(2, audio, audio, c2_zero)
        assert result.audio_data_matched is True
        assert result.c2_flags_all_zero is True
        assert result.c2_appears_honest is False

    def test_nonzero_c2_with_matching_audio_appears_honest(self):
        audio = bytes([3]) * SECTOR_SIZE
        c2_nonzero = bytes([1]) + bytes(C2_FLAG_BYTES_PER_SECTOR - 1)
        result = self._run_diagnostic(2, audio, audio, c2_nonzero)
        assert result.audio_data_matched is True
        assert result.c2_flags_all_zero is False
        assert result.c2_appears_honest is True
        assert (
            result.c2_nonzero_byte_count == 2
        )  # one non-zero byte per sector, 2 sectors


class TestResolveByMajority:
    def test_two_identical_reads_fully_resolved(self):
        data = bytes([10, 20, 30, 40])
        resolved, unresolved = _resolve_by_majority([data, data])
        assert resolved == data
        assert unresolved == 0

    def test_two_reads_disagree_at_one_position_is_unresolved(self):
        a = bytes([1, 2, 3])
        b = bytes([1, 9, 3])
        resolved, unresolved = _resolve_by_majority([a, b])
        assert unresolved == 1

    def test_three_reads_two_of_three_wins_majority(self):
        a = bytes([1, 2, 3])
        b = bytes([1, 2, 3])
        c = bytes([1, 9, 3])
        resolved, unresolved = _resolve_by_majority([a, b, c])
        assert resolved == bytes([1, 2, 3])
        assert unresolved == 0

    def test_three_reads_all_disagree_at_one_position_is_unresolved(self):
        a = bytes([1, 2, 3])
        b = bytes([1, 5, 3])
        c = bytes([1, 9, 3])
        resolved, unresolved = _resolve_by_majority([a, b, c])
        assert unresolved == 1
        # Positions that DID agree are still resolved correctly.
        assert resolved[0] == 1
        assert resolved[2] == 3


@pytest.mark.hardware
class TestReadVerifiedChunk:
    def _fake_read_sequence(self, sequence, request_c2_expected=None):
        state = {"calls": 0}

        def _fake_read(handle, lba, count, buf, log_cb, request_c2=False):
            data = sequence[state["calls"]]
            state["calls"] += 1
            buf[: len(data)] = data
            return len(data)

        return _fake_read, state

    def test_two_matching_reads_short_circuit_after_two_calls(self):
        data = bytes([7]) * (2 * SECTOR_SIZE)
        fake_read, state = self._fake_read_sequence([data, data])
        buf = ctypes.create_string_buffer(2 * SECTOR_SIZE)
        config = RipVerificationConfig()

        with patch(
            "cd_ripper.core.track_processor._read_cd_scsi", side_effect=fake_read
        ):
            result = _read_verified_chunk(
                1, 0, 2, buf, _noop, track_num=1, config=config
            )

        assert result == data
        assert state["calls"] == 2

    def test_mismatch_then_third_read_resolves_by_majority(self):
        a = bytes([1]) * (2 * SECTOR_SIZE)
        mutated = bytearray(a)
        mutated[100] = 99
        b = bytes(mutated)
        fake_read, state = self._fake_read_sequence([a, b, a])
        buf = ctypes.create_string_buffer(2 * SECTOR_SIZE)
        config = RipVerificationConfig(max_read_attempts=3)

        with patch(
            "cd_ripper.core.track_processor._read_cd_scsi", side_effect=fake_read
        ):
            result = _read_verified_chunk(
                1, 0, 2, buf, _noop, track_num=1, config=config
            )

        assert result == a
        assert state["calls"] == 3

    def test_all_reads_disagree_raises_unresolved_sector_error(self):
        base = bytearray(bytes([1]) * (2 * SECTOR_SIZE))
        b = bytearray(base)
        b[50] = 2
        c = bytearray(base)
        c[50] = 3
        fake_read, state = self._fake_read_sequence([bytes(base), bytes(b), bytes(c)])
        buf = ctypes.create_string_buffer(2 * SECTOR_SIZE)
        config = RipVerificationConfig(max_read_attempts=3)

        with patch(
            "cd_ripper.core.track_processor._read_cd_scsi", side_effect=fake_read
        ):
            with pytest.raises(UnresolvedSectorError, match="Track 05"):
                _read_verified_chunk(1, 0, 2, buf, _noop, track_num=5, config=config)

    def test_c2_hint_all_zero_takes_single_read_fast_path(self):
        sectors = 2
        bytes_per_sector = SECTOR_SIZE + C2_FLAG_BYTES_PER_SECTOR
        audio = bytes([9]) * SECTOR_SIZE
        c2_zero = bytes(C2_FLAG_BYTES_PER_SECTOR)
        full = (audio + c2_zero) * sectors
        fake_read, state = self._fake_read_sequence([full])
        buf = ctypes.create_string_buffer(sectors * bytes_per_sector)
        config = RipVerificationConfig(use_c2_hint=True)

        with patch(
            "cd_ripper.core.track_processor._read_cd_scsi", side_effect=fake_read
        ):
            result = _read_verified_chunk(
                1, 0, sectors, buf, _noop, track_num=1, config=config
            )

        assert result == audio * sectors
        assert state["calls"] == 1

    def test_c2_hint_nonzero_falls_back_to_full_verification(self):
        sectors = 2
        bytes_per_sector = SECTOR_SIZE + C2_FLAG_BYTES_PER_SECTOR
        audio = bytes([9]) * SECTOR_SIZE
        c2_nonzero = bytes([1]) + bytes(C2_FLAG_BYTES_PER_SECTOR - 1)
        full_with_c2 = (audio + c2_nonzero) * sectors
        plain_audio = audio * sectors

        def _fake_read(handle, lba, count, buf, log_cb, request_c2=False):
            data = full_with_c2 if request_c2 else plain_audio
            buf[: len(data)] = data
            return len(data)

        buf = ctypes.create_string_buffer(sectors * bytes_per_sector)
        config = RipVerificationConfig(use_c2_hint=True)

        with patch(
            "cd_ripper.core.track_processor._read_cd_scsi", side_effect=_fake_read
        ):
            result = _read_verified_chunk(
                1, 0, sectors, buf, _noop, track_num=1, config=config
            )

        assert result == plain_audio


@pytest.mark.hardware
class TestSpinDownDrive:
    """Tests for spin_down_drive — SCSI STOP UNIT via pass-through."""

    def test_spin_down_sends_command_and_logs(self):
        log_lines = []
        with (
            patch("cd_ripper.core.drive_handler._open_device", return_value=1),
            patch("sys.platform", "win32"),
            patch("ctypes.windll") as mock_windll,
        ):
            mock_windll.kernel32 = MagicMock()
            spin_down_drive("D", log_lines.append)

        assert any("[Drive] Spin-down" in line for line in log_lines)

    def test_open_device_failure_is_swallowed_and_logged(self):
        log_lines = []
        with (
            patch(
                "cd_ripper.core.drive_handler._open_device",
                side_effect=RuntimeError("device not found"),
            ),
            patch("sys.platform", "win32"),
        ):
            spin_down_drive("D", log_lines.append)  # must not raise

        assert any("skipped" in line for line in log_lines)

    def test_close_handle_called_on_success(self):
        log_lines = []
        with (
            patch("cd_ripper.core.drive_handler._open_device", return_value=1),
            patch("sys.platform", "win32"),
            patch("cd_ripper.core.drive_handler._kernel32") as mock_kernel32,
        ):
            spin_down_drive("D", log_lines.append)

        mock_kernel32.CloseHandle.assert_called_once_with(1)

    def test_device_io_control_failure_still_logs_message(self):
        """Even if DeviceIoControl returns 0, the function logs success
        (the spin-down is best-effort) and still closes the handle."""
        log_lines = []

        with (
            patch("cd_ripper.core.drive_handler._open_device", return_value=1),
            patch("sys.platform", "win32"),
            patch("cd_ripper.core.drive_handler._kernel32") as mock_kernel32,
        ):
            mock_kernel32.DeviceIoControl.return_value = 0
            spin_down_drive("D", log_lines.append)

        assert any("Spin-down" in line for line in log_lines)
        mock_kernel32.CloseHandle.assert_called_once_with(1)


@pytest.mark.hardware
class TestExtractTrackScsiAbortsOnUnresolvedSector:
    def test_unresolved_sector_error_propagates_without_writing_final_data(
        self, tmp_path
    ):
        out_wav = str(tmp_path / "track.wav")

        with (
            patch("cd_ripper.core.track_processor._open_device", return_value=1),
            patch("ctypes.windll") as mock_windll,
            patch(
                "cd_ripper.core.track_processor._read_verified_chunk",
                side_effect=UnresolvedSectorError("Track 01: unresolved"),
            ),
        ):
            mock_windll.kernel32 = MagicMock()
            with pytest.raises(UnresolvedSectorError):
                extract_track_scsi(
                    drive_letter="D",
                    start_lba=0,
                    sectors=20,
                    out_wav=out_wav,
                    progress_cb=_noop,
                    track_num=1,
                    cancelled_fn=lambda: False,
                    log_cb=_noop,
                )


def test_riptask_surfaces_unresolved_sector_as_track_failure(tmp_path):
    """
    UnresolvedSectorError subclasses RuntimeError, so RipTask's existing
    ``except RuntimeError`` clause must catch it and report failure --
    per the "abort track, don't write a partial file" policy, done_cb
    must be called with ok=False and no output path.
    """
    done_events = []
    task = RipTask(
        drive="D:",
        track=_make_track(),
        toc_entry=_make_toc_entry(),
        out_dir=str(tmp_path),
        fmt="FLAC",
        codec_args=FORMAT_OPTIONS["FLAC"]["codec_args"],
        progress_cb=_noop,
        done_cb=lambda num, ok, path, err: done_events.append((num, ok, path, err)),
        ffmpeg_path="ffmpeg",
        log_cb=_noop,
    )

    with (
        patch(
            "cd_ripper.core.encoding_pipeline.extract_track_scsi",
            side_effect=UnresolvedSectorError(
                "Track 01: 3 byte position(s) at LBA 0 disagreed across all 3 "
                "read attempts with no majority -- aborting track"
            ),
        ),
        patch(
            "cd_ripper.core.encoding_pipeline.tempfile.mkstemp",
            return_value=(0, str(tmp_path / "t.wav")),
        ),
        patch("os.close"),
        patch("os.makedirs"),
    ):
        task.run()

    assert len(done_events) == 1
    num, ok, path, err = done_events[0]
    assert ok is False
    assert path == ""
    assert "aborting" in err


def test_riptask_default_verification_config_is_created_when_omitted():
    task = RipTask(
        drive="D:",
        track=_make_track(),
        toc_entry=_make_toc_entry(),
        out_dir=".",
        fmt="FLAC",
        codec_args=FORMAT_OPTIONS["FLAC"]["codec_args"],
        progress_cb=_noop,
        done_cb=_noop,
        ffmpeg_path="ffmpeg",
    )
    assert isinstance(task.verification_config, RipVerificationConfig)
    assert task.verification_config.max_read_attempts == 3
    assert task.verification_config.use_c2_hint is False


# ===========================================================================
# read_wav_pcm — canonical RIFF/WAVE chunk walking
# ===========================================================================


class TestReadWavPcm:
    def test_canonical_wav_returns_data_chunk(self, tmp_path):
        path = tmp_path / "canonical.wav"
        chunk = bytes(range(256)) * 20
        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + len(chunk),
            b"WAVE",
            b"fmt ",
            16,
            1,
            2,
            44100,
            176400,
            4,
            16,
            b"data",
            len(chunk),
        )
        path.write_bytes(header + chunk)
        assert read_wav_pcm(str(path)) == chunk

    def test_extra_chunk_before_data_is_skipped(self, tmp_path):
        path = tmp_path / "listed.wav"
        chunk = b"\x01\x02\x03\x04" * 10
        body = (
            b"fmt "
            + struct.pack("<IHHIIHH", 16, 1, 2, 44100, 176400, 4, 16)
            + b"LIST"
            + struct.pack("<I", 4)
            + b"INFO"
            + b"data"
            + struct.pack("<I", len(chunk))
            + chunk
        )
        path.write_bytes(b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body)
        assert read_wav_pcm(str(path)) == chunk

    def test_missing_data_chunk_raises(self, tmp_path):
        path = tmp_path / "nodata.wav"
        # A >44-byte RIFF/WAVE that declares only a fmt chunk (trailing
        # padding so the file clears the minimal-44 container gate).
        payload = (
            b"fmt "
            + struct.pack("<IHHIIHH", 16, 1, 2, 44100, 176400, 4, 16)
            + b"\x00" * 32
        )
        path.write_bytes(
            b"RIFF" + struct.pack("<I", 4 + len(payload)) + b"WAVE" + payload
        )
        with pytest.raises(ValueError, match="no data chunk"):
            read_wav_pcm(str(path))

    def test_not_a_wave_raises(self, tmp_path):
        path = tmp_path / "junk.bin"
        path.write_bytes(b"not a riff file at all")
        with pytest.raises(ValueError, match="RIFF/WAVE"):
            read_wav_pcm(str(path))

    def test_truncated_data_chunk_raises(self, tmp_path):
        path = tmp_path / "trunc.wav"
        chunk = b"\xaa" * 8
        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + len(chunk) + 4,
            b"WAVE",
            b"fmt ",
            16,
            1,
            2,
            44100,
            176400,
            4,
            16,
            b"data",
            len(chunk) + 4,
        )
        path.write_bytes(header + chunk)
        with pytest.raises(ValueError, match="truncated"):
            read_wav_pcm(str(path))


# ===========================================================================
# read_track_pcm — independent second read for rip-twice verification
# ===========================================================================


@pytest.mark.hardware
class TestReadTrackPcm:
    def test_reads_all_sectors_and_returns_pcm(self):
        sectors = 4
        fake_audio = bytes([0xAB]) * (sectors * SECTOR_SIZE)
        captured = []

        def _fake_chunk(handle, lba, count, buf, log_cb, track_num, config):
            captured.append((lba, count))
            payload = bytes([0xAB]) * (count * SECTOR_SIZE)
            buf[: len(payload)] = payload
            return payload

        with (
            patch("cd_ripper.core.track_processor._open_device", return_value=42),
            patch(
                "cd_ripper.core.track_processor._read_verified_chunk",
                side_effect=_fake_chunk,
            ),
            patch("ctypes.windll") as mock_windll,
        ):
            mock_windll.kernel32 = MagicMock()
            result = read_track_pcm(
                "D",
                start_lba=100,
                sectors=sectors,
                track_num=2,
                cancelled_fn=lambda: False,
                log_cb=_noop,
            )

        assert result == fake_audio
        assert captured == [(100, 4)]
        mock_windll.kernel32.CloseHandle.assert_called_once_with(42)

    def test_cancelled_mid_read_returns_partial_bytes(self):
        state = {"calls": 0}

        def _fake_chunk(handle, lba, count, buf, log_cb, track_num, config):
            state["calls"] += 1
            payload = bytes([7]) * (count * SECTOR_SIZE)
            buf[: len(payload)] = payload
            return payload

        with (
            patch("cd_ripper.core.track_processor._open_device", return_value=1),
            patch(
                "cd_ripper.core.track_processor._read_verified_chunk",
                side_effect=_fake_chunk,
            ),
            patch("ctypes.windll") as mock_windll,
        ):
            mock_windll.kernel32 = MagicMock()
            result = read_track_pcm(
                "D",
                start_lba=0,
                sectors=25,
                track_num=1,
                cancelled_fn=lambda: state["calls"] >= 1,
                log_cb=_noop,
            )

        # One full 20-sector chunk is read before the cancellation fires.
        assert len(result) == 20 * SECTOR_SIZE
        mock_windll.kernel32.CloseHandle.assert_called_once_with(1)


# ===========================================================================
# verify_extracted_track — rip-twice + AccurateRip matching matrix
# ===========================================================================


def _db_entry_with_track(track_count, index, crc1, crc2, confidence=20):
    tracks = (
        tuple(DBTrackEntry(confidence=confidence, crc1=0, crc2=0) for _ in range(index))
        + (DBTrackEntry(confidence=confidence, crc1=crc1, crc2=crc2),)
        + tuple(
            DBTrackEntry(confidence=confidence, crc1=0, crc2=0)
            for _ in range(track_count - index - 1)
        )
    )
    return DBEntry(disc_id1=0, disc_id2=0, cddb_id=0, tracks=tracks)


def _sectors_pcm(value, sectors):
    return bytes([value]) * (sectors * SECTOR_SIZE)


class TestVerifyExtractedTrack:
    def _toc(self):
        return [
            _make_toc_entry(number=1, start_lba=0, sectors=10),
            _make_toc_entry(number=2, start_lba=10, sectors=10),
            _make_toc_entry(number=3, start_lba=20, sectors=10),
        ]

    def _verify(self, first_pcm, plan, second_pcm=None, cancelled_fn=lambda: False):
        toc = self._toc()
        if second_pcm is None:
            second_pcm = first_pcm

        with patch(
            "cd_ripper.core.track_processor.read_track_pcm",
            return_value=second_pcm,
        ) as mock_read:
            status, detail = verify_extracted_track(
                drive_letter="D",
                toc_entry=toc[1],
                toc=toc,
                first_pcm=first_pcm,
                plan=plan,
                verification_config=None,
                track_num=2,
                cancelled_fn=cancelled_fn,
                log_cb=_noop,
            )
        return status, detail, mock_read

    def test_twice_mode_matching_reads_verifies(self):
        pcm = _sectors_pcm(0x11, 10)
        plan = VerificationPlan(mode=RipVerificationMode.TWICE, toc=tuple(self._toc()))
        status, detail, mock_read = self._verify(pcm, plan)
        assert status.value == "VERIFIED"
        assert "rip-twice" in detail
        mock_read.assert_called_once()

    def test_twice_mode_crc_difference_is_mismatch(self):
        plan = VerificationPlan(mode=RipVerificationMode.TWICE, toc=tuple(self._toc()))
        status, detail, _ = self._verify(
            _sectors_pcm(0x11, 10), plan, second_pcm=_sectors_pcm(0x22, 10)
        )
        assert status.value == "MISMATCH"
        assert "rip-twice" in detail

    def test_mismatched_payload_length_reports_mismatch_without_reread(self):
        plan = VerificationPlan(mode=RipVerificationMode.TWICE, toc=tuple(self._toc()))
        with patch("cd_ripper.core.track_processor.read_track_pcm") as mock_read:
            status, detail = verify_extracted_track(
                drive_letter="D",
                toc_entry=self._toc()[1],
                toc=self._toc(),
                first_pcm=_sectors_pcm(0x11, 9),
                plan=plan,
                verification_config=None,
                track_num=2,
                cancelled_fn=lambda: False,
                log_cb=_noop,
            )
        assert status.value == "MISMATCH"
        assert "expected" in detail
        mock_read.assert_not_called()

    def test_cancelled_during_reread_returns_none(self):
        plan = VerificationPlan(mode=RipVerificationMode.TWICE, toc=tuple(self._toc()))
        status, detail, _ = self._verify(
            _sectors_pcm(0x11, 10), plan, cancelled_fn=lambda: True
        )
        assert status is None
        assert detail == "cancelled"

    def test_off_plan_raises(self):
        plan = VerificationPlan(mode=RipVerificationMode.OFF, toc=tuple(self._toc()))
        with pytest.raises(ValueError, match="non-OFF"):
            self._verify(_sectors_pcm(0x11, 10), plan)

    def test_toc_missing_entry_raises(self):
        plan = VerificationPlan(mode=RipVerificationMode.TWICE, toc=tuple(self._toc()))
        bogus = _make_toc_entry(number=99, start_lba=999, sectors=10)
        with patch("cd_ripper.core.track_processor.read_track_pcm"):
            with pytest.raises(ValueError, match="does not contain"):
                verify_extracted_track(
                    drive_letter="D",
                    toc_entry=bogus,
                    toc=self._toc(),
                    first_pcm=_sectors_pcm(0x11, 10),
                    plan=plan,
                    verification_config=None,
                    track_num=2,
                    cancelled_fn=lambda: False,
                    log_cb=_noop,
                )

    def _acqui_plan(self, entries):
        return VerificationPlan(
            mode=RipVerificationMode.ACCURATERIP,
            lookup=LookupFound(
                entries=tuple(entries), url="https://x.accuraterip/test"
            ),
            toc=tuple(self._toc()),
        )

    def test_accuraterip_track_window_match_verifies_with_single_read(self):
        second = _sectors_pcm(0x33, 10)
        sums = compute_track_checksums(second, track_number=2, track_count=3)
        plan = self._acqui_plan([_db_entry_with_track(3, 1, sums.crc1, sums.crc2)])
        status, detail, mock_read = self._verify(second, plan)
        assert status.value == "VERIFIED"
        assert "track window" in detail
        mock_read.assert_called_once()

    def test_accuraterip_with_gap_window_match_verifies_after_edge_rereads(self):
        second = _sectors_pcm(0x44, 10)
        prev_tail = _sectors_pcm(0x55, 5)
        next_head = _sectors_pcm(0x66, 5)

        cache = {
            (10, 10): second,
            (5, 5): prev_tail,
            (20, 5): next_head,
        }

        def _fake_read(
            drive, start_lba, sectors, track_num, cancelled_fn, log_cb, config
        ):
            return cache[(start_lba, sectors)]

        toc = self._toc()
        gap_pcm = with_gap_window(second, prev_tail, next_head)
        gap_sums = compute_track_checksums(gap_pcm, track_number=2, track_count=3)
        plan = self._acqui_plan(
            [_db_entry_with_track(3, 1, gap_sums.crc1, gap_sums.crc2)]
        )

        with patch(
            "cd_ripper.core.track_processor.read_track_pcm", side_effect=_fake_read
        ) as mock_read:
            status, detail = verify_extracted_track(
                drive_letter="D",
                toc_entry=toc[1],
                toc=toc,
                first_pcm=second,
                plan=plan,
                verification_config=None,
                track_num=2,
                cancelled_fn=lambda: False,
                log_cb=_noop,
            )
        assert status.value == "VERIFIED"
        assert "with-gap" in detail
        assert mock_read.call_count == 3

    def test_accuraterip_no_match_is_mismatch(self):
        second = _sectors_pcm(0x77, 10)
        # A structurally different PCM whose checksum matches neither the
        # track-window nor the with-gap candidate (constant-byte streams
        # share a crc2 collision, so use a non-constant pattern here).
        other_pcm = (bytes(range(16)) * 9999)[: 10 * SECTOR_SIZE]
        other = compute_track_checksums(other_pcm, 2, 3)
        entry = _db_entry_with_track(3, 1, other.crc1, other.crc2)
        plan = self._acqui_plan([entry])

        toc = self._toc()
        cache = {
            (10, 10): second,
            (5, 5): _sectors_pcm(0xAA, 5),
            (20, 5): _sectors_pcm(0xBB, 5),
        }

        def _fake_read(
            drive, start_lba, sectors, track_num, cancelled_fn, log_cb, config
        ):
            return cache[(start_lba, sectors)]

        with patch(
            "cd_ripper.core.track_processor.read_track_pcm", side_effect=_fake_read
        ) as mock_read:
            status, detail = verify_extracted_track(
                drive_letter="D",
                toc_entry=toc[1],
                toc=toc,
                first_pcm=second,
                plan=plan,
                verification_config=None,
                track_num=2,
                cancelled_fn=lambda: False,
                log_cb=_noop,
            )
        assert status.value == "MISMATCH"
        assert "AccurateRip cross-check failed" in detail
        assert mock_read.call_count == 3

    def test_accuraterip_not_found_is_no_entry_without_edge_rereads(self):
        second = _sectors_pcm(0x11, 10)
        plan = VerificationPlan(
            mode=RipVerificationMode.ACCURATERIP,
            lookup=LookupNotFound(reason="no entry"),
            toc=tuple(self._toc()),
        )
        status, detail, mock_read = self._verify(second, plan)
        assert status.value == "NO_ENTRY"
        assert "no entry" in detail
        mock_read.assert_called_once()

    def test_accuraterip_offline_degrades_to_offline(self):
        second = _sectors_pcm(0x11, 10)
        plan = VerificationPlan(
            mode=RipVerificationMode.ACCURATERIP,
            lookup=LookupOffline(reason="network down"),
            toc=tuple(self._toc()),
        )
        status, detail, mock_read = self._verify(second, plan)
        assert status.value == "OFFLINE"
        assert "network down" in detail
        mock_read.assert_called_once()


# ===========================================================================
# RipTask verification gating — MISMATCH must block the write
# ===========================================================================


class TestRipTaskVerificationGating:
    def _run_with_verify(self, tmp_path, task, plan, status_detail):
        out_wav = str(tmp_path / "track.wav")
        Path(out_wav).write_bytes(b"RIFF" + b"\x00" * 44)

        encode_calls = []

        def _fake_popen(ffmpeg, args, **kw):
            encode_calls.append(args)
            proc = MagicMock()
            proc.returncode = 0
            proc.stderr = iter([])
            proc.wait.return_value = 0
            return proc

        status, detail = status_detail
        with (
            patch("cd_ripper.core.encoding_pipeline.extract_track_scsi"),
            patch(
                "cd_ripper.core.encoding_pipeline.tempfile.mkstemp",
                return_value=(0, out_wav),
            ),
            patch("os.close"),
            patch("os.path.exists", return_value=True),
            patch("os.path.getsize", return_value=1000),
            patch(
                "cd_ripper.core.encoding_pipeline.read_wav_pcm",
                return_value=b"\x11" * 2352,
            ),
            patch(
                "cd_ripper.core.encoding_pipeline.verify_extracted_track",
                return_value=(status, detail),
            ),
            patch(
                "cd_ripper.core.metadata_resolver.run_secure_popen",
                side_effect=_fake_popen,
            ),
            patch("os.makedirs"),
        ):
            task.run()
        return encode_calls

    def _task(self, tmp_path, plan, **kwargs):
        return RipTask(
            drive="D:",
            track=_make_track(),
            toc_entry=_make_toc_entry(),
            out_dir=str(tmp_path),
            fmt="FLAC",
            codec_args=FORMAT_OPTIONS["FLAC"]["codec_args"],
            progress_cb=_noop,
            done_cb=_noop,
            ffmpeg_path="ffmpeg",
            log_cb=_noop,
            verification=plan,
            **kwargs,
        )

    def test_mismatch_blocks_encode_and_reports(self, tmp_path):
        plan = VerificationPlan(
            mode=RipVerificationMode.TWICE,
            toc=(_make_toc_entry(),),
        )
        task = self._task(tmp_path, plan)
        done = []
        task.done_cb = lambda num, ok, path, err: done.append((num, ok, path, err))
        from cd_ripper.core.accuraterip import VerificationStatus

        encode_calls = self._run_with_verify(
            tmp_path,
            task,
            plan,
            (VerificationStatus.MISMATCH, "rip-twice: second read differs"),
        )
        assert encode_calls == []
        num, ok, path, err = done[0]
        assert ok is False
        assert path == ""
        assert err.startswith("MISMATCH:")

    def test_verified_labels_done_and_encode_proceeds(self, tmp_path):
        plan = VerificationPlan(
            mode=RipVerificationMode.TWICE,
            toc=(_make_toc_entry(),),
        )
        task = self._task(tmp_path, plan)
        done = []
        task.done_cb = lambda num, ok, path, err: done.append((num, ok, path, err))
        from cd_ripper.core.accuraterip import VerificationStatus

        encode_calls = self._run_with_verify(
            tmp_path,
            task,
            plan,
            (VerificationStatus.VERIFIED, "rip-twice check passed"),
        )
        assert len(encode_calls) == 1
        num, ok, path, err = done[0]
        assert ok is True
        assert err == "VERIFIED"

    def test_no_entry_label_flows_to_done_when_encode_succeeds(self, tmp_path):
        plan = VerificationPlan(
            mode=RipVerificationMode.ACCURATERIP,
            lookup=LookupNotFound(reason="absent"),
            toc=(_make_toc_entry(),),
        )
        task = self._task(tmp_path, plan)
        done = []
        task.done_cb = lambda num, ok, path, err: done.append((num, ok, path, err))
        from cd_ripper.core.accuraterip import VerificationStatus

        self._run_with_verify(
            tmp_path,
            task,
            plan,
            (VerificationStatus.NO_ENTRY, "absent"),
        )
        num, ok, path, err = done[0]
        assert ok is True
        assert err == "NO_ENTRY"

    def test_off_mode_skips_verification_entirely(self, tmp_path):
        plan = VerificationPlan()  # mode OFF
        task = self._task(tmp_path, plan)
        done = []
        task.done_cb = lambda num, ok, path, err: done.append((num, ok, path, err))

        out_wav = str(tmp_path / "track.wav")
        Path(out_wav).write_bytes(b"RIFF" + b"\x00" * 44)
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = iter([])
        mock_proc.wait.return_value = 0

        with (
            patch("cd_ripper.core.encoding_pipeline.extract_track_scsi"),
            patch(
                "cd_ripper.core.encoding_pipeline.tempfile.mkstemp",
                return_value=(0, out_wav),
            ),
            patch("os.close"),
            patch("os.path.exists", return_value=True),
            patch("os.path.getsize", return_value=1000),
            patch(
                "cd_ripper.core.metadata_resolver.run_secure_popen",
                return_value=mock_proc,
            ),
            patch("os.makedirs"),
            patch(
                "cd_ripper.core.encoding_pipeline.verify_extracted_track"
            ) as mock_verify,
        ):
            task.run()
        mock_verify.assert_not_called()
        num, ok, path, err = done[0]
        assert ok is True
        assert err == ""

    def test_read_wav_failure_blocks_encode(self, tmp_path):
        plan = VerificationPlan(
            mode=RipVerificationMode.TWICE,
            toc=(_make_toc_entry(),),
        )
        task = self._task(tmp_path, plan)
        done = []
        task.done_cb = lambda num, ok, path, err: done.append((num, ok, path, err))

        out_wav = str(tmp_path / "track.wav")
        Path(out_wav).write_bytes(b"RIFF" + b"\x00" * 44)

        with (
            patch("cd_ripper.core.encoding_pipeline.extract_track_scsi"),
            patch(
                "cd_ripper.core.encoding_pipeline.tempfile.mkstemp",
                return_value=(0, out_wav),
            ),
            patch("os.close"),
            patch("os.path.exists", return_value=True),
            patch("os.path.getsize", return_value=1000),
            patch(
                "cd_ripper.core.encoding_pipeline.read_wav_pcm",
                side_effect=ValueError("not a RIFF/WAVE file"),
            ),
            patch("cd_ripper.core.metadata_resolver.run_secure_popen") as mock_popen,
            patch("os.makedirs"),
        ):
            task.run()
        mock_popen.assert_not_called()
        num, ok, path, err = done[0]
        assert ok is False
        assert "Verification failed" in err

    def test_verify_value_error_blocks_encode(self, tmp_path):
        plan = VerificationPlan(
            mode=RipVerificationMode.ACCURATERIP,
            lookup=LookupFound(entries=(), url="https://x.test/none"),
            toc=(_make_toc_entry(),),
        )
        task = self._task(tmp_path, plan)
        done = []
        task.done_cb = lambda num, ok, path, err: done.append((num, ok, path, err))

        out_wav = str(tmp_path / "track.wav")
        Path(out_wav).write_bytes(b"RIFF" + b"\x00" * 44)

        with (
            patch("cd_ripper.core.encoding_pipeline.extract_track_scsi"),
            patch(
                "cd_ripper.core.encoding_pipeline.tempfile.mkstemp",
                return_value=(0, out_wav),
            ),
            patch("os.close"),
            patch("os.path.exists", return_value=True),
            patch("os.path.getsize", return_value=1000),
            patch(
                "cd_ripper.core.encoding_pipeline.read_wav_pcm",
                return_value=b"\x11" * 2352,
            ),
            patch(
                "cd_ripper.core.encoding_pipeline.verify_extracted_track",
                side_effect=ValueError("verification TOC does not contain"),
            ),
            patch("cd_ripper.core.metadata_resolver.run_secure_popen") as mock_popen,
            patch("os.makedirs"),
        ):
            task.run()
        mock_popen.assert_not_called()
        num, ok, path, err = done[0]
        assert ok is False
        assert "Verification failed" in err


# ===========================================================================
# RipSession verification planning — one plan per disc, reused by every task
# ===========================================================================


class TestRipSessionVerificationPlan:
    def _session(self, tmp_path, verify_mode="off"):
        tracks = [_make_track(number=1)]
        return RipSession(
            drive="D:",
            tracks=tracks,
            out_dir=str(tmp_path),
            fmt="FLAC",
            quality_args=None,
            progress_cb=_noop,
            track_done_cb=_noop,
            session_done_cb=_noop,
            ffmpeg_path="ffmpeg",
            log_cb=_noop,
            verify_mode=verify_mode,
        )

    def test_default_mode_is_off(self, tmp_path):
        session = self._session(tmp_path)
        assert session.verify_mode is RipVerificationMode.OFF

    def test_string_modes_coerce_to_enum(self, tmp_path):
        assert self._session(tmp_path, "twice").verify_mode is RipVerificationMode.TWICE
        assert (
            self._session(tmp_path, "accuraterip").verify_mode
            is RipVerificationMode.ACCURATERIP
        )

    def test_invalid_mode_raises_value_error(self, tmp_path):
        with pytest.raises(ValueError):
            self._session(tmp_path, "banana")

    def test_enum_instance_is_kept(self, tmp_path):
        session = self._session(tmp_path, RipVerificationMode.TWICE)
        assert session.verify_mode is RipVerificationMode.TWICE

    def test_twice_plan_has_no_lookup_and_toc(self, tmp_path):
        toc = [_make_toc_entry(number=1), _make_toc_entry(number=2)]
        session = self._session(tmp_path, "twice")
        plan = session._build_verification_plan(toc)
        assert plan.mode is RipVerificationMode.TWICE
        assert plan.lookup is None
        assert plan.toc == tuple(toc)

    def test_empty_toc_skips_database_lookup(self, tmp_path):
        session = self._session(tmp_path, "accuraterip")
        with patch("cd_ripper.core.ripper.AccurateRipClient") as mock_client_cls:
            plan = session._build_verification_plan([])
        assert plan.mode is RipVerificationMode.ACCURATERIP
        assert plan.lookup is None
        assert plan.toc == ()
        mock_client_cls.assert_not_called()

    def test_accuraterip_plan_resolves_disc_ids_and_url(self, tmp_path):
        toc = [
            _make_toc_entry(number=1, start_lba=0, sectors=16875),
            _make_toc_entry(number=2, start_lba=16875, sectors=5475),
        ]
        session = self._session(tmp_path, "accuraterip")
        entries = (
            DBEntry(
                disc_id1=0,
                disc_id2=0,
                cddb_id=0,
                tracks=(DBTrackEntry(confidence=1, crc1=0, crc2=0),),
            ),
        )
        found = LookupFound(entries=entries, url="https://x.test/raw/0")
        log_lines = []
        session.log_cb = log_lines.append

        with patch("cd_ripper.core.ripper.AccurateRipClient") as mock_client_cls:
            mock_client_cls.return_value.resolve.return_value = found
            plan = session._build_verification_plan(toc)

        expected_ids = compute_disc_ids(
            [e["start_lba"] for e in toc],
            toc[-1]["start_lba"] + toc[-1]["sectors"],
        )
        mock_client_cls.return_value.resolve.assert_called_once_with(
            expected_ids.accuraterip_path
        )
        assert plan.mode is RipVerificationMode.ACCURATERIP
        assert isinstance(plan.lookup, LookupFound)
        assert plan.lookup.entries == entries
        assert plan.toc == tuple(toc)
        assert any("Disc ID" in line for line in log_lines)

    def test_accuraterip_offline_result_is_kept_for_degraded_rip(self, tmp_path):
        toc = [_make_toc_entry(number=1, start_lba=0, sectors=16875)]
        session = self._session(tmp_path, "accuraterip")
        offline = LookupOffline(reason="network down")
        session.log_cb = _noop
        with patch(
            "cd_ripper.core.ripper.AccurateRipClient",
            return_value=MagicMock(resolve=MagicMock(return_value=offline)),
        ):
            plan = session._build_verification_plan(toc)
        assert isinstance(plan.lookup, LookupOffline)
        assert plan.mode is RipVerificationMode.ACCURATERIP

    def test_session_passes_plan_into_each_task(self, tmp_path):
        captures = []

        class _CaptureTask:
            def __init__(self, **kwargs):
                captures.append(kwargs.get("verification"))

            def run(self):
                return None

        toc = [_make_toc_entry(number=1, start_lba=0, sectors=16875)]
        session = RipSession(
            drive="D:",
            tracks=[_make_track(number=1)],
            out_dir=str(tmp_path),
            fmt="FLAC",
            quality_args=None,
            progress_cb=_noop,
            track_done_cb=_noop,
            session_done_cb=_noop,
            ffmpeg_path="ffmpeg",
            log_cb=_noop,
            verify_mode="twice",
        )
        with (
            patch("cd_ripper.core.ripper.probe_ffmpeg", return_value={"version": "t"}),
            patch("cd_ripper.core.ripper.read_toc", return_value=toc),
            patch("cd_ripper.core.ripper.spin_down_drive"),
            patch("cd_ripper.core.ripper.RipTask", _CaptureTask),
        ):
            session._run()
        assert len(captures) == 1
        plan = captures[0]
        assert plan.mode is RipVerificationMode.TWICE
        assert plan.toc == tuple(toc)
