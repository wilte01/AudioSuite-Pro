"""
error_logger.py — Compatibility shim for audio_suite_shared.

All logging is now handled by stdlib logging configured once at startup
via logging_setup.configure_logging() (re-exported as
app_bootstrap.configure_logging for the .pyw launchers).  This module
retains the original public API (ErrorLogger class, get_logger(),
cleanup_logs()) so that existing call sites need no changes.

Migration note
--------------
New code should use ``logging.getLogger(__name__)`` directly: since
iteration-9 G4.2 the suite's RotatingFileHandler is attached to every
first-party package logger as well as to the ``audio_suite`` tree, so a
package-module logger reaches the file either way (third-party loggers
are deliberately left alone).  Where standardized error handling is
required use ``@handle_audio_errors`` from
``audio_suite_shared.exceptions`` and ``show_error_from_exception`` from
``audio_suite_shared.ui_helpers``.  Existing call sites using
``get_logger("program_name")`` continue to work — they receive an
ErrorLogger instance backed by a stdlib logger in the ``audio_suite.*``
namespace.  ``log_and_show_error`` is deprecated (logging only; dialogs
are the caller's concern).
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Optional

from audio_suite_shared.exceptions import (
    AudioConfigValueError,
    AudioDirectoryError,
    AudioFileNotFoundError,
    AudioIOError,
    AudioPermissionError,
    AudioSuiteError,
)

# Type aliases kept for backward-compatibility with type-annotated call sites.
ErrorContext = Optional[dict[str, Any]]
LogLevel = str


def _resolve_error_type(error_type: str, error_message: str) -> str:
    """Map a legacy string error-type label to the AudioSuiteError class name.

    ``log_error`` historically received string labels such as
    ``"PermissionError"``.  These are mapped to the matching
    :class:`AudioSuiteError` subclass so the log record name and the shared
    exception tree stay consistent.  Unknown labels pass through unchanged.
    """
    cls = _STRING_TYPE_TO_AUDIO.get(error_type)
    if cls is None:
        return error_type
    return type(cls(error_message)).__name__


_STRING_TYPE_TO_AUDIO: dict[str, type[AudioSuiteError]] = {
    "ValueError": AudioConfigValueError,
    "TypeError": AudioConfigValueError,
    "FileNotFoundError": AudioFileNotFoundError,
    "PermissionError": AudioPermissionError,
    "NotADirectoryError": AudioDirectoryError,
    "IsADirectoryError": AudioDirectoryError,
    "OSError": AudioIOError,
    "IOError": AudioIOError,
}


class ErrorLogger:
    """
    Thin wrapper around a stdlib logger.

    Retains the original public API so all existing call sites work
    without modification.  GUI dialog display is intentionally removed
    from this layer — callers that need to show a messagebox should do
    so explicitly after calling log_error / log_and_show_error.
    """

    def __init__(self, program_name: str) -> None:
        self.program_name = program_name
        self._log = logging.getLogger(f"audio_suite.{program_name}")

    # ------------------------------------------------------------------
    # Backward-compatible no-op — GUI dialogs are the caller's concern.
    # ------------------------------------------------------------------

    def set_root(self, root: object) -> None:
        """No-op.  Retained for API compatibility."""

    # ------------------------------------------------------------------
    # Logging methods
    # ------------------------------------------------------------------

    def log_error(
        self,
        error_type: str,
        error_message: str,
        show_gui: bool = True,  # parameter kept; GUI display removed here
        gui_title: str = "Error",  # parameter kept for API compatibility
        context: ErrorContext = None,
        include_traceback: bool | None = None,
    ) -> None:
        """
        Log an error via the stdlib logging framework.

        Args:
            error_type:        Short label for the error class, e.g. "PermissionError".
            error_message:     Human-readable description.
            show_gui:          Ignored — retained for API compatibility.
            gui_title:         Ignored — retained for API compatibility.
            context:           Optional dict of extra key/value pairs to append.
            include_traceback: True forces the active traceback into the
                               record, False suppresses it.  When omitted
                               (default) the traceback is attached
                               automatically whenever log_error is called
                               while handling an exception.
        """
        parts = [f"[{_resolve_error_type(error_type, error_message)}] {error_message}"]
        if context:
            parts.append("Context:")
            parts.extend(f"  {k}: {v}" for k, v in context.items())
        if include_traceback is None:
            include_traceback = sys.exc_info()[0] is not None
        self._log.error("\n".join(parts), exc_info=include_traceback)

    def log_and_show_error(
        self,
        error_type: str,
        error_message: str,
        gui_title: str = "Error",
        context: ErrorContext = None,
        include_traceback: bool | None = None,
    ) -> None:
        """
        DEPRECATED — Log an error (convenience alias for log_error).

        The original implementation also showed a tkinter messagebox.
        GUI display is now the responsibility of the calling code, and
        callers should migrate to ``@handle_audio_errors`` (processing
        logic) or ``audio_suite_shared.ui_helpers.show_error_from_exception``
        (UI validation errors).  Retained as a backwards-compatible thin
        wrapper until all call sites are migrated.
        """
        self.log_error(
            error_type,
            error_message,
            context=context,
            include_traceback=include_traceback,
        )

    def log_info(self, message: str, context: ErrorContext = None) -> None:
        """Log an informational message."""
        if context:
            self._log.info("%s | context=%s", message, context)
        else:
            self._log.info(message)

    def log_warning(self, message: str, context: ErrorContext = None) -> None:
        """Log a warning."""
        if context:
            self._log.warning("%s | context=%s", message, context)
        else:
            self._log.warning(message)

    def log_debug(self, message: str, context: ErrorContext = None) -> None:
        """Log a debug-level message."""
        if context:
            self._log.debug("%s | context=%s", message, context)
        else:
            self._log.debug(message)

    def get_log_stats(self) -> dict[str, Any]:
        """
        Return basic log statistics.

        The original implementation parsed log files manually.  File
        parsing is no longer needed — RotatingFileHandler in
        logging_setup handles all rotation.  Returns a safe empty
        structure for any call sites that consume the return value.
        """
        return {"total": 0, "by_type": {}, "log_files": []}


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def get_logger(program_name: str) -> ErrorLogger:
    """
    Return an ErrorLogger for the given program.

    Args:
        program_name: Short identifier, e.g. ``"bpm_analyzer"``.

    Returns:
        ErrorLogger instance backed by ``audio_suite.<program_name>``.
    """
    return ErrorLogger(program_name)


def cleanup_logs(
    max_files_per_program: int = 5,  # kept for API compatibility
    max_age_days: int = 30,  # kept for API compatibility
) -> None:
    """
    No-op.  Log rotation is handled by RotatingFileHandler in logging_setup.

    Parameters are retained so any existing call sites continue to work.
    """
