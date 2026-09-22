"""
Tests for audio_normalizer.app — core orchestration logic.

Covers:
  - _apply_cli_args()  — parsing and applying CLI arguments to Tk variables
  - start_processing() — early-return validation guards
  - _run()             — log path computation and parameter dispatch

Widget-heavy UI construction is mocked out.  Tests that require a real Tk
instance are gated behind ``requires_display``, consistent with the pattern
used in test_setup_tab.py.
"""

import os
import tkinter as tk
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from audio_normalizer.app import AudioNormalizerApp
from audio_normalizer.utils.cli_args import NormalizerArgs

# Module-level Tk root — created once, shared by all tests, never destroyed
# mid-session.  The per-test fixture below patches it out after constructing
# the app, so widget state doesn't leak between tests.
_TK_ROOT: tk.Tk | None = None


def _ensure_tk_root() -> tk.Tk:
    global _TK_ROOT
    if _TK_ROOT is None:
        _TK_ROOT = tk.Tk()
        _TK_ROOT.withdraw()
    return _TK_ROOT


def _has_display() -> bool:
    try:
        _ensure_tk_root()  # creates once, never destroys
        return True
    except tk.TclError:
        return False


requires_display = pytest.mark.skipif(
    not _has_display(), reason="No graphical display — Tkinter unavailable"
)


def _make_app() -> tuple[AudioNormalizerApp, tk.Tk]:
    """Build an AudioNormalizerApp with UI construction patched out.

    Uses a shared module-level Tk root so Tcl doesn't need to re-initialise
    between tests.
    """
    root = _ensure_tk_root()
    with (
        patch(
            "audio_normalizer.app.bootstrap_tool_app",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch.object(AudioNormalizerApp, "_build_ui"),
        patch.object(AudioNormalizerApp, "_apply_cli_args"),
        patch(
            "audio_normalizer.app.suite_config.load_last_directory",
            return_value=None,
        ),
    ):
        app = AudioNormalizerApp(root)
    return app, root


# ═════════════════════════════════════════════════════════════════════════════
# _apply_cli_args
# ═════════════════════════════════════════════════════════════════════════════


@requires_display
class TestAppApplyCliArgs:
    """CLI-argument application to Tk variables."""

    def test_returns_early_when_no_folder_path(self) -> None:
        app, _root = _make_app()
        with (
            patch(
                "audio_normalizer.app.cli_args.parse",
                return_value=NormalizerArgs(folder_path=""),
            ),
            patch("audio_normalizer.app.UniversalCLIHandler") as mock_cls,
        ):
            app._apply_cli_args()
            mock_cls.assert_not_called()

    def test_sets_target_lufs_and_tolerance(self, tmp_path: os.PathLike) -> None:
        app, _root = _make_app()
        with (
            patch(
                "audio_normalizer.app.cli_args.parse",
                return_value=NormalizerArgs(
                    folder_path=str(tmp_path), target_lufs=-23.0, tolerance=1.5
                ),
            ),
            patch("audio_normalizer.app.UniversalCLIHandler") as mock_cls,
        ):
            mock_handler = MagicMock()
            mock_handler.apply_cli_args.return_value = False
            mock_cls.return_value = mock_handler
            app._apply_cli_args()
            assert app.target_lufs.get() == -23.0
            assert app.tolerance.get() == 1.5

    def test_creates_handler_with_self(self, tmp_path: os.PathLike) -> None:
        app, _root = _make_app()
        with (
            patch(
                "audio_normalizer.app.cli_args.parse",
                return_value=NormalizerArgs(
                    folder_path=str(tmp_path), target_lufs=-16.0
                ),
            ),
            patch("audio_normalizer.app.UniversalCLIHandler") as mock_cls,
        ):
            mock_handler = MagicMock()
            mock_handler.apply_cli_args.return_value = False
            mock_cls.return_value = mock_handler
            app._apply_cli_args()
            mock_cls.assert_called_once_with(app)

    def test_auto_start_schedules_processing(self, tmp_path: os.PathLike) -> None:
        app, _root = _make_app()
        with (
            patch(
                "audio_normalizer.app.cli_args.parse",
                return_value=NormalizerArgs(
                    folder_path=str(tmp_path), target_lufs=-16.0
                ),
            ),
            patch("audio_normalizer.app.UniversalCLIHandler") as mock_cls,
            patch.object(app.root, "after") as mock_after,
        ):
            mock_handler = MagicMock()
            mock_handler.apply_cli_args.return_value = True
            mock_cls.return_value = mock_handler
            app._apply_cli_args()
            mock_after.assert_called_once_with(1500, app.start_processing)

    def test_live_normalise_mode_sets_normalize(self, tmp_path: os.PathLike) -> None:
        app, _root = _make_app()
        with (
            patch(
                "audio_normalizer.app.cli_args.parse",
                return_value=NormalizerArgs(
                    folder_path=str(tmp_path),
                    live_mode=True,
                    normalization_mode="normalise",
                ),
            ),
            patch("audio_normalizer.app.UniversalCLIHandler") as mock_cls,
        ):
            mock_handler = MagicMock()
            mock_handler.apply_cli_args.return_value = False
            mock_cls.return_value = mock_handler
            app._apply_cli_args()
            assert app.run_mode.get() == "Normalize"

    def test_live_lossless_sets_lossless_mode(self, tmp_path: os.PathLike) -> None:
        app, _root = _make_app()
        with (
            patch(
                "audio_normalizer.app.cli_args.parse",
                return_value=NormalizerArgs(
                    folder_path=str(tmp_path),
                    live_mode=True,
                    normalization_mode="lossless",
                ),
            ),
            patch("audio_normalizer.app.UniversalCLIHandler") as mock_cls,
        ):
            mock_handler = MagicMock()
            mock_handler.apply_cli_args.return_value = False
            mock_cls.return_value = mock_handler
            app._apply_cli_args()
            assert app.run_mode.get() == "Lossless Normalize"


# ═════════════════════════════════════════════════════════════════════════════
# start_processing — validation guards
# ═════════════════════════════════════════════════════════════════════════════


@requires_display
class TestAppStartProcessing:
    """Early-return validation in start_processing."""

    def test_empty_folder_shows_warning(self) -> None:
        app, _root = _make_app()
        app.folder_path.set("")
        with patch("audio_normalizer.app.messagebox.showwarning") as mock_warn:
            app.start_processing()
            mock_warn.assert_called_once_with(
                "Warning", "Please select a music directory first."
            )

    def test_non_existent_folder_shows_error(self, tmp_path: os.PathLike) -> None:
        app, _root = _make_app()
        app.folder_path.set(str(tmp_path / "does_not_exist"))
        with patch("audio_normalizer.app.messagebox.showerror") as mock_err:
            app.start_processing()
            mock_err.assert_called_once()

    def test_file_path_shows_error(self, tmp_path: os.PathLike) -> None:
        app, _root = _make_app()
        f = tmp_path / "afile.txt"
        f.write_text("content")
        app.folder_path.set(str(f))
        with patch("audio_normalizer.app.messagebox.showerror") as mock_err:
            app.start_processing()
            mock_err.assert_called_once()


# ═════════════════════════════════════════════════════════════════════════════
# _run — background orchestrator
# ═════════════════════════════════════════════════════════════════════════════


@requires_display
class TestAppRun:
    """Log-path computation and parameter dispatch in _run."""

    def test_dry_run_log_path(self, tmp_path: os.PathLike) -> None:
        app, _root = _make_app()
        # Inject mocks for UI widgets that _run accesses before reaching
        # the mocked run_parallel_process call.
        app.progress = MagicMock()
        app.stats_label = MagicMock()
        app.overall_status = MagicMock()
        app.file_listbox = MagicMock()

        app.folder_path.set(str(tmp_path))
        app.run_mode.set("Dry Run")
        with patch("audio_normalizer.app.file_processor.run_parallel_process"):
            app._run()
        expected = os.path.join(str(tmp_path), "normalization_dry_run_log.txt")
        assert app._log_path == expected

    def test_live_mode_log_path(self, tmp_path: os.PathLike) -> None:
        app, _root = _make_app()
        app.progress = MagicMock()
        app.stats_label = MagicMock()
        app.overall_status = MagicMock()
        app.file_listbox = MagicMock()

        app.folder_path.set(str(tmp_path))
        app.run_mode.set("Normalize")
        with patch("audio_normalizer.app.file_processor.run_parallel_process"):
            app._run()
        expected = os.path.join(str(tmp_path), "audio_normalization_log.txt")
        assert app._log_path == expected

    def test_lossless_mode_log_path(self, tmp_path: os.PathLike) -> None:
        app, _root = _make_app()
        app.progress = MagicMock()
        app.stats_label = MagicMock()
        app.overall_status = MagicMock()
        app.file_listbox = MagicMock()

        app.folder_path.set(str(tmp_path))
        app.run_mode.set("Lossless Normalize")
        with patch("audio_normalizer.app.file_processor.run_parallel_process"):
            app._run()
        expected = os.path.join(str(tmp_path), "audio_normalization_log.txt")
        assert app._log_path == expected

    def test_passes_correct_parameters_to_file_processor(
        self, tmp_path: os.PathLike
    ) -> None:
        app, _root = _make_app()
        app.progress = MagicMock()
        app.stats_label = MagicMock()
        app.overall_status = MagicMock()
        app.file_listbox = MagicMock()

        app.folder_path.set(str(tmp_path))
        app.target_lufs.set(-18.0)
        app.tolerance.set(0.3)
        app.run_mode.set("Normalize")

        with patch(
            "audio_normalizer.app.file_processor.run_parallel_process"
        ) as mock_run:
            app._run()
            _, kwargs = mock_run.call_args
            assert kwargs["dir_path"] == str(tmp_path)
            assert kwargs["target_lufs"] == -18.0
            assert kwargs["tolerance"] == 0.3
            assert kwargs["is_dry_run"] is False
            assert kwargs["normalization_mode"] == "normalise"

    def test_lossless_mode_passes_normalization_mode(
        self, tmp_path: os.PathLike
    ) -> None:
        app, _root = _make_app()
        app.progress = MagicMock()
        app.stats_label = MagicMock()
        app.overall_status = MagicMock()
        app.file_listbox = MagicMock()

        app.folder_path.set(str(tmp_path))
        app.run_mode.set("Lossless Normalize")

        with patch(
            "audio_normalizer.app.file_processor.run_parallel_process"
        ) as mock_run:
            app._run()
            _, kwargs = mock_run.call_args
            assert kwargs["normalization_mode"] == "lossless"
            assert kwargs["is_dry_run"] is False

    def test_dry_run_passes_is_dry_run_true(self, tmp_path: os.PathLike) -> None:
        app, _root = _make_app()
        app.progress = MagicMock()
        app.stats_label = MagicMock()
        app.overall_status = MagicMock()
        app.file_listbox = MagicMock()

        app.folder_path.set(str(tmp_path))
        app.run_mode.set("Dry Run")

        with patch(
            "audio_normalizer.app.file_processor.run_parallel_process"
        ) as mock_run:
            app._run()
            _, kwargs = mock_run.call_args
            assert kwargs["is_dry_run"] is True


def _audition_caption(root: Any) -> str:
    """Latest caption scheduled by _on_complete through root.after."""
    for call in root.after.call_args_list:
        args = call[0]
        if len(args) == 3 and args[0] == 0 and isinstance(args[2], str):
            return args[2]
    return ""


class TestAuditionOnComplete:
    """_on_complete() drives the shared audition state machine."""

    @pytest.fixture(autouse=True)
    def _patch_messagebox(self) -> None:
        with patch("audio_normalizer.app.messagebox"):
            yield

    @pytest.fixture
    def app(self, tmp_path: Path) -> AudioNormalizerApp:
        root = MagicMock()
        app = object.__new__(AudioNormalizerApp)
        app.root = root
        app._log_path = str(tmp_path / "normalization_log.txt")
        app.time_label = MagicMock()
        app.summary_label = MagicMock()
        app.completion_label = MagicMock()
        app.notebook = MagicMock()
        app._tab_results = MagicMock()
        app.start_btn = MagicMock()
        app.run_mode = tk.StringVar(value="Normalize")
        app.auto_end = False
        app._run_was_dry_run = False
        app._audition_original = None
        app._audition_result = None
        return app

    def _complete(self, app: AudioNormalizerApp) -> None:
        app._on_complete(
            header=["HEADER\n"],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
        )

    def test_dry_run_schedules_result_disabled(self, app: AudioNormalizerApp) -> None:
        app._run_was_dry_run = True
        app._audition_original = Path("track_orig.mp3")
        self._complete(app)
        assert app._audition_result is None
        assert "Dry Run" in _audition_caption(app.root)

    def test_live_pair_schedules_ready_caption(self, app: AudioNormalizerApp) -> None:
        app._audition_original = Path("track_orig.mp3")
        app._audition_result = Path("track.mp3")
        self._complete(app)
        assert (
            _audition_caption(app.root)
            == "Audition ready — track.mp3 (original vs result)"
        )

    def test_no_source_schedules_message(self, app: AudioNormalizerApp) -> None:
        self._complete(app)
        assert (
            _audition_caption(app.root) == "No supported audio file found for audition."
        )
