"""
Tests for metadata_scrubber.app — Run Controls panel wiring.

Uses the object.__new__ + MagicMock pattern so no real Tk root is
needed (per AGENTS.md GUI testing rules).
"""

import sys
import tkinter as tk
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from metadata_scrubber.app import MetadataScrubberApp
from metadata_scrubber.utils.cli_args import ScrubberArgs


@pytest.fixture()
def app_root(root: tk.Tk) -> Any:
    top = tk.Toplevel(root)
    top.withdraw()
    try:
        yield top
    finally:
        top.destroy()


def _pinned_app(app_root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Real app with the Master-Driver CLI handshake neutralised."""
    monkeypatch.setattr(
        "metadata_scrubber.app.suite_config.load_last_directory", lambda: ""
    )
    monkeypatch.setattr(sys, "argv", ["metadata_scrubber"])
    return MetadataScrubberApp(app_root)


def _make_app() -> MetadataScrubberApp:
    """Build a shell app instance with mock attributes (no real Tk)."""
    app = object.__new__(MetadataScrubberApp)
    app.root = MagicMock()
    app.folder_path = MagicMock(spec=tk.StringVar)
    app.run_mode = MagicMock(spec=tk.StringVar)
    app.auto_start_var = MagicMock(spec=tk.BooleanVar)
    app.auto_end_var = MagicMock(spec=tk.BooleanVar)
    app.clear_logs_var = MagicMock(spec=tk.BooleanVar)
    app.parallel_var = MagicMock(spec=tk.BooleanVar)
    app.cli_handler = MagicMock()
    app.cli_handler.apply_cli_args.return_value = False
    return app


class TestApplyCliArgsDriven:
    """A driver launch populates and locks the Run Controls values."""

    def test_inherited_values_applied_to_panel_vars(self):
        app = _make_app()
        parsed = ScrubberArgs(
            folder_path="D:/Music",
            live_mode=True,
            auto_start=True,
            auto_end=True,
            clear_logs=True,
            parallel_run=True,
        )
        with (
            patch("metadata_scrubber.utils.cli_args.parse", return_value=parsed),
            patch(
                "metadata_scrubber.utils.cli_args.was_launched_from_driver",
                return_value=True,
            ),
        ):
            app._apply_cli_args()

        app.run_mode.set.assert_called_once_with("Live Update")
        app.auto_start_var.set.assert_called_once_with(True)
        app.auto_end_var.set.assert_called_once_with(True)
        app.clear_logs_var.set.assert_called_once_with(True)
        app.parallel_var.set.assert_called_once_with(True)

    def test_folder_passed_to_cli_handler(self):
        app = _make_app()
        parsed = ScrubberArgs(folder_path="D:/Music")
        with (
            patch("metadata_scrubber.utils.cli_args.parse", return_value=parsed),
            patch(
                "metadata_scrubber.utils.cli_args.was_launched_from_driver",
                return_value=True,
            ),
        ):
            app._apply_cli_args()

        app.cli_handler.apply_cli_args.assert_called_once_with(
            parsed,
            folder_var=app.folder_path,
            auto_start_func=app._do_scan,
        )

    def test_scan_scheduled_after_apply(self):
        app = _make_app()
        parsed = ScrubberArgs(folder_path="D:/Music")
        with (
            patch("metadata_scrubber.utils.cli_args.parse", return_value=parsed),
            patch(
                "metadata_scrubber.utils.cli_args.was_launched_from_driver",
                return_value=True,
            ),
        ):
            app._apply_cli_args()

        after_delays = [call.args[0] for call in app.root.after.call_args_list]
        assert 500 in after_delays

    def test_auto_start_schedules_processing(self):
        app = _make_app()
        app.cli_handler.apply_cli_args.return_value = True
        parsed = ScrubberArgs(folder_path="D:/Music", auto_start=True)
        with (
            patch("metadata_scrubber.utils.cli_args.parse", return_value=parsed),
            patch(
                "metadata_scrubber.utils.cli_args.was_launched_from_driver",
                return_value=True,
            ),
        ):
            app._apply_cli_args()

        after_delays = [call.args[0] for call in app.root.after.call_args_list]
        assert 1000 in after_delays


class TestApplyCliArgsStandalone:
    """Standalone start: defaults applied, no handler/after scheduling."""

    def test_defaults_applied_to_panel_vars(self):
        app = _make_app()
        with (
            patch(
                "metadata_scrubber.utils.cli_args.parse",
                return_value=ScrubberArgs(),
            ),
            patch(
                "metadata_scrubber.utils.cli_args.was_launched_from_driver",
                return_value=False,
            ),
        ):
            app._apply_cli_args()

        app.run_mode.set.assert_called_once_with("Dry Run")
        app.auto_start_var.set.assert_called_once_with(False)
        app.auto_end_var.set.assert_called_once_with(False)
        app.clear_logs_var.set.assert_called_once_with(False)
        app.parallel_var.set.assert_called_once_with(False)

    def test_no_handler_or_scheduling_without_folder(self):
        app = _make_app()
        with (
            patch(
                "metadata_scrubber.utils.cli_args.parse",
                return_value=ScrubberArgs(),
            ),
            patch(
                "metadata_scrubber.utils.cli_args.was_launched_from_driver",
                return_value=False,
            ),
        ):
            app._apply_cli_args()

        app.run_mode.set.assert_called_once_with("Dry Run")
        app.cli_handler.apply_cli_args.assert_not_called()
        app.root.after.assert_not_called()


def assert_bound(callback: object, name: str, obj: object) -> None:
    """Bound methods are fresh objects per access: compare attributes."""
    assert getattr(callback, "__self__", None) is obj
    assert getattr(callback, "__name__", None) == name


class TestRealAppConstructionD3:
    def test_full_ui_builds_and_wires_vars(
        self, app_root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _pinned_app(app_root, monkeypatch)
        assert app.start_btn is not None
        assert app.folder_path.get() == ""
        assert app.run_mode.get() in {"Dry Run", "Live Update"}

    def test_settings_collect_and_apply_roundtrip(
        self, app_root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _pinned_app(app_root, monkeypatch)
        app._apply_preset(
            {
                "run_mode": "Live Update",
                "preserve_lyrics": False,
                "preserve_album_artist": True,
                "preserve_embedded_art": False,
            }
        )
        assert app.run_mode.get() == "Live Update"
        assert app.preserve_lyrics.get() is False
        assert app.preserve_album_artist.get() is True
        assert app.preserve_embedded_art.get() is False
        collected = app._collect_settings()
        assert collected["run_mode"] == "Live Update"


class TestStartProcessingD3:
    def _shell(self) -> Any:
        app = object.__new__(MetadataScrubberApp)
        app.root = MagicMock()
        app.folder_path = MagicMock()
        app.run_mode = MagicMock()
        app.preserve_lyrics = MagicMock()
        app.preserve_album_artist = MagicMock()
        app.preserve_embedded_art = MagicMock()
        app.overall_status = MagicMock()
        app.notebook = MagicMock()
        app.start_btn = MagicMock()
        app._tab_processing = MagicMock()
        app._tab_results = MagicMock()
        app._setup_tab = MagicMock()
        app._safe_slot_vars = MagicMock()
        app.slot_queue = MagicMock()
        return app

    def test_missing_folder_warns(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = self._shell()
        dialogs = MagicMock()
        monkeypatch.setattr("metadata_scrubber.app.messagebox", dialogs)
        app.folder_path.get.return_value = ""

        app.start_processing()

        dialogs.showwarning.assert_called_once()

    def test_start_threads_scrubbing_with_mode_flags(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import metadata_scrubber.app as app_mod

        app = self._shell()
        fake_threading = MagicMock()
        monkeypatch.setattr(app_mod, "threading", fake_threading)
        monkeypatch.setattr("metadata_scrubber.app.messagebox", MagicMock())
        app.folder_path.get.return_value = str(tmp_path)
        app._setup_tab.get_preserve_list.return_value = ["BPM"]
        app.preserve_lyrics.get.return_value = True
        app.preserve_album_artist.get.return_value = False
        app.preserve_embedded_art.get.return_value = True
        app.run_mode.get.return_value = "Live Update"

        app.start_processing()

        thread = fake_threading.Thread.call_args
        assert_bound(thread.kwargs["target"], "_run_scrubbing", app)
        assert thread.kwargs["args"] == (["BPM"], True, False, True, True)

    def test_run_scrubbing_passes_all_flags_to_core(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        app = self._shell()
        app.progress = MagicMock()
        app.stats_label = MagicMock()
        app.folder_path.get.return_value = str(tmp_path)
        calls: dict[str, object] = {}

        def fake_run_scrubbing(**kwargs: Any) -> None:
            calls.update(kwargs)

        monkeypatch.setattr(
            "metadata_scrubber.core.scrubber.run_scrubbing", fake_run_scrubbing
        )

        app._run_scrubbing(["BPM"], True, False, True, False)

        assert calls["dir_path"] == str(tmp_path)
        assert calls["is_dry_run"] is True
        assert calls["preserve_lyrics"] is True
        assert calls["preserve_album_artist"] is False
        assert calls["preserve_embedded_art"] is True


class TestProgressAndCompleteD3:
    def test_on_progress_updates_widgets(self) -> None:
        app = object.__new__(MetadataScrubberApp)
        app.progress = MagicMock()
        app.stats_label = MagicMock()
        app.file_listbox = MagicMock()

        app._on_progress(3, 10, 1, 1, "song.mp3: scrubbed")

        assert app.stats_label.config.call_args.kwargs["text"].startswith(
            "Processed: 3"
        )
        assert app.file_listbox.insert.call_args.args[0] == tk.END

    def test_on_complete_writes_log_and_renders_summary(
        self, app_root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        app = _pinned_app(app_root, monkeypatch)
        # The real app started fresh; point its log path at the scratch dir.
        import metadata_scrubber.app as app_mod

        app._log_path = str(tmp_path / "dry_log.txt")
        app.auto_end = False
        monkeypatch.setattr(app_mod, "messagebox", MagicMock())

        app._on_complete(
            header=["REPORT\n"],
            is_live=False,
            preserve_list=["BPM"],
            total=10,
            processed=8,
            skipped=1,
            errors=1,
            duration_secs=65.4,
            log_entries=["entry\n"],
        )

        log_text = Path(app._log_path).read_text(encoding="utf-8")
        # The mode string lives in the header the worker passes in.
        assert "Total files: 10" in log_text
        assert str(app.completion_label.cget("text")) == "Analysis Complete!"
        assert str(app.summary_label.cget("text")).startswith("Total: 10")

    def test_live_completion_saves_tag_prefs(
        self, app_root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The live branch (app.py ``if is_live:`` → ``save_kept_tags``) is
        the side effect users depend on: the ticked set is persisted to
        tag_prefs.json.  Audit M5 found only the dry-run negative existed,
        so deleting the save would have left the suite green."""
        import metadata_scrubber.app as app_mod

        save_kept = MagicMock()
        monkeypatch.setattr(
            "metadata_scrubber.utils.tag_prefs.save_kept_tags", save_kept
        )
        app = _pinned_app(app_root, monkeypatch)
        app._log_path = str(tmp_path / "live_log.txt")
        app.auto_end = False
        monkeypatch.setattr(app_mod, "messagebox", MagicMock())

        app._on_complete(
            header=["REPORT\n"],
            is_live=True,
            preserve_list=["BPM"],
            total=10,
            processed=8,
            skipped=1,
            errors=1,
            duration_secs=65.4,
            log_entries=["entry\n"],
        )

        save_kept.assert_called_once_with(app_mod._PACKAGE_DIR, ["BPM"])
        assert str(app.completion_label.cget("text")) == "Metadata Scrubbing Complete!"
        log_text = Path(app._log_path).read_text(encoding="utf-8")
        assert "Total files: 10" in log_text

    def test_dry_run_completion_never_saves_tag_prefs(
        self, app_root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        save_kept = MagicMock()
        monkeypatch.setattr(
            "metadata_scrubber.utils.tag_prefs.save_kept_tags", save_kept
        )
        app = _pinned_app(app_root, monkeypatch)
        app._log_path = str(tmp_path / "log2.txt")
        app.auto_end = False

        app._on_complete(
            header=["R\n"],
            is_live=False,
            preserve_list=["KEY"],
            total=2,
            processed=2,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
        )

        save_kept.assert_not_called()  # dry runs never update the rolling prefs
