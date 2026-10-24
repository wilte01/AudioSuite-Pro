"""
preflight.py — Fast-fail syntax/import guard for the Audio Suite entry points.

Each ``*.pyw`` launcher invokes :func:`verify_suite` before importing the
tool's app module.  A missing import or a stray indentation error in the
package chain would otherwise surface as an opaque ``traceback`` written to a
log file, long after the user has launched the tool.  This guard syntax-checks
every first-party ``.py`` file under the suite root (via ``compileall``) so a
broken module produces one clear, actionable error instead of a silent crash.

The guard deliberately does **not** import the modules (importing can create
Tk roots, run side effects, or recurse into the very bug we are catching).  It
only verifies that every module *parses*.  Runtime import failures are surfaced
separately by Python's own import machinery once the guard passes.

The scan covers first-party source only: ``plugins/`` is excluded, because the
guard blocks the launch it checks and a third-party plugin must not be able to
stop every tool in the suite from starting.  A broken plugin is reported by
the plugin loader instead.

:func:`report_missing_requirements` is a second, independent check: it probes the
external binaries declared in :mod:`audio_suite_shared.system_requirements`.
That check is **warning-level only** — it never blocks.  A missing ``ffmpeg``
must not stop a user who only wants to run, say, the tag editor, so only the
compile gate keeps blocking semantics.

The core scan is pure (no GUI) and fully unit-testable; :func:`guard_or_exit`
adds the blocking-dialog behaviour used by the launchers.

Changed in 2.1.0: the plugin directory is skipped when byte-compiling: a broken
third-party plugin must not block every tool's launch.
"""

from __future__ import annotations

import compileall
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Callable

from audio_suite_shared.system_requirements import (
    SystemRequirement,
    find_missing_requirements,
    format_requirement_report,
)

logger = logging.getLogger(f"audio_suite.{__name__}")

#: Title of the blocking dialog shown when the compile gate fails.
BLOCKED_TITLE = "Audio Suite — Startup Blocked"

#: Title of the non-blocking dialog shown when a required system tool is
#: missing.  Deliberately distinct from :data:`BLOCKED_TITLE` so a user (or a
#: screenshot in a bug report) can tell a warning from a block.
WARNING_TITLE = "Audio Suite — Missing System Tool"

#: Mostly-unique extensions checked by the suite's build tooling.  Only
#: first-party ``.py`` source is *.py; ``.pyw`` launchers are checked too since
#: a broken launcher is equally fatal.
_SOURCE_SUFFIXES = (".py", ".pyw")

#: Directories that are never part of the shipped tool chain.
#:
#: ``plugins`` is excluded on purpose: a third-party plugin is not first-party
#: source, and the guard blocks the launch it is checking.  A syntactically
#: broken plugin must therefore not stop every tool in the suite from starting
#: — the plugin loader reports it as a rejected plugin (``audiosuite plugins
#: list``, ``audiosuite doctor``) and the rest of the suite keeps working.
_EXCLUDED_DIRS = {
    ".venv",
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".idea",
    ".github",
    "runtime",
    "plugins",
}


def iter_source_files(root: Path) -> list[Path]:
    """Return the sorted list of first-party source files under *root*.

    Walks *root* recursively, skipping virtual-environment and tooling caches,
    and yields only ``.py`` / ``.pyw`` files.

    Args:
        root: The suite root directory to scan.

    Returns:
        Sorted list of source file paths.
    """
    results: list[Path] = []
    for current_root, dirnames, filenames in os.walk(root):
        relative_root = Path(current_root)
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDED_DIRS]
        for name in filenames:
            if name.endswith(_SOURCE_SUFFIXES) and name != "__init__.py":
                results.append(relative_root / name)
    return sorted(results)


def find_broken_files(root: Path) -> list[Path]:
    """Return the source files under *root* that fail to byte-compile.

    Uses :func:`compileall.compile_file` to parse each module without
    executing it, catching ``SyntaxError`` / ``IndentationError`` exactly as
    an import would, but without triggering import side effects.

    Args:
        root: The suite root directory to scan.

    Returns:
        Sorted list of files that produced a syntax error.
    """
    broken: list[Path] = []
    for path in iter_source_files(root):
        if not compileall.compile_file(str(path), quiet=1, force=False):
            broken.append(path)
    return broken


def _format_report(root: Path, broken: Sequence[Path]) -> str:
    """Build a human-readable multi-line report from the broken file list."""
    lines = [
        f"Audio Suite pre-flight check failed on {len(broken)} file(s):",
        f"Suite root: {root}",
        "",
    ]
    for path in broken:
        lines.append(f"  - {path}")
    lines.extend(
        [
            "",
            "The errors above are syntax/indentation problems in the source.",
            "Fix them (or run the verification pipeline) before launching the tool.",
        ]
    )
    return "\n".join(lines)


def _emit_failure(
    report: str,
    show_dialog: Callable[[str, str], None],
    log_fn: Callable[[str], object] | None,
    exit_fn: Callable[[int], object] | None,
) -> None:
    """Log, dialog, and block for a failed pre-flight check."""
    if log_fn is not None:
        log_fn(report)
    else:
        logger.error(report)

    show_dialog(BLOCKED_TITLE, report)

    if exit_fn is not None:
        exit_fn(1)
    else:
        sys.exit(1)


def verify_suite(
    root: Path,
    show_dialog: Callable[[str, str], None],
    *,
    log_fn: Callable[[str], object] | None = None,
    exit_fn: Callable[[int], object] | None = None,
) -> bool:
    """Syntax-check the suite and, on failure, block launch with a dialog.

    Compiles every source file under *root*.  On success returns ``True`` so
    the launcher proceeds.  On failure logs the report, shows the blocking
    dialog via *show_dialog*, and calls *exit_fn* (default ``sys.exit(1)``).

    Args:
        root: The suite root directory to scan.
        show_dialog: Callable(title, message) invoked on failure.
        log_fn: Callable used to emit the report line (defaults to
            ``logger.error``).  Injectable for hermetic tests.
        exit_fn: Callable invoked with the exit code on failure (defaults to
            ``sys.exit``).

    Returns:
        ``True`` when every module parses successfully.
    """
    broken = find_broken_files(root)
    if not broken:
        logger.info(
            "Pre-flight: all %d source files parsed OK",
            len(iter_source_files(root)),
        )
        return True

    report = _format_report(root, broken)
    _emit_failure(report, show_dialog, log_fn, exit_fn)
    return False


def report_missing_requirements(
    show_dialog: Callable[[str, str], None],
    *,
    log_fn: Callable[[str], object] | None = None,
) -> list[SystemRequirement]:
    """Report any missing system tool as a **warning**, without blocking.

    This is deliberately warning-level.  ``ffmpeg`` is used by many tools and
    by none of the metadata-only ones, so a hard exit here would break a user
    whose task never touches a binary.  The message names each missing binary,
    what the suite uses it for, and the plain install command per platform, so
    the user can act on it without leaving the tool.

    Pure by contract: it takes the dialog as a parameter and never imports
    ``tkinter`` or constructs a widget, so it is callable from a headless
    context and unit-testable without a display.

    Args:
        show_dialog: Callable(title, message) invoked only when something is
            missing.
        log_fn: Callable used to emit the report line (defaults to
            ``logger.warning``).  Injectable for hermetic tests.

    Returns:
        The requirements that could not be found, in declaration order; empty
        when every declared tool is present.
    """
    missing = find_missing_requirements()
    if not missing:
        return []

    report = format_requirement_report(missing)
    if log_fn is not None:
        log_fn(report)
    else:
        logger.warning(report)

    show_dialog(WARNING_TITLE, report)
    return missing


def guard_or_exit(root: Path) -> bool:
    """Run :func:`verify_suite` with the standard GUI + exit behaviour.

    Runs the blocking compile gate first, then the warning-level system-tool
    check.  Only the compile gate can block: a missing ``ffmpeg`` is reported
    and the launcher continues.

    Args:
        root: The suite root directory to scan.

    Returns:
        ``True`` when the suite parses cleanly.
    """
    from tkinter import messagebox

    def show_dialog(title: str, message: str) -> None:
        messagebox.showerror(title, message)

    def warn_dialog(title: str, message: str) -> None:
        messagebox.showwarning(title, message)

    parsed = verify_suite(root, show_dialog)
    if not parsed:
        return parsed

    report_missing_requirements(warn_dialog)
    return parsed
