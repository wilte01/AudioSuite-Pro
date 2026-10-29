"""logging_setup.py — Tk-free suite logging configuration.

This module exists because ``app_bootstrap`` imports ``tkinter`` at module
level, so its ``configure_logging`` could not be imported by the headless
CLI (which previously only had ``logging.basicConfig`` writing to stderr)
or by any other Tk-free entry point.  Everything here is standard-library
only and safe to import before a Tk root — or any display — exists.

It owns the suite's file logging end to end.  A single
``configure_logging(program_name)`` call, made at startup by each ``.pyw``
launcher, the Master Driver, the CLI and the ``lyrics_manager`` entry
point, installs **two** rotating file handlers on the ``audio_suite``
logger and on every first-party tool package logger:

* the **suite log**, ``logs/audio_suite.log`` — the administrator-facing
  record.  It carries the startup lifecycle line plus every WARNING,
  ERROR and CRITICAL record from any first-party logger, and deliberately
  drops DEBUG and normal-running INFO.  DEBUG/INFO from the tool packages
  and the shared ``audio_suite.*`` tree was the per-file processing
  firehose that made the suite log unusable for its actual purpose
  (spotting failures), so it is filtered out here by
  :class:`_SuiteAdminFilter`.
* the **per-program log**, ``logs/<program_name>.log`` — the diagnostic
  record for the one program this process is running.  It is unfiltered
  (bounded only by ``min_level``), so every processing detail the tool or
  its shared infrastructure emits is preserved, just not in the shared
  file.  Because one process runs one program, exactly one per-program
  handler is ever installed.

``AUDIOSUITE_LOG_DIR`` overrides the log directory entirely; the test
session points it at a scratch directory so a suite run can never write
into the shipped ``logs/`` tree.

Changed in 1.4.0: every startup records the resolved worker count beside the
lifecycle line, so a host-dependent default is visible during triage (D67).

The uncaught-exception hooks (``sys.excepthook`` /
``threading.excepthook``) keep crash tracebacks in the suite log when
running under ``pythonw``.

``app_bootstrap`` re-exports ``configure_logging`` so its existing
importers (the ``.pyw`` launchers, ``lyrics_manager/__main__`` and
``undo_gui``) keep working unchanged.

Changed in 1.2.0: exposes :func:`get_logs_dir` so other shared modules (the
per-tool run-outcome notes) resolve the same directory, including the
``AUDIOSUITE_LOG_DIR`` override, instead of re-deriving it.

Changed in 2.1.7: the non-package documentation tree is ``documentation``; its
``__init__.py`` test already excludes it.

"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import tempfile
import threading
from pathlib import Path
from types import TracebackType

from .constants import MAX_WORKERS_CEILING, default_max_workers

_HOOK_MARKER = "_audio_suite_hook"

#: The suite's shared namespace logger and its administrator-facing log.
_SUITE_LOGGER_NAME = "audio_suite"
_SUITE_LOG_FILENAME = "audio_suite.log"

#: Env var that redirects the log directory.  Set by the test session so a
#: test run never writes into (or rotates) the shipped ``logs/`` tree.
_LOG_DIR_ENV = "AUDIOSUITE_LOG_DIR"

#: Shared admin log: 2 MB active file, five backups (~12 MB on disk).
_SUITE_MAX_BYTES = 2 * 1024 * 1024
_SUITE_BACKUP_COUNT = 5

#: Per-program detail log: smaller (many tools, each writing its own file).
_PROGRAM_MAX_BYTES = 1024 * 1024
_PROGRAM_BACKUP_COUNT = 3

_LOG_FORMAT = "%(asctime)s  %(name)-40s  %(levelname)-8s  %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"


class _SuiteAdminFilter(logging.Filter):
    """Keep the suite log administrator-relevant, not a processing firehose.

    WARNING and above always pass.  INFO passes only for records emitted
    directly on the ``audio_suite`` logger — the lifecycle ``=== <program>
    started ===`` line.  Every DEBUG and normal-running INFO from a module
    or tool package is per-program processing detail and belongs in that
    program's own ``logs/<program>.log`` instead.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.WARNING or record.name == _SUITE_LOGGER_NAME


def _log_uncaught(
    level: int,
    message: str,
    exc_type: type[BaseException],
    exc_value: BaseException | None,
    exc_tb: TracebackType | None,
) -> None:
    """Write an uncaught exception (with traceback) to the audio_suite log."""
    logger = logging.getLogger(_SUITE_LOGGER_NAME)
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
    ``.venv``, ``documentation``, ``utilities``, ``logs`` — are excluded by
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


def _resolve_logs_dir(suite_root: Path) -> Path:
    """Return the directory the log files are written to.

    ``AUDIOSUITE_LOG_DIR`` overrides the location entirely.  Without it the
    suite's own ``logs/`` directory is used.  If the chosen directory cannot
    be created the system temporary folder is used instead, so a read-only
    install still logs something rather than crashing at startup.

    Args:
        suite_root: The AudioSuite-Pro root directory.

    Returns:
        An existing, writable log directory.
    """
    override = os.environ.get(_LOG_DIR_ENV)
    primary = Path(override) if override else suite_root / "logs"
    try:
        primary.mkdir(parents=True, exist_ok=True)
        return primary
    except OSError:
        fallback = Path(tempfile.gettempdir()) / "audio_suite_logs"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def get_logs_dir() -> Path:
    """Return the directory this suite writes its logs to.

    The public face of :func:`_resolve_logs_dir` for callers outside this
    module's logging setup — e.g. the per-tool run-outcome notes
    (:mod:`audio_suite_shared.run_outcome`) — so the ``AUDIOSUITE_LOG_DIR``
    override and the read-only-install fallback are implemented once, not
    re-derived per caller.

    Returns:
        An existing, writable log directory.
    """
    return _resolve_logs_dir(Path(__file__).resolve().parent.parent)


def _program_log_path(logs_dir: Path, program_name: str) -> Path:
    """Return the per-program log path for ``program_name``.

    The name is reduced to filesystem-safe characters; an empty result
    (a program named entirely of punctuation) falls back to ``program``.
    """
    safe = "".join(
        char if char.isalnum() or char in "-_" else "_" for char in program_name
    )
    return logs_dir / f"{safe or 'program'}.log"


def _ensure_handler(
    logger: logging.Logger,
    path: Path,
    *,
    level: int,
    max_bytes: int,
    backup_count: int,
    record_filter: logging.Filter | None = None,
) -> logging.handlers.RotatingFileHandler:
    """Return the handler writing ``path`` on ``logger``, creating it if needed.

    Keyed on the resolved log path, so a caller's in-memory handler can
    neither suppress file creation nor end up counted as this file's
    handler.  The level (and, for the suite log, the filter) is re-applied
    on every call so a repeated ``configure_logging`` cannot drift.
    """
    target = str(path.resolve())
    for existing in logger.handlers:
        if (
            isinstance(existing, logging.handlers.RotatingFileHandler)
            and str(Path(existing.baseFilename).resolve()) == target
        ):
            existing.setLevel(level)
            if record_filter is not None and not existing.filters:
                existing.addFilter(record_filter)
            return existing

    handler = logging.handlers.RotatingFileHandler(
        path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(fmt=_LOG_FORMAT, datefmt=_LOG_DATEFMT))
    if record_filter is not None:
        handler.addFilter(record_filter)
    logger.addHandler(handler)
    return handler


def configure_logging(program_name: str, *, min_level: int = logging.DEBUG) -> None:
    """
    Configure the suite's file logging for the current process.

    Call this once, early in each .pyw launcher, after setup_sys_path()
    but before import tkinter.  Subsequent calls are safe but do nothing
    beyond the idempotent handler/level bookkeeping below (the handler
    guard prevents duplicate handlers being registered).

    Installs two rotating handlers on the ``audio_suite`` logger and on
    every first-party tool package logger:

    * ``logs/audio_suite.log`` — the suite's administrator-facing log
      (lifecycle INFO on the ``audio_suite`` logger plus every WARNING and
      above from any first-party logger; DEBUG and normal-running INFO are
      filtered out).  2 MB per file, 5 backups.
    * ``logs/<program_name>.log`` — this program's unfiltered diagnostic
      log, bounded only by ``min_level``.  A repeated call with a different
      ``program_name`` replaces (and closes) the previous program log.  1 MB
      per file, 3 backups.

    The root logger is deliberately left alone: the CLI configures it with
    ``logging.basicConfig`` for stderr, and touching it would double-write
    every record.  Third-party loggers are never handed either handler.

    Also installs sys.excepthook / threading.excepthook so uncaught
    exceptions (including their tracebacks) are written to the log —
    without this they only reach stderr, which is lost under pythonw.

    Args:
        program_name: Short identifier for the startup log entry and the
                      per-program log file, e.g. "bpm_analyzer".
        min_level: Level recorded by the first-party package loggers and the
            per-program log.  GUI launchers use the default (DEBUG, every
            detail is preserved in the per-program log); the CLI passes its
            ``--log-level`` value so records match the console verbosity it
            configured.
    """
    logs_dir = get_logs_dir()

    # Named for what it is: the suite's own namespace logger, NOT the root
    # logger. Every first-party module logger is a descendant of this name
    # (iteration-8 C8), which is how their records reach these file handlers.
    suite_logger = logging.getLogger(_SUITE_LOGGER_NAME)
    suite_logger.setLevel(logging.DEBUG)

    package_loggers = [logging.getLogger(name) for name in _first_party_package_names()]
    managed_loggers = [suite_logger, *package_loggers]

    suite_path = logs_dir / _SUITE_LOG_FILENAME
    program_path = _program_log_path(logs_dir, program_name)
    desired = {str(suite_path.resolve()), str(program_path.resolve())}

    # Drop (and close) any handler this module installed for a *different*
    # program on an earlier call, so a repeated call cannot strand a second
    # open file and the process always owns at most one program log.
    for managed in managed_loggers:
        for handler in list(managed.handlers):
            if not isinstance(handler, logging.handlers.RotatingFileHandler):
                continue
            if str(Path(handler.baseFilename).resolve()) not in desired:
                managed.removeHandler(handler)
                handler.close()

    suite_handler = _ensure_handler(
        suite_logger,
        suite_path,
        level=logging.INFO,
        max_bytes=_SUITE_MAX_BYTES,
        backup_count=_SUITE_BACKUP_COUNT,
        record_filter=_SuiteAdminFilter(),
    )
    program_handler = _ensure_handler(
        suite_logger,
        program_path,
        level=min_level,
        max_bytes=_PROGRAM_MAX_BYTES,
        backup_count=_PROGRAM_BACKUP_COUNT,
    )

    # Hand both handlers to every first-party tool package. Idempotent per
    # package (the handler-membership guard) and level-pinned so a CLI run's
    # --log-level is not overridden by the DEBUG default.
    for package_logger in package_loggers:
        package_logger.setLevel(min_level)
        for handler in (suite_handler, program_handler):
            if handler not in package_logger.handlers:
                package_logger.addHandler(handler)

    suite_logger.info("=== %s started ===", program_name)
    # The worker default is host-dependent (one per logical CPU, capped), so
    # record what this process actually resolved: triage otherwise cannot tell
    # a slow run on a 4-core host from a miscounted pool.  Emitted on the
    # suite logger, which is the one INFO line the admin log admits.
    suite_logger.info(
        "Workers: %d resolved (cpu_count=%s, ceiling=%d)",
        default_max_workers(),
        os.cpu_count(),
        MAX_WORKERS_CEILING,
    )
    _install_excepthooks()
