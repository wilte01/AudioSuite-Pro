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
  - worker slot status    (Analyzing/Tagging labels, run_with_retry wiring)
  - BatchResult summary

All heavy dependencies (load_analysis_audio, analyze_mood, tag writes) are
mocked so the suite runs quickly and standalone.
"""

from __future__ import annotations

import os
import queue
import threading
from unittest.mock import patch

import pytest

from audio_suite_shared.exceptions import AudioDirectoryError
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
