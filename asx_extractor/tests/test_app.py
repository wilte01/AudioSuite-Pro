"""
Tests for asx_extractor.app.ASXExtractorTool GUI-level methods.

Covers preset CRUD, user actions (_open_log, _open_folder,
start_extraction), auto-end behaviour, and the log-write-failure
branch inside _run().  The existing test_app_run.py covers the
full _run() orchestration; this file targets the surrounding
GUI wiring that sits outside _run().

ASXExtractorTool requires a live tk.Tk() + bootstrap_tool_app() to
construct normally.  We bypass __init__ via __new__ and stub only
the attributes each method under test reads.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from asx_extractor.app import TOOL_ID, ASXExtractorTool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(
    folder: str = "",
    mode: str = "Dry Run (Simulated)",
    auto_end: bool = False,
) -> ASXExtractorTool:
    """Build an ASXExtractorTool instance with only the attributes
    the GUI-level methods depend on, bypassing __init__."""
    tool = ASXExtractorTool.__new__(ASXExtractorTool)

    tool.current_folder = MagicMock()
    tool.current_folder.get.return_value = folder

    tool.asx_action_mode = MagicMock()
    tool.asx_action_mode.get.return_value = mode

    tool.root = MagicMock()
    tool.root.after.side_effect = lambda _delay, callback=None: (
        callback() if callable(callback) else None
    )

    tool._update_step = MagicMock()
    tool.notebook = MagicMock()
    tool._tab_extractor = MagicMock()
    tool._tab_review = MagicMock()
    tool._btn_log = MagicMock()

    tool.auto_end = auto_end
    tool.auto_end_var = MagicMock()
    tool.auto_end_var.get.return_value = auto_end

    tool._refresh_preset_list = MagicMock()
    tool._preset_combo = MagicMock()
    tool._out_dir = ""

    return tool


# ---------------------------------------------------------------------------
# Preset CRUD
# ---------------------------------------------------------------------------


class TestCollectSettings:
    def test_returns_run_mode_from_widget(self) -> None:
        tool = _make_tool(mode="Execute Extraction (Permanent)")
        result = tool._collect_settings()
        assert result == {"run_mode": "Execute Extraction (Permanent)"}
        tool.asx_action_mode.get.assert_called_once()

    def test_returns_dry_run_mode(self) -> None:
        tool = _make_tool(mode="Dry Run (Simulated)")
        result = tool._collect_settings()
        assert result == {"run_mode": "Dry Run (Simulated)"}


class TestApplyPreset:
    def test_sets_mode_when_run_mode_present(self) -> None:
        tool = _make_tool()
        tool._apply_preset({"run_mode": "Execute Extraction (Permanent)"})
        tool.asx_action_mode.set.assert_called_once_with(
            "Execute Extraction (Permanent)"
        )

    def test_does_nothing_when_run_mode_absent(self) -> None:
        tool = _make_tool()
        tool._apply_preset({"other_key": "value"})
        tool.asx_action_mode.set.assert_not_called()

    def test_empty_dict_is_a_noop(self) -> None:
        tool = _make_tool()
        tool._apply_preset({})
        tool.asx_action_mode.set.assert_not_called()


class TestOnPresetSelected:
    @patch("asx_extractor.app.suite_config")
    def test_loads_and_applies_when_settings_nonempty(self, mock_sc: MagicMock) -> None:
        mock_sc.load_preset.return_value = {
            "run_mode": "Execute Extraction (Permanent)"
        }
        tool = _make_tool()
        tool._on_preset_selected("my_preset")

        mock_sc.load_preset.assert_called_once_with(TOOL_ID, "my_preset")
        tool.asx_action_mode.set.assert_called_once_with(
            "Execute Extraction (Permanent)"
        )

    @patch("asx_extractor.app.suite_config")
    def test_does_not_apply_when_settings_empty(self, mock_sc: MagicMock) -> None:
        mock_sc.load_preset.return_value = {}
        tool = _make_tool()
        tool._on_preset_selected("empty_preset")

        mock_sc.load_preset.assert_called_once_with(TOOL_ID, "empty_preset")
        tool.asx_action_mode.set.assert_not_called()

    @patch("asx_extractor.app.suite_config")
    def test_does_not_apply_when_settings_none(self, mock_sc: MagicMock) -> None:
        mock_sc.load_preset.return_value = None
        tool = _make_tool()
        tool._on_preset_selected("missing_preset")

        mock_sc.load_preset.assert_called_once_with(TOOL_ID, "missing_preset")
        tool.asx_action_mode.set.assert_not_called()


class TestSaveCurrentAsPreset:
    @patch("asx_extractor.app.suite_config")
    def test_saves_collected_settings_and_refreshes(self, mock_sc: MagicMock) -> None:
        mock_sc.list_presets.return_value = ["a", "b"]
        tool = _make_tool(mode="Dry Run (Simulated)")
        tool._save_current_as_preset("my_preset")

        mock_sc.save_preset.assert_called_once_with(
            TOOL_ID, "my_preset", {"run_mode": "Dry Run (Simulated)"}
        )
        mock_sc.list_presets.assert_called_once_with(TOOL_ID)
        tool._refresh_preset_list.assert_called_once_with(["a", "b"])


class TestDeletePreset:
    @patch("asx_extractor.app.suite_config")
    def test_deletes_and_refreshes(self, mock_sc: MagicMock) -> None:
        mock_sc.list_presets.return_value = ["remaining"]
        tool = _make_tool()
        tool._delete_preset("old_preset")

        mock_sc.delete_preset.assert_called_once_with(TOOL_ID, "old_preset")
        mock_sc.list_presets.assert_called_once_with(TOOL_ID)
        tool._refresh_preset_list.assert_called_once_with(["remaining"])

    @patch("asx_extractor.app.suite_config")
    def test_refresh_shows_empty_list_after_last_delete(
        self, mock_sc: MagicMock
    ) -> None:
        mock_sc.list_presets.return_value = []
        tool = _make_tool()
        tool._delete_preset("only_preset")

        tool._refresh_preset_list.assert_called_once_with([])


# ---------------------------------------------------------------------------
# User actions
# ---------------------------------------------------------------------------


class TestOpenLog:
    @patch("asx_extractor.app.platform_utils")
    @patch("asx_extractor.app.messagebox")
    def test_opens_log_when_file_exists(
        self,
        mock_mb: MagicMock,
        mock_pu: MagicMock,
        tmp_path: Path,
    ) -> None:
        log = tmp_path / "Extraction_Log.txt"
        log.write_text("log content", encoding="utf-8")

        tool = _make_tool(folder=str(tmp_path))
        tool._open_log()

        mock_pu.open_path.assert_called_once_with(str(log))
        mock_mb.showwarning.assert_not_called()

    @patch("asx_extractor.app.platform_utils")
    @patch("asx_extractor.app.messagebox")
    def test_shows_warning_when_log_missing(
        self,
        mock_mb: MagicMock,
        mock_pu: MagicMock,
        tmp_path: Path,
    ) -> None:
        tool = _make_tool(folder=str(tmp_path))
        tool._open_log()

        mock_mb.showwarning.assert_called_once_with(
            "Log Not Found", "Extraction log file does not exist."
        )
        mock_pu.open_path.assert_not_called()


class TestOpenFolder:
    @patch("asx_extractor.app.platform_utils")
    def test_sets_out_dir_and_opens_when_folder_present(
        self, mock_pu: MagicMock, tmp_path: Path
    ) -> None:
        tool = _make_tool(folder=str(tmp_path))
        tool._open_folder_standard = MagicMock()

        tool._open_folder()

        assert tool._out_dir == str(tmp_path)
        tool._open_folder_standard.assert_called_once()

    @patch("asx_extractor.app.messagebox")
    def test_shows_warning_when_folder_empty(self, mock_mb: MagicMock) -> None:
        tool = _make_tool(folder="")
        tool._open_folder_standard = MagicMock()

        tool._open_folder()

        mock_mb.showwarning.assert_called_once_with(
            "No Folder", "Output folder not available."
        )
        tool._open_folder_standard.assert_not_called()


class TestStartExtraction:
    @patch("asx_extractor.app.threading.Thread")
    def test_resets_steps_selects_tab_starts_thread(
        self, mock_thread_cls: MagicMock
    ) -> None:
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        tool = _make_tool(folder="/some/folder")
        tool.start_extraction()

        tool._update_step.reset.assert_called_once()
        tool.notebook.select.assert_called_once_with(tool._tab_extractor)
        mock_thread_cls.assert_called_once_with(target=tool._run, daemon=True)
        mock_thread.start.assert_called_once()

    @patch("asx_extractor.app.threading.Thread")
    @patch("asx_extractor.app.messagebox")
    def test_shows_warning_when_no_folder(
        self,
        mock_mb: MagicMock,
        mock_thread_cls: MagicMock,
    ) -> None:
        tool = _make_tool(folder="")
        tool.start_extraction()

        mock_mb.showwarning.assert_called_once_with(
            "No Directory", "Please select a target directory first."
        )
        mock_thread_cls.assert_not_called()
        tool._update_step.reset.assert_not_called()
        tool.notebook.select.assert_not_called()


# ---------------------------------------------------------------------------
# Auto-end in _run (lines 334-335)
# ---------------------------------------------------------------------------


class TestRunAutoEnd:
    """When auto_end_var.get() is truthy, _run() schedules root.destroy()
    after 2000 ms so the Master Driver handshake closes the window."""

    def test_auto_end_schedules_destroy(self, tmp_path: Path) -> None:
        tool = _make_tool(folder=str(tmp_path), auto_end=True)

        with patch("asx_extractor.app.active_batch", MagicMock()):
            tool._run()

        # root.after must have been called with (2000, root.destroy)
        destroy_calls = [c for c in tool.root.after.call_args_list if c.args[0] == 2000]
        assert len(destroy_calls) == 1
        assert destroy_calls[0].args[1] == tool.root.destroy

    def test_no_auto_end_does_not_schedule_destroy(self, tmp_path: Path) -> None:
        tool = _make_tool(folder=str(tmp_path), auto_end=False)

        with patch("asx_extractor.app.active_batch", MagicMock()):
            tool._run()

        destroy_calls = [c for c in tool.root.after.call_args_list if c.args[0] == 2000]
        assert len(destroy_calls) == 0


# ---------------------------------------------------------------------------
# Log-write failure in _run (lines 319-325)
# ---------------------------------------------------------------------------


class TestRunLogWriteFailure:
    """When write_extraction_log returns a falsy value, _run() shows an
    error messagebox via root.after."""

    def test_log_write_failure_shows_error(self, tmp_path: Path) -> None:
        tool = _make_tool(folder=str(tmp_path))

        with (
            patch("asx_extractor.app.active_batch", MagicMock()),
            patch(
                "asx_extractor.app.file_ops.write_extraction_log",
                return_value=False,
            ),
            patch("asx_extractor.app.messagebox") as mock_mb,
        ):
            tool._run()

        # The error is scheduled via root.after(0, lambda: messagebox.showerror(...))
        # Because root.after is synchronous in our stub, the call already fired.
        # We verify messagebox.showerror was called.
        mock_mb.showerror.assert_called_once_with(
            "Log Error", "Could not write the extraction log."
        )

    def test_log_write_success_does_not_show_error(self, tmp_path: Path) -> None:
        tool = _make_tool(folder=str(tmp_path))

        with (
            patch("asx_extractor.app.active_batch", MagicMock()),
            patch(
                "asx_extractor.app.file_ops.write_extraction_log",
                return_value=True,
            ),
            patch("asx_extractor.app.messagebox") as mock_mb,
        ):
            tool._run()

        mock_mb.showerror.assert_not_called()


# ---------------------------------------------------------------------------
# _run log-write failure end-to-end (real file, no ASX files → zero/zero)
# ---------------------------------------------------------------------------


class TestRunLogWriteFailureEndToEnd:
    """Integration: the log-write-failure branch fires on an empty
    directory (zero ASX files) when write_extraction_log is mocked
    to return False.  Verifies the messagebox is reached without
    crashing the rest of _run()."""

    def test_log_failure_on_empty_dir_shows_error(self, tmp_path: Path) -> None:
        tool = _make_tool(folder=str(tmp_path))

        with (
            patch("asx_extractor.app.active_batch", MagicMock()),
            patch(
                "asx_extractor.app.file_ops.write_extraction_log",
                return_value=False,
            ),
            patch("asx_extractor.app.messagebox") as mock_mb,
        ):
            tool._run()

        mock_mb.showerror.assert_called_once_with(
            "Log Error", "Could not write the extraction log."
        )
        # btn_log is still enabled and tab switches to review
        tool._btn_log.config.assert_called_once_with(state="normal")
        # The 1000ms tab-switch to review was scheduled.
        delays = [c.args[0] for c in tool.root.after.call_args_list]
        assert 1000 in delays


# ---------------------------------------------------------------------------
# _browse_folder and _open_help (delegation methods)
# ---------------------------------------------------------------------------


class TestBrowseFolder:
    def test_delegates_to_browse_folder_standard(self) -> None:
        tool = _make_tool(folder="/some/folder")
        tool._browse_folder_standard = MagicMock()
        tool._browse_folder()
        tool._browse_folder_standard.assert_called_once_with(
            title="Select Music Directory",
            path_variable=tool.current_folder,
            save_last_dir=True,
        )


class TestOpenHelp:
    def test_delegates_to_open_help_standard(self) -> None:
        tool = _make_tool()
        tool._open_help_standard = MagicMock()
        tool._open_help()
        tool._open_help_standard.assert_called_once_with(tool.HELP_GUIDE)
