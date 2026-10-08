"""logging_setup.py — Tk-free suite logging configuration.

This module exists because ``app_bootstrap`` imports ``tkinter`` at module
level, so its ``configure_logging`` could not be imported by the headless
CLI (which previously only had ``logging.basicConfig`` writing to stderr)
or by any other Tk-free entry point.  Everything here is standard-library
only and safe to import before a Tk root — or any display — exists.

It owns the suite's file logging end to end:

* the rotating ``logs/audio_suite.log`` handler on the ``audio_suite``
  logger and the startup line written to it;
* the uncaught-exception hooks (``sys.excepthook`` /
  ``threading.excepthook``) that keep crash tracebacks in that file when
  running under ``pythonw``;
* iteration-9 G4.2: attaching the *same* handler to every first-party
  tool package logger, so records from ``getLogger(__name__)`` modules
  (``noise_reduction.app`` and friends) reach the file instead of dying
  on the root logger, which has no file handler under a GUI launch.

``app_bootstrap`` re-exports ``configure_logging`` so its existing
importers (the ``.pyw`` launchers, ``lyrics_manager/__main__`` and
``undo_gui``) keep working unchanged.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import tempfile
import threading
from pathlib import Path
from types import TracebackType

_HOOK_MARKER = "_audio_suite_hook"


def _log_uncaught(
    level: int,
    message: str,
    exc_type: type[BaseException],
    exc_value: BaseException | None,
    exc_tb: TracebackType | None,
) -> None:
    """Write an uncaught exception (with traceback) to the audio_suite log."""
    logger = logging.getLogger("audio_suite")
    if exc_value is None:
        logger.log(level, "%s: %s", message, exc_type.__name__)
        return
    logger.log(level, message, exc_info=(exc_type, exc_value, exc_tb))


def _log_fatal_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> None:
    """Route an uncaught exception into the audio_suite log.

    Installed as ``sys.excepthook`` so crashes are captured in
    audio_suite.log even when running under pythonw (no console).
    """
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    _log_uncaught(logging.CRITICAL, "Uncaught exception", exc_type, exc_value, exc_tb)


_log_fatal_exception._audio_suite_hook = True  # type: ignore[attr-defined]


def _log_thread_exception(args: threading.ExceptHookArgs) -> None:
    """Route an uncaught worker-thread exception into the audio_suite log."""
    thread_name = args.thread.name if args.thread is not None else "unknown"
    _log_uncaught(
        logging.CRITICAL,
        f"Uncaught exception in thread {thread_name}",
        args.exc_type,
        args.exc_value,
        args.exc_traceback,
    )


_log_thread_exception._audio_suite_hook = True  # type: ignore[attr-defined]


def _install_excepthooks() -> None:
    """Install fatal-exception hooks once (idempotent via marker attribute)."""
    if getattr(sys.excepthook, _HOOK_MARKER, False) is not True:
        sys.excepthook = _log_fatal_exception
    if getattr(threading.excepthook, _HOOK_MARKER, False) is not True:
        threading.excepthook = _log_thread_exception


def _first_party_package_names() -> list[str]:
    """Names of the first-party tool packages living at the suite root.

    Every immediate subdirectory of the suite root that carries an
    ``__init__.py`` is a first-party package whose ``getLogger(__name__)``
    records belong in the suite log.  Directories without one —
    ``.venv``, ``user_guides``, ``utilities``, ``logs`` — are excluded by
    the ``__init__.py`` test, and ``tests`` is excluded by name because its
    package does carry one and its records are test artefacts, never
    production events.

    Returns:
        Sorted package (logger) names.
    """
    suite_root = Path(__file__).resolve().parent.parent
    return sorted(
        entry.name
        for entry in suite_root.iterdir()
        if entry.is_dir()
        and entry.name != "tests"
        and (entry / "__init__.py").is_file()
    )


def configure_logging(program_name: str, *, min_level: int = logging.DEBUG) -> None:
    """
    Configure the suite's file logging for the current process.

    Call this once, early in each .pyw launcher, after setup_sys_path()
    but before import tkinter.  Subsequent calls are safe but do nothing
    beyond the idempotent handler/level bookkeeping below (the handler
    guard prevents duplicate handlers being registered).

    Writes to <suite_root>/logs/audio_suite.log with rotation:
    2 MB per file, 5 backup files (10 MB total on disk).

    The suite's RotatingFileHandler is attached to the ``audio_suite``
    logger *and* to every first-party tool package logger (G4.2), so
    records from ``getLogger(__name__)`` modules reach the file under both
    GUI and CLI launches.  The root logger is deliberately left alone: the
    CLI configures it with ``logging.basicConfig`` for stderr, and touching
    it would double-write every record.

    Also installs sys.excepthook / threading.excepthook so uncaught
    exceptions (including their tracebacks) are written to the log —
    without this they only reach stderr, which is lost under pythonw.

    Args:
        program_name: Short identifier for the startup log entry,
                      e.g. "bpm_analyzer".
        min_level: Level recorded by the first-party package loggers.
            GUI launchers use the default (DEBUG, everything reaches the
            file); the CLI passes its ``--log-level`` value so package
            records match the console verbosity it configured.
    """
    suite_root = Path(__file__).parent.parent
    logs_dir = suite_root / "logs"

    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        logs_dir = Path(tempfile.gettempdir()) / "audio_suite_logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

    log_file = logs_dir / "audio_suite.log"

    # Named for what it is: the suite's own namespace logger, NOT the root
    # logger. Every first-party module logger is a descendant of this name
    # (iteration-8 C8), which is how their records reach this file handler.
    suite_logger = logging.getLogger("audio_suite")
    suite_logger.setLevel(logging.DEBUG)

    # The suite handler is *the file handler* specifically: keying the guard
    # on "any handler at all" would let a caller's in-memory handler both
    # suppress file creation and end up attached to the package loggers.
    handler = next(
        (
            existing
            for existing in suite_logger.handlers
            if isinstance(existing, logging.handlers.RotatingFileHandler)
        ),
        None,
    )
    if handler is None:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=2 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s  %(name)-40s  %(levelname)-8s  %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        suite_logger.addHandler(file_handler)
        handler = file_handler

    # G4.2: hand the same handler to every first-party tool package.
    # Idempotent per package (the handler-membership guard) and level-pinned
    # so a CLI run's --log-level is not overridden by the DEBUG default.
    for package_name in _first_party_package_names():
        package_logger = logging.getLogger(package_name)
        package_logger.setLevel(min_level)
        if handler not in package_logger.handlers:
            package_logger.addHandler(handler)

    suite_logger.info("=== %s started ===", program_name)
    _install_excepthooks()
