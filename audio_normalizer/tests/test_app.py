"""
Tests for audio_normalizer.app — core orchestration logic.

Covers:
  - _apply_cli_args()  — parsing and applying CLI arguments to Tk variables
  - start_processing() — early-return validation guards
  - _run()             — log path computation and parameter dispatch

Widget-heavy UI construction is mocked out.  Tests that require a real Tk
instance are gated behind ``requires_display``, consistent with the pattern
used in test_setup_tab.py.
Changed in 2.0.0: adds the ``TestCompletionSeam`` cases driving
``run_parallel_process`` into the completion handler (PLAN D117).
Changed in 2.1.7: covers the true-peak/LRA variables, the >-1.0 dBTP
confirmation, and their reach into the processing call.
"""

import os
import tkinter as tk
from pathlib import Path
from queue import Queue
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from audio_normalizer.app import AudioNormalizerApp
from audio_normalizer.utils.cli_args import NormalizerArgs, parse

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
        args = NormalizerArgs(folder_path="")
        with (
            patch("audio_normalizer.app.cli_args.parse", return_value=args),
            patch("audio_normalizer.app.UniversalCLIHandler") as mock_cls,
            patch.object(app.root, "after"),
        ):
            app._apply_cli_args()
            mock_cls.assert_not_called()
            args.folder_path = "/music"
            app._apply_cli_args()
        mock_cls.assert_called_once_with(app)

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

    def test_threads_driver_display_vars_from_parsed_args(
        self, tmp_path: os.PathLike
    ) -> None:
        app, _root = _make_app()
        with (
            patch(
                "audio_normalizer.app.cli_args.parse",
                return_value=NormalizerArgs(
                    folder_path=str(tmp_path),
                    target_lufs=-16.0,
                    auto_start=True,
                    auto_end=True,
                    clear_logs=True,
                    parallel_run=True,
                ),
            ),
            patch("audio_normalizer.app.UniversalCLIHandler") as mock_cls,
        ):
            mock_handler = MagicMock()
            mock_handler.apply_cli_args.return_value = False
            mock_cls.return_value = mock_handler
            app._apply_cli_args()
            assert app.auto_start_var.get() is True
            assert app.auto_end_var.get() is True
            assert app.clear_logs_var.get() is True
            assert app.parallel_var.get() is True

    def test_cli_arg_defaults_leave_gui_target_lufs_at_minus_14(
        self, tmp_path: os.PathLike
    ) -> None:
        """D4 (iteration 9): argv with a folder but no explicit LUFS flag.

        Applying the parser's own defaults must not rewrite the GUI's -14
        (the guide documents "The app default is -14.0"); pre-fix the
        argparse default of -16.0 overwrote it on every CLI/Driver launch.
        """
        app, _root = _make_app()
        assert app.target_lufs.get() == -14.0

        default_args = parse(["prog", str(tmp_path)])
        assert default_args.target_lufs == -14.0

        with (
            patch(
                "audio_normalizer.app.cli_args.parse",
                return_value=default_args,
            ),
            patch("audio_normalizer.app.UniversalCLIHandler") as mock_cls,
        ):
            mock_handler = MagicMock()
            mock_handler.apply_cli_args.return_value = False
            mock_cls.return_value = mock_handler
            app._apply_cli_args()

        assert app.target_lufs.get() == -14.0


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


@pytest.mark.gui  # builds real tk.Variable objects: needs a Tk root
class TestAuditionOnComplete:
    """_on_complete() drives the shared audition state machine."""

    @staticmethod
    @pytest.fixture(autouse=True)
    def _patch_messagebox() -> None:
        with patch("audio_normalizer.app.messagebox"):
            yield

    @staticmethod
    @pytest.fixture
    def app(tmp_path: Path) -> AudioNormalizerApp:
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
        app.auto_end_var = tk.BooleanVar(value=False)
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


# ---------------------------------------------------------------------------
# Completion seam: the processor payload must reach the handler _run binds and
# land in the report the run writes.
# ---------------------------------------------------------------------------

_HEADER = ["NORMALIZATION REPORT\n"]


def _completion_shell(tmp_path: Path) -> AudioNormalizerApp:
    """Shell with only what the completion path touches."""
    app = object.__new__(AudioNormalizerApp)
    app.root = MagicMock()
    app._log_path = str(tmp_path / "normalization_log.txt")
    app.run_mode = MagicMock()
    app.run_mode.get.return_value = "Dry Run"
    app.auto_end_var = MagicMock()
    app.auto_end_var.get.return_value = False
    app.time_label = MagicMock()
    app.summary_label = MagicMock()
    app.completion_label = MagicMock()
    app.notebook = MagicMock()
    app._tab_results = MagicMock()
    app.start_btn = MagicMock()
    app._run_was_dry_run = True
    app._audition_original = None
    app._audition_result = None
    app.set_audition_state = MagicMock()
    return app


class TestCompletionSeam:
    """``run_parallel_process`` publishes into the handler ``_run`` binds."""

    @staticmethod
    def _wire(app: AudioNormalizerApp):
        """Return the completion callable ``_run`` hands to the processor."""
        return lambda **kw: app._on_complete(header=_HEADER, **kw)

    @staticmethod
    def _fake_process_single_file(**kwargs: Any) -> None:
        """Stand in for the per-file normaliser, one outcome per file."""
        outcomes = {
            "a.wav": {"n_skipped": 0, "n_errors": 0},
            "b.wav": {"n_skipped": 1, "n_errors": 0},
            "c.wav": {"n_skipped": 0, "n_errors": 1},
        }
        progress = kwargs["on_progress"]
        outcome = outcomes[kwargs["name"]]
        progress(
            n_skipped=outcome["n_skipped"],
            n_errors=outcome["n_errors"],
            display_text=kwargs["name"],
            log_text=f"{kwargs['name']}\n",
        )

    def test_the_real_payload_is_written(self, tmp_path: Path) -> None:
        """Every published count reaches the report the handler writes."""
        from audio_normalizer.core import file_processor

        for name in ("a.wav", "b.wav", "c.wav"):
            (tmp_path / name).write_bytes(b"")
        app = _completion_shell(tmp_path)

        with patch.object(
            file_processor,
            "process_single_file",
            side_effect=self._fake_process_single_file,
        ):
            file_processor.run_parallel_process(
                dir_path=str(tmp_path),
                target_lufs=-14.0,
                tolerance=0.5,
                is_dry_run=True,
                slot_vars=[MagicMock()],
                slot_queue=Queue(),
                on_progress=MagicMock(),
                on_complete=self._wire(app),
                on_error=MagicMock(),
            )

        report = (tmp_path / "normalization_log.txt").read_text(encoding="utf-8")
        assert "Total files: 3" in report
        assert "Normalized: 1" in report
        assert "Skipped (within tolerance): 1" in report
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
        assert not (tmp_path / "normalization_log.txt").exists()


@requires_display
class TestDeliveryTargetsApp:
    """F-09: the GUI carries the ceiling/LRA into the run and warns above -1.0."""

    def test_run_passes_the_delivery_targets(self, tmp_path: os.PathLike) -> None:
        app, _root = _make_app()
        app.progress = MagicMock()
        app.stats_label = MagicMock()
        app.overall_status = MagicMock()
        app.file_listbox = MagicMock()
        app.folder_path.set(str(tmp_path))
        app.true_peak.set(-1.0)
        app.lra.set(7.0)

        with patch(
            "audio_normalizer.app.file_processor.run_parallel_process"
        ) as mock_run:
            app._run()

        _args, kwargs = mock_run.call_args
        assert kwargs["true_peak"] == -1.0
        assert kwargs["lra"] == 7.0

    def test_presets_round_trip_the_delivery_targets(self) -> None:
        app, _root = _make_app()
        app.true_peak.set(-1.0)
        app.lra.set(7.0)

        settings = app._collect_settings()
        assert settings["true_peak"] == -1.0
        assert settings["lra"] == 7.0

        app.true_peak.set(-1.5)
        app.lra.set(11.0)
        app._apply_preset(settings)
        assert app.true_peak.get() == -1.0
        assert app.lra.get() == pytest.approx(7.0)

    def test_cli_targets_reach_the_variables(self, tmp_path: os.PathLike) -> None:
        app, _root = _make_app()
        with (
            patch(
                "audio_normalizer.app.cli_args.parse",
                return_value=NormalizerArgs(
                    folder_path=str(tmp_path), target_lufs=-16.0, true_peak=-2.0, lra=8
                ),
            ),
            patch("audio_normalizer.app.UniversalCLIHandler") as mock_cls,
        ):
            mock_handler = MagicMock()
            mock_handler.apply_cli_args.return_value = False
            mock_cls.return_value = mock_handler
            app._apply_cli_args()

        assert app.true_peak.get() == -2.0
        assert app.lra.get() == pytest.approx(8.0)

    def test_ceiling_above_minus_one_asks_before_running(
        self, tmp_path: os.PathLike
    ) -> None:
        app, _root = _make_app()
        app.folder_path.set(str(tmp_path))
        app.true_peak.set(-0.5)

        with (
            patch(
                "audio_normalizer.app.messagebox.askyesno", return_value=False
            ) as ask,
            patch("audio_normalizer.app.threading.Thread") as thread,
        ):
            app.start_processing()

        ask.assert_called_once()
        thread.assert_not_called()

    def test_ceiling_at_or_below_minus_one_does_not_ask(
        self, tmp_path: os.PathLike
    ) -> None:
        app, _root = _make_app()
        app.folder_path.set(str(tmp_path))
        app.true_peak.set(-1.0)
        app.start_btn = MagicMock()
        app.file_listbox = MagicMock()
        app.notebook = MagicMock()
        app._tab_processing = MagicMock()
        app.overall_status = MagicMock()

        with (
            patch("audio_normalizer.app.messagebox.askyesno") as ask,
            patch("audio_normalizer.app.threading.Thread"),
        ):
            app.start_processing()

        ask.assert_not_called()
