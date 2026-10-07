"""
Tests for bpm_analyzer.app — BPMAnalyzerApp CLI mirroring and wiring.

Uses the object.__new__ + MagicMock shell pattern (no real display).
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


def _make_shell_app():
    """Build a BPMAnalyzerApp shell with mock attributes."""
    from bpm_analyzer.app import BPMAnalyzerApp

    app = object.__new__(BPMAnalyzerApp)
    app.root = MagicMock()
    app.folder_path = MagicMock()
    app.run_mode = MagicMock()
    app.auto_end = False
    app.auto_start_var = MagicMock()
    app.auto_end_var = MagicMock()
    app.clear_logs_var = MagicMock()
    app.parallel_var = MagicMock()

    handler = MagicMock()
    handler.apply_cli_args.return_value = False
    handler_cls = MagicMock(return_value=handler)
    return app, handler, handler_cls


class TestApplyCliArgsDriven:
    """A driver launch populates the Run Controls values before applying."""

    def _run(self, parsed):
        from audio_suite_shared.cli_dataclasses import BPMArgs

        app, handler, handler_cls = _make_shell_app()
        with (
            patch(
                "bpm_analyzer.utils.cli_args.parse",
                return_value=parsed,
            ),
            patch("bpm_analyzer.app.UniversalCLIHandler", handler_cls),
        ):
            assert isinstance(parsed, BPMArgs)
            app._apply_cli_args()
        return app, handler

    def test_inherited_values_applied_to_panel_vars(self):
        from audio_suite_shared.cli_dataclasses import BPMArgs

        app, _ = self._run(
            BPMArgs(
                folder_path="D:/Music",
                live_mode=True,
                auto_start=True,
                auto_end=True,
                clear_logs=True,
                parallel_run=True,
            )
        )
        app.run_mode.set.assert_called_once_with("Live Update")
        app.auto_start_var.set.assert_called_once_with(True)
        app.auto_end_var.set.assert_called_once_with(True)
        app.clear_logs_var.set.assert_called_once_with(True)
        app.parallel_var.set.assert_called_once_with(True)

    def test_handler_invoked_with_folder_and_auto_start(self):
        from audio_suite_shared.cli_dataclasses import BPMArgs

        parsed = BPMArgs(folder_path="D:/Music")
        app, handler = self._run(parsed)
        handler.apply_cli_args.assert_called_once_with(
            parsed, folder_var=app.folder_path, auto_start_func=app.start_processing
        )

    def test_auto_start_schedules_processing(self):
        from audio_suite_shared.cli_dataclasses import BPMArgs

        app, _, handler_cls = _make_shell_app()
        handler_cls.return_value.apply_cli_args.return_value = True
        with (
            patch(
                "bpm_analyzer.utils.cli_args.parse",
                return_value=BPMArgs(folder_path="D:/Music"),
            ),
            patch("bpm_analyzer.app.UniversalCLIHandler", handler_cls),
        ):
            app._apply_cli_args()

        after_delays = [call.args[0] for call in app.root.after.call_args_list]
        assert 1500 in after_delays


class TestApplyCliArgsStandalone:
    """Standalone start: defaults applied, no handler/after scheduling."""

    def test_defaults_applied_to_panel_vars(self):
        from audio_suite_shared.cli_dataclasses import BPMArgs

        app, _, handler_cls = _make_shell_app()
        with (
            patch(
                "bpm_analyzer.utils.cli_args.parse",
                return_value=BPMArgs(),
            ),
            patch("bpm_analyzer.app.UniversalCLIHandler", handler_cls),
        ):
            app._apply_cli_args()

        app.run_mode.set.assert_called_once_with("Dry Run")
        app.auto_start_var.set.assert_called_once_with(False)
        app.auto_end_var.set.assert_called_once_with(False)
        app.clear_logs_var.set.assert_called_once_with(False)
        app.parallel_var.set.assert_called_once_with(False)

    def test_no_handler_or_scheduling_without_folder(self):
        from audio_suite_shared.cli_dataclasses import BPMArgs

        app, handler, handler_cls = _make_shell_app()
        with (
            patch(
                "bpm_analyzer.utils.cli_args.parse",
                return_value=BPMArgs(),
            ),
            patch("bpm_analyzer.app.UniversalCLIHandler", handler_cls),
        ):
            app._apply_cli_args()

        app.run_mode.set.assert_called_once_with("Dry Run")
        handler.apply_cli_args.assert_not_called()
        app.root.after.assert_not_called()


# ---------------------------------------------------------------------------
# Stage 3 / item D3 (audit A4): the real app is constructed on a withdrawn
# Toplevel of the shared hidden root; the run-mode plumbing is asserted where
# it reaches the core entry (bpm_analyzer.core.file_processor.run_analysis).
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_root(root):
    import tkinter as tk

    top = tk.Toplevel(root)
    top.withdraw()
    try:
        yield top
    finally:
        top.destroy()


def assert_bound(callback: object, name: str, obj: object) -> None:
    """Bound methods are fresh objects per access: compare attributes."""
    assert getattr(callback, "__self__", None) is obj
    assert getattr(callback, "__name__", None) == name


class TestRealAppConstructionD3:
    def test_full_ui_builds_and_wires_vars(self, app_root, tmp_path, monkeypatch):
        from bpm_analyzer.app import BPMAnalyzerApp

        monkeypatch.setattr(
            "bpm_analyzer.app._suite_config.load_last_directory", lambda: ""
        )
        # The constructor consumes the Master-Driver CLI handshake from
        # sys.argv; pytest's own argv must not leak into that parser.
        monkeypatch.setattr(sys, "argv", ["bpm_analyzer"])
        app = BPMAnalyzerApp(app_root)
        assert app.start_btn is not None
        assert app.folder_path.get() == ""
        assert app.run_mode.get() in {"Dry Run", "Live Update"}
        assert app.bpm_range_min.get() != ""

    def test_preset_collect_and_apply_roundtrip(self, app_root, tmp_path, monkeypatch):
        from bpm_analyzer.app import BPMAnalyzerApp

        monkeypatch.setattr(
            "bpm_analyzer.app._suite_config.load_last_directory", lambda: ""
        )
        monkeypatch.setattr(sys, "argv", ["bpm_analyzer"])
        app = BPMAnalyzerApp(app_root)
        app = BPMAnalyzerApp(app_root)
        app._apply_preset(
            {
                "bpm_min": 60,
                "bpm_max": 200,
                "duration": 30,
                "parallel_mode": True,
                "max_workers": 2,
                "run_mode": "Live Update",
            }
        )
        assert app.bpm_range_min.get() == 60
        assert app.bpm_range_max.get() == 200
        assert app.analysis_duration.get() == 30
        assert app.parallel_mode.get() is True
        assert app.max_workers.get() == 2
        assert app.run_mode.get() == "Live Update"
        collected = app._collect_settings()
        assert collected["run_mode"] == "Live Update"


class TestStartProcessingD3:
    def _shell(self):
        from bpm_analyzer.app import BPMAnalyzerApp

        app = object.__new__(BPMAnalyzerApp)
        app.root = MagicMock()
        app.folder_path = MagicMock()
        app.bpm_range_min = MagicMock()
        app.bpm_range_max = MagicMock()
        app.analysis_duration = MagicMock()
        app.max_workers = MagicMock()
        app.parallel_mode = MagicMock()
        app.run_mode = MagicMock()
        app.overall_status = MagicMock()
        app.notebook = MagicMock()
        app.start_btn = MagicMock()
        app._tab_processing = MagicMock()
        app._safe_slot_vars = MagicMock()
        app.slot_queue = MagicMock()
        return app

    def test_valid_folder_starts_analysis_with_run_mode(self, monkeypatch, tmp_path):
        import bpm_analyzer.app as app_mod

        app = self._shell()
        fake_threading = MagicMock()
        monkeypatch.setattr(app_mod, "threading", fake_threading)
        monkeypatch.setattr("bpm_analyzer.app.messagebox", MagicMock())
        src = tmp_path / "music"
        src.mkdir()
        (src / "a.mp3").write_bytes(b"\x00" * 8)
        app.folder_path.get.return_value = str(src)
        app.bpm_range_min.get.return_value = 60
        app.bpm_range_max.get.return_value = 200
        app.analysis_duration.get.return_value = 30
        app.max_workers.get.return_value = 2
        app.parallel_mode.get.return_value = False
        app.run_mode.get.return_value = "Dry Run"
        saves: list[tuple[str, object]] = []
        monkeypatch.setattr(
            "bpm_analyzer.app._suite_config.save_value",
            lambda key, value: saves.append((key, value)),
        )

        app.start_processing()

        thread = fake_threading.Thread.call_args
        assert_bound(thread.kwargs["target"], "_run_analysis", app)
        assert thread.kwargs["args"][1] is True  # is_dry_run from "Dry Run"
        assert thread.kwargs["args"][2] == 60
        assert thread.kwargs["args"][3] == 200
        assert saves

    def test_missing_folder_shows_error(self, monkeypatch):

        app = self._shell()
        dialogs = MagicMock()
        monkeypatch.setattr("bpm_analyzer.app.messagebox", dialogs)
        app.folder_path.get.return_value = ""

        app.start_processing()

        dialogs.showerror.assert_called_once()

    def test_bad_bpm_range_shows_error(self, monkeypatch, tmp_path):

        app = self._shell()
        dialogs = MagicMock()
        monkeypatch.setattr("bpm_analyzer.app.messagebox", dialogs)
        src = tmp_path / "music"
        src.mkdir()
        (src / "a.mp3").write_bytes(b"x")
        app.folder_path.get.return_value = str(src)
        app.bpm_range_min.get.return_value = 300
        app.bpm_range_max.get.return_value = 200

        app.start_processing()

        dialogs.showerror.assert_called_once()

    def test_worker_thread_calls_core_entry_with_flags(self, monkeypatch, tmp_path):
        from bpm_analyzer.app import BPMAnalyzerApp

        app = object.__new__(BPMAnalyzerApp)
        app.root = MagicMock()
        app._safe_slot_vars = MagicMock()
        app.slot_queue = MagicMock()
        calls: dict[str, object] = {}

        def fake_run_analysis(**kwargs):
            calls.update(kwargs)

        import bpm_analyzer.core.file_processor as core

        monkeypatch.setattr(core, "run_analysis", fake_run_analysis)

        app._run_analysis(str(tmp_path), True, 60, 200, 30, False, 2)

        assert calls["dir_path"] == str(tmp_path)
        assert calls["is_dry_run"] is True
        assert calls["min_bpm"] == 60
        assert calls["max_bpm"] == 200
