"""
Tests for audio_suite_shared.cli_base

Covers the tkinter-free shims (_NullStringVar, slot helpers), the _Result
collector, and the _run_tool orchestration with terminal callbacks.

Changed in 1.4.0: the slot-helper expectations derive from
``default_max_workers()`` instead of the old fixed 4, and a regression test
asserts the default shims cover every worker slot index a default-sized pool
can hand out.
Changed in 1.4.0: locks the per-run stale-install warning printed by the group
callback.
Changed in 1.4.1: locks ``finish_run`` - a fatal run exits 1 after its payload,
a run whose failures were per-file keeps the command's exit status - and asserts
that every CLI module calling ``_run_tool`` also calls it (PLAN D92).
Changed in 2.1.4: the per-file half of that lock is inverted by the audit's R-06
contract (PLAN D9): a run that reports errors now exits 1, skips alone stay 0,
and ``finish_batch`` applies the same rule to a command that builds its own
payload (D22).  ``TestRunExitStatus`` drives the real group so the status is
observed on a command invocation, not only on the helper.
"""

from __future__ import annotations

import ast
import io
import json
import logging
from pathlib import Path
from queue import Queue
from typing import Any, Callable
from unittest.mock import MagicMock

import pytest

from audio_suite_shared.cli_base import (
    _configure_console_logging,
    _make_slot_queue,
    _make_slot_vars,
    _NullStringVar,
    _Result,
    _run_tool,
    finish_batch,
    finish_run,
)
from audio_suite_shared.constants import default_max_workers


class TestNullStringVar:
    """tkinter-free StringVar drop-in used by headless CLI runs."""

    def test_get_returns_empty_string(self) -> None:
        var = _NullStringVar()
        assert var.get() == ""

    def test_set_discards_value(self) -> None:
        var = _NullStringVar()
        var.set("anything")
        assert var.get() == ""


class TestConsoleLogLevel:
    """``--log-level`` must filter the console handler, not just the root.

    First-party loggers carry an explicit level, so their DEBUG records
    bypass the root logger's level and reach a NOTSET console handler.  The
    regression: ``audiosuite bpm <dir>`` at the default WARNING printed every
    processing detail and the stack trace logged for a corrupt file.
    """

    def test_warning_level_hides_debug_records_from_the_console(self) -> None:
        root = logging.getLogger()
        previous = [(handler, handler.level) for handler in root.handlers]
        stream = io.StringIO()
        console = logging.StreamHandler(stream)
        root.addHandler(console)
        logger = logging.getLogger("test_console_level_probe")
        previous_logger_level = logger.level
        logger.setLevel(logging.DEBUG)
        try:
            _configure_console_logging(logging.WARNING)
            logger.debug("processing detail")
            logger.error("visible failure")
            err = stream.getvalue()
        finally:
            root.removeHandler(console)
            logger.setLevel(previous_logger_level)
            for handler, level in previous:
                handler.setLevel(level)

        assert "processing detail" not in err
        assert "visible failure" in err


class TestSlotHelpers:
    def test_make_slot_vars_creates_null_vars(self) -> None:
        vars_ = _make_slot_vars()
        assert len(vars_) == default_max_workers()
        assert all(isinstance(v, _NullStringVar) for v in vars_)

    def test_make_slot_vars_custom_count(self) -> None:
        vars_ = _make_slot_vars(n=0)
        assert vars_ == []

    def test_make_slot_queue_preloads_slot_ids(self) -> None:
        q = _make_slot_queue(n=3)
        assert q.qsize() == 3
        assert sorted([q.get(), q.get(), q.get()]) == [0, 1, 2]

    def test_make_slot_queue_default_count(self) -> None:
        assert _make_slot_queue().qsize() == default_max_workers()

    def test_default_slot_shims_cover_every_worker_slot_index(self) -> None:
        """A default-sized pool indexes every shim, not just the first four.

        Regression: the shims were fixed at 4 while ``default_max_workers()``
        became CPU-derived, so a CLI run on five or more files raised
        ``IndexError`` inside the worker and reported the file as an
        unexplained error.
        """
        seen: list[int] = []

        def run_fn(
            *,
            slot_vars: list[_NullStringVar],
            slot_queue: Queue[Any],
            on_progress: Callable[..., None],
            on_complete: Callable[..., None],
            on_error: Callable[[str], None],
        ) -> None:
            del slot_queue, on_progress, on_error
            for idx in range(default_max_workers()):
                slot_vars[idx].set(f"worker {idx}")
                seen.append(idx)
            on_complete(total=default_max_workers())

        result = _run_tool("probe", run_fn)

        assert seen == list(range(default_max_workers()))
        assert result.total == default_max_workers()
        assert result.errors == 0


class TestExplicitWorkerOverride:
    """A ``--workers`` value above the default gets a shim for every index."""

    def test_slot_shims_cover_an_explicit_worker_override(self) -> None:
        """D66: the shims were default-sized while the pool was the override.

        A CLI run with ``--workers 12`` on a 8-worker host handed the ninth
        worker ``slot_vars[8]`` and reported the file as an unexplained error.
        """
        seen: list[int] = []

        def run_fn(
            *,
            slot_vars: list[_NullStringVar],
            slot_queue: Queue[Any],
            on_progress: Callable[..., None],
            on_complete: Callable[..., None],
            on_error: Callable[[str], None],
            max_workers: int,
        ) -> None:
            del slot_queue, on_progress, on_error
            for idx in range(max_workers):
                slot_vars[idx].set(f"worker {idx}")
                seen.append(idx)
            on_complete(total=len(seen))

        result = _run_tool("probe", run_fn, max_workers=12)

        assert seen == list(range(12))
        assert result.errors == 0
        assert result.total == 12

    def test_the_default_count_is_not_enlarged(self) -> None:
        assert len(_make_slot_vars()) == default_max_workers()


class TestResult:
    def test_to_dict_includes_duration_str(self) -> None:
        result = _Result(total=10, processed=7, duration_secs=3.25)
        d = result.to_dict()
        assert d["total"] == 10
        assert d["processed"] == 7
        assert d["duration_str"] == "3.2s"

    def test_defaults_are_zero(self) -> None:
        d = _Result().to_dict()
        assert d["total"] == 0
        assert d["errors"] == 0
        assert d["log_entries"] == []


class TestRunTool:
    def test_forwards_defaults_and_calls_run_fn(self) -> None:
        run_fn = MagicMock()

        captured = {}

        def on_progress(**cb_kwargs):
            captured["on_progress"] = cb_kwargs

        result = _run_tool(
            "test_tool",
            run_fn,
            on_progress=on_progress,
        )

        run_fn.assert_called_once()
        kwargs = run_fn.call_args[1]
        # Default slot vars / queue are injected when not supplied.
        assert "slot_vars" in kwargs
        assert "slot_queue" in kwargs
        assert callable(kwargs["on_complete"])

        # Firing on_complete populates the result collector.
        kwargs["on_complete"](
            total=5, processed=5, skipped=0, errors=0, duration_secs=1.0
        )
        assert result.total == 5

    def test_on_error_path_marks_result(self) -> None:
        run_fn = MagicMock()
        captured_errors: list[str] = []

        def on_error(msg: str) -> None:
            captured_errors.append(msg)

        result = _run_tool("test_tool", run_fn, on_error=on_error)
        assert result.errors == 0


class TestCliSuiteLogging:
    """cli() must hand the parsed --log-level to the suite file logger (G4.3).

    Audit M1: the CLI only ran ``logging.basicConfig`` (stderr), so
    first-party records never reached ``logs/audio_suite.log`` under a CLI
    run either.  This pins the wiring at the call site — patching the
    ``cli_base`` binding (the namespace ``cli()`` resolves at call time) and
    driving the real group through real click parsing, so a future change
    that drops the ``min_level=`` keyword fails here rather than silently
    reverting to the DEBUG default.
    """

    def test_cli_invocation_wires_suite_logging(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from click.testing import CliRunner

        from audio_suite_shared import cli_app, cli_base

        # cli_app registers the tool subcommands onto cli_base.cli, which is
        # how "stats" exists; without it the group would reject the command
        # before the callback (and this assertion) could run.
        assert cli_app.cli is cli_base.cli

        configure = MagicMock()
        monkeypatch.setattr(cli_base, "configure_logging", configure)

        result = CliRunner().invoke(
            cli_base.cli, ["--log-level", "INFO", "stats", "--help"]
        )

        assert result.exit_code == 0, result.output
        configure.assert_called_once()
        assert configure.call_args.args == ("audiosuite_cli",)
        assert configure.call_args.kwargs["min_level"] == logging.INFO


class TestStaleInstallWarning:
    """A version gap between the install and the checkout reaches the user."""

    @staticmethod
    def _invoke(monkeypatch, warning: str | None, tmp_path) -> str:
        from click.testing import CliRunner

        from audio_suite_shared import cli_base, runtime_check

        monkeypatch.setattr(runtime_check, "stale_install_warning", lambda: warning)
        result = CliRunner().invoke(cli_base.cli, ["bpm", str(tmp_path), "--help"])
        assert result.exit_code == 0, result.output
        return result.output

    def test_mismatch_is_printed_with_the_locked_runtime(
        self, monkeypatch, tmp_path
    ) -> None:
        message = "Warning: stale install. Run: uv run audiosuite --help"
        assert message in self._invoke(monkeypatch, message, tmp_path)

    def test_matching_install_prints_no_warning(self, monkeypatch, tmp_path) -> None:
        output = self._invoke(monkeypatch, None, tmp_path)
        assert "Warning: the installed audiosuite-pro" not in output


class TestFinishRun:
    """The exit status a command reports once its payload is on stdout."""

    def test_a_fatal_run_exits_1(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            finish_run(_Result(errors=1, fatal=True))

        assert excinfo.value.code == 1

    @pytest.mark.parametrize("errors", [1, 3])
    def test_a_run_that_reported_errors_exits_1(self, errors: int) -> None:
        """R-06: the payload's ``errors`` governs the status too.

        Before the fix ``convert`` printed ``1 errors`` and returned 0, so a
        scheduler could not tell a clean run from one that converted nothing.
        """
        with pytest.raises(SystemExit) as excinfo:
            finish_run(_Result(total=3, processed=3, errors=errors))

        assert excinfo.value.code == 1

    def test_a_clean_run_returns(self) -> None:
        assert finish_run(_Result(total=2, processed=2, errors=0)) is None

    def test_skips_alone_stay_clean(self) -> None:
        """A skipped file was not a failure: an all-skipped tree exits 0."""
        assert finish_run(_Result(total=4, processed=4, skipped=4, errors=0)) is None

    def test_a_fatal_run_still_counts_one_error(self) -> None:
        """The text summary cannot print a negative count, and JSON forbids it."""
        result = _run_tool("test", MagicMock(side_effect=RuntimeError("boom")))

        assert result.fatal is True
        assert result.errors == 1
        assert result.to_payload("bpm")["errors"] == 1
        assert "fatal" not in result.to_dict()


class TestFinishBatch:
    """The same rule for a command that builds its own payload (D22)."""

    def test_zero_errors_returns(self) -> None:
        assert finish_batch(0) is None

    @pytest.mark.parametrize("errors", [1, 7])
    def test_any_reported_error_exits_1(self, errors: int) -> None:
        with pytest.raises(SystemExit) as excinfo:
            finish_batch(errors)

        assert excinfo.value.code == 1


class TestRunExitStatus:
    """``_run_tool`` commands report a crash and per-file errors through status.

    Before D92 a run that died on its first file printed ``FATAL`` and a
    payload with ``errors: 1``, then exited 0 - a shell couldn't gate on it.
    Before R-06 the *per-file* case was deliberately left at 0, so ``convert``
    exited 0 after converting none of its input; D9 supersedes that.
    """

    @staticmethod
    def _invoke(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        run_fn: Callable[..., None],
        *argv: str,
    ) -> tuple[int, str, str]:
        from click.testing import CliRunner

        from audio_suite_shared import cli_app, cli_base

        # cli_app is what registers the tool commands onto the group.
        assert cli_app.cli is cli_base.cli
        monkeypatch.setattr("bpm_analyzer.core.file_processor.run_analysis", run_fn)
        result = CliRunner().invoke(cli_base.cli, ["bpm", str(tmp_path), *argv])
        return result.exit_code, result.stdout, result.stderr

    def test_a_fatal_run_exits_1_with_the_reason(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def _boom(**_kwargs: object) -> None:
            raise RuntimeError("decoder exploded")

        exit_code, stdout, stderr = self._invoke(monkeypatch, tmp_path, _boom, "--json")

        assert exit_code == 1, stderr
        payload = json.loads(stdout)
        assert payload["errors"] == 1
        assert payload["error"] == "decoder exploded"
        assert "FATAL" in stderr

    def test_a_fatal_run_exits_1_in_text_mode(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def _boom(**_kwargs: object) -> None:
            raise RuntimeError("decoder exploded")

        exit_code, stdout, stderr = self._invoke(monkeypatch, tmp_path, _boom)

        assert exit_code == 1
        # The text summary is the normal display, and it must not leak the
        # failure marker as a count ("-1 errors").
        assert "1 errors" in stdout
        assert "-1" not in stdout
        assert "FATAL" in stderr

    def test_per_file_failures_exit_1_with_the_payload_intact(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """R-06: the document is unchanged and only the status moves."""

        def _three_failures(**kwargs: object) -> None:
            on_complete = kwargs["on_complete"]
            assert callable(on_complete)
            on_complete(total=3, processed=3, skipped=0, errors=3, duration_secs=0.5)

        exit_code, stdout, _ = self._invoke(
            monkeypatch, tmp_path, _three_failures, "--json"
        )

        assert exit_code == 1
        payload = json.loads(stdout)
        assert payload["errors"] == 3
        assert payload["succeeded"] == 0

    def test_a_clean_run_exits_0(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def _clean(**kwargs: object) -> None:
            on_complete = kwargs["on_complete"]
            assert callable(on_complete)
            on_complete(total=2, processed=2, skipped=0, errors=0, duration_secs=0.5)

        exit_code, _, stderr = self._invoke(monkeypatch, tmp_path, _clean, "--json")

        assert exit_code == 0, stderr

    def test_skips_alone_exit_0(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A tree already in the target format is a clean run, not a failure."""

        def _skipped(**kwargs: object) -> None:
            on_complete = kwargs["on_complete"]
            assert callable(on_complete)
            on_complete(total=3, processed=3, skipped=3, errors=0, duration_secs=0.5)

        exit_code, stdout, stderr = self._invoke(
            monkeypatch, tmp_path, _skipped, "--json"
        )

        assert exit_code == 0, stderr
        payload = json.loads(stdout)
        assert payload["skipped"] == 3
        assert payload["succeeded"] == 0

    def test_every_run_tool_call_site_also_calls_finish_run(self) -> None:
        """A tool that wires ``_run_tool`` but skips the exit check fails here."""
        repo_root = Path(__file__).resolve().parents[2]
        runs: set[str] = set()
        finishes: set[str] = set()
        for cli_file in sorted(repo_root.glob("*/cli.py")):
            calls = {
                node.func.id
                for node in ast.walk(ast.parse(cli_file.read_text(encoding="utf-8")))
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            }
            # The package directory, not the file name: every candidate is
            # called ``cli.py``, so keying on the name collapsed both sets to
            # one entry and the scan passed with a call site removed.
            package = cli_file.parent.name
            if "_run_tool" in calls:
                runs.add(package)
            if "finish_run" in calls:
                finishes.add(package)

        assert runs, "no _run_tool call site found - the scan would pass vacuously"
        assert finishes, "no finish_run call site found - the scan would pass vacuously"
        assert not runs - finishes, (
            "CLI modules that use _run_tool without finish_run: "
            f"{sorted(runs - finishes)}"
        )
