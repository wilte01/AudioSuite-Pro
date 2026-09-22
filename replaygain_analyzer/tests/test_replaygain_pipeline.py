"""
test_replaygain_pipeline.py
Tests for replaygain_analyzer.core.ffmpeg_metrics  (G-30a)
         replaygain_analyzer.core.file_processor   (G-30b)
         replaygain_analyzer.utils.cli_args        (new: auto_end wiring)

Changes vs original:
  - TestApplyReplaygainTags: adds dry-run behaviour tests (#14)
  - TestReplaygainRunAnalysis: adds dry-run propagation test (#14)
  - TestCliArgs: new class testing auto_end parsing (#16)
  - TestReplaygainProcessSingleFile: adds slot double-put regression test
"""

import os
import subprocess
import threading
from queue import Queue
from unittest.mock import MagicMock, patch

import pytest
from pydub import AudioSegment

from audio_suite_shared.exceptions import AudioFormatError
from replaygain_analyzer.core.ffmpeg_metrics import (
    _get_ffmpeg_exe,
    _get_startupinfo,
    get_metrics,
    get_resource_path,
)
from replaygain_analyzer.core.file_processor import (
    apply_replaygain_tags,
    process_single_file,
    run_analysis,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_audio(tmp_path, name: str = "track.mp3") -> str:
    path = tmp_path / name
    AudioSegment.silent(duration=100).export(str(path), format=name.rsplit(".", 1)[-1])
    return str(path)


def _make_slot_fixtures(n: int = 4) -> tuple[list, Queue]:
    slot_vars = [MagicMock() for _ in range(n)]
    slot_q: Queue = Queue()
    for i in range(n):
        slot_q.put(i)
    return slot_vars, slot_q


MOCK_STDERR_GOOD = (
    "  Summary:\n"
    "    Integrated loudness:\n"
    "      I:         -18.20 LUFS\n"
    "      Threshold: -28.35 LUFS\n"
    "    True peak:\n"
    "      Peak:       -1.45 dBFS\n"
)

MOCK_STDERR_NO_LUFS = "Some ffmpeg output with no ebur128 data"

MOCK_STDERR_NO_PEAK = (
    "  Summary:\n    Integrated loudness:\n      I:         -18.20 LUFS\n"
)


# ═════════════════════════════════════════════════════════════════════════════
# G-30a — ffmpeg_metrics
# ═════════════════════════════════════════════════════════════════════════════


class TestGetResourcePath:
    def test_returns_string(self) -> None:
        assert isinstance(get_resource_path("ffmpeg.exe"), str)

    def test_path_contains_relative_component(self) -> None:
        result = get_resource_path("ffmpeg.exe")
        assert "ffmpeg.exe" in result


class TestGetFfmpegExe:
    def test_returns_string(self) -> None:
        assert isinstance(_get_ffmpeg_exe(), str)

    def test_non_windows_returns_ffmpeg(self) -> None:
        with patch("audio_suite_shared.subprocess_utils.os.name", "posix"):
            assert _get_ffmpeg_exe() == "ffmpeg"

    def test_windows_with_no_local_exe_returns_ffmpeg(self) -> None:
        with (
            patch("audio_suite_shared.subprocess_utils.os.name", "nt"),
            patch(
                "replaygain_analyzer.core.ffmpeg_metrics.os.path.exists",
                return_value=False,
            ),
        ):
            assert _get_ffmpeg_exe() == "ffmpeg"

    def test_windows_with_local_exe_returns_local_path(self, tmp_path) -> None:
        local_exe = str(tmp_path / "ffmpeg.exe")
        open(local_exe, "w").close()
        with (
            patch("audio_suite_shared.subprocess_utils.os.name", "nt"),
            patch(
                "replaygain_analyzer.core.ffmpeg_metrics.get_resource_path",
                return_value=local_exe,
            ),
        ):
            result = _get_ffmpeg_exe()
        assert result == local_exe


class TestGetStartupInfo:
    def test_windows_returns_startupinfo(self) -> None:
        with patch(
            "audio_suite_shared.subprocess_utils.os.name",
            "nt",
        ):
            si = _get_startupinfo()
        assert si is not None
        assert si.dwFlags & subprocess.STARTF_USESHOWWINDOW

    def test_non_windows_returns_none(self) -> None:
        with patch("audio_suite_shared.subprocess_utils.os.name", "posix"):
            si = _get_startupinfo()
        assert si is None


class TestGetMetrics:
    def _mock_run(self, stderr: str, returncode: int = 0) -> MagicMock:
        mock_result = MagicMock()
        mock_result.returncode = returncode
        mock_result.stderr = stderr
        return mock_result

    def test_returns_tuple(self, tmp_path) -> None:
        f = tmp_path / "t.mp3"
        f.write_bytes(b"x")
        with patch(
            "replaygain_analyzer.core.ffmpeg_metrics.run_secure_subprocess",
            return_value=self._mock_run(MOCK_STDERR_GOOD),
        ):
            result = get_metrics(str(f))
        assert isinstance(result, tuple) and len(result) == 2

    def test_parses_lufs_value(self, tmp_path) -> None:
        f = tmp_path / "t.mp3"
        f.write_bytes(b"x")
        with patch(
            "replaygain_analyzer.core.ffmpeg_metrics.run_secure_subprocess",
            return_value=self._mock_run(MOCK_STDERR_GOOD),
        ):
            lufs, peak = get_metrics(str(f))
        assert lufs is not None
        assert abs(lufs - (-18.20)) < 0.01

    def test_parses_peak_value(self, tmp_path) -> None:
        f = tmp_path / "t.mp3"
        f.write_bytes(b"x")
        with patch(
            "replaygain_analyzer.core.ffmpeg_metrics.run_secure_subprocess",
            return_value=self._mock_run(MOCK_STDERR_GOOD),
        ):
            lufs, peak = get_metrics(str(f))
        assert abs(peak - (-1.45)) < 0.01

    def test_no_lufs_output_returns_none(self, tmp_path) -> None:
        f = tmp_path / "t.mp3"
        f.write_bytes(b"x")
        with patch(
            "replaygain_analyzer.core.ffmpeg_metrics.run_secure_subprocess",
            return_value=self._mock_run(MOCK_STDERR_NO_LUFS),
        ):
            lufs, peak = get_metrics(str(f))
        assert lufs is None
        assert peak == 0.0

    def test_ffmpeg_not_found_returns_none(self, tmp_path) -> None:
        f = tmp_path / "t.mp3"
        f.write_bytes(b"x")
        with patch(
            "replaygain_analyzer.core.ffmpeg_metrics.run_secure_subprocess",
            side_effect=FileNotFoundError("ffmpeg not found"),
        ):
            lufs, peak = get_metrics(str(f))
        assert lufs is None
        assert peak == 0.0

    def test_timeout_returns_none(self, tmp_path) -> None:
        import subprocess

        f = tmp_path / "t.mp3"
        f.write_bytes(b"x")
        with patch(
            "replaygain_analyzer.core.ffmpeg_metrics.run_secure_subprocess",
            side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=300),
        ):
            lufs, peak = get_metrics(str(f))
        assert lufs is None
        assert peak == 0.0

    def test_unexpected_exception_returns_none(self, tmp_path) -> None:
        f = tmp_path / "t.mp3"
        f.write_bytes(b"x")
        with patch(
            "replaygain_analyzer.core.ffmpeg_metrics.run_secure_subprocess",
            side_effect=OSError("unexpected"),
        ):
            lufs, peak = get_metrics(str(f))
        assert lufs is None

    def test_uses_normpath_on_file_path(self, tmp_path) -> None:
        f = tmp_path / "t.mp3"
        f.write_bytes(b"x")
        calls: list = []

        def fake_run(ffmpeg, args, **kw):
            cmd = [ffmpeg, *args]
            calls.append(cmd)
            return self._mock_run(MOCK_STDERR_GOOD)

        with patch(
            "replaygain_analyzer.core.ffmpeg_metrics.run_secure_subprocess",
            fake_run,
        ):
            get_metrics(str(f))
        assert os.path.normpath(str(f)) in calls[0]

    def test_multiple_lufs_matches_uses_last(self, tmp_path) -> None:
        f = tmp_path / "t.mp3"
        f.write_bytes(b"x")
        stderr = (
            "  I:  -20.00 LUFS\n"  # intermediate
            "  I:  -18.20 LUFS\n"  # final summary
        )
        with patch(
            "replaygain_analyzer.core.ffmpeg_metrics.run_secure_subprocess",
            return_value=self._mock_run(stderr),
        ):
            lufs, _ = get_metrics(str(f))
        assert abs(lufs - (-18.20)) < 0.01

    def test_peak_defaults_to_zero_when_not_in_output(self, tmp_path) -> None:
        f = tmp_path / "t.mp3"
        f.write_bytes(b"x")
        with patch(
            "replaygain_analyzer.core.ffmpeg_metrics.run_secure_subprocess",
            return_value=self._mock_run(MOCK_STDERR_NO_PEAK),
        ):
            lufs, peak = get_metrics(str(f))
        assert abs(lufs - (-18.20)) < 0.01
        assert peak == 0.0


# ═════════════════════════════════════════════════════════════════════════════
# G-30b — file_processor.process_single_file
# ═════════════════════════════════════════════════════════════════════════════


class TestReplaygainProcessSingleFile:
    def _call(
        self,
        tmp_path,
        name: str,
        lufs_return: tuple,
        album_data: dict | None = None,
    ) -> tuple:
        slot_vars, slot_q = _make_slot_fixtures()
        lock = threading.Lock()
        album_lock = threading.Lock()
        album_data = album_data if album_data is not None else {}
        progress: list = []

        with patch(
            "replaygain_analyzer.core.file_processor.get_metrics",
            return_value=lufs_return,
        ):
            process_single_file(
                file_name=name,
                folder_path=str(tmp_path),
                target_lufs=-16.0,
                slot_vars=slot_vars,
                slot_queue=slot_q,
                lock=lock,
                album_lock=album_lock,
                album_data=album_data,
                on_progress=lambda **kw: progress.append(kw),
            )
        return progress, album_data, slot_q

    def test_successful_measurement_stored_in_album_data(self, tmp_path) -> None:
        _make_audio(tmp_path, "t.mp3")
        _, album_data, _ = self._call(tmp_path, "t.mp3", (-18.0, -0.5))
        assert str(tmp_path) in album_data
        assert len(album_data[str(tmp_path)]) == 1

    def test_track_gain_calculated_correctly(self, tmp_path) -> None:
        _make_audio(tmp_path, "t.mp3")
        _, album_data, _ = self._call(tmp_path, "t.mp3", (-18.0, -0.5))
        entry = album_data[str(tmp_path)][0]
        assert abs(entry["track_gain"] - 2.0) < 1e-9

    def test_null_lufs_reports_error(self, tmp_path) -> None:
        _make_audio(tmp_path, "t.mp3")
        progress, _, _ = self._call(tmp_path, "t.mp3", (None, 0.0))
        assert any(r.get("n_errors", 0) == 1 for r in progress)

    def test_slot_returned_on_success(self, tmp_path) -> None:
        _make_audio(tmp_path, "t.mp3")
        _, _, slot_q = self._call(tmp_path, "t.mp3", (-18.0, -0.5))
        assert slot_q.qsize() == 4

    def test_slot_returned_on_null_lufs(self, tmp_path) -> None:
        _make_audio(tmp_path, "t.mp3")
        _, _, slot_q = self._call(tmp_path, "t.mp3", (None, 0.0))
        assert slot_q.qsize() == 4

    def test_slot_not_double_put_on_null_lufs(self, tmp_path) -> None:
        """Regression: original code had a manual slot_queue.put() before return
        AND a finally block that also put — causing qsize() > 4."""
        _make_audio(tmp_path, "t.mp3")
        _, _, slot_q = self._call(tmp_path, "t.mp3", (None, 0.0))
        assert slot_q.qsize() == 4, "Slot was double-put (qsize > 4)"

    def test_album_data_key_is_folder_path(self, tmp_path) -> None:
        _make_audio(tmp_path, "t.mp3")
        _, album_data, _ = self._call(tmp_path, "t.mp3", (-20.0, -1.0))
        assert str(tmp_path) in album_data

    def test_multiple_files_accumulate_in_album_data(self, tmp_path) -> None:
        album_data: dict = {}
        for i, name in enumerate(["a.mp3", "b.mp3", "c.mp3"]):
            _make_audio(tmp_path, name)
            slot_vars, slot_q = _make_slot_fixtures()
            with patch(
                "replaygain_analyzer.core.file_processor.get_metrics",
                return_value=(-18.0 - i, -0.5),
            ):
                process_single_file(
                    file_name=name,
                    folder_path=str(tmp_path),
                    target_lufs=-16.0,
                    slot_vars=slot_vars,
                    slot_queue=slot_q,
                    lock=threading.Lock(),
                    album_lock=threading.Lock(),
                    album_data=album_data,
                    on_progress=lambda **kw: None,
                )
        assert len(album_data[str(tmp_path)]) == 3

    def test_unexpected_exception_reports_error(self, tmp_path) -> None:
        _make_audio(tmp_path, "t.mp3")
        slot_vars, slot_q = _make_slot_fixtures()
        progress: list = []
        with patch(
            "replaygain_analyzer.core.file_processor.get_metrics",
            side_effect=OSError("ffmpeg crash"),
        ):
            process_single_file(
                file_name="t.mp3",
                folder_path=str(tmp_path),
                target_lufs=-16.0,
                slot_vars=slot_vars,
                slot_queue=slot_q,
                lock=threading.Lock(),
                album_lock=threading.Lock(),
                album_data={},
                on_progress=lambda **kw: progress.append(kw),
            )
        assert any(r.get("n_errors", 0) == 1 for r in progress)
        assert slot_q.qsize() == 4  # slot still released in finally


# ═════════════════════════════════════════════════════════════════════════════
# G-30b — file_processor.apply_replaygain_tags
# ═════════════════════════════════════════════════════════════════════════════


class TestApplyReplaygainTags:
    def _make_files_data(self, tmp_path, count: int = 2) -> list:
        files_data: list = []
        for i in range(count):
            name = f"t{i}.mp3"
            _make_audio(tmp_path, name)
            files_data.append(
                {
                    "name": name,
                    "path": str(tmp_path / name),
                    "lufs": -18.0,
                    "peak": -0.5,
                    "track_gain": 2.0,
                }
            )
        return files_data

    def test_on_folder_complete_called(self, tmp_path) -> None:
        files_data = self._make_files_data(tmp_path, 2)
        completions: list = []
        apply_replaygain_tags(
            folder_path=str(tmp_path),
            files_data=files_data,
            target_lufs=-16.0,
            is_dry_run=False,
            on_folder_complete=lambda **kw: completions.append(kw),
            lock=threading.Lock(),
        )
        assert len(completions) == 1

    def test_on_folder_complete_has_album_gain_str(self, tmp_path) -> None:
        files_data = self._make_files_data(tmp_path)
        completions: list = []
        apply_replaygain_tags(
            folder_path=str(tmp_path),
            files_data=files_data,
            target_lufs=-16.0,
            is_dry_run=False,
            on_folder_complete=lambda **kw: completions.append(kw),
            lock=threading.Lock(),
        )
        assert "album_gain_str" in completions[0]
        assert " dB" in completions[0]["album_gain_str"]

    def test_tag_results_length_matches_files(self, tmp_path) -> None:
        files_data = self._make_files_data(tmp_path, 3)
        completions: list = []
        apply_replaygain_tags(
            folder_path=str(tmp_path),
            files_data=files_data,
            target_lufs=-16.0,
            is_dry_run=False,
            on_folder_complete=lambda **kw: completions.append(kw),
            lock=threading.Lock(),
        )
        assert len(completions[0]["tag_results"]) == 3

    def test_all_files_tagged_in_live_mode(self, tmp_path) -> None:
        files_data = self._make_files_data(tmp_path, 2)
        completions: list = []
        apply_replaygain_tags(
            folder_path=str(tmp_path),
            files_data=files_data,
            target_lufs=-16.0,
            is_dry_run=False,
            on_folder_complete=lambda **kw: completions.append(kw),
            lock=threading.Lock(),
        )
        statuses = [r[1] for r in completions[0]["tag_results"]]
        assert all(s == "TAGGED" for s in statuses)

    def test_empty_files_data_skipped(self, tmp_path) -> None:
        completions: list = []
        apply_replaygain_tags(
            folder_path=str(tmp_path),
            files_data=[],
            target_lufs=-16.0,
            is_dry_run=False,
            on_folder_complete=lambda **kw: completions.append(kw),
            lock=threading.Lock(),
        )
        assert len(completions) == 0

    def test_log_header_contains_folder_path(self, tmp_path) -> None:
        files_data = self._make_files_data(tmp_path, 1)
        completions: list = []
        apply_replaygain_tags(
            folder_path=str(tmp_path),
            files_data=files_data,
            target_lufs=-16.0,
            is_dry_run=False,
            on_folder_complete=lambda **kw: completions.append(kw),
            lock=threading.Lock(),
        )
        assert str(tmp_path) in completions[0]["log_header"]

    # ── New: dry-run behaviour tests (finding #14) ────────────────────────────

    def test_dry_run_status_is_dry_run(self, tmp_path) -> None:
        """In dry-run mode all statuses must be 'DRY RUN', never 'TAGGED'."""
        files_data = self._make_files_data(tmp_path, 2)
        completions: list = []
        apply_replaygain_tags(
            folder_path=str(tmp_path),
            files_data=files_data,
            target_lufs=-16.0,
            is_dry_run=True,
            on_folder_complete=lambda **kw: completions.append(kw),
            lock=threading.Lock(),
        )
        statuses = [r[1] for r in completions[0]["tag_results"]]
        assert all(s == "DRY RUN" for s in statuses)

    def test_dry_run_does_not_call_write_replaygain_tags(self, tmp_path) -> None:
        """Verify that tag_writer.write_replaygain_tags is NEVER called in dry-run."""
        files_data = self._make_files_data(tmp_path, 2)
        with patch(
            "replaygain_analyzer.core.file_processor.write_replaygain_tags"
        ) as mock_write:
            apply_replaygain_tags(
                folder_path=str(tmp_path),
                files_data=files_data,
                target_lufs=-16.0,
                is_dry_run=True,
                on_folder_complete=lambda **kw: None,
                lock=threading.Lock(),
            )
        mock_write.assert_not_called()

    def test_live_mode_does_call_write_replaygain_tags(self, tmp_path) -> None:
        """Verify that tag_writer.write_replaygain_tags IS called in live mode."""
        files_data = self._make_files_data(tmp_path, 2)
        with patch(
            "replaygain_analyzer.core.file_processor.write_replaygain_tags",
            return_value=(True, "TAGGED"),
        ) as mock_write:
            apply_replaygain_tags(
                folder_path=str(tmp_path),
                files_data=files_data,
                target_lufs=-16.0,
                is_dry_run=False,
                on_folder_complete=lambda **kw: None,
                lock=threading.Lock(),
            )
        assert mock_write.call_count == len(files_data)

    def test_dry_run_result_still_includes_track_gain_str(self, tmp_path) -> None:
        """tag_results tuples must still carry gain/peak strings in dry-run."""
        files_data = self._make_files_data(tmp_path, 1)
        completions: list = []
        apply_replaygain_tags(
            folder_path=str(tmp_path),
            files_data=files_data,
            target_lufs=-16.0,
            is_dry_run=True,
            on_folder_complete=lambda **kw: completions.append(kw),
            lock=threading.Lock(),
        )
        _, status, track_gain_str, track_peak_str = completions[0]["tag_results"][0]
        assert " dB" in track_gain_str
        assert "." in track_peak_str

    # ── New: one bad file must not abort the folder/run ───────────────────────
    #
    # Regression coverage: _write_tags_for_file previously re-raised after
    # recording an ERROR result, which propagated out of apply_replaygain_tags
    # uncaught — aborting the entire folder (and, one level up, the entire
    # run_analysis loop over all remaining folders) on a single tag-write
    # failure, with no error dialog and a frozen GUI.

    def test_one_failed_file_does_not_raise(self, tmp_path) -> None:
        """A single write_replaygain_tags failure must not propagate."""
        files_data = self._make_files_data(tmp_path, 2)
        with patch(
            "replaygain_analyzer.core.file_processor.write_replaygain_tags",
            side_effect=[(False, "simulated failure"), (True, "TAGGED")],
        ):
            apply_replaygain_tags(
                folder_path=str(tmp_path),
                files_data=files_data,
                target_lufs=-16.0,
                is_dry_run=False,
                on_folder_complete=lambda **kw: None,
                lock=threading.Lock(),
            )  # must not raise

    def test_one_failed_file_still_processes_remaining_files(self, tmp_path) -> None:
        """The second file in the same folder must still be TAGGED."""
        files_data = self._make_files_data(tmp_path, 2)
        completions: list = []
        with patch(
            "replaygain_analyzer.core.file_processor.write_replaygain_tags",
            side_effect=[(False, "simulated failure"), (True, "TAGGED")],
        ):
            apply_replaygain_tags(
                folder_path=str(tmp_path),
                files_data=files_data,
                target_lufs=-16.0,
                is_dry_run=False,
                on_folder_complete=lambda **kw: completions.append(kw),
                lock=threading.Lock(),
            )
        statuses = [r[1] for r in completions[0]["tag_results"]]
        assert statuses == ["ERROR", "TAGGED"]

    def test_failed_file_result_retains_computed_gain_and_peak(self, tmp_path) -> None:
        """An ERROR row from a normal write failure still shows real gain/peak,
        not blank values — the file was measured, only the tag write failed."""
        files_data = self._make_files_data(tmp_path, 1)
        completions: list = []
        with patch(
            "replaygain_analyzer.core.file_processor.write_replaygain_tags",
            return_value=(False, "simulated failure"),
        ):
            apply_replaygain_tags(
                folder_path=str(tmp_path),
                files_data=files_data,
                target_lufs=-16.0,
                is_dry_run=False,
                on_folder_complete=lambda **kw: completions.append(kw),
                lock=threading.Lock(),
            )
        _, status, track_gain_str, track_peak_str = completions[0]["tag_results"][0]
        assert status == "ERROR"
        assert " dB" in track_gain_str
        assert track_peak_str != ""

    def test_on_folder_complete_still_called_after_failure(self, tmp_path) -> None:
        """on_folder_complete must still fire even when one file errors,
        so the run proceeds to the next folder instead of hanging."""
        files_data = self._make_files_data(tmp_path, 2)
        completions: list = []
        with patch(
            "replaygain_analyzer.core.file_processor.write_replaygain_tags",
            side_effect=[(False, "simulated failure"), (True, "TAGGED")],
        ):
            apply_replaygain_tags(
                folder_path=str(tmp_path),
                files_data=files_data,
                target_lufs=-16.0,
                is_dry_run=False,
                on_folder_complete=lambda **kw: completions.append(kw),
                lock=threading.Lock(),
            )
        assert len(completions) == 1

    def test_unexpected_tag_write_exception_records_error(self, tmp_path) -> None:
        files_data = self._make_files_data(tmp_path, 1)
        completions: list = []
        with patch(
            "replaygain_analyzer.core.file_processor.write_replaygain_tags",
            side_effect=OSError("unexpected write error"),
        ):
            apply_replaygain_tags(
                folder_path=str(tmp_path),
                files_data=files_data,
                target_lufs=-16.0,
                is_dry_run=False,
                on_folder_complete=lambda **kw: completions.append(kw),
                lock=threading.Lock(),
            )
        assert len(completions) == 1
        _, status, _, _ = completions[0]["tag_results"][0]
        assert status == "ERROR"


# ═════════════════════════════════════════════════════════════════════════════
# G-30b — apply_lossless_gain post-tag application
# ═════════════════════════════════════════════════════════════════════════════


class TestApplyReplaygainTagsLosslessGain:
    """apply_lossless_gain flag: bake track gain into MP3 files after tagging."""

    def _make_files_data(self, tmp_path, name: str = "track.mp3") -> list:
        path = _make_audio(tmp_path, name)
        return [
            {
                "name": name,
                "path": path,
                "lufs": -18.0,
                "peak": -0.5,
                "track_gain": 2.0,
            }
        ]

    def test_mp3_gain_applied_status(self, tmp_path) -> None:
        files_data = self._make_files_data(tmp_path)
        completions: list = []
        apply_replaygain_tags(
            folder_path=str(tmp_path),
            files_data=files_data,
            target_lufs=-16.0,
            is_dry_run=False,
            on_folder_complete=lambda **kw: completions.append(kw),
            lock=threading.Lock(),
            apply_lossless_gain=True,
        )
        assert completions[0]["tag_results"][0][1] == "TAGGED + GAIN APPLIED"

    def test_non_mp3_not_applied(self, tmp_path) -> None:
        """FLAC files get tags but not lossless gain (no lossless path)."""
        flac = tmp_path / "track.flac"
        AudioSegment.silent(duration=100).export(str(flac), format="flac")
        files_data = [
            {
                "name": "track.flac",
                "path": str(flac),
                "lufs": -18.0,
                "peak": -0.5,
                "track_gain": 2.0,
            }
        ]
        completions: list = []
        apply_replaygain_tags(
            folder_path=str(tmp_path),
            files_data=files_data,
            target_lufs=-16.0,
            is_dry_run=False,
            on_folder_complete=lambda **kw: completions.append(kw),
            lock=threading.Lock(),
            apply_lossless_gain=True,
        )
        assert completions[0]["tag_results"][0][1] == "TAGGED"

    def test_dry_run_skips_apply(self, tmp_path) -> None:
        files_data = self._make_files_data(tmp_path)
        completions: list = []
        apply_replaygain_tags(
            folder_path=str(tmp_path),
            files_data=files_data,
            target_lufs=-16.0,
            is_dry_run=True,
            on_folder_complete=lambda **kw: completions.append(kw),
            lock=threading.Lock(),
            apply_lossless_gain=True,
        )
        assert completions[0]["tag_results"][0][1] == "DRY RUN"

    def test_apply_failure_sets_error_status(self, tmp_path) -> None:
        files_data = self._make_files_data(tmp_path)
        completions: list = []
        with (
            patch(
                "replaygain_analyzer.core.file_processor.apply_track_gain",
                side_effect=AudioFormatError("no frames"),
            ),
        ):
            apply_replaygain_tags(
                folder_path=str(tmp_path),
                files_data=files_data,
                target_lufs=-16.0,
                is_dry_run=False,
                on_folder_complete=lambda **kw: completions.append(kw),
                lock=threading.Lock(),
                apply_lossless_gain=True,
            )
        assert completions[0]["tag_results"][0][1] == "ERROR"

    def test_apply_not_called_when_flag_false(self, tmp_path) -> None:
        files_data = self._make_files_data(tmp_path)
        with patch(
            "replaygain_analyzer.core.file_processor.apply_track_gain"
        ) as mock_apply:
            apply_replaygain_tags(
                folder_path=str(tmp_path),
                files_data=files_data,
                target_lufs=-16.0,
                is_dry_run=False,
                on_folder_complete=lambda **kw: None,
                lock=threading.Lock(),
                apply_lossless_gain=False,
            )
        mock_apply.assert_not_called()

    def test_apply_receives_track_gain_value(self, tmp_path) -> None:
        files_data = self._make_files_data(tmp_path)
        with patch(
            "replaygain_analyzer.core.file_processor.apply_track_gain",
            return_value=1,
        ) as mock_apply:
            apply_replaygain_tags(
                folder_path=str(tmp_path),
                files_data=files_data,
                target_lufs=-16.0,
                is_dry_run=False,
                on_folder_complete=lambda **kw: None,
                lock=threading.Lock(),
                apply_lossless_gain=True,
            )
        mock_apply.assert_called_once_with(files_data[0]["path"], 2.0)

    def test_tag_write_failure_skips_gain_application(self, tmp_path) -> None:
        """When tag write fails, gain must not be applied."""
        files_data = self._make_files_data(tmp_path)
        completions: list = []
        with (
            patch(
                "replaygain_analyzer.core.file_processor.write_replaygain_tags",
                return_value=(False, "tag write failed"),
            ),
            patch(
                "replaygain_analyzer.core.file_processor.apply_track_gain"
            ) as mock_apply,
        ):
            apply_replaygain_tags(
                folder_path=str(tmp_path),
                files_data=files_data,
                target_lufs=-16.0,
                is_dry_run=False,
                on_folder_complete=lambda **kw: completions.append(kw),
                lock=threading.Lock(),
                apply_lossless_gain=True,
            )
        mock_apply.assert_not_called()
        assert completions[0]["tag_results"][0][1] == "ERROR"


# ═════════════════════════════════════════════════════════════════════════════
# G-30b — file_processor.run_analysis
# ═════════════════════════════════════════════════════════════════════════════


class TestReplaygainRunAnalysis:
    def _run(
        self,
        tmp_path,
        lufs_return: tuple = (-18.0, -0.5),
        is_dry_run: bool = False,
    ) -> tuple:
        slot_vars, slot_q = _make_slot_fixtures()
        file_progress: list = []
        folder_complete: list = []
        complete: list = []
        errors: list = []

        with patch(
            "replaygain_analyzer.core.file_processor.get_metrics",
            return_value=lufs_return,
        ):
            run_analysis(
                dir_path=str(tmp_path),
                target_lufs=-16.0,
                is_dry_run=is_dry_run,
                slot_vars=slot_vars,
                slot_queue=slot_q,
                on_progress=lambda **kw: file_progress.append(kw),
                on_folder_complete=lambda **kw: folder_complete.append(kw),
                on_complete=lambda **kw: complete.append(kw),
                on_error=lambda msg: errors.append(msg),
            )
        return file_progress, folder_complete, complete, errors

    def test_empty_directory_calls_on_error(self, tmp_path) -> None:
        _, _, _, errors = self._run(tmp_path)
        assert len(errors) == 1
        assert "No audio" in errors[0]

    def test_on_complete_called(self, tmp_path) -> None:
        _make_audio(tmp_path, "t.mp3")
        _, _, complete, _ = self._run(tmp_path)
        assert len(complete) == 1

    def test_total_matches_file_count(self, tmp_path) -> None:
        for i in range(3):
            _make_audio(tmp_path, f"t{i}.mp3")
        _, _, complete, _ = self._run(tmp_path)
        assert complete[0]["total"] == 3

    def test_on_folder_complete_called_per_folder(self, tmp_path) -> None:
        _make_audio(tmp_path, "t.mp3")
        _, folder_complete, _, _ = self._run(tmp_path)
        assert len(folder_complete) == 1

    def test_null_lufs_counted_as_error(self, tmp_path) -> None:
        _make_audio(tmp_path, "t.mp3")
        _, _, complete, _ = self._run(tmp_path, lufs_return=(None, 0.0))
        assert complete[0]["errors"] == 1

    def test_nonexistent_directory_calls_on_error(self, tmp_path) -> None:
        slot_vars, slot_q = _make_slot_fixtures()
        errors: list = []
        run_analysis(
            dir_path=str(tmp_path / "missing"),
            target_lufs=-16.0,
            is_dry_run=False,
            slot_vars=slot_vars,
            slot_queue=slot_q,
            on_progress=lambda **kw: None,
            on_folder_complete=lambda **kw: None,
            on_complete=lambda **kw: None,
            on_error=errors.append,
        )
        assert len(errors) == 1

    def test_log_entries_populated(self, tmp_path) -> None:
        _make_audio(tmp_path, "t.mp3")
        _, _, complete, _ = self._run(tmp_path)
        assert isinstance(complete[0]["log_entries"], list)
        assert len(complete[0]["log_entries"]) > 0

    def test_dry_run_propagated_to_tag_results(self, tmp_path) -> None:
        """run_analysis with is_dry_run=True must produce DRY RUN statuses."""
        _make_audio(tmp_path, "t.mp3")
        _, folder_complete, _, _ = self._run(tmp_path, is_dry_run=True)
        assert len(folder_complete) == 1
        statuses = [r[1] for r in folder_complete[0]["tag_results"]]
        assert all(s == "DRY RUN" for s in statuses)

    def test_multiple_folders_each_get_on_folder_complete(self, tmp_path) -> None:
        sub1 = tmp_path / "sub1"
        sub1.mkdir()
        sub2 = tmp_path / "sub2"
        sub2.mkdir()
        _make_audio(sub1, "a.mp3")
        _make_audio(sub1, "b.mp3")
        _make_audio(sub2, "c.mp3")

        slot_vars, slot_q = _make_slot_fixtures()
        folder_complete: list = []
        complete: list = []
        errors: list = []

        with patch(
            "replaygain_analyzer.core.file_processor.get_metrics",
            return_value=(-18.0, -0.5),
        ):
            run_analysis(
                dir_path=str(tmp_path),
                target_lufs=-16.0,
                is_dry_run=False,
                slot_vars=slot_vars,
                slot_queue=slot_q,
                on_progress=lambda **kw: None,
                on_folder_complete=lambda **kw: folder_complete.append(kw),
                on_complete=lambda **kw: complete.append(kw),
                on_error=errors.append,
            )
        assert len(errors) == 0
        assert len(folder_complete) == 2
        assert complete[0]["total"] == 3

    def test_os_walk_failure_calls_on_error(self, tmp_path) -> None:
        slot_vars, slot_q = _make_slot_fixtures()
        errors: list = []
        with patch(
            "replaygain_analyzer.core.file_processor.os.walk",
            side_effect=PermissionError("access denied"),
        ):
            run_analysis(
                dir_path=str(tmp_path),
                target_lufs=-16.0,
                is_dry_run=False,
                slot_vars=slot_vars,
                slot_queue=slot_q,
                on_progress=lambda **kw: None,
                on_folder_complete=lambda **kw: None,
                on_complete=lambda **kw: None,
                on_error=errors.append,
            )
        assert len(errors) == 1

    def test_apply_lossless_gain_forwarded_to_write_worker(self, tmp_path) -> None:
        """apply_lossless_gain=True triggers apply_track_gain for MP3 files."""
        _make_audio(tmp_path, "t.mp3")
        with (
            patch(
                "replaygain_analyzer.core.file_processor.get_metrics",
                return_value=(-18.0, -0.5),
            ),
            patch(
                "replaygain_analyzer.core.file_processor.apply_track_gain",
                return_value=1,
            ) as mock_apply,
        ):
            run_analysis(
                dir_path=str(tmp_path),
                target_lufs=-16.0,
                is_dry_run=False,
                slot_vars=_make_slot_fixtures()[0],
                slot_queue=_make_slot_fixtures()[1],
                on_progress=lambda **kw: None,
                on_folder_complete=lambda **kw: None,
                on_complete=lambda **kw: None,
                on_error=lambda msg: None,
                apply_lossless_gain=True,
            )
        mock_apply.assert_called_once()


# ═════════════════════════════════════════════════════════════════════════════
# G-30b — Undo-batch recording (record side of undo feature)
# ═════════════════════════════════════════════════════════════════════════════


class TestUndoBatchRecording:
    def test_live_run_records_snapshots_from_worker_threads(self, tmp_path) -> None:
        """run_analysis must record tag snapshots from its Phase 2 worker
        thread into the active undo batch (via use_batch)."""
        from audio_suite_shared.batch_undo import active_batch, list_recent_batches

        undo_db = tmp_path / "undo_log.db"
        _make_audio(tmp_path, "t1.mp3")
        _make_audio(tmp_path, "t2.mp3")

        slot_vars, slot_q = _make_slot_fixtures()
        handler = MagicMock()
        handler.get_raw_tags.return_value = {"REPLAYGAIN_TRACK_GAIN": "old"}

        # record_tag_edit_snapshot resolves TagHandlerFactory lazily from
        # tag_helper_base on the worker thread; patch it so the snapshot
        # reads hit the mock handler deterministically.
        shared_factory = MagicMock()
        shared_factory.get_handler.return_value = handler
        with (
            patch(
                "replaygain_analyzer.core.file_processor.get_metrics",
                return_value=(-18.0, -0.5),
            ),
            patch(
                "audio_suite_shared.tag_helper_base.TagHandlerFactory",
                shared_factory,
            ),
        ):
            with active_batch("replaygain_analyzer", "tag_edit", db_path=undo_db):
                run_analysis(
                    dir_path=str(tmp_path),
                    target_lufs=-16.0,
                    is_dry_run=False,
                    slot_vars=slot_vars,
                    slot_queue=slot_q,
                    on_progress=lambda **kw: None,
                    on_folder_complete=lambda **kw: None,
                    on_complete=lambda **kw: None,
                    on_error=lambda msg: None,
                )

        batches = list_recent_batches(limit=10, db_path=undo_db)
        assert len(batches) == 1
        assert batches[0].tool_name == "replaygain_analyzer"
        assert batches[0].operation_type == "tag_edit"
        assert batches[0].record_count == 2

    def test_apply_lossless_gain_bake_is_undo_recorded(self, tmp_path) -> None:
        """--apply-gain bake must leave the file in the undo batch.

        record_tag_edit keeps only the FIRST snapshot per (batch, file), so
        the bake's lossless_gain_track snapshot dedupes into the
        write_replaygain record the tag writer took moments earlier.  Assert
        on the file's presence and snapshot — not the operation name.
        """
        from audio_suite_shared.batch_undo import (
            BatchUndoLog,
            active_batch,
            list_recent_batches,
        )

        undo_db = tmp_path / "undo_log.db"
        _make_audio(tmp_path, "t1.mp3")

        slot_vars, slot_q = _make_slot_fixtures()
        handler = MagicMock()
        handler.get_raw_tags.return_value = {"REPLAYGAIN_TRACK_GAIN": "old"}

        shared_factory = MagicMock()
        shared_factory.get_handler.return_value = handler
        with (
            patch(
                "replaygain_analyzer.core.file_processor.get_metrics",
                return_value=(-18.0, -0.5),
            ),
            patch(
                "audio_suite_shared.tag_helper_base.TagHandlerFactory",
                shared_factory,
            ),
        ):
            with active_batch("replaygain_analyzer", "tag_edit", db_path=undo_db):
                run_analysis(
                    dir_path=str(tmp_path),
                    target_lufs=-16.0,
                    is_dry_run=False,
                    slot_vars=slot_vars,
                    slot_queue=slot_q,
                    on_progress=lambda **kw: None,
                    on_folder_complete=lambda **kw: None,
                    on_complete=lambda **kw: None,
                    on_error=lambda msg: None,
                    apply_lossless_gain=True,
                )

        batches = list_recent_batches(limit=10, db_path=undo_db)
        assert len(batches) == 1
        records = BatchUndoLog(db_path=undo_db).get_batch_records(batches[0].batch_id)
        baked = [r for r in records if r.file_path.endswith("t1.mp3")]
        assert baked, "baked file has no undo record"
        assert all(r.has_snapshot for r in baked)

    def test_dry_run_creates_no_batch_records(self, tmp_path) -> None:
        """A dry run performs no writes, so the batch is pruned on exit."""
        from audio_suite_shared.batch_undo import active_batch, list_recent_batches

        undo_db = tmp_path / "undo_log.db"
        _make_audio(tmp_path, "t1.mp3")

        slot_vars, slot_q = _make_slot_fixtures()
        with patch(
            "replaygain_analyzer.core.file_processor.get_metrics",
            return_value=(-18.0, -0.5),
        ):
            with active_batch("replaygain_analyzer", "tag_edit", db_path=undo_db):
                run_analysis(
                    dir_path=str(tmp_path),
                    target_lufs=-16.0,
                    is_dry_run=True,
                    slot_vars=slot_vars,
                    slot_queue=slot_q,
                    on_progress=lambda **kw: None,
                    on_folder_complete=lambda **kw: None,
                    on_complete=lambda **kw: None,
                    on_error=lambda msg: None,
                )

        assert list_recent_batches(limit=10, db_path=undo_db) == []


# ═════════════════════════════════════════════════════════════════════════════
# CLI args — auto_end wiring (finding #16)
# ═════════════════════════════════════════════════════════════════════════════


class TestCliArgs:
    """Verify that auto_end is correctly parsed from argv[5] (finding #16)."""

    def test_auto_end_set_true_when_end_flag_present(self, tmp_path) -> None:
        from replaygain_analyzer.utils.cli_args import parse

        argv = [
            "prog",
            str(tmp_path),
            "-16.0",
            "--live",
            "--start",
            "--end",
        ]
        args = parse(argv)
        assert args.auto_end is True

    def test_auto_end_set_false_when_no_end_flag(self, tmp_path) -> None:
        from replaygain_analyzer.utils.cli_args import parse

        argv = [
            "prog",
            str(tmp_path),
            "-16.0",
            "--live",
            "--start",
            "--no-end",
        ]
        args = parse(argv)
        assert args.auto_end is False

    def test_auto_end_defaults_false_when_argv_short(self, tmp_path) -> None:
        from replaygain_analyzer.utils.cli_args import parse

        # Only folder path supplied — auto_end must remain the dataclass default
        args = parse(["prog", str(tmp_path)])
        assert args.auto_end is False

    def test_target_lufs_parsed_correctly(self, tmp_path) -> None:
        from replaygain_analyzer.utils.cli_args import parse

        args = parse(
            ["prog", str(tmp_path), "-23.0", "--dry", "--no-start", "--no-end"]
        )
        assert abs(args.target_lufs - (-23.0)) < 1e-9

    def test_invalid_lufs_keeps_default(self, tmp_path) -> None:
        from replaygain_analyzer.utils.cli_args import parse

        # Non-float argv[2] should silently keep the default
        args = parse(["prog", str(tmp_path), "not-a-float"])
        assert args.target_lufs == -16.0

    def test_non_preset_lufs_value_exits(self, tmp_path) -> None:
        from replaygain_analyzer.utils.cli_args import parse

        # -20.0 is a valid float but not one of the 5 supported presets
        # (-12.0, -14.0, -16.0, -18.0, -23.0); validate_target_lufs must
        # reject it rather than silently accepting any in-range float.
        with pytest.raises(SystemExit):
            parse(["prog", str(tmp_path), "-20.0"])

    def test_validate_args_returns_empty_for_defaults(self) -> None:
        from replaygain_analyzer.utils.cli_args import ReplayGainArgs, validate_args

        args = ReplayGainArgs()
        errors = validate_args(args)

        # Empty folder_path + default -16.0 are both valid
        assert errors == []

    def test_validate_args_reports_invalid_path_and_lufs(self) -> None:
        from replaygain_analyzer.utils.cli_args import ReplayGainArgs, validate_args

        args = ReplayGainArgs(folder_path="/no/such/path_xyz", target_lufs=-20.0)
        errors = validate_args(args)

        assert len(errors) == 2
        assert any("not exist" in e for e in errors)
        assert any("Target LUFS" in e for e in errors)
