"""
tests/test_app.py
Tests for app.py — TempoAnalyzerApp orchestration logic.

Run with:
    pytest tests/test_app.py -v

Coverage
--------
_on_complete
  * Writes log file with header, entries, and summary
  * Summary format includes total/analysed/skipped/errors/time
  * UI update scheduled via root.after
  * OSError during log write does not crash
  * auto_end schedules root.destroy

_collect_settings
  * Returns dict with tempo_scheme and run_mode

_apply_preset
  * Sets both variables from preset dict
  * Partial preset only sets provided keys

_on_scheme_change
  * Updates _active_markings from TEMPO_SCHEMES
  * Persists preference via suite_config
  * Refreshes reference table
  * Ignores unknown scheme names
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tempo_analyzer.app import TempoAnalyzerApp
from tempo_analyzer.core.tempo_schemes import TEMPO_SCHEMES


class TestOnComplete:
    """_on_complete() writes log files and schedules UI updates."""

    @pytest.fixture
    def app(self, tmp_path: Path) -> TempoAnalyzerApp:
        root = MagicMock()
        scheduled: list = []
        root.after.side_effect = lambda delay, fn, *a, **kw: scheduled.append((fn, a))

        app = object.__new__(TempoAnalyzerApp)
        app.root = root
        app._log_path = str(tmp_path / "tempo_log.txt")
        app._scheduled = scheduled
        app.progress = MagicMock()
        app.overall_status = MagicMock()
        app.time_label = MagicMock()
        app.summary_label = MagicMock()
        app.completion_label = MagicMock()
        app.notebook = MagicMock()
        app.start_btn = MagicMock()
        app._tab_results = MagicMock()
        app.run_mode = MagicMock()
        app.run_mode.get.return_value = "Dry Run"
        app.auto_end = False
        return app

    def _run(self, app: TempoAnalyzerApp, **kwargs: object) -> None:
        defaults: dict[str, object] = {
            "header": ["TEMPO ANALYSIS REPORT\n", "Scheme: Italian\n"],
            "total": 0,
            "processed": 0,
            "skipped": 0,
            "errors": 0,
            "duration_secs": 0.0,
            "log_entries": [],
        }
        defaults.update(kwargs)
        app._on_complete(**defaults)  # type: ignore[arg-type]
        if app._scheduled:
            fn, args = app._scheduled[-1]
            fn(*args)

    def test_log_file_created(self, app: TempoAnalyzerApp) -> None:
        self._run(app, total=1, processed=1, log_entries=["line1\n"])
        assert Path(app._log_path).exists()

    def test_log_contains_header(self, app: TempoAnalyzerApp) -> None:
        self._run(app)
        content = Path(app._log_path).read_text(encoding="utf-8")
        assert "TEMPO ANALYSIS REPORT" in content
        assert "Scheme: Italian" in content

    def test_log_contains_entries(self, app: TempoAnalyzerApp) -> None:
        self._run(app, log_entries=["track_a.txt\n", "track_b.txt\n"])
        content = Path(app._log_path).read_text(encoding="utf-8")
        assert "track_a.txt" in content
        assert "track_b.txt" in content

    def test_summary_format(self, app: TempoAnalyzerApp) -> None:
        self._run(app, total=10, processed=8, skipped=1, errors=1, duration_secs=65.0)
        content = Path(app._log_path).read_text(encoding="utf-8")
        assert "Total files: 10" in content
        assert "Tagged/Analyzed: 6" in content
        assert "Skipped (no BPM): 1" in content
        assert "Errors: 1" in content
        assert "Time: 01:05" in content

    def test_summary_zero_duration(self, app: TempoAnalyzerApp) -> None:
        self._run(app, total=1, processed=1, skipped=0, errors=0, duration_secs=0.0)
        content = Path(app._log_path).read_text(encoding="utf-8")
        assert "Time: 00:00" in content

    def test_schedules_ui_update(self, app: TempoAnalyzerApp) -> None:
        self._run(app, total=3, processed=3, skipped=0, errors=0, duration_secs=10.0)
        app.time_label.config.assert_called()
        app.summary_label.config.assert_called()
        app.completion_label.config.assert_called()
        app.notebook.select.assert_called_with(app._tab_results)
        app.start_btn.config.assert_called_with(state="normal")

    def test_oserror_during_log_write_does_not_crash(
        self, app: TempoAnalyzerApp
    ) -> None:
        with patch("builtins.open", side_effect=OSError(13, "denied")):
            self._run(app, total=1, processed=1)

    def test_auto_end_schedules_root_destroy(self, app: TempoAnalyzerApp) -> None:
        app.auto_end = True
        app._scheduled.clear()
        self._run(app, total=1, processed=1)
        destroy_calls = [
            c
            for c in app.root.after.call_args_list
            if len(c[0]) >= 2 and c[0][1] == app.root.destroy
        ]
        assert len(destroy_calls) == 1

    def test_ui_label_dry_run(self, app: TempoAnalyzerApp) -> None:
        app.run_mode.get.return_value = "Dry Run"
        self._run(app, total=1, processed=1)
        app.completion_label.config.assert_called_with(text="Analysis Complete!")

    def test_ui_label_live_update(self, app: TempoAnalyzerApp) -> None:
        app.run_mode.get.return_value = "Live Update"
        self._run(app, total=1, processed=1)
        app.completion_label.config.assert_called_with(text="Tempo Tagging Complete!")


class TestCollectSettings:
    """_collect_settings() reads Tk variable values into a dict."""

    @pytest.fixture
    def app(self) -> TempoAnalyzerApp:
        app = object.__new__(TempoAnalyzerApp)
        app.tempo_scheme = MagicMock()
        app.tempo_scheme.get.return_value = "Italian"
        app.run_mode = MagicMock()
        app.run_mode.get.return_value = "Dry Run"
        return app

    def test_returns_all_settings(self, app: TempoAnalyzerApp) -> None:
        settings = app._collect_settings()
        assert settings == {
            "tempo_scheme": "Italian",
            "run_mode": "Dry Run",
        }

    def test_reflects_english_scheme(self, app: TempoAnalyzerApp) -> None:
        app.tempo_scheme.get.return_value = "English"
        settings = app._collect_settings()
        assert settings["tempo_scheme"] == "English"

    def test_reflects_live_mode(self, app: TempoAnalyzerApp) -> None:
        app.run_mode.get.return_value = "Live Update"
        settings = app._collect_settings()
        assert settings["run_mode"] == "Live Update"


class TestApplyPreset:
    """_apply_preset() writes preset values back to Tk variables."""

    @pytest.fixture
    def app(self) -> TempoAnalyzerApp:
        app = object.__new__(TempoAnalyzerApp)
        app.tempo_scheme = MagicMock()
        app.run_mode = MagicMock()
        return app

    def test_sets_both(self, app: TempoAnalyzerApp) -> None:
        app._apply_preset(
            {
                "tempo_scheme": "English",
                "run_mode": "Live Update",
            }
        )
        app.tempo_scheme.set.assert_called_once_with("English")
        app.run_mode.set.assert_called_once_with("Live Update")

    def test_partial_preset_only_sets_provided(self, app: TempoAnalyzerApp) -> None:
        app._apply_preset({"run_mode": "Dry Run"})
        app.tempo_scheme.set.assert_not_called()
        app.run_mode.set.assert_called_once_with("Dry Run")

    def test_empty_preset_does_nothing(self, app: TempoAnalyzerApp) -> None:
        app._apply_preset({})
        app.tempo_scheme.set.assert_not_called()
        app.run_mode.set.assert_not_called()


class TestOnSchemeChange:
    """_on_scheme_change() updates markings, persists, and refreshes reference."""

    @pytest.fixture
    def app(self) -> TempoAnalyzerApp:
        root = MagicMock()
        app = object.__new__(TempoAnalyzerApp)
        app.root = root
        app.tempo_scheme = MagicMock()
        app.tempo_scheme.get.return_value = "English"
        app._active_markings = TEMPO_SCHEMES["Italian"]
        app._update_reference = MagicMock()
        return app

    def test_updates_active_markings(self, app: TempoAnalyzerApp) -> None:
        with patch("tempo_analyzer.app.suite_config"):
            app._on_scheme_change()
        assert app._active_markings == TEMPO_SCHEMES["English"]

    def test_persists_preference(self, app: TempoAnalyzerApp) -> None:
        with patch("tempo_analyzer.app.suite_config") as mock_cfg:
            app._on_scheme_change()
            mock_cfg.save_value.assert_called_once_with("tempo_scheme", "English")

    def test_refreshes_reference_table(self, app: TempoAnalyzerApp) -> None:
        with patch("tempo_analyzer.app.suite_config"):
            app._on_scheme_change()
        app._update_reference.assert_called_once_with(TEMPO_SCHEMES["English"])

    def test_ignores_unknown_scheme(self, app: TempoAnalyzerApp) -> None:
        app.tempo_scheme.get.return_value = "Nonexistent"
        original = app._active_markings
        with patch("tempo_analyzer.app.suite_config") as mock_cfg:
            app._on_scheme_change()
        assert app._active_markings is original
        mock_cfg.save_value.assert_not_called()
        app._update_reference.assert_not_called()

    def test_scheme_change_to_dance(self, app: TempoAnalyzerApp) -> None:
        app.tempo_scheme.get.return_value = "Dance"
        with patch("tempo_analyzer.app.suite_config"):
            app._on_scheme_change()
        assert app._active_markings == TEMPO_SCHEMES["Dance"]
        app._update_reference.assert_called_once_with(TEMPO_SCHEMES["Dance"])


# ---------------------------------------------------------------------------
# _apply_cli_args — driver mirroring before the early return
# ---------------------------------------------------------------------------


def _make_cli_app(parsed) -> TempoAnalyzerApp:
    """Shell app with MagicMock Tk vars for CLI-mirroring tests."""
    root = MagicMock()
    scheduled: list = []
    root.after.side_effect = lambda delay, fn, *a, **kw: scheduled.append((fn, a))
    app = object.__new__(TempoAnalyzerApp)
    app.root = root
    app._scheduled = scheduled
    app.folder_path = MagicMock()
    app.run_mode = MagicMock()
    app.auto_start_var = MagicMock()
    app.auto_end_var = MagicMock()
    app.clear_logs_var = MagicMock()
    app.parallel_var = MagicMock()
    app.tempo_scheme = MagicMock()
    app.start_processing = MagicMock()
    return app


class TestApplyCliArgsDriven:
    """Driver launch: run controls mirrored onto the Setup tab panel."""

    def test_mirrors_all_five_values(self):
        parsed = MagicMock(
            folder_path="C:/music",
            live_mode=True,
            auto_start=True,
            auto_end=True,
            clear_logs=True,
            parallel_run=True,
            scheme=None,
        )
        app = _make_cli_app(parsed)
        with (
            patch("tempo_analyzer.utils.cli_args.parse", return_value=parsed),
            patch("tempo_analyzer.app.UniversalCLIHandler") as handler_cls,
        ):
            handler_cls.return_value.apply_cli_args.return_value = False
            app._apply_cli_args()
        app.run_mode.set.assert_called_once_with("Live Update")
        app.auto_start_var.set.assert_called_once_with(True)
        app.auto_end_var.set.assert_called_once_with(True)
        app.clear_logs_var.set.assert_called_once_with(True)
        app.parallel_var.set.assert_called_once_with(True)

    def test_auto_start_schedules_processing(self):
        parsed = MagicMock(
            folder_path="C:/music",
            live_mode=False,
            auto_start=True,
            auto_end=True,
            clear_logs=False,
            parallel_run=False,
            scheme=None,
        )
        app = _make_cli_app(parsed)
        with (
            patch("tempo_analyzer.utils.cli_args.parse", return_value=parsed),
            patch("tempo_analyzer.app.UniversalCLIHandler") as handler_cls,
        ):
            handler_cls.return_value.apply_cli_args.return_value = True
            app._apply_cli_args()
        fn, args = app._scheduled[-1]
        assert fn == app.start_processing
        assert args == ()

    def test_scheme_applied_when_valid(self):
        parsed = MagicMock(
            folder_path="C:/music",
            live_mode=False,
            auto_start=False,
            auto_end=False,
            clear_logs=False,
            parallel_run=False,
            scheme="English",
        )
        app = _make_cli_app(parsed)
        with (
            patch("tempo_analyzer.utils.cli_args.parse", return_value=parsed),
            patch("tempo_analyzer.app.UniversalCLIHandler") as handler_cls,
        ):
            handler_cls.return_value.apply_cli_args.return_value = False
            app._apply_cli_args()
        app.tempo_scheme.set.assert_called_once_with("English")


class TestApplyCliArgsStandalone:
    """Standalone launch: no folder arg leaves everything untouched."""

    def test_no_folder_path_returns_before_mirroring(self):
        parsed = MagicMock(folder_path="", live_mode=True)
        app = _make_cli_app(parsed)
        with patch("tempo_analyzer.utils.cli_args.parse", return_value=parsed):
            app._apply_cli_args()
        app.run_mode.set.assert_not_called()
        app.clear_logs_var.set.assert_not_called()

    def test_dry_run_mode_string(self):
        parsed = MagicMock(
            folder_path="C:/music",
            live_mode=False,
            auto_start=False,
            auto_end=False,
            clear_logs=False,
            parallel_run=False,
            scheme=None,
        )
        app = _make_cli_app(parsed)
        with (
            patch("tempo_analyzer.utils.cli_args.parse", return_value=parsed),
            patch("tempo_analyzer.app.UniversalCLIHandler") as handler_cls,
        ):
            handler_cls.return_value.apply_cli_args.return_value = False
            app._apply_cli_args()
        app.run_mode.set.assert_called_once_with("Dry Run")
