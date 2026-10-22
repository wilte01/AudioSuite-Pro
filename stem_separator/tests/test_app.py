"""Tests for ``stem_separator.app`` without a real display.

The completion seam is the important one: it drives the tool's real
``run_stem_separation`` into the handler ``app.py`` binds and asserts the
*written* report, with distinct counts per field, so a processor that renames
or stops publishing a field fails here instead of at the end of a separation
that already ran.

Changed in 2.0.0: initial version (Sprint 6, Item 6.1).
"""

from __future__ import annotations

from pathlib import Path
from queue import Queue
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from pydub import AudioSegment

from audio_suite_shared.exceptions import AudioMissingDependencyError
from stem_separator.app import StemSeparatorApp
from stem_separator.core import demucs_engine, file_processor
from stem_separator.core.models import (
    MODEL_SAMPLE_RATE,
    STEM_NAMES,
    SeparatedTrack,
    StemSeparationParams,
)

SR = MODEL_SAMPLE_RATE


def _source(path: Path) -> Path:
    """Write a short discoverable WAV."""
    AudioSegment.silent(duration=250, frame_rate=SR).export(str(path), format="wav")
    return path


def _track(amplitude: float = 0.05) -> SeparatedTrack:
    """Return four stems with a known level."""
    return SeparatedTrack(
        sample_rate=SR,
        stems={
            name: np.full((2, SR // 4), amplitude, dtype=np.float32)
            for name in STEM_NAMES
        },
    )


def _slots() -> tuple[list[MagicMock], Queue[int]]:
    """Return one worker slot per pool worker and its index queue.

    The queue must hold an index for every worker the pool can start: an
    empty queue makes ``slot_queue.get()`` block and the run never finishes.
    """
    slots = [MagicMock() for _ in range(file_processor.MAX_WORKERS)]
    queue: Queue[int] = Queue()
    for index in range(file_processor.MAX_WORKERS):
        queue.put(index)
    return slots, queue


def _shell(tmp_path: Path) -> StemSeparatorApp:
    """Build the app shell with only what the paths under test touch.

    ``root.after`` runs its callback immediately: that is how a test observes
    the widget update a worker thread scheduled, on the thread that owns Tk.
    """
    app = object.__new__(StemSeparatorApp)
    app.root = MagicMock()
    app.root.after.side_effect = lambda _delay, fn, *args: fn(*args)
    app.time_label = MagicMock()
    app.summary_label = MagicMock()
    app.completion_label = MagicMock()
    app.notebook = MagicMock()
    app.start_btn = MagicMock()
    app._tab_results = MagicMock()
    app.auto_end_var = MagicMock()
    app.auto_end_var.get.return_value = False
    app.progress = MagicMock()
    app.stats_label = MagicMock()
    app.file_listbox = MagicMock()
    app._log_path = ""
    app._log_entries = []
    return app


class TestCompletionSeam:
    """``run_stem_separation`` publishes into the handler ``app.py`` binds."""

    def test_the_written_report_carries_every_count(self, tmp_path: Path) -> None:
        _source(tmp_path / "song.wav")
        out = tmp_path / "stems"
        app = _shell(tmp_path)

        with (
            patch.object(file_processor, "separate", return_value=_track()),
            patch.object(demucs_engine, "require_demucs", lambda: None),
        ):
            file_processor.run_stem_separation(
                str(tmp_path),
                StemSeparationParams(output_dir=str(out), device="cpu", write_mix=True),
                *_slots(),
                app._on_progress,
                app._on_complete,
                MagicMock(),
            )

        report = (out / "stem_separation_log.txt").read_text(encoding="utf-8")
        assert "[SEPARATED] song.wav" in report

        summary = app.summary_label.config.call_args.kwargs["text"]
        assert "Files examined: 1" in summary
        assert "Separated: 1" in summary
        assert "Stem files written: 5" in summary
        assert "Skipped: 0" in summary
        assert "Errors: 0" in summary
        assert "Device: CPU" in summary
        assert str(out) in summary
        assert (out / "song" / "vocals.wav").is_file()

    def test_distinct_counts_are_not_swapped(self, tmp_path: Path) -> None:
        """Two files, one duplicate output: each field keeps its own value."""
        _source(tmp_path / "a.wav")
        (tmp_path / "a.mp3").write_bytes(b"")
        _source(tmp_path / "b.wav")
        out = tmp_path / "stems"
        app = _shell(tmp_path)

        with (
            patch.object(file_processor, "separate", return_value=_track()),
            patch.object(demucs_engine, "require_demucs", lambda: None),
        ):
            file_processor.run_stem_separation(
                str(tmp_path),
                StemSeparationParams(output_dir=str(out), device="cpu"),
                *_slots(),
                app._on_progress,
                app._on_complete,
                MagicMock(),
            )

        summary = app.summary_label.config.call_args.kwargs["text"]
        assert "Files examined: 3" in summary
        assert "Separated: 2" in summary
        assert "Stem files written: 8" in summary
        assert "Skipped: 1" in summary

    @pytest.mark.parametrize(
        "field",
        [
            "total",
            "processed",
            "separated",
            "files_written",
            "skipped",
            "errors",
            "duration_secs",
            "log_entries",
            "output_dir",
            "device",
        ],
    )
    def test_a_missing_field_raises_and_writes_no_report(
        self, tmp_path: Path, field: str
    ) -> None:
        out = tmp_path / "stems"
        app = _shell(tmp_path)
        payload: dict[str, Any] = {
            "total": 3,
            "processed": 3,
            "separated": 2,
            "files_written": 8,
            "skipped": 1,
            "errors": 0,
            "duration_secs": 1.5,
            "log_entries": ["line\n"],
            "output_dir": str(out),
            "device": "CPU",
        }
        payload.pop(field)

        with pytest.raises(TypeError) as caught:
            app._on_complete(**payload)

        assert field in str(caught.value)
        assert not (out / "stem_separation_log.txt").exists()


class TestValidation:
    """A run that cannot work is refused with a message, before the thread."""

    @staticmethod
    def _app(tmp_path: Path) -> StemSeparatorApp:
        app = object.__new__(StemSeparatorApp)
        app.folder_path = MagicMock()
        app.folder_path.get.return_value = str(tmp_path)
        app.output_dir = MagicMock()
        app.output_dir.get.return_value = str(tmp_path / "out")
        app.stem_vars = {stem: MagicMock() for stem in STEM_NAMES}
        for var in app.stem_vars.values():
            var.get.return_value = True
        app.run_mode = MagicMock()
        app.run_mode.get.return_value = "Dry Run"
        app.device = MagicMock()
        app.device.get.return_value = "auto"
        return app

    def test_a_blank_folder_is_refused(self, tmp_path: Path) -> None:
        app = self._app(tmp_path)
        app.folder_path.get.return_value = "  "

        problem = app._validate_start()

        assert problem is not None and "music directory" in problem

    def test_a_missing_folder_is_refused(self, tmp_path: Path) -> None:
        app = self._app(tmp_path)
        app.folder_path.get.return_value = str(tmp_path / "gone")

        problem = app._validate_start()

        assert problem is not None and "not found" in problem

    def test_no_output_directory_is_refused(self, tmp_path: Path) -> None:
        app = self._app(tmp_path)
        app.output_dir.get.return_value = ""

        problem = app._validate_start()

        assert problem is not None and "output" in problem.lower()

    def test_no_selected_stem_is_refused(self, tmp_path: Path) -> None:
        app = self._app(tmp_path)
        for var in app.stem_vars.values():
            var.get.return_value = False

        problem = app._validate_start()

        assert problem is not None and "stem" in problem

    def test_a_live_run_without_demucs_is_refused(self, tmp_path: Path) -> None:
        app = self._app(tmp_path)
        app.run_mode.get.return_value = "Live Update"

        with patch.object(
            demucs_engine, "missing_dependency_reason", return_value="no demucs"
        ):
            problem = app._validate_start()

        assert problem == "no demucs"

    def test_a_dry_run_does_not_need_demucs(self, tmp_path: Path) -> None:
        app = self._app(tmp_path)

        with patch.object(
            demucs_engine,
            "missing_dependency_reason",
            MagicMock(side_effect=AssertionError("dry run probed Demucs")),
        ):
            assert app._validate_start() is None

    def test_selected_stems_follow_the_checkboxes(self, tmp_path: Path) -> None:
        app = self._app(tmp_path)
        for stem, var in app.stem_vars.items():
            var.get.return_value = stem in {"vocals", "bass"}

        assert app._selected_stems() == ("vocals", "bass")


class TestFatalRun:
    """A live run that cannot import Demucs reaches the error dialog."""

    def test_the_error_is_routed_to_the_ui(self, tmp_path: Path) -> None:
        app = _shell(tmp_path)
        app.slot_vars = []
        app.slot_queue = Queue()
        app._on_error = MagicMock()

        with patch.object(
            file_processor,
            "run_stem_separation",
            side_effect=AudioMissingDependencyError("Demucs is not installed"),
        ):
            app._run_separation(
                str(tmp_path),
                StemSeparationParams(output_dir=str(tmp_path / "out"), device="cpu"),
            )

        assert app._on_error.call_count == 1
        assert "not installed" in str(app._on_error.call_args.args[0])
