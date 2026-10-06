"""
test_tool_launcher.py — Tests for master_driver/tool_launcher.py.

Focus: launch_utility() validation gating.

Regression background
---------------------
launch_utility previously classified utility tools against hardcoded ID
sets that were never updated when ``tag_field_updater`` was registered as
a standalone utility tool. Ticking only Tag Field Updater therefore hit
the "Nothing Selected" guard instead of launching. The fix derives the
classification from ``ToolManifest.standalone`` in the registry; these
tests lock that behaviour in.

External effects are patched out (threading.Thread, suite-config writes,
popup dialogs) so the tests never spawn subprocesses or touch user files.
"""

from __future__ import annotations

import sys
import threading
import tkinter as tk
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from audio_refinery.core.models import StageConfig
from master_driver.runner import arg_builder
from master_driver.state.app_state import AppState
from master_driver.tool_launcher import (
    _get_current_accent,
    _on_refinery_complete,
    _run_enrich,
    _run_refinery,
    _run_utility_modules,
    launch_enrich,
    launch_refinery,
    launch_utility,
)


@pytest.fixture()
def state() -> AppState:
    """Real AppState backed by the session-scoped hidden Tk root."""
    return AppState()


@pytest.fixture()
def launch_mocks():
    """Patch subprocess launching, config persistence and popup dialogs."""
    with (
        patch.object(threading, "Thread", autospec=True) as mock_thread,
        patch("master_driver.tool_launcher._suite_config.save_last_directory"),
        patch("master_driver.tool_launcher.ui_common.show_message") as mock_msg,
    ):
        yield SimpleNamespace(thread=mock_thread, show_message=mock_msg)


@pytest.mark.gui  # builds real tk.Variable objects: needs a Tk root
class TestLaunchUtilityValidation:
    """Validation gating in launch_utility()."""

    def test_tag_field_updater_alone_launches(
        self, state: AppState, launch_mocks: SimpleNamespace
    ) -> None:
        """Regression: Tag Field Updater alone must start, not pop up."""
        state.module_toggles["tag_field_updater"].set(True)

        launch_utility(state, MagicMock(), MagicMock())

        launch_mocks.show_message.assert_not_called()
        launch_mocks.thread.assert_called_once()

    def test_standalone_tool_alone_launches(
        self, state: AppState, launch_mocks: SimpleNamespace
    ) -> None:
        """Standalone tools need no directory and must not be blocked."""
        state.module_toggles["cd_ripper"].set(True)

        launch_utility(state, MagicMock(), MagicMock())

        launch_mocks.show_message.assert_not_called()
        launch_mocks.thread.assert_called_once()

    def test_no_selection_shows_nothing_selected(
        self, state: AppState, launch_mocks: SimpleNamespace
    ) -> None:
        """With every toggle off the guard dialog is shown and no thread starts."""
        launch_utility(state, MagicMock(), MagicMock())

        assert launch_mocks.show_message.call_args.args[1] == "Nothing Selected"
        launch_mocks.thread.assert_not_called()

    def test_folder_tool_without_dir_shows_no_directory(
        self, state: AppState, launch_mocks: SimpleNamespace
    ) -> None:
        """Non-standalone tools require a directory path first."""
        state.module_toggles["converter"].set(True)
        assert state.dir_path.get() == ""

        launch_utility(state, MagicMock(), MagicMock())

        assert launch_mocks.show_message.call_args.args[1] == "No Directory"
        launch_mocks.thread.assert_not_called()

    def test_folder_tool_with_dir_launches(
        self, state: AppState, launch_mocks: SimpleNamespace, tmp_path
    ) -> None:
        state.module_toggles["converter"].set(True)
        state.dir_path.set(str(tmp_path))

        launch_utility(state, MagicMock(), MagicMock())

        launch_mocks.show_message.assert_not_called()
        launch_mocks.thread.assert_called_once()

    def test_thread_is_daemonised(
        self, state: AppState, launch_mocks: SimpleNamespace
    ) -> None:
        """The launcher thread must never block interpreter shutdown."""
        state.module_toggles["tag_field_updater"].set(True)

        launch_utility(state, MagicMock(), MagicMock())

        kwargs = launch_mocks.thread.call_args.kwargs
        assert kwargs.get("daemon") is True

    def test_registry_and_toggles_stay_in_sync(self, state: AppState) -> None:
        """Every utility manifest id has a matching toggle variable."""
        from audio_suite_shared.tool_plugin import get_registry

        utility_ids = {m.id for m in get_registry().by_category("utility")}
        assert utility_ids <= set(state.module_toggles.keys())


@pytest.mark.gui  # builds real tk.Variable objects: needs a Tk root
class TestDirectoryExistenceValidation:
    """Regression: non-existent directories must be blocked with a friendly
    popup before any subprocess is spawned (previously produced an ugly
    CalledProcessError traceback and a stuck Run button)."""

    def test_utility_nonexistent_dir_shows_directory_not_found(
        self, state: AppState, launch_mocks: SimpleNamespace, tmp_path
    ) -> None:
        state.module_toggles["converter"].set(True)
        state.dir_path.set(str(tmp_path / "does_not_exist"))

        launch_utility(state, MagicMock(), MagicMock())

        assert launch_mocks.show_message.call_args.args[1] == "Directory Not Found"
        launch_mocks.thread.assert_not_called()

    def test_enrich_nonexistent_dir_shows_directory_not_found(
        self, state: AppState, launch_mocks: SimpleNamespace, tmp_path
    ) -> None:
        state.dir_path.set(str(tmp_path / "does_not_exist"))

        launch_enrich(state, MagicMock(), MagicMock())

        assert launch_mocks.show_message.call_args.args[1] == "Directory Not Found"
        launch_mocks.thread.assert_not_called()

    def test_enrich_valid_dir_launches(
        self, state: AppState, launch_mocks: SimpleNamespace, tmp_path
    ) -> None:
        state.dir_path.set(str(tmp_path))

        launch_enrich(state, MagicMock(), MagicMock())

        launch_mocks.show_message.assert_not_called()
        launch_mocks.thread.assert_called_once()

    def test_refinery_nonexistent_source_shows_directory_not_found(
        self, state: AppState, launch_mocks: SimpleNamespace, tmp_path
    ) -> None:
        state.refinery_source.set(str(tmp_path / "does_not_exist"))

        launch_refinery(state, MagicMock(), MagicMock(), MagicMock())

        assert launch_mocks.show_message.call_args.args[1] == "Directory Not Found"
        launch_mocks.thread.assert_not_called()


class _RunAfterRoot:
    """Fake Tk root whose after() runs the callback synchronously."""

    def __init__(self) -> None:
        self.after_calls: list[tuple[int, object]] = []

    def after(self, delay, func, *args, **kwargs):
        self.after_calls.append((delay, func))
        func(*args, **kwargs)


class TestGetCurrentAccent:
    def test_returns_accent_normal_when_winaccent_available(self) -> None:
        with patch.dict(
            sys.modules, {"winaccent": SimpleNamespace(accent_normal="#c0ffee")}
        ):
            assert _get_current_accent() == "#c0ffee"

    def test_returns_none_when_winaccent_missing(self) -> None:
        with patch.dict(sys.modules, {"winaccent": None}):
            assert _get_current_accent() is None


@pytest.mark.gui  # builds real tk.Variable objects: needs a Tk root
class TestLaunchRefineryValidation:
    def test_no_source_shows_message(self, state, launch_mocks) -> None:
        state.refinery_source.set("")
        launch_refinery(state, MagicMock(), MagicMock(), MagicMock())
        assert launch_mocks.show_message.call_args.args[1] == "No Source Folder"
        launch_mocks.thread.assert_not_called()

    def test_no_active_stages_shows_message(
        self, state, launch_mocks, tmp_path
    ) -> None:
        state.refinery_source.set(str(tmp_path))
        config = StageConfig(declick=False, trim=False, enhance=False, normalise=False)
        launch_refinery(state, config, MagicMock(), MagicMock())
        assert launch_mocks.show_message.call_args.args[1] == "No Stages Selected"
        launch_mocks.thread.assert_not_called()

    def test_reduce_noise_alone_counts_as_active_stage(
        self, state, launch_mocks, tmp_path
    ) -> None:
        state.refinery_source.set(str(tmp_path))
        config = StageConfig(
            declick=False,
            trim=False,
            enhance=False,
            normalise=False,
            reduce_noise=True,
        )
        with patch("master_driver.ui.refinery_tab.save_settings") as save:
            launch_refinery(state, config, MagicMock(), MagicMock())
        assert launch_mocks.show_message.call_count == 0
        save.assert_called_once_with(config)
        assert launch_mocks.thread.call_args.kwargs.get("daemon") is True

    def test_happy_path_starts_daemon_thread(
        self, state, launch_mocks, tmp_path
    ) -> None:
        state.refinery_source.set(str(tmp_path))
        config = StageConfig(declick=True)
        with patch("master_driver.ui.refinery_tab.save_settings") as save:
            launch_refinery(state, config, MagicMock(), MagicMock())
        save.assert_called_once_with(config)
        assert launch_mocks.thread.call_args.kwargs.get("daemon") is True


@pytest.mark.gui  # builds real tk.Variable objects: needs a Tk root
class TestLaunchEnrichValidation:
    def test_no_directory_shows_message(self, state, launch_mocks) -> None:
        state.dir_path.set("")
        launch_enrich(state, MagicMock(), MagicMock())
        assert launch_mocks.show_message.call_args.args[1] == "No Directory"
        launch_mocks.thread.assert_not_called()


@pytest.mark.gui  # builds real tk.Variable objects: needs a Tk root
class TestRunRefineryPipeline:
    def test_runs_modules_and_completes(self, state, launch_mocks, tmp_path) -> None:
        root = _RunAfterRoot()
        btn = MagicMock()
        with (
            patch("master_driver.runner.module_runner.run_modules") as run_m,
            patch("master_driver.tool_launcher.ui_common.show_message"),
        ):
            run_m.side_effect = lambda **kw: kw["on_complete"](0)
            _run_refinery(
                [],
                btn,
                root,
                snapshot_clear_logs=False,
                snapshot_source=str(tmp_path),
            )
        run_m.assert_called_once()
        btn.config.assert_any_call(state="normal", text="LAUNCH REFINERY")

    def test_greater_than_zero_executed_skips_message(
        self, state, launch_mocks
    ) -> None:
        root = _RunAfterRoot()
        btn = MagicMock()
        with patch("master_driver.tool_launcher.ui_common.show_message") as msg:
            _on_refinery_complete(2, btn, root)
        msg.assert_not_called()
        btn.config.assert_any_call(state="normal", text="LAUNCH REFINERY")


@pytest.mark.gui  # builds real tk.Variable objects: needs a Tk root
class TestRunEnrichPipeline:
    def test_runs_modules_and_completes(self, state, launch_mocks, tmp_path) -> None:
        root = _RunAfterRoot()
        btn = MagicMock()
        on_done = MagicMock()
        with patch("master_driver.runner.module_runner.run_modules") as run_m:
            run_m.side_effect = lambda **kw: (
                kw["on_start"](),
                kw["on_complete"](2),
            )
            _run_enrich(
                [],
                btn,
                root,
                on_batch_done=on_done,
                parallel=False,
                snapshot_clear_logs=False,
                snapshot_dir=str(tmp_path),
            )
        run_m.assert_called_once()
        btn.config.assert_any_call(state="normal", text="LAUNCH ENRICH PROCESS")
        on_done.assert_called_once()


@pytest.mark.gui  # builds real tk.Variable objects: needs a Tk root
class TestRunUtilityPipeline:
    def test_runs_modules_and_completes(self, state, launch_mocks, tmp_path) -> None:
        root = _RunAfterRoot()
        btn = MagicMock()
        on_done = MagicMock()
        with patch("master_driver.runner.module_runner.run_modules") as run_m:
            run_m.side_effect = lambda **kw: (
                kw["on_start"](),
                kw["on_complete"](1),
            )
            _run_utility_modules(
                [],
                btn,
                root,
                on_batch_done=on_done,
                parallel=False,
                snapshot_clear_logs=False,
                snapshot_dir=str(tmp_path),
            )
        run_m.assert_called_once()
        btn.config.assert_any_call(state="normal", text="LAUNCH UTILITY PROCESS")
        on_done.assert_called_once()

    def test_complete_without_done_callback(
        self, state, launch_mocks, tmp_path
    ) -> None:
        root = _RunAfterRoot()
        btn = MagicMock()
        with patch("master_driver.runner.module_runner.run_modules") as run_m:
            run_m.side_effect = lambda **kw: kw["on_complete"](0)
            _run_utility_modules([], btn, root, snapshot_dir=str(tmp_path))
        run_m.assert_called_once()
        btn.config.assert_any_call(state="normal", text="LAUNCH UTILITY PROCESS")


class _DeferredThreads:
    """Collects the launcher threads a test never lets start."""

    def __init__(self) -> None:
        self.created: list = []

    def run_latest(self) -> None:
        assert self.created, "launcher never created a thread"
        self.created[-1].target()


@contextmanager
def deferred_threads():
    """Replace threading.Thread with a recorder, innermost patch wins.

    Applied inside the test body rather than as a fixture so it always wins
    over the launch_mocks fixture's Thread patch, whatever the setup order.
    """
    holder = _DeferredThreads()

    class _Recorder:
        """Thread stand-in: records the target, ``start()`` does nothing."""

        def __init__(self, target, daemon: bool = False, **_kwargs) -> None:
            self.target = target
            self.daemon = daemon
            holder.created.append(self)

        def start(self) -> None:
            """Deliberately inert — the test invokes ``target`` explicitly."""

    with patch.object(threading, "Thread", _Recorder):
        yield holder


@pytest.mark.gui  # builds real tk.Variable objects: needs a Tk root
class TestArgvBuiltOnMainThread:
    """A4 (audit H4): the argv must be built before the thread starts.

    Regression background
    ---------------------
    ``build_*_args`` reads live widget state. The launchers used to call it
    *inside* the daemon thread, so an edit made while the batch was launching
    silently re-derived the argv — most visibly flipping the emitted
    ``--live``/``--dry`` token of the run already in flight.
    """

    @staticmethod
    def _argv_of(specs) -> list[list[str]]:
        return [list(args) for _, _, args, *_ in specs]

    def test_enrich_argv_survives_state_edit_before_thread_start(
        self, state, launch_mocks, tmp_path
    ) -> None:
        state.dir_path.set(str(tmp_path))
        state.global_mode.set("Live Update")
        expected = self._argv_of(arg_builder.build_enrich_args(state))

        with (
            deferred_threads() as threads,
            patch("master_driver.runner.module_runner.run_modules") as run_m,
        ):
            launch_enrich(state, MagicMock(), MagicMock())
            # The edit lands after argv construction, before the thread runs.
            state.global_mode.set("Dry Run")
            state.dir_path.set(str(tmp_path / "elsewhere"))
            threads.run_latest()

        run_m.assert_called_once()
        assert self._argv_of(run_m.call_args.kwargs["module_specs"]) == expected
        assert any("--live" in args for args in expected)

    def test_utility_argv_survives_state_edit_before_thread_start(
        self, state, launch_mocks, tmp_path
    ) -> None:
        state.dir_path.set(str(tmp_path))
        state.module_toggles["converter"].set(True)
        expected = self._argv_of(arg_builder.build_utility_args(state))

        with (
            deferred_threads() as threads,
            patch("master_driver.runner.module_runner.run_modules") as run_m,
        ):
            launch_utility(state, MagicMock(), MagicMock())
            state.dir_path.set(str(tmp_path / "elsewhere"))
            state.module_toggles["converter"].set(False)
            threads.run_latest()

        run_m.assert_called_once()
        assert self._argv_of(run_m.call_args.kwargs["module_specs"]) == expected

    def test_refinery_argv_survives_state_edit_before_thread_start(
        self, state, launch_mocks, tmp_path
    ) -> None:
        state.refinery_source.set(str(tmp_path))
        state.refinery_output.set(str(tmp_path / "out_a"))
        config = StageConfig(declick=True)
        expected = self._argv_of(arg_builder.build_refinery_args(state, config))

        with (
            deferred_threads() as threads,
            patch("master_driver.runner.module_runner.run_modules") as run_m,
            patch("master_driver.ui.refinery_tab.save_settings"),
        ):
            launch_refinery(state, config, MagicMock(), MagicMock())
            state.refinery_output.set(str(tmp_path / "out_b"))
            threads.run_latest()

        run_m.assert_called_once()
        argv = self._argv_of(run_m.call_args.kwargs["module_specs"])
        assert argv == expected
        assert any("out_a" in arg for args in argv for arg in args), (
            "the pre-edit output path is missing from the emitted argv"
        )
        assert not any("out_b" in arg for args in argv for arg in args)

    def test_thread_receives_resolved_specs_not_live_variables(
        self, state, launch_mocks, tmp_path
    ) -> None:
        """The spec list holds plain values: no Tk variable crosses the boundary."""
        state.dir_path.set(str(tmp_path))
        state.module_toggles["converter"].set(True)

        with (
            deferred_threads() as threads,
            patch("master_driver.runner.module_runner.run_modules") as run_m,
        ):
            launch_utility(state, MagicMock(), MagicMock())
            threads.run_latest()

        specs = run_m.call_args.kwargs["module_specs"]
        assert specs, "build_utility_args returned no specs for the enabled registry"
        assert all(type(enabled) is bool for enabled, *_ in specs)
        converter = next(
            args for _, manifest, args, *_ in specs if manifest.id == "converter"
        )
        assert converter, "the enabled converter tool contributed no argv"
        assert not any(type(arg) is tk.Variable for arg in converter)
