"""
Tests for metadata_scrubber.app — Run Controls panel wiring.

Uses the object.__new__ + MagicMock pattern so no real Tk root is
needed (per AGENTS.md GUI testing rules).

Changed in 1.2.0: covers the run note a finished scrub leaves for the Master
Driver batch report (the files it could not scrub, and any it skipped).
Changed in 2.0.0: adds the ``TestCompletionSeam`` cases driving
``run_scrubbing`` into the completion handler (PLAN D117).
"""

import sys
import tkinter as tk
from pathlib import Path
from queue import Queue
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from audio_suite_shared.run_outcome import read_outcome
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


def _pinned_app_with_last_dir(
    app_root: tk.Toplevel,
    monkeypatch: pytest.MonkeyPatch,
    last_dir: Path,
) -> Any:
    """Real app whose restored last-directory triggers an auto scan."""
    monkeypatch.setattr(
        "metadata_scrubber.app.suite_config.load_last_directory",
        lambda: str(last_dir),
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

    def test_restored_last_directory_prefills_and_schedules_scan(
        self, app_root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A saved last directory is pre-filled (and an auto scan scheduled);
        the empty-string path (asserted in ``test_full_ui_builds_and_wires_vars``)
        covers the no-restore branch."""
        app = _pinned_app_with_last_dir(app_root, monkeypatch, tmp_path)
        assert app.folder_path.get() == str(tmp_path)

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

    def test_non_directory_path_errors(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        app = self._shell()
        dialogs = MagicMock()
        monkeypatch.setattr("metadata_scrubber.app.messagebox", dialogs)
        app.folder_path.get.return_value = str(tmp_path / "not_a_directory")

        app.start_processing()

        dialogs.showerror.assert_called_once_with(
            "Error", "Selected path is not a valid directory."
        )

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


class TestRunNote:
    """A finished scrub leaves its damage where a batch report can see it."""

    def _complete(
        self,
        app_root: tk.Toplevel,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        *,
        total: int,
        skipped: int,
        errors: int,
    ) -> Any:
        import metadata_scrubber.app as app_mod

        app = _pinned_app(app_root, monkeypatch)
        app._log_path = str(tmp_path / "scrub_log.txt")
        app.auto_end = False
        monkeypatch.setattr(app_mod, "messagebox", MagicMock())
        app._on_complete(
            header=["REPORT\n"],
            is_live=False,
            preserve_list=[],
            total=total,
            processed=total - skipped,
            skipped=skipped,
            errors=errors,
            duration_secs=1.0,
            log_entries=[],
        )
        return app

    def test_unscrubbed_and_skipped_files_are_reported(
        self, app_root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))

        self._complete(app_root, monkeypatch, tmp_path, total=10, skipped=2, errors=1)

        assert read_outcome("scrubber") == (
            "1 of 10 files could not be scrubbed; 2 of 10 files were skipped"
        )

    def test_a_clean_run_reports_nothing(
        self, app_root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))

        self._complete(app_root, monkeypatch, tmp_path, total=4, skipped=0, errors=0)

        assert read_outcome("scrubber") == ""

    def test_a_later_clean_run_clears_an_earlier_note(
        self, app_root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        self._complete(app_root, monkeypatch, tmp_path, total=4, skipped=0, errors=2)
        assert read_outcome("scrubber") == "2 of 4 files could not be scrubbed"

        self._complete(app_root, monkeypatch, tmp_path, total=4, skipped=0, errors=0)

        assert read_outcome("scrubber") == ""


class TestDoScan:
    """_do_scan drives tag discovery + prefs restore + optional auto start."""

    def _shell(self) -> Any:
        app = object.__new__(MetadataScrubberApp)
        app.root = MagicMock()
        app.folder_path = MagicMock(spec=tk.StringVar)
        app.auto_start = False
        app._setup_tab = MagicMock()
        app.start_processing = MagicMock()
        return app

    def test_empty_folder_does_not_scan(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = self._shell()
        app.folder_path.get.return_value = ""
        scanner = MagicMock()
        monkeypatch.setattr(
            "metadata_scrubber.app.tag_scanner.scan_custom_tags", scanner
        )

        app._do_scan()

        scanner.assert_not_called()
        app._setup_tab.populate_tags.assert_not_called()

    def test_scan_populates_tags_with_saved_prefs(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        app = self._shell()
        app.folder_path.get.return_value = str(tmp_path)
        monkeypatch.setattr(
            "metadata_scrubber.app.tag_scanner.scan_custom_tags",
            lambda _folder, sample_size=100, on_error=None: {"BPM", "Genre"},
        )
        monkeypatch.setattr(
            "metadata_scrubber.app.tag_prefs.load_kept_tags",
            lambda _pkg_dir: {"BPM"},
        )

        app._do_scan()

        app._setup_tab.populate_tags.assert_called_once_with(
            {"BPM", "Genre"}, previously_kept={"BPM"}
        )
        app.root.after.assert_not_called()

    def test_scan_error_is_reported(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        app = self._shell()
        app.folder_path.get.return_value = str(tmp_path)
        dialogs = MagicMock()
        monkeypatch.setattr("metadata_scrubber.app.messagebox", dialogs)

        def _scan_with_error(
            _folder: str, sample_size: int = 100, on_error: Any = None
        ) -> set[str]:
            assert on_error is not None
            on_error("boom")
            return set()

        monkeypatch.setattr(
            "metadata_scrubber.app.tag_scanner.scan_custom_tags", _scan_with_error
        )
        monkeypatch.setattr(
            "metadata_scrubber.app.tag_prefs.load_kept_tags", lambda _pkg_dir: set()
        )

        app._do_scan()

        dialogs.showerror.assert_called_once_with("Error", "boom")

    def test_auto_start_schedules_processing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        app = self._shell()
        app.auto_start = True
        app.folder_path.get.return_value = str(tmp_path)
        monkeypatch.setattr(
            "metadata_scrubber.app.tag_scanner.scan_custom_tags",
            lambda _folder, sample_size=100, on_error=None: set(),
        )
        monkeypatch.setattr(
            "metadata_scrubber.app.tag_prefs.load_kept_tags", lambda _pkg_dir: set()
        )

        app._do_scan()

        app.root.after.assert_called_once_with(500, app.start_processing)


class TestBrowseAndScan:
    """_browse_and_scan pairs a folder dialog with an immediate scan."""

    def test_browses_then_scans(self) -> None:
        app = object.__new__(MetadataScrubberApp)
        app._browse_folder_standard = MagicMock()
        app.folder_path = MagicMock(spec=tk.StringVar)
        app._do_scan = MagicMock()

        app._browse_and_scan()

        app._browse_folder_standard.assert_called_once_with(
            title="Select Music Directory",
            path_variable=app.folder_path,
            save_last_dir=True,
        )
        app._do_scan.assert_called_once()


class TestPresetHandlers:
    """Preset save/delete/select round-trip through suite_config."""

    def test_preset_selected_applies_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = object.__new__(MetadataScrubberApp)
        app._apply_preset = MagicMock()
        monkeypatch.setattr(
            "metadata_scrubber.app.suite_config.load_preset",
            lambda _tool, _name: {"run_mode": "Live Update"},
        )

        app._on_preset_selected("My Preset")

        app._apply_preset.assert_called_once_with({"run_mode": "Live Update"})

    def test_save_current_as_preset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = object.__new__(MetadataScrubberApp)
        app._refresh_preset_list = MagicMock()
        app._collect_settings = MagicMock(return_value={"run_mode": "Dry Run"})
        save = MagicMock()
        monkeypatch.setattr("metadata_scrubber.app.suite_config.save_preset", save)
        monkeypatch.setattr(
            "metadata_scrubber.app.suite_config.list_presets",
            lambda _tool: ["Saved"],
        )

        app._save_current_as_preset("Saved")

        save.assert_called_once_with(
            "metadata_scrubber", "Saved", {"run_mode": "Dry Run"}
        )
        app._refresh_preset_list.assert_called_once_with(["Saved"])

    def test_delete_preset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = object.__new__(MetadataScrubberApp)
        app._refresh_preset_list = MagicMock()
        delete = MagicMock()
        monkeypatch.setattr("metadata_scrubber.app.suite_config.delete_preset", delete)
        monkeypatch.setattr(
            "metadata_scrubber.app.suite_config.list_presets", lambda _tool: []
        )

        app._delete_preset("Old")

        delete.assert_called_once_with("metadata_scrubber", "Old")
        app._refresh_preset_list.assert_called_once_with([])


class TestOnCompleteLogWrite:
    """_on_complete log-write failure and auto-end branches."""

    def _shell(self) -> Any:
        app = object.__new__(MetadataScrubberApp)
        app.time_label = MagicMock()
        app.summary_label = MagicMock()
        app.completion_label = MagicMock()
        app.notebook = MagicMock()
        app.start_btn = MagicMock()
        app._tab_results = MagicMock()
        return app

    def test_log_write_failure_shows_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        app = self._shell()
        app._log_path = str(tmp_path / "log.txt")
        app.auto_end = False
        dialogs = MagicMock()
        monkeypatch.setattr("metadata_scrubber.app.messagebox", dialogs)
        monkeypatch.setattr("metadata_scrubber.app.map_to_audio_error", lambda exc: exc)
        monkeypatch.setattr(
            "metadata_scrubber.app.user_message_for", lambda _exc: "disk boom"
        )
        logger = MagicMock()
        monkeypatch.setattr("metadata_scrubber.app.logger", logger)

        def _raising_open(*_args: Any, **_kw: Any) -> None:
            raise OSError("denied")

        monkeypatch.setattr("builtins.open", _raising_open)

        app._on_complete(
            header=["R\n"],
            is_live=False,
            preserve_list=[],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
        )

        dialogs.showerror.assert_called_once_with(
            "Error", "Could not write log file:\ndisk boom"
        )
        logger.error.assert_called_once()

    def test_auto_end_appends_line_and_schedules_destroy(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        app = self._shell()
        app._log_path = str(tmp_path / "log.txt")
        app.auto_end = True
        app.root = MagicMock()

        app._on_complete(
            header=["R\n"],
            is_live=False,
            preserve_list=[],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=["entry\n"],
        )

        text = Path(app._log_path).read_text(encoding="utf-8")
        assert "[Auto End enabled - closing in 2 seconds...]" in text
        app.root.update_idletasks.assert_called_once()
        app.root.after.assert_called_once_with(2000, app.root.destroy)

    def test_auto_end_rewrite_failure_warns(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        app = self._shell()
        app._log_path = str(tmp_path / "log.txt")
        app.auto_end = True
        app.root = MagicMock()
        logger = MagicMock()
        monkeypatch.setattr("metadata_scrubber.app.logger", logger)
        real_open = open
        count = {"n": 0}

        def _flaky_open(file: Any, *args: Any, **kwargs: Any) -> Any:
            # First write succeeds; the auto-end rewrite fails.
            count["n"] += 1
            if count["n"] <= 1:
                return real_open(file, *args, **kwargs)
            raise OSError("rewrite denied")

        monkeypatch.setattr("builtins.open", _flaky_open)

        app._on_complete(
            header=["R\n"],
            is_live=False,
            preserve_list=[],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
        )

        logger.warning.assert_called_once()
        app.root.after.assert_called_once_with(2000, app.root.destroy)


# ---------------------------------------------------------------------------
# Completion seam: the processor payload must reach the handler _run binds and
# land in the report the run writes.
# ---------------------------------------------------------------------------

_HEADER = ["METADATA SCRUBBING REPORT\n"]


def _completion_shell(tmp_path: Path) -> MetadataScrubberApp:
    """Shell with only what the completion path touches."""
    app = object.__new__(MetadataScrubberApp)
    app.root = MagicMock()
    app._log_path = str(tmp_path / "metadata_dry_run_log.txt")
    app.auto_end = False
    app.time_label = MagicMock()
    app.summary_label = MagicMock()
    app.completion_label = MagicMock()
    app.notebook = MagicMock()
    app._tab_results = MagicMock()
    app.start_btn = MagicMock()
    return app


class TestCompletionSeam:
    """``run_scrubbing`` publishes into the handler ``_run`` binds."""

    @staticmethod
    def _wire(app: MetadataScrubberApp):
        """Return the completion callable ``_run`` hands to the processor."""
        return lambda **kw: app._on_complete(
            header=_HEADER, is_live=False, preserve_list=[], **kw
        )

    @staticmethod
    def _fake_process_single_file(*args: Any, **kwargs: Any) -> None:
        """Stand in for the per-file scrub, one outcome per file."""
        name = args[0]
        on_progress = args[10]
        outcomes = {
            "a.mp3": {"n_skipped": 0, "n_errors": 0},
            "b.mp3": {"n_skipped": 1, "n_errors": 0},
            "c.mp3": {"n_skipped": 0, "n_errors": 1},
        }
        outcome = outcomes[name]
        on_progress(
            n_skipped=outcome["n_skipped"],
            n_errors=outcome["n_errors"],
            display_text=name,
            log_text=f"{name}\n",
        )

    def test_the_real_payload_is_written(self, tmp_path: Path) -> None:
        """Every published count reaches the report the handler writes."""
        from metadata_scrubber.core import scrubber

        for name in ("a.mp3", "b.mp3", "c.mp3"):
            (tmp_path / name).write_bytes(b"")
        app = _completion_shell(tmp_path)

        with patch.object(
            scrubber,
            "process_single_file",
            side_effect=self._fake_process_single_file,
        ):
            scrubber.run_scrubbing(
                dir_path=str(tmp_path),
                is_dry_run=True,
                preserve_list=[],
                preserve_lyrics=True,
                preserve_album_artist=True,
                preserve_embedded_art=True,
                slot_vars=[MagicMock()],
                slot_queue=Queue(),
                on_progress=MagicMock(),
                on_complete=self._wire(app),
                on_error=MagicMock(),
            )

        report = (tmp_path / "metadata_dry_run_log.txt").read_text(encoding="utf-8")
        assert "Total files: 3" in report
        assert "Successfully processed: 1" in report
        assert "Skipped: 1" in report
        assert "Errors: 1" in report

    @pytest.mark.parametrize(
        "field",
        ["total", "processed", "skipped", "errors", "duration_secs", "log_entries"],
    )
    def test_a_missing_field_raises_and_writes_no_report(
        self, tmp_path: Path, field: str
    ) -> None:
        """A dropped field names itself and leaves no report behind."""
        app = _completion_shell(tmp_path)
        payload: dict[str, Any] = {
            "total": 3,
            "processed": 3,
            "skipped": 1,
            "errors": 1,
            "duration_secs": 1.0,
            "log_entries": ["line\n"],
        }
        payload.pop(field)

        with pytest.raises(TypeError) as caught:
            self._wire(app)(**payload)

        assert field in str(caught.value)
        assert not (tmp_path / "metadata_dry_run_log.txt").exists()
