"""
Tests for audio_suite_shared.cli_base

Covers the tkinter-free shims (_NullStringVar, slot helpers), the _Result
collector, and the _run_tool orchestration with terminal callbacks.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from audio_suite_shared.cli_base import (
    _make_slot_queue,
    _make_slot_vars,
    _NullStringVar,
    _Result,
    _run_tool,
)


class TestNullStringVar:
    """tkinter-free StringVar drop-in used by headless CLI runs."""

    def test_get_returns_empty_string(self) -> None:
        var = _NullStringVar()
        assert var.get() == ""

    def test_set_discards_value(self) -> None:
        var = _NullStringVar()
        var.set("anything")
        assert var.get() == ""


class TestSlotHelpers:
    def test_make_slot_vars_creates_null_vars(self) -> None:
        vars_ = _make_slot_vars()
        assert len(vars_) == 4
        assert all(isinstance(v, _NullStringVar) for v in vars_)

    def test_make_slot_vars_custom_count(self) -> None:
        vars_ = _make_slot_vars(n=0)
        assert vars_ == []

    def test_make_slot_queue_preloads_slot_ids(self) -> None:
        q = _make_slot_queue(n=3)
        assert q.qsize() == 3
        assert sorted([q.get(), q.get(), q.get()]) == [0, 1, 2]

    def test_make_slot_queue_default_count(self) -> None:
        assert _make_slot_queue().qsize() == 4


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
