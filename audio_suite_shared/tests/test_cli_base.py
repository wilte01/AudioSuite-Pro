"""
Tests for audio_suite_shared.cli_base

Covers the tkinter-free shims (_NullStringVar, slot helpers), the _Result
collector, and the _run_tool orchestration with terminal callbacks.
"""

from __future__ import annotations

from unittest.mock import MagicMock

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
