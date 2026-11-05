"""launch_failure.py — why a tool launcher refused to start, for the driver.

A ``.pyw`` tool the Master Driver runs validates its argv before it builds a
window.  When that validation refuses — the source folder no longer exists, an
option value is missing — the launcher exits 1, and everything it said went to
stderr: a stream a ``pythonw`` parent never shows.  The driver's dialog could
therefore name only the exit code (``PLAN_feature_expansion.md`` D135), and the
user was left with ``Module failed: Library Statistics Dashboard (exit code
1)`` and no way to know a folder had moved.

This module is the smallest shared channel for that one sentence.
:func:`audio_suite_shared.launcher.parse_cli_args` records the reason it
refused, keyed by the launcher's script name, and
:mod:`master_driver.runner.module_runner` reads it back when a step exits
non-zero.

Design rules:

* It is deliberately separate from :mod:`audio_suite_shared.run_outcome`: that
  note describes a run that *happened* (a caveat on a finished scan), and is
  keyed by manifest id.  This one describes a run that never started, and is
  keyed by the script name the launcher and the driver both hold — no tool
  needs to learn its manifest id to report a startup failure.
* A record never survives its launch: ``parse_cli_args`` clears it before
  parsing, and :class:`~master_driver.batch_orchestrator.BatchOrchestrator`
  clears it again before starting the step, so a stale reason cannot explain a
  later, different failure.
* Records live under ``<logs>/launch_failures/``, so they inherit the
  ``AUDIOSUITE_LOG_DIR`` override and a test run never writes into the shipped
  ``logs/`` tree.
* Recording is best-effort.  The launcher is already on its way out; a
  read-only install or a full disk must not turn a clean ``exit 1`` into a
  traceback.

Changed in 2.4.3: initial version — a refused launch explains itself
(PLAN_2026-11-03_2.4.3_structure.md D-22).
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .logging_setup import get_logs_dir

#: Namespaced like every other shared module, so its records reach the suite
#: log through the ``audio_suite`` logger hierarchy.
logger = logging.getLogger(f"audio_suite.{__name__}")

#: Directory (under the suite logs dir) holding the per-launcher records.
FAILURE_DIR_NAME = "launch_failures"

#: Longest reason kept.  The reason is quoted inside a modal dialog, so a wall
#: of usage text would size the dialog off the screen.
MAX_REASON_CHARS = 300

#: Anything that cannot appear in a file name, collapsed to one underscore.
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")


def _safe_stem(script_path: str) -> str:
    """Return ``script_path``'s file name reduced to a safe record stem.

    The record is keyed by the script's *stem* because that is the one name the
    launcher (``sys.argv[0]``) and the driver (``BatchStep.script_path``) both
    hold without sharing a manifest id.  Case is folded so a differently-cased
    invocation on a case-insensitive filesystem still finds its record.

    Args:
        script_path: Path to the launcher, as either process sees it.

    Returns:
        A lowercase token of letters, digits, ``_`` and ``-``; ``"launcher"``
        when the path carries no usable stem.
    """
    stem = Path(script_path).stem if script_path else ""
    safe = _UNSAFE.sub("_", stem).strip("_-").lower()
    return safe or "launcher"


def failure_path(script_path: str) -> Path:
    """Return the file holding ``script_path``'s launch-failure reason.

    Args:
        script_path: Path to the launcher script.

    Returns:
        The record's path, whether or not it exists.
    """
    return get_logs_dir() / FAILURE_DIR_NAME / f"{_safe_stem(script_path)}.json"


def _one_line(reason: str) -> str:
    """Collapse ``reason`` to one bounded line.

    Args:
        reason: The text the launcher wrote, possibly spanning lines.

    Returns:
        Whitespace-collapsed text of at most :data:`MAX_REASON_CHARS`
        characters, with an ASCII ellipsis when it was cut.
    """
    collapsed = " ".join(reason.split())
    if len(collapsed) <= MAX_REASON_CHARS:
        return collapsed
    return collapsed[: MAX_REASON_CHARS - 3].rstrip() + "..."


def record_launch_failure(script_path: str, reason: str) -> str:
    """Record *why* the launcher refuses to start, for the driver to show.

    The write is atomic (a temporary file replaced into position), so a driver
    reading the record can never see a half-written document.  Failure to write
    is logged and swallowed: the caller is already exiting, and the exit code
    is the contract that survives.

    Args:
        script_path: Path to the launcher script (``sys.argv[0]`` in the tool).
        reason: The reason as the tool worded it.  Blank text records nothing.

    Returns:
        The reason now stored, or ``""`` when there was nothing to store or the
        record could not be written.
    """
    cleaned = _one_line(reason)
    if not cleaned:
        # A blank reason records nothing *and* drops any earlier one: a record
        # that outlived its launch is exactly what must not explain a failure.
        clear_launch_failure(script_path)
        return ""

    path = failure_path(script_path)
    payload: dict[str, Any] = {
        "launcher": Path(script_path).name,
        "reason": cleaned,
        "recorded": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f"{path.name}.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, path)
    except OSError:
        logger.debug("Could not record the launch failure", exc_info=True)
        return ""
    return cleaned


def read_launch_failure(script_path: str) -> str:
    """Return the reason ``script_path`` last refused to start, or ``""``.

    Args:
        script_path: Path to the launcher script.

    Returns:
        The recorded reason, or ``""`` when none was recorded, the file cannot
        be read, or its content is not a record.  Never raises: this feeds a
        failure dialog, and a damaged file must not replace the real error with
        a traceback.
    """
    try:
        payload = json.loads(failure_path(script_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    reason = payload.get("reason") if isinstance(payload, dict) else None
    return _one_line(reason) if isinstance(reason, str) else ""


def clear_launch_failure(script_path: str) -> None:
    """Forget ``script_path``'s reason; safe when nothing was recorded.

    Args:
        script_path: Path to the launcher script.
    """
    try:
        failure_path(script_path).unlink()
    except OSError:
        return


__all__ = [
    "FAILURE_DIR_NAME",
    "MAX_REASON_CHARS",
    "clear_launch_failure",
    "failure_path",
    "read_launch_failure",
    "record_launch_failure",
]
