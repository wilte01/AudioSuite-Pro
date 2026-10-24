"""Tests for ``stem_separator.app`` without a real display.

The completion seam is the important one: it drives the tool's real
``run_stem_separation`` into the handler ``app.py`` binds and asserts the
*written* report, with distinct counts per field, so a processor that renames
or stops publishing a field fails here instead of at the end of a separation
that already ran.

Changed in 2.0.0: initial version (Sprint 6, Item 6.1).
Changed in 2.1.0: covers the run mode reaching the Setup tab from the driver's
argv, including a standalone launch that carries no source folder, and a live
run installing Demucs on first use instead of refusing to start.
Changed in 2.1.1: ``TestFatalRun`` patches the name ``app.py`` binds, not the
module it was imported from. ``app.py`` does ``from .core.file_processor import
run_stem_separation``, so patching ``file_processor.run_stem_separation`` left
the real processor running: it found no audio in the temporary folder, returned
normally, and the test failed on a zero-call ``_on_error`` instead of exercising
the error path at all (PLAN_feature_expansion D11).
"""

from __future__ import annotations

import sys
from pathlib import Path
from queue import Queue
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from pydub import AudioSegment

from audio_suite_shared import optional_deps, ui_common
from audio_suite_shared.cli_helpers import UniversalCLIHandler
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


class _Var:
    """Minimal stand-in for a tk variable: ``set`` stores, ``get`` returns."""

    def __init__(self, value: Any = "") -> None:
        self._value = value

    def get(self) -> Any:
        return self._value

    def set(self, value: Any) -> None:
        self._value = value


class TestStartupMode:
    """The mode the Master Driver picked must reach the Setup tab.

    Regression background
    ---------------------
    ``_apply_cli_args`` applied the run mode *after* an early return on a
    missing ``folder_path``.  A standalone utility launch passes an empty
    positional slot (the tool opens its own window and picks its folder
    itself), so ``--live`` arrived, parsed, and was then dropped: the separator
    opened in Dry Run while the driver's toolbar showed Live Update.
    """

    @staticmethod
    def _shell() -> StemSeparatorApp:
        app = object.__new__(StemSeparatorApp)
        app.root = MagicMock()
        app.folder_path = _Var("")
        app.output_dir = _Var("")
        app.model = _Var("htdemucs")
        app.stem_vars = {stem: _Var(True) for stem in STEM_NAMES}
        app.write_mix = _Var(False)
        app.device = _Var("auto")
        app.run_mode = _Var("Dry Run")
        app.auto_start_var = _Var(False)
        app.auto_end_var = _Var(False)
        app.clear_logs_var = _Var(False)
        app.parallel_var = _Var(False)
        app.cli_handler = UniversalCLIHandler(app)
        return app

    @staticmethod
    def _launch(monkeypatch: pytest.MonkeyPatch, *args: str) -> None:
        monkeypatch.setattr(sys, "argv", ["Stem_Separator.pyw", *args])

    @staticmethod
    def _standalone_argv(mode: str, output: str) -> list[str]:
        """The argv the driver builds for a standalone launch (no folder)."""
        return [
            "",
            mode,
            "--no-start",
            "--no-end",
            "--output-dir",
            output,
            "--model",
            "htdemucs",
            "--stems",
            "vocals,drums,bass,other",
            "--device",
            "auto",
            "--no-clear-logs",
            "--no-parallel-run",
        ]

    def test_live_update_reaches_the_ui_without_a_source_folder(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._launch(
            monkeypatch, *self._standalone_argv("--live", str(tmp_path / "stems"))
        )
        app = self._shell()

        app._apply_cli_args()

        assert app.run_mode.get() == "Live Update"
        assert app.output_dir.get() == str(tmp_path / "stems")
        # No folder was handed over, so nothing may be auto-started; the tool
        # keeps its own empty source and its last-directory fallback.
        assert app.folder_path.get() == ""
        app.root.after.assert_not_called()

    def test_dry_run_is_applied_the_same_way(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._launch(
            monkeypatch, *self._standalone_argv("--dry", str(tmp_path / "stems"))
        )
        app = self._shell()
        app.run_mode.set("Live Update")

        app._apply_cli_args()

        assert app.run_mode.get() == "Dry Run"

    def test_a_folder_launch_still_applies_the_mode_and_auto_start(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        argv = self._standalone_argv("--live", str(tmp_path / "stems"))
        argv[0] = str(tmp_path)
        argv[2] = "--start"
        self._launch(monkeypatch, *argv)
        app = self._shell()

        app._apply_cli_args()

        assert app.run_mode.get() == "Live Update"
        assert app.folder_path.get() == str(tmp_path)
        assert app.auto_start_var.get() is True
        assert app.root.after.call_args.args[0] == 1500


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

    def test_a_missing_demucs_is_not_a_refusal(self, tmp_path: Path) -> None:
        """A live run installs Demucs instead of stopping with a dialog."""
        app = self._app(tmp_path)
        app.run_mode.get.return_value = "Live Update"

        with patch.object(
            demucs_engine, "missing_dependency_reason", return_value="no demucs"
        ):
            assert app._validate_start() is None

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


class TestDemucsInstallOnFirstUse:
    """A live run installs Demucs itself the first time it needs it.

    Regression background
    ---------------------
    The run used to stop with "Demucs is not installed ... uv sync --extra ml".
    For a non-technical user that is a dead end, and it installed nothing at all
    when the window had been started by a different interpreter than the one
    ``uv`` wrote the extra into.
    """

    @staticmethod
    def _app(tmp_path: Path) -> StemSeparatorApp:
        app = object.__new__(StemSeparatorApp)
        app.root = MagicMock()
        app.folder_path = _Var(str(tmp_path))
        app.output_dir = _Var(str(tmp_path / "out"))
        app.stem_vars = {stem: _Var(True) for stem in STEM_NAMES}
        app.run_mode = _Var("Live Update")
        app.device = _Var("auto")
        app._begin_run = MagicMock()
        return app

    def test_a_live_run_installs_demucs_before_starting(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = self._app(tmp_path)
        monkeypatch.setattr(
            demucs_engine, "missing_dependency_reason", lambda: "no demucs"
        )
        install = MagicMock()
        monkeypatch.setattr(ui_common, "install_optional_dependency", install)

        app.start_processing()

        app._begin_run.assert_not_called()
        install.assert_called_once()
        assert install.call_args.args[1] is optional_deps.DEMUCS
        assert install.call_args.kwargs["on_ready"] == app._begin_run

    def test_the_install_completion_runs_the_separation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = self._app(tmp_path)
        monkeypatch.setattr(
            demucs_engine, "missing_dependency_reason", lambda: "no demucs"
        )
        install = MagicMock()
        monkeypatch.setattr(ui_common, "install_optional_dependency", install)
        app.start_processing()

        install.call_args.kwargs["on_ready"]()

        app._begin_run.assert_called_once()

    def test_an_installed_demucs_starts_immediately(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = self._app(tmp_path)
        monkeypatch.setattr(demucs_engine, "missing_dependency_reason", lambda: None)
        install = MagicMock()
        monkeypatch.setattr(ui_common, "install_optional_dependency", install)

        app.start_processing()

        app._begin_run.assert_called_once()
        install.assert_not_called()

    def test_a_dry_run_never_probes_or_installs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = self._app(tmp_path)
        app.run_mode.set("Dry Run")
        install = MagicMock()
        monkeypatch.setattr(ui_common, "install_optional_dependency", install)
        monkeypatch.setattr(
            demucs_engine,
            "missing_dependency_reason",
            MagicMock(side_effect=AssertionError("dry run probed Demucs")),
        )

        app.start_processing()

        app._begin_run.assert_called_once()
        install.assert_not_called()


class TestFatalRun:
    """A live run that cannot import Demucs reaches the error dialog."""

    def test_the_error_is_routed_to_the_ui(self, tmp_path: Path) -> None:
        app = _shell(tmp_path)
        app.slot_vars = []
        app.slot_queue = Queue()
        app._on_error = MagicMock()

        with patch(
            "stem_separator.app.run_stem_separation",
            side_effect=AudioMissingDependencyError("Demucs is not installed"),
        ):
            app._run_separation(
                str(tmp_path),
                StemSeparationParams(output_dir=str(tmp_path / "out"), device="cpu"),
            )

        assert app._on_error.call_count == 1
        assert "not installed" in str(app._on_error.call_args.args[0])
