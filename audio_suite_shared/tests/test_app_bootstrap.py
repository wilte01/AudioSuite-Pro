"""
test_app_bootstrap.py — Unit tests for audio_suite_shared.app_bootstrap

Strategy
--------
app_bootstrap imports tkinter at module level, which requires a display
on headless CI.  Tests that exercise pure-logic (configure_logging) run
unconditionally.  Tests that require a Tk root are guarded with the
``requires_display`` mark: skipped automatically when no display is available.

Covers:
    • configure_logging: handler registered, idempotent, correct type and level
    • configure_logging: fallback to tempdir when suite/logs is unwritable
    • configure_logging: sys/threading excepthooks installed and logging
      uncaught exceptions with full tracebacks
    • bootstrap_tool_app: Tkinter report_callback_exception routed to the log
"""

from __future__ import annotations

import logging
import logging.handlers as lh
import os
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from audio_suite_shared import logging_setup

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_display() -> bool:
    """Return True if a graphical display is available."""
    if sys.platform == "win32":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


requires_display = pytest.mark.skipif(
    not _has_display(), reason="No graphical display — Tkinter unavailable"
)


def _clear_audio_suite_handlers() -> None:
    """Strip and close every suite file handler, on every logger holding it.

    The suite's RotatingFileHandler is shared: ``configure_logging`` (G4.2)
    attaches the same object to the ``audio_suite`` logger *and* to every
    first-party package logger.  Clearing only the suite logger's list
    would leave the old stream open on the package loggers, and the next
    ``configure_logging`` call — seeing an empty suite logger — would create
    a *second* handler on the same ``logs/audio_suite.log``.  On Windows the
    rename inside ``doRollover()`` then fails with PermissionError once the
    file crosses ``maxBytes``, and the handler's ``handleError`` writes a
    ``--- Logging error ---`` traceback to stderr, which Click's CliRunner
    mixes into command output (intermittent JSON/traceback test failures).
    """
    suite_logger = logging.getLogger("audio_suite")
    loggers = [suite_logger] + [
        logging.getLogger(name) for name in logging_setup._first_party_package_names()
    ]

    file_handlers = {
        handler
        for logger in loggers
        for handler in logger.handlers
        if isinstance(handler, lh.RotatingFileHandler)
    }
    for logger in loggers:
        for handler in file_handlers:
            logger.removeHandler(handler)
    for handler in file_handlers:
        handler.close()

    suite_logger.handlers.clear()


class _ListHandler(logging.Handler):
    """In-memory handler capturing records for assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def hook_guard() -> None:
    """Save/restore sys.excepthook and threading.excepthook around a test."""
    saved_sys_hook = sys.excepthook
    saved_thread_hook = threading.excepthook
    yield
    sys.excepthook = saved_sys_hook
    threading.excepthook = saved_thread_hook


# ---------------------------------------------------------------------------
# configure_logging
# ---------------------------------------------------------------------------


class TestConfigureLogging:
    """Tests for the configure_logging helper (pure-logic, no Tk dependency)."""

    def setup_method(self) -> None:
        _clear_audio_suite_handlers()

    def test_handler_registered_after_call(self) -> None:
        """configure_logging must attach at least one handler."""
        from audio_suite_shared.app_bootstrap import configure_logging

        configure_logging("test_program")
        lg = logging.getLogger("audio_suite")
        assert len(lg.handlers) >= 1

    def test_configure_logging_is_idempotent(self) -> None:
        """Calling configure_logging twice must not duplicate handlers."""
        from audio_suite_shared.app_bootstrap import configure_logging

        configure_logging("prog_a")
        count_after_first = len(logging.getLogger("audio_suite").handlers)

        configure_logging("prog_a")
        count_after_second = len(logging.getLogger("audio_suite").handlers)

        assert count_after_second == count_after_first

    def test_uses_rotating_file_handler(self) -> None:
        """The attached handler must be a RotatingFileHandler."""
        from audio_suite_shared.app_bootstrap import configure_logging

        configure_logging("test_rotating")
        handler_types = [type(h) for h in logging.getLogger("audio_suite").handlers]
        assert lh.RotatingFileHandler in handler_types

    def test_sets_debug_level(self) -> None:
        """Root audio_suite logger must be set to DEBUG level."""
        from audio_suite_shared.app_bootstrap import configure_logging

        configure_logging("level_check")
        assert logging.getLogger("audio_suite").level == logging.DEBUG

    def test_fallback_to_tempdir_when_logs_dir_unwritable(self) -> None:
        """If the primary logs directory cannot be created, configure_logging
        must fall back to a subdirectory of tempfile.gettempdir() without raising."""

        from audio_suite_shared.app_bootstrap import configure_logging

        mkdir_calls: list = []
        real_mkdir = Path.mkdir

        def patched_mkdir(self, *args, **kwargs):
            mkdir_calls.append(str(self))
            # Fail the first mkdir (primary logs dir), succeed on fallback
            if len(mkdir_calls) == 1:
                raise OSError("permission denied — primary logs dir")
            real_mkdir(self, *args, **kwargs)

        with patch.object(Path, "mkdir", patched_mkdir):
            try:
                configure_logging("fallback_test")
            except Exception as exc:
                pytest.fail(
                    f"configure_logging raised unexpectedly after fallback: {exc}"
                )

        # Verify the fallback path was attempted
        assert any("audio_suite_logs" in p for p in mkdir_calls), (
            "Fallback to tempdir/audio_suite_logs must have been attempted"
        )


class TestClearAudioSuiteHandlers:
    """The between-tests reset must leave no open suite file handler anywhere.

    Regression (found while tracing G5.3): clearing only the ``audio_suite``
    logger's handler list — the pre-G4.2 behaviour — left the shared
    RotatingFileHandler attached to the package loggers, so the next
    ``configure_logging`` created a *second* open handle on
    ``logs/audio_suite.log``; the first rollover then failed with a Windows
    rename PermissionError and polluted CLI output with ``--- Logging
    error ---`` tracebacks (3 intermittent failures across full-suite runs).
    """

    def test_clear_detaches_and_closes_the_shared_handler(self) -> None:
        from audio_suite_shared.app_bootstrap import configure_logging

        configure_logging("clear_probe")
        suite_logger = logging.getLogger("audio_suite")
        shared = [
            handler
            for handler in suite_logger.handlers
            if isinstance(handler, lh.RotatingFileHandler)
        ]
        assert len(shared) == 1, shared
        file_handler = shared[0]
        package_loggers = [
            logging.getLogger(name)
            for name in logging_setup._first_party_package_names()
        ]
        attached = [lg for lg in package_loggers if file_handler in lg.handlers]
        assert attached, "G4.2 shares the suite handler with package loggers"

        _clear_audio_suite_handlers()

        assert file_handler.stream is None, "the cleared handler must be closed"
        assert all(
            file_handler not in logger.handlers
            for logger in [suite_logger, *package_loggers]
        )
        assert not any(
            isinstance(handler, lh.RotatingFileHandler)
            for handler in suite_logger.handlers
        )

        # Positive contract: the next call creates exactly one fresh shared
        # handler, so no package logger ever holds two handles on the file.
        configure_logging("clear_probe_again")
        fresh = [
            handler
            for handler in suite_logger.handlers
            if isinstance(handler, lh.RotatingFileHandler)
        ]
        assert len(fresh) == 1, fresh
        assert fresh[0] is not file_handler
        assert all(
            sum(
                isinstance(handler, lh.RotatingFileHandler)
                for handler in logger.handlers
            )
            <= 1
            for logger in package_loggers
        )


# ---------------------------------------------------------------------------
# exception hooks (pure-logic, no Tk dependency)
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("hook_guard")
class TestExceptionHooks:
    """configure_logging must install fatal-exception hooks that log
    uncaught exceptions with full tracebacks."""

    def setup_method(self) -> None:
        _clear_audio_suite_handlers()

    def _attach_list_handler(self) -> _ListHandler:
        handler = _ListHandler()
        logging.getLogger("audio_suite").addHandler(handler)
        return handler

    def test_sys_excepthook_installed(self) -> None:
        from audio_suite_shared.app_bootstrap import configure_logging

        configure_logging("hook_sys")
        assert getattr(sys.excepthook, "_audio_suite_hook", False) is True

    def test_threading_excepthook_installed(self) -> None:
        from audio_suite_shared.app_bootstrap import configure_logging

        configure_logging("hook_thread")
        assert getattr(threading.excepthook, "_audio_suite_hook", False) is True

    def test_hooks_are_idempotent(self) -> None:
        from audio_suite_shared.app_bootstrap import configure_logging

        configure_logging("hook_idem_a")
        sys_hook_first = sys.excepthook
        thread_hook_first = threading.excepthook

        configure_logging("hook_idem_b")

        assert sys.excepthook is sys_hook_first
        assert threading.excepthook is thread_hook_first

    def test_uncaught_exception_logged_with_traceback(self) -> None:
        from audio_suite_shared.app_bootstrap import configure_logging

        configure_logging("hook_log")
        handler = self._attach_list_handler()

        try:
            raise ValueError("boom_traceback_sentinel")
        except ValueError:
            sys.excepthook(*sys.exc_info())

        fatals = [r for r in handler.records if r.levelno == logging.CRITICAL]
        assert len(fatals) == 1
        assert fatals[0].exc_info is not None
        assert fatals[0].exc_text is not None
        assert "boom_traceback_sentinel" in fatals[0].exc_text

    def test_keyboard_interrupt_passthrough_not_logged(self) -> None:
        from audio_suite_shared.app_bootstrap import configure_logging

        configure_logging("hook_ki")
        handler = self._attach_list_handler()

        try:
            raise KeyboardInterrupt
        except KeyboardInterrupt:
            sys.excepthook(*sys.exc_info())

        assert not [r for r in handler.records if r.levelno == logging.CRITICAL]

    def test_thread_exception_logged_with_traceback(self) -> None:
        from audio_suite_shared.app_bootstrap import configure_logging

        configure_logging("hook_thr")
        handler = self._attach_list_handler()

        try:
            raise RuntimeError("thread_boom_sentinel")
        except RuntimeError:
            args = threading.ExceptHookArgs(
                (*sys.exc_info(), threading.current_thread())
            )
            threading.excepthook(args)

        fatals = [r for r in handler.records if r.levelno == logging.CRITICAL]
        assert len(fatals) == 1
        assert fatals[0].exc_text is not None
        assert "thread_boom_sentinel" in fatals[0].exc_text


# ═══════════════════════════════════════════════════════════════════════════════
# bootstrap_tool_app  (requires display)
# ═══════════════════════════════════════════════════════════════════════════════


@requires_display
class TestBootstrapToolApp:
    """Tests for the full bootstrap_tool_app function."""

    @pytest.fixture(autouse=True)
    @staticmethod
    def setup_tk(tk_root):
        return tk_root

    def test_returns_expected_tuple(self, setup_tk) -> None:
        from audio_suite_shared.app_bootstrap import bootstrap_tool_app

        result = bootstrap_tool_app(
            setup_tk, "Test App", "test_window_key", "test_logger"
        )
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_returns_error_logger_and_style(self, setup_tk) -> None:
        from audio_suite_shared.app_bootstrap import bootstrap_tool_app
        from audio_suite_shared.error_logger import ErrorLogger

        error_logger, style = bootstrap_tool_app(
            setup_tk, "Test App", "test_window_key", "test_logger"
        )
        assert isinstance(error_logger, ErrorLogger)
        from tkinter import ttk

        assert isinstance(style, ttk.Style)

    def test_returns_none_style_when_apply_ttk_styles_false(self, setup_tk) -> None:
        from audio_suite_shared.app_bootstrap import bootstrap_tool_app

        _, style = bootstrap_tool_app(
            setup_tk,
            "Test App",
            "test_window_key",
            "test_logger",
            apply_ttk_styles=False,
        )
        assert style is None

    def test_custom_dimensions(self, setup_tk) -> None:
        from audio_suite_shared.app_bootstrap import bootstrap_tool_app

        error_logger, style = bootstrap_tool_app(
            setup_tk,
            "Size Test",
            "size_test_key",
            "size_logger",
            width=1024,
            height=768,
        )
        assert error_logger is not None

    def test_root_title_set(self, setup_tk) -> None:
        from audio_suite_shared.app_bootstrap import bootstrap_tool_app

        bootstrap_tool_app(setup_tk, "My Custom Title", "title_key", "title_logger")
        assert setup_tk.title() == "My Custom Title"

    def test_tk_callback_exception_logged_with_traceback(self, setup_tk) -> None:
        from audio_suite_shared.app_bootstrap import bootstrap_tool_app

        bootstrap_tool_app(setup_tk, "TkHook", "tkhook_key", "tkhook_logger")

        handler = _ListHandler()
        lg = logging.getLogger("audio_suite")
        lg.addHandler(handler)
        try:
            try:
                raise ZeroDivisionError("tk_boom_sentinel")
            except ZeroDivisionError:
                assert callable(setup_tk.report_callback_exception)
                setup_tk.report_callback_exception(*sys.exc_info())  # type: ignore[misc]
        finally:
            lg.removeHandler(handler)

        errors = [r for r in handler.records if r.levelno == logging.ERROR]
        assert len(errors) == 1
        assert errors[0].exc_text is not None
        assert "tk_boom_sentinel" in errors[0].exc_text


# ═══════════════════════════════════════════════════════════════════════════════
# BaseSuiteApp  (requires display)
# ═══════════════════════════════════════════════════════════════════════════════


@requires_display
class TestBaseSuiteApp:
    """Tests for the BaseSuiteApp class."""

    @pytest.fixture(autouse=True)
    @staticmethod
    def setup_tk(tk_root):
        return tk_root

    def test_initialization(self, setup_tk) -> None:
        from audio_suite_shared.app_bootstrap import BaseSuiteApp

        app = BaseSuiteApp(
            setup_tk, "Suite App", "suite_key", "suite_logger", help_guide="guide.docx"
        )
        assert app.root is setup_tk
        assert app.help_guide == "guide.docx"
        assert app.num_workers == 4
        assert app.error_logger is not None
        assert not hasattr(app, "style")
        assert app.auto_end is False
        assert app.auto_start is False
        assert len(app.slot_vars) == 4
        assert app.cli_handler is not None

    def test_custom_worker_count(self, setup_tk) -> None:
        from audio_suite_shared.app_bootstrap import BaseSuiteApp

        app = BaseSuiteApp(
            setup_tk,
            "Workers Test",
            "workers_key",
            "workers_logger",
            num_workers=8,
        )
        assert app.num_workers == 8
        assert len(app.slot_vars) == 8

    def test_slot_queue_initialized(self, setup_tk) -> None:
        from audio_suite_shared.app_bootstrap import BaseSuiteApp

        app = BaseSuiteApp(
            setup_tk,
            "Queue Test",
            "queue_key",
            "queue_logger",
            num_workers=3,
        )
        assert app.slot_queue.qsize() == 3
        for i in range(3):
            assert app.slot_queue.get() == i

    def test_open_help_no_guide_does_not_raise(self, setup_tk) -> None:
        from audio_suite_shared.app_bootstrap import BaseSuiteApp

        app = BaseSuiteApp(
            setup_tk, "NoHelp", "nohelp_key", "nohelp_logger", help_guide=""
        )
        # Must not raise
        app._open_help()

    def test_open_log_does_not_raise(self, setup_tk, monkeypatch) -> None:
        from audio_suite_shared.app_bootstrap import BaseSuiteApp

        app = BaseSuiteApp(
            setup_tk, "LogTest", "log_key", "log_logger", help_guide="guide.docx"
        )
        monkeypatch.setattr(
            "audio_suite_shared.ui_helpers.messagebox.showinfo", lambda *a, **kw: None
        )
        # Must not raise (messagebox.showinfo is mocked to no-op)
        app._open_log()
