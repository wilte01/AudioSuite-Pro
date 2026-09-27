"""
test_batch_analysis_engine.py
Pytest suite for mood_analysis_batch_tagger.core.batch_analysis_engine.

Covers:
  - _collect_audio_files  (recursive scan, extension filter, sorting, errors)
  - _determine_folder_plan
  - _analyse_file         (imported from mood_analyzer.core.file_processor)
  - _write_tags / _write_tags_from_result
  - _analyse_audio_cpu    (process-pool worker)
  - run_batch             (dry-run, live, empty, scan error, stop event,
                           thread-pool and process-pool dispatch)
  - _run_process_pool     (really executed: real child processes, real
                           decoded audio, ordering, progress, worker-slot
                           accounting, error mapping, cancellation)
  - worker slot status    (Analyzing/Tagging labels, run_with_retry wiring)
  - BatchResult summary

All heavy dependencies (load_analysis_audio, analyze_mood, tag writes) are
mocked so the suite runs quickly and standalone.
"""

from __future__ import annotations

import inspect
import os
import pickle
import queue
import threading
import wave
from collections.abc import Callable
from contextlib import ExitStack
from unittest.mock import patch

import numpy as np
import pytest

from audio_suite_shared.exceptions import (
    AudioAnalysisError,
    AudioDirectoryError,
    user_message_for,
)
from audio_suite_shared.tag_helper_reader import read_energy, read_mood
from mood_analyzer.core.signal_mood_engine import MoodAnalysis

MODULE = "mood_analysis_batch_tagger.core.batch_analysis_engine"

from mood_analysis_batch_tagger.core import batch_analysis_engine  # noqa: E402

_SR = 22050
_FAKE_ANALYSIS = MoodAnalysis(
    valence=0.7,
    arousal=0.7,
    mood_words=("Energetic", "Bright", "Confident"),
    confidence=0.87,
    energy=5,
)

_TEST_EXTENSIONS = (
    ".mp3",
    ".flac",
    ".ogg",
    ".m4a",
    ".wav",
    ".aiff",
    ".aif",
    ".opus",
    ".mp4",
)


def _drain(q: queue.Queue[object]) -> list[tuple]:
    msgs: list[tuple] = []
    while True:
        try:
            msgs.append(q.get_nowait())
        except queue.Empty:
            break
    return msgs


def _run(
    root: str,
    live: bool = True,
    parallel: bool = False,
    duration: int = 90,
) -> tuple[list[tuple], list[MoodAnalysis]]:
    """Run run_batch with _analyse_file and tag writes mocked."""
    q: queue.Queue[object] = queue.Queue()
    stop = threading.Event()

    def _fake_analyse_file(path: str, d: int) -> MoodAnalysis:
        return _FAKE_ANALYSIS

    with (
        patch(f"{MODULE}._analyse_file", side_effect=_fake_analyse_file),
        patch(f"{MODULE}._write_tags"),
    ):
        batch_analysis_engine.run_batch(
            root,
            q,
            stop,
            live=live,
            analysis_duration=duration,
            parallel_mode=parallel,
            max_workers=2,
        )
    return _drain(q), []


def _make_file(path: str) -> str:
    import os

    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"dummy")
    return path


# ═════════════════════════════════════════════════════════════════════════════
# _collect_audio_files
# ═════════════════════════════════════════════════════════════════════════════


class TestCollectAudioFiles:
    def test_finds_supported_extensions_case_insensitive(self, tmp_path) -> None:
        for name, ext in (
            ("a", ".mp3"),
            ("b", ".MP3"),
            ("c", ".flac"),
            ("d", ".FLAC"),
            ("e", ".ogg"),
            ("f", ".m4a"),
            ("g", ".wav"),
        ):
            (tmp_path / f"{name}{ext}").touch()
        (tmp_path / "notes.txt").touch()
        names = [
            os.path.basename(p)
            for p in batch_analysis_engine._collect_audio_files(str(tmp_path))
        ]
        assert "a.mp3" in names
        assert "b.MP3" in names
        assert "c.flac" in names
        assert "d.FLAC" in names
        assert "e.ogg" in names
        assert "f.m4a" in names
        assert "g.wav" in names
        assert "notes.txt" not in names

    def test_recurses_subdirectories(self, tmp_path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (tmp_path / "root.mp3").touch()
        (sub / "nested.flac").touch()
        assert len(batch_analysis_engine._collect_audio_files(str(tmp_path))) == 2

    def test_sorted_by_folder_then_name(self, tmp_path) -> None:
        sub_a = tmp_path / "z_folder"
        sub_b = tmp_path / "a_folder"
        sub_a.mkdir()
        sub_b.mkdir()
        (sub_b / "z.mp3").touch()
        (sub_b / "a.mp3").touch()
        (sub_a / "m.flac").touch()
        filenames = [
            os.path.basename(p)
            for p in batch_analysis_engine._collect_audio_files(str(tmp_path))
        ]
        assert filenames.index("a.mp3") < filenames.index("m.flac")
        assert filenames.index("a.mp3") < filenames.index("z.mp3")
        assert filenames.index("z.mp3") < filenames.index("m.flac")

    def test_empty_directory(self, tmp_path) -> None:
        assert batch_analysis_engine._collect_audio_files(str(tmp_path)) == []

    def test_covers_shared_supported_extensions(self) -> None:
        from audio_suite_shared.tag_helper import SUPPORTED_EXTENSIONS

        for ext in SUPPORTED_EXTENSIONS:
            assert ext in _TEST_EXTENSIONS

    def test_raises_audio_directory_error_on_nonexistent_root(self) -> None:
        with pytest.raises(AudioDirectoryError):
            batch_analysis_engine._collect_audio_files("/nonexistent/__nope__")


# ═════════════════════════════════════════════════════════════════════════════
# _determine_folder_plan
# ═════════════════════════════════════════════════════════════════════════════


class TestDetermineFolderPlan:
    def test_groups_by_folder(self, tmp_path) -> None:
        root = str(tmp_path)
        sub = tmp_path / "sub"
        sub.mkdir()
        files = [
            os.path.join(root, "a.mp3"),
            os.path.join(root, "b.flac"),
            os.path.join(str(sub), "c.wav"),
        ]
        plan = batch_analysis_engine._determine_folder_plan(files)
        assert [p for p, _ in plan] == [root, str(sub)]
        assert dict(plan)[root] == 2
        assert dict(plan)[str(sub)] == 1

    def test_empty_returns_empty(self) -> None:
        assert batch_analysis_engine._determine_folder_plan([]) == []


# ═════════════════════════════════════════════════════════════════════════════
# _analyse_file
# ═════════════════════════════════════════════════════════════════════════════


class TestAnalyseFile:
    def test_is_mood_analyzer_function(self) -> None:
        """The batch engine must reuse mood_analyzer's analysis function, not
        re-implement it, so results are identical by construction."""
        from mood_analyzer.core.file_processor import _analyse_file

        assert batch_analysis_engine._analyse_file is _analyse_file

    def test_result_matches_mood_analyzer_path(self) -> None:
        """A track analysed here must produce the same tag string as
        mood_analyzer's pipeline."""
        import numpy as np

        fake_y = np.zeros(1000, dtype=np.float64)
        with (
            patch(
                "mood_analyzer.core.file_processor.load_analysis_audio",
                return_value=(fake_y, _SR),
            ) as mock_load,
            patch(
                "mood_analyzer.core.file_processor.analyze_mood",
                return_value=_FAKE_ANALYSIS,
            ) as mock_analyze,
        ):
            result = batch_analysis_engine._analyse_file("/music/track.mp3", 45)
        mock_load.assert_called_once_with("/music/track.mp3", max_duration=45)
        mock_analyze.assert_called_once_with(fake_y, _SR)
        assert result.to_tag_string() == "Energetic;Bright;Confident"
        assert f"{result.confidence:.2f}" == "0.87"


# ═════════════════════════════════════════════════════════════════════════════
# _write_tags
# ═════════════════════════════════════════════════════════════════════════════


class TestWriteTags:
    def test_writes_mood_and_confidence(self) -> None:
        with (
            patch(f"{MODULE}.record_tag_edit_snapshot") as mock_snap,
            patch(f"{MODULE}.write_mood") as mock_write,
            patch(f"{MODULE}.write_mood_confidence") as mock_write_conf,
            patch(f"{MODULE}.write_energy") as mock_write_energy,
        ):
            batch_analysis_engine._write_tags("/music/a.mp3", _FAKE_ANALYSIS)
        mock_snap.assert_called_once_with("/music/a.mp3", "write_mood")
        mock_write.assert_called_once_with("/music/a.mp3", "Energetic;Bright;Confident")
        mock_write_conf.assert_called_once_with("/music/a.mp3", "0.87")
        mock_write_energy.assert_called_once_with("/music/a.mp3", "5")

    def test_write_tags_from_result(self) -> None:
        with (
            patch(f"{MODULE}.record_tag_edit_snapshot") as mock_snap,
            patch(f"{MODULE}.write_mood") as mock_write,
            patch(f"{MODULE}.write_mood_confidence") as mock_write_conf,
            patch(f"{MODULE}.write_energy") as mock_write_energy,
        ):
            batch_analysis_engine._write_tags_from_result(
                "/music/a.mp3",
                {
                    "status": "ok",
                    "mood": "Calm;Serene;Warm",
                    "confidence": 0.9,
                    "energy": 3,
                },
            )
        mock_snap.assert_called_once_with("/music/a.mp3", "write_mood")
        mock_write.assert_called_once_with("/music/a.mp3", "Calm;Serene;Warm")
        mock_write_conf.assert_called_once_with("/music/a.mp3", "0.90")
        mock_write_energy.assert_called_once_with("/music/a.mp3", "3")


# ═════════════════════════════════════════════════════════════════════════════
# _analyse_audio_cpu
# ═════════════════════════════════════════════════════════════════════════════


class TestAnalyseAudioCpu:
    def test_ok_result(self) -> None:
        with patch(f"{MODULE}._analyse_file", return_value=_FAKE_ANALYSIS):
            result = batch_analysis_engine._analyse_audio_cpu("/music/a.mp3", 60)
        assert result["status"] == "ok"
        assert result["mood"] == "Energetic;Bright;Confident"
        assert result["confidence"] == pytest.approx(0.87)
        assert result["energy"] == 5

    def test_error_result_on_failure(self) -> None:
        with patch(f"{MODULE}._analyse_file", side_effect=RuntimeError("boom")):
            result = batch_analysis_engine._analyse_audio_cpu("/music/a.mp3", 60)
        assert result["status"] == "error"
        assert "boom" in result["error"]


# ═════════════════════════════════════════════════════════════════════════════
# run_batch — thread-pool path
# ═════════════════════════════════════════════════════════════════════════════


class TestRunBatchThreadDryRun:
    def test_dry_run_reports_without_writing(self, tmp_path) -> None:
        _make_file(str(tmp_path / "a.mp3"))
        msgs, _ = _run(str(tmp_path), live=False)
        kinds = [m[0] for m in msgs]
        assert "done" in kinds
        assert "result" in kinds
        done = next(m for m in msgs if m[0] == "done")
        _, tagged, skipped, errors, folders, log_path = done
        assert tagged == 1
        assert skipped == 0
        assert errors == 0
        assert folders == 1
        assert log_path
        result_msg = next(m for m in msgs if m[0] == "result")
        assert result_msg[3] is True
        assert "(dry run" in result_msg[4]
        assert "Energetic;Bright;Confident" in result_msg[4]

    def test_live_mode_writes_tags(self, tmp_path) -> None:
        _make_file(str(tmp_path / "a.mp3"))
        with patch(f"{MODULE}._write_tags") as mock_write:
            q: queue.Queue[object] = queue.Queue()
            stop = threading.Event()

            def _fake_analyse_file(path: str, d: int) -> MoodAnalysis:
                return _FAKE_ANALYSIS

            with patch(f"{MODULE}._analyse_file", side_effect=_fake_analyse_file):
                batch_analysis_engine.run_batch(
                    str(tmp_path), q, stop, live=True, max_workers=2
                )
        mock_write.assert_called()
        msgs = _drain(q)
        done = next(m for m in msgs if m[0] == "done")
        _, tagged, skipped, errors, folders, log_path = done
        assert tagged == 1
        assert log_path

    def test_skips_undecodable_as_skip(self, tmp_path) -> None:
        from audio_suite_shared.exceptions import AudioCodecError

        _make_file(str(tmp_path) + "/bad.flac")
        q: queue.Queue[object] = queue.Queue()
        stop = threading.Event()

        def _raise(path: str, d: int) -> MoodAnalysis:
            raise AudioCodecError("cannot decode")

        with patch(f"{MODULE}._analyse_file", side_effect=_raise):
            batch_analysis_engine.run_batch(
                str(tmp_path), q, stop, live=True, max_workers=2
            )
        msgs = _drain(q)
        done = next(m for m in msgs if m[0] == "done")
        _, tagged, skipped, errors, folders, _ = done
        assert tagged == 0
        assert skipped == 1
        assert errors == 0


class TestRunBatchEmpty:
    def test_empty_dir_posts_only_done(self, tmp_path) -> None:
        msgs, _ = _run(str(tmp_path))
        assert [m[0] for m in msgs] == ["done"]
        _, tagged, skipped, errors, folders, log_path = msgs[0]
        assert tagged == skipped == errors == folders == 0
        assert log_path == ""


class TestRunBatchScanError:
    def test_posts_done_zeros_on_scan_failure(self, tmp_path) -> None:
        q: queue.Queue[object] = queue.Queue()
        stop = threading.Event()
        with patch(f"{MODULE}._collect_audio_files", side_effect=OSError("boom")):
            batch_analysis_engine.run_batch(str(tmp_path), q, stop, live=True)
        msgs = _drain(q)
        assert msgs == [("done", 0, 0, 0, 0, "")]

    def test_posts_done_zeros_on_nonexistent_root(self, tmp_path) -> None:
        q: queue.Queue[object] = queue.Queue()
        stop = threading.Event()
        batch_analysis_engine.run_batch(str(tmp_path / "not_here"), q, stop, live=True)
        msgs = _drain(q)
        assert msgs == [("done", 0, 0, 0, 0, "")]


class TestRunBatchLog:
    def test_log_written_to_root(self, tmp_path) -> None:
        _make_file(str(tmp_path / "a.mp3"))
        msgs, _ = _run(str(tmp_path))
        done = next(m for m in msgs if m[0] == "done")
        _, _, _, _, _, log_path = done
        assert log_path == str(tmp_path / "mood_analysis_batch_log.txt")
        import os

        assert os.path.isfile(log_path)
        with open(log_path, encoding="utf-8") as fh:
            content = fh.read()
        assert "Energetic;Bright;Confident" in content

    def test_log_write_failure_sets_empty_path(self, tmp_path, monkeypatch) -> None:
        _make_file(str(tmp_path / "a.mp3"))
        q: queue.Queue[object] = queue.Queue()
        stop = threading.Event()

        def _fake_analyse_file(path: str, d: int) -> MoodAnalysis:
            return _FAKE_ANALYSIS

        import builtins

        real_open = builtins.open

        def _block_log(path: str, mode: str = "r", **kwargs: object):
            if "mood_analysis_batch_log.txt" in path:
                raise OSError("denied")
            return real_open(path, mode, **kwargs)

        with (
            patch(f"{MODULE}._analyse_file", side_effect=_fake_analyse_file),
            patch("builtins.open", side_effect=_block_log),
        ):
            batch_analysis_engine.run_batch(str(tmp_path), q, stop, live=True)
        msgs = _drain(q)
        done = next(m for m in msgs if m[0] == "done")
        _, _, _, _, _, log_path = done
        assert log_path == ""


# ═════════════════════════════════════════════════════════════════════════════
# run_batch — worker-slot status
# ═════════════════════════════════════════════════════════════════════════════


class TestRunBatchWorkerStatus:
    def test_thread_pool_emits_slot_messages(self, tmp_path) -> None:
        _make_file(str(tmp_path / "a.mp3"))
        _make_file(str(tmp_path / "b.flac"))
        q: queue.Queue[object] = queue.Queue()
        stop = threading.Event()
        status: list[tuple[int, str]] = []

        def _fake_analyse_file(path: str, d: int) -> MoodAnalysis:
            return _FAKE_ANALYSIS

        with (
            patch(f"{MODULE}._analyse_file", side_effect=_fake_analyse_file),
            patch(f"{MODULE}._write_tags"),
        ):
            batch_analysis_engine.run_batch(
                str(tmp_path),
                q,
                stop,
                live=False,
                max_workers=2,
                on_worker_status=lambda slot, label: status.append((slot, label)),
            )
        labels = [label for _, label in status]
        assert any(label.startswith("Analyzing:") for label in labels)
        assert labels.count("IDLE") == 2
        assert all(slot in (0, 1) for slot, _ in status)

    def test_worker_status_is_optional(self, tmp_path) -> None:
        _make_file(str(tmp_path / "a.mp3"))
        _make_file(str(tmp_path / "b.flac"))
        q: queue.Queue[object] = queue.Queue()
        stop = threading.Event()

        def _fake_analyse_file(path: str, d: int) -> MoodAnalysis:
            return _FAKE_ANALYSIS

        with (
            patch(f"{MODULE}._analyse_file", side_effect=_fake_analyse_file),
            patch(f"{MODULE}._write_tags"),
        ):
            batch_analysis_engine.run_batch(
                str(tmp_path), q, stop, live=False, max_workers=2
            )
        msgs = _drain(q)
        done = next(m for m in msgs if m[0] == "done")
        assert done[1] == 2

    def test_thread_pool_live_emits_tagging_label(self, tmp_path) -> None:
        """Live runs show the mood_analyzer-style Tagging phase and truncated
        filenames in the Active Workers slots."""
        _make_file(str(tmp_path / "a.mp3"))
        q: queue.Queue[object] = queue.Queue()
        stop = threading.Event()
        status: list[tuple[int, str]] = []

        def _fake_analyse_file(path: str, d: int) -> MoodAnalysis:
            return _FAKE_ANALYSIS

        with (
            patch(f"{MODULE}._analyse_file", side_effect=_fake_analyse_file),
            patch(f"{MODULE}._write_tags"),
        ):
            batch_analysis_engine.run_batch(
                str(tmp_path),
                q,
                stop,
                live=True,
                max_workers=2,
                on_worker_status=lambda slot, label: status.append((slot, label)),
            )
        labels = [label for _, label in status]
        assert any(label.startswith("Analyzing:") for label in labels)
        assert any(label.startswith("Tagging:") for label in labels)
        assert "Analyzing: a.mp3..." in labels
        assert "Tagging: a.mp3..." in labels

    def test_thread_worker_runs_through_retry_wrapper(self, tmp_path) -> None:
        """Every file must be processed via run_with_retry, matching
        mood_analyzer's transient-failure recovery."""
        _make_file(str(tmp_path / "a.mp3"))
        _make_file(str(tmp_path / "b.flac"))
        q: queue.Queue[object] = queue.Queue()
        stop = threading.Event()

        def _fake_analyse_file(path: str, d: int) -> MoodAnalysis:
            return _FAKE_ANALYSIS

        with (
            patch(f"{MODULE}._analyse_file", side_effect=_fake_analyse_file),
            patch(f"{MODULE}._write_tags"),
            patch.object(
                batch_analysis_engine._BatchAnalysisProcessor, "run_with_retry"
            ) as mock_retry,
        ):
            mock_retry.side_effect = lambda func, **kwargs: func()
            batch_analysis_engine.run_batch(
                str(tmp_path), q, stop, live=False, max_workers=2
            )
        assert mock_retry.call_count == 2
        for call in mock_retry.call_args_list:
            assert call.kwargs["label"].startswith("mood_")


# ═════════════════════════════════════════════════════════════════════════════
# run_batch — process-pool dispatch
# ═════════════════════════════════════════════════════════════════════════════


class TestRunBatchProcessPool:
    def test_parallel_routes_to_process_pool(self, tmp_path) -> None:
        _make_file(str(tmp_path / "a.mp3"))
        q: queue.Queue[object] = queue.Queue()
        stop = threading.Event()
        with (
            patch(f"{MODULE}._run_process_pool") as mock_pool,
            patch(f"{MODULE}._run_thread_pool") as mock_thread,
        ):
            batch_analysis_engine.run_batch(
                str(tmp_path),
                q,
                stop,
                live=True,
                parallel_mode=True,
                max_workers=2,
            )
        mock_pool.assert_called_once()
        mock_thread.assert_not_called()
        _drain(q)  # consume remaining messages

    def test_default_uses_thread_pool(self, tmp_path) -> None:
        _make_file(str(tmp_path / "a.mp3"))
        q: queue.Queue[object] = queue.Queue()
        stop = threading.Event()

        def _fake_analyse_file(path: str, d: int) -> MoodAnalysis:
            return _FAKE_ANALYSIS

        with (
            patch(f"{MODULE}._analyse_file", side_effect=_fake_analyse_file),
            patch(f"{MODULE}._run_thread_pool") as mock_thread,
        ):
            batch_analysis_engine.run_batch(str(tmp_path), q, stop, live=True)
        mock_thread.assert_called_once()
        _drain(q)


class TestUndoBatchIntegration:
    """Regression: thread-pool workers must bridge the undo batch via use_batch."""

    def test_thread_pool_records_undo_snapshots(self, tmp_path) -> None:
        from audio_suite_shared.batch_undo import active_batch

        _make_file(str(tmp_path / "a.mp3"))
        _make_file(str(tmp_path / "b.mp3"))
        q: queue.Queue[object] = queue.Queue()
        stop = threading.Event()

        def _fake_analyse_file(path: str, d: int) -> MoodAnalysis:
            return _FAKE_ANALYSIS

        with (
            active_batch("mood_analysis_batch_tagger", "tag_edit"),
            patch(f"{MODULE}._analyse_file", side_effect=_fake_analyse_file),
            patch(f"{MODULE}.record_tag_edit_snapshot") as mock_snapshot,
        ):
            batch_analysis_engine.run_batch(
                str(tmp_path),
                q,
                stop,
                live=True,
                parallel_mode=False,
                max_workers=2,
            )
            assert mock_snapshot.call_count >= 2, (
                f"Expected >= 2 snapshot calls, got {mock_snapshot.call_count}"
            )

    def test_passes_undo_batch_to_pool_runners(self, tmp_path) -> None:
        from audio_suite_shared.batch_undo import active_batch

        _make_file(str(tmp_path / "a.mp3"))
        q: queue.Queue[object] = queue.Queue()
        stop = threading.Event()

        def _fake_analyse_file(path: str, d: int) -> MoodAnalysis:
            return _FAKE_ANALYSIS

        with (
            active_batch("mood_analysis_batch_tagger", "tag_edit") as batch_id,
            patch(f"{MODULE}._analyse_file", side_effect=_fake_analyse_file),
            patch(f"{MODULE}._run_thread_pool") as mock_thread,
        ):
            batch_analysis_engine.run_batch(
                str(tmp_path),
                q,
                stop,
                live=True,
                parallel_mode=False,
                max_workers=2,
            )
            call_kwargs = mock_thread.call_args
            assert call_kwargs.kwargs.get("undo_batch") == batch_id or (
                call_kwargs[1].get("undo_batch") == batch_id
            ), "undo_batch not passed to _run_thread_pool"

        _make_file(str(tmp_path / "c.mp3"))
        with (
            active_batch("mood_analysis_batch_tagger", "tag_edit") as batch_id2,
            patch(f"{MODULE}._analyse_file", side_effect=_fake_analyse_file),
            patch(f"{MODULE}._run_process_pool") as mock_proc,
        ):
            batch_analysis_engine.run_batch(
                str(tmp_path),
                q,
                stop,
                live=True,
                parallel_mode=True,
                max_workers=2,
            )
            call_kwargs = mock_proc.call_args
            assert call_kwargs.kwargs.get("undo_batch") == batch_id2 or (
                call_kwargs[1].get("undo_batch") == batch_id2
            ), "undo_batch not passed to _run_process_pool"


class TestBatchResult:
    def test_batch_result_dataclass(self) -> None:
        from mood_analysis_batch_tagger.core.batch_analysis_engine import BatchResult

        result = BatchResult(
            total=10, tagged=8, skipped=1, errors=1, folders=2, log_path="x.txt"
        )
        assert result.total == 10
        assert result.tagged == 8
        assert result.skipped == 1
        assert result.errors == 1
        assert result.folders == 2
        assert result.log_path == "x.txt"


# ═════════════════════════════════════════════════════════════════════════════
# run_batch — the process pool, really executed
# ═════════════════════════════════════════════════════════════════════════════
#
# The ProcessPoolExecutor branch is the highest-risk untested region in the
# suite.  Windows and macOS default to the ``spawn`` start method, so the worker
# callable is pickled *by reference* and imported inside the child: a closure, a
# lambda, or a double that only exists in the parent's namespace fails there and
# nowhere else.  Two properties make that concrete and both are asserted here —
# the production worker is a module-level function (``TestProcessPoolWorker-
# Picklability``), and the analyses really do run in child processes
# (``TestProcessPoolExecution.test_pool_runs_the_analysis_in_child_processes``).
#
# Every stand-in below is therefore a module-level function taking the exact
# two positional arguments ``executor.submit`` passes.  The audio cases use the
# genuine ``_analyse_audio_cpu`` on real generated WAV files, and cross-check the
# value that crossed the process boundary against the same analysis performed
# in-process, so a corrupted worker result cannot pass unnoticed.

#: Worker stand-in mood.  Carries the child's PID so the tests can prove the
#: analysis ran somewhere other than the parent process.
_PID_MOOD_PREFIX = "pid"

#: Basename stem whose file makes ``_spawn_worker_boom`` raise.  Sorted between
#: the two healthy stems so the batch is in-flight across the failure.
_BOOM_STEM = "b_boom"


#: Deterministic stand-in for ``_analyse_audio_cpu``.
def _spawn_worker_report(file_path: str, analysis_duration: int) -> dict[str, object]:
    """Succeed for every file, stamping the executing process's PID.

    Module level and two positional parameters because that is exactly what
    ``executor.submit(_analyse_audio_cpu, file_path, analysis_duration)``
    pickles and replays in the child.
    """
    return {
        "status": "ok",
        "mood": f"{_PID_MOOD_PREFIX}{os.getpid()}",
        "confidence": 0.5,
        "energy": 2,
    }


def _spawn_worker_boom(file_path: str, analysis_duration: int) -> dict[str, object]:
    """Raise for one designated file, succeed for the rest.

    The production worker swallows its own exceptions and returns a
    ``status="error"`` dict, so this is the only way to reach the pool's
    ``future.result()`` failure branch — the case where the exception never
    made it back as a value at all.
    """
    name = os.path.basename(file_path)
    if name.startswith(_BOOM_STEM):
        raise RuntimeError(f"worker exploded on {name}")
    return _spawn_worker_report(file_path, analysis_duration)


def _write_tone_wav(path: str, seconds: float = 1.0, sr: int = 22050) -> str:
    """Write a real, decodable mono WAV tone and return its path.

    A deterministic sine, written with the stdlib ``wave`` module so the
    fixture is byte-reproducible and genuinely decodable by the real
    ``_analyse_audio_cpu`` — the process-pool cases need a signal the analysis
    engines can actually run on, not a placeholder.
    """
    t = np.arange(int(seconds * sr), dtype=np.float64) / sr
    samples = (0.3 * np.sin(2.0 * np.pi * 220.0 * t) * 32767.0).astype("<i2")
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(samples.tobytes())
    return path


def _run_pool(
    root: str,
    *,
    live: bool,
    max_workers: int,
    worker: Callable[..., dict[str, object]] | None = None,
    stop: threading.Event | None = None,
    on_worker_status: Callable[[int, str], None] | None = None,
) -> tuple[list[tuple], list[tuple[int, str]]]:
    """Run ``run_batch`` through the real ProcessPoolExecutor branch.

    Nothing about the pool itself is mocked; only the CPU worker may be
    substituted, so dispatch, result collection, error mapping, slot
    accounting and cancellation are all executed for real.

    Args:
        root:        Directory scanned for audio files.
        live:        When True the real tag-write path runs.
        max_workers: Pool size, which also bounds the worker-slot pool.
        worker:      Optional stand-in for the production CPU worker.  When
                     ``None`` the real ``_analyse_audio_cpu`` is used.
        stop:        Optional pre-built stop event (for cancellation tests).
        on_worker_status: Optional extra slot-status callback, invoked after
                     recording, so a test can raise the stop event from inside
                     the result handler instead of racing the workers.

    Returns:
        The drained queue messages and the worker-slot status events.
    """
    q: queue.Queue[object] = queue.Queue()
    stop_event = stop if stop is not None else threading.Event()
    status: list[tuple[int, str]] = []

    def _record(slot: int, label: str) -> None:
        status.append((slot, label))
        if on_worker_status is not None:
            on_worker_status(slot, label)

    with ExitStack() as stack:
        if worker is not None:
            stack.enter_context(patch(f"{MODULE}._analyse_audio_cpu", worker))
        batch_analysis_engine.run_batch(
            root,
            q,
            stop_event,
            live=live,
            analysis_duration=30,
            parallel_mode=True,
            max_workers=max_workers,
            on_worker_status=_record,
        )
    return _drain(q), status


def _results(msgs: list[tuple]) -> list[tuple]:
    return [m for m in msgs if m[0] == "result"]


def _progress(msgs: list[tuple]) -> list[tuple]:
    return [m for m in msgs if m[0] == "progress"]


def _done(msgs: list[tuple]) -> tuple:
    return next(m for m in msgs if m[0] == "done")


class TestProcessPoolWorkerPicklability:
    """The ``spawn`` contract: the worker must be importable by name."""

    def test_worker_is_a_module_level_function_not_a_closure(self) -> None:
        worker = batch_analysis_engine._analyse_audio_cpu
        assert inspect.isfunction(worker)
        assert worker.__module__ == MODULE
        assert worker.__qualname__ == "_analyse_audio_cpu"
        assert "<locals>" not in worker.__qualname__

    def test_worker_round_trips_through_pickle_by_reference(self) -> None:
        """A closure would raise ``PicklingError`` here — and, on Windows,
        only at run time, long after the suite went green."""
        worker = batch_analysis_engine._analyse_audio_cpu
        assert pickle.loads(pickle.dumps(worker)) is worker

    def test_every_test_stand_in_is_also_importable_by_name(self) -> None:
        """The stand-ins must clear the same bar as the production worker."""
        for stand_in in (_spawn_worker_report, _spawn_worker_boom):
            assert stand_in.__module__ == __name__
            assert pickle.loads(pickle.dumps(stand_in)) is stand_in


class TestProcessPoolExecution:
    """The pool branch, executed — not collected, not short-circuited."""

    def test_pool_runs_the_analysis_in_child_processes(self, tmp_path) -> None:
        _make_file(str(tmp_path / "a.mp3"))
        _make_file(str(tmp_path / "b.mp3"))
        msgs, _ = _run_pool(
            str(tmp_path),
            live=False,
            max_workers=2,
            worker=_spawn_worker_report,
        )
        results = _results(msgs)
        assert len(results) == 2
        child_pids = {int(str(m[4]).removeprefix("pid").split(" ")[0]) for m in results}
        assert child_pids, "no result detail carried a pid"
        assert os.getpid() not in child_pids, (
            "the analysis ran in the parent process — the pool did not execute"
        )
        assert (_done(msgs)[1], _done(msgs)[3]) == (2, 0)

    def test_happy_path_reports_every_file_in_input_order(self, tmp_path) -> None:
        """One worker, so submission order and completion order must agree."""
        names = ("a.wav", "b.wav", "c.wav")
        files = [_write_tone_wav(str(tmp_path / name)) for name in names]
        expected = {
            os.path.basename(path): batch_analysis_engine._analyse_audio_cpu(path, 30)
            for path in files
        }
        msgs, status = _run_pool(str(tmp_path), live=False, max_workers=1)

        results = _results(msgs)
        assert [os.path.basename(m[1]) for m in results] == ["a.wav", "b.wav", "c.wav"]
        assert all(m[3] is True for m in results)
        for message in results:
            want = expected[os.path.basename(message[1])]
            assert message[4] == f"{want['mood']} (dry run - not written)"

        progress = _progress(msgs)
        assert [m[1] for m in progress] == [1, 2, 3]
        assert [m[2] for m in progress] == [3, 3, 3]
        assert [m[3] for m in progress] == ["a.wav", "b.wav", "c.wav"]

        kinds = [m[0] for m in msgs]
        assert kinds[0] == "folder"
        assert kinds[-1] == "done"
        assert kinds.count("result") == 3
        assert kinds.count("progress") == 3

        done = _done(msgs)
        assert (done[1], done[2], done[3], done[4]) == (3, 0, 0, 1)

        with open(done[5], encoding="utf-8") as handle:
            log = handle.read()
        for name, want in expected.items():
            assert f"  DRY   {name}" in log
            assert str(want["mood"]) in log

    def test_worker_slots_alternate_claim_and_release_with_one_worker(
        self, tmp_path
    ) -> None:
        _make_file(str(tmp_path / "a.mp3"))
        _make_file(str(tmp_path / "b.mp3"))
        _, status = _run_pool(
            str(tmp_path),
            live=False,
            max_workers=1,
            worker=_spawn_worker_report,
        )
        assert [label for _, label in status] == [
            "Analyzing: a.mp3...",
            "IDLE",
            "Analyzing: b.mp3...",
            "IDLE",
        ]
        assert {slot for slot, _ in status} == {0}

    def test_slot_claims_stay_within_the_pool_and_are_all_released(
        self, tmp_path
    ) -> None:
        for stem in ("a", "b", "c", "d"):
            _make_file(str(tmp_path / f"{stem}.mp3"))
        msgs, status = _run_pool(
            str(tmp_path),
            live=False,
            max_workers=2,
            worker=_spawn_worker_report,
        )
        assert {slot for slot, _ in status} <= {0, 1}
        labels = [label for _, label in status]
        assert sum(1 for label in labels if label.startswith("Analyzing:")) == 4
        assert labels.count("IDLE") == 4
        outstanding = 0
        for _, label in status:
            outstanding += -1 if label == "IDLE" else 1
            assert 0 <= outstanding <= 2, f"slot accounting leaked: {status}"
        assert outstanding == 0
        assert (_done(msgs)[1], _done(msgs)[3]) == (4, 0)

    def test_live_run_writes_the_workers_own_mood_onto_the_file(self, tmp_path) -> None:
        """Outcome check: decode the worker's result off disk, not the queue.

        The tags are read back with the suite's own readers, so a value that
        was mangled in transit between the child process and the writer shows
        up as a tag mismatch rather than passing unnoticed.
        """
        path = _write_tone_wav(str(tmp_path / "a.wav"))
        expected = batch_analysis_engine._analyse_audio_cpu(path, 30)
        msgs, status = _run_pool(str(tmp_path), live=True, max_workers=1)

        results = _results(msgs)
        assert len(results) == 1
        assert results[0][3] is True
        assert read_mood(path) == expected["mood"]
        assert read_energy(path) == str(expected["energy"])
        assert "Tagging: a.wav..." in [label for _, label in status]
        assert (_done(msgs)[1], _done(msgs)[3]) == (1, 0)

    def test_dry_run_writes_nothing(self, tmp_path) -> None:
        path = _write_tone_wav(str(tmp_path / "a.wav"))
        msgs, _ = _run_pool(str(tmp_path), live=False, max_workers=1)
        assert len(_results(msgs)) == 1
        assert read_mood(path) is None
        assert read_energy(path) is None


class TestProcessPoolErrorMapping:
    """Failures are mapped and reported; the batch always finishes."""

    def test_worker_error_status_becomes_a_reported_error(self, tmp_path) -> None:
        """The real worker returns ``status="error"`` for an undecodable file.

        Which *message* the decoder produces is a backend-dependent branch,
        not a batch-level contract: librosa ≤ 0.11's audioread fallback can
        return an empty decode (yielding the loader's "too short to analyse"
        message) while librosa ≥ 1.0 raises the soundfile error instead
        (yielding "Could not decode audio file …"). Both branch texts are
        pinned in ``audio_suite_shared/tests/test_analysis_loader.py``; this
        batch-level test pins the batch outcome — status="error", a non-empty
        reported message, and the other files still completing.
        """
        good = _write_tone_wav(str(tmp_path / "a_good.wav"))
        bad = str(tmp_path / "b_broken.flac")
        with open(bad, "wb") as handle:
            handle.write(b"this is not an audio file at all")

        msgs, _ = _run_pool(str(tmp_path), live=False, max_workers=2)

        done = _done(msgs)
        assert (done[1], done[2], done[3]) == (1, 0, 1)
        results = {os.path.basename(m[1]): m for m in _results(msgs)}
        assert results["b_broken.flac"][3] is False
        error_message = results["b_broken.flac"][4]
        assert isinstance(error_message, str) and error_message.strip(), (
            f"a corrupt file must yield a reported, non-empty error message, "
            f"got: {error_message!r}"
        )
        assert results["a_good.wav"][3] is True
        with open(done[5], encoding="utf-8") as handle:
            log = handle.read()
        assert "  ERROR b_broken.flac" in log
        assert "  DRY   a_good.wav" in log
        assert os.path.isfile(good)

    def test_raised_worker_exception_is_mapped_not_propagated(self, tmp_path) -> None:
        _make_file(str(tmp_path / "a_ok.mp3"))
        _make_file(str(tmp_path / f"{_BOOM_STEM}.mp3"))
        _make_file(str(tmp_path / "c_ok.mp3"))

        msgs, _ = _run_pool(
            str(tmp_path),
            live=False,
            max_workers=2,
            worker=_spawn_worker_boom,
        )

        done = _done(msgs)
        assert (done[1], done[2], done[3]) == (2, 0, 1)
        results = {os.path.basename(m[1]): m for m in _results(msgs)}
        assert set(results) == {"a_ok.mp3", f"{_BOOM_STEM}.mp3", "c_ok.mp3"}
        assert results[f"{_BOOM_STEM}.mp3"][3] is False
        assert results[f"{_BOOM_STEM}.mp3"][4] == user_message_for(
            AudioAnalysisError("worker exploded")
        )
        assert {name for name, m in results.items() if m[3] is True} == {
            "a_ok.mp3",
            "c_ok.mp3",
        }
        with open(done[5], encoding="utf-8") as handle:
            log = handle.read()
        assert f"  ERROR {_BOOM_STEM}.mp3" in log

    def test_failed_worker_still_releases_its_slot(self, tmp_path) -> None:
        _make_file(str(tmp_path / "a_ok.mp3"))
        _make_file(str(tmp_path / f"{_BOOM_STEM}.mp3"))
        _, status = _run_pool(
            str(tmp_path),
            live=False,
            max_workers=2,
            worker=_spawn_worker_boom,
        )
        assert [label for _, label in status].count("IDLE") == 2

    def test_pre_set_stop_event_cancels_without_reporting_results(
        self, tmp_path
    ) -> None:
        _make_file(str(tmp_path / "a.mp3"))
        _make_file(str(tmp_path / "b.mp3"))
        stop = threading.Event()
        stop.set()
        msgs, status = _run_pool(
            str(tmp_path),
            live=False,
            max_workers=2,
            worker=_spawn_worker_report,
            stop=stop,
        )
        assert _results(msgs) == []
        assert _progress(msgs) == []
        assert status == []
        done = _done(msgs)
        assert (done[1], done[2], done[3]) == (0, 0, 0)

    def test_stop_mid_flight_reports_only_the_completed_item(self, tmp_path) -> None:
        """The stop event is raised from the slot callback, i.e. from inside
        the result handler, so the cancellation branch runs deterministically
        rather than depending on a race with the workers.

        Exactly one result is reported — whichever of the two in-flight files
        finished first — and the item still queued is never reported at all.
        """
        for stem in ("a", "b", "c"):
            _make_file(str(tmp_path / f"{stem}.mp3"))
        stop = threading.Event()
        msgs, status = _run_pool(
            str(tmp_path),
            live=False,
            max_workers=2,
            worker=_spawn_worker_report,
            stop=stop,
            on_worker_status=lambda slot, label: (
                stop.set() if label == "IDLE" else None
            ),
        )
        results = _results(msgs)
        assert len(results) == 1
        assert results[0][3] is True
        assert os.path.basename(results[0][1]) in {"a.mp3", "b.mp3"}
        assert [m[3] for m in _progress(msgs)] == [os.path.basename(results[0][1])]
        # Both claimed slots are released, including the in-flight one that was
        # cancelled rather than completed.
        assert [label for _, label in status].count("IDLE") == 2
        done = _done(msgs)
        assert (done[1], done[2], done[3]) == (1, 0, 0)

    def test_tag_write_failure_is_reported_as_a_skip_and_the_batch_completes(
        self, tmp_path
    ) -> None:
        """An error writing the tag must not abort the batch: the file is
        counted as skipped with the declared user message, the slot is still
        released, and every other file is processed."""
        from audio_suite_shared.exceptions import AudioTagError

        _make_file(str(tmp_path / "a.mp3"))
        _make_file(str(tmp_path / "b.mp3"))
        q: queue.Queue[object] = queue.Queue()
        status: list[tuple[int, str]] = []
        with (
            patch(f"{MODULE}._analyse_audio_cpu", _spawn_worker_report),
            patch(
                f"{MODULE}._write_tags_from_result",
                side_effect=AudioTagError("tag write failed"),
            ),
        ):
            batch_analysis_engine.run_batch(
                str(tmp_path),
                q,
                threading.Event(),
                live=True,
                analysis_duration=30,
                parallel_mode=True,
                max_workers=2,
                on_worker_status=lambda slot, label: status.append((slot, label)),
            )
        msgs = _drain(q)
        results = _results(msgs)
        assert len(results) == 2
        assert all(m[3] is False for m in results)
        assert all(
            m[4] == user_message_for(AudioTagError("tag write failed")) for m in results
        )
        assert [label for _, label in status].count("IDLE") == 2
        done = _done(msgs)
        assert (done[1], done[2], done[3]) == (0, 2, 0)
