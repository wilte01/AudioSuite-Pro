"""
launcher.py — Shared CLI argument parsing for .pyw entry points.

Each standalone tool's ``*.pyw`` calls ``parse_cli_args(tool_parse)`` to parse
the command-line arguments passed by the Master Driver (or a direct invocation)
before the Tk root is created.  The *tool_parse* callable reads ``sys.argv``
and returns a typed args dataclass.

Changed in 2.4.3: a refused launch now explains itself.  The tool writes its
reason to stderr, which a ``pythonw`` parent never shows, so that text is
captured here, written to the tool's log, and recorded through
:mod:`audio_suite_shared.launch_failure` for the Master Driver's failure dialog
— which could previously say only ``Module failed: <name> (exit code 1)``
(PLAN_2026-11-03_2.4.3_structure.md D-22).
"""

from __future__ import annotations

import contextlib
import io
import logging
import sys
from typing import Any, Callable

from audio_suite_shared.cli_dataclasses import CLIValidationError
from audio_suite_shared.launch_failure import (
    clear_launch_failure,
    record_launch_failure,
)

logger = logging.getLogger(f"audio_suite.{__name__}")


def _launcher_name() -> str:
    """Return the launcher's script path, or ``""`` when argv carries none."""
    return sys.argv[0] if sys.argv else ""


def _replay(text: str) -> None:
    """Re-emit captured stderr so a console launch still shows the message.

    Args:
        text: Everything the tool wrote to stderr while parsing.
    """
    if not text:
        return
    stream = sys.stderr
    if stream is None:
        return
    try:
        stream.write(text)
    except (OSError, ValueError):
        logger.debug("Could not re-emit the launcher's message", exc_info=True)


def parse_cli_args(tool_parse: Callable[..., Any]) -> Any:
    """Parse CLI arguments using the given *tool_parse* function.

    *tool_parse* is typically a module's ``cli_args.parse()`` function that
    reads ``sys.argv``, validates the values, and returns a typed args
    dataclass (e.g. ``ArtArgs``, ``BpmArgs``).

    Its stderr is captured for the duration of the parse so the reason a launch
    is refused survives: the Master Driver shows its own dialog and never the
    child's stderr, and a GUI tool has no console at all.

    If validation raises ``SystemExit`` (e.g. invalid flags), what the tool
    wrote is logged, recorded for the driver, and the process exits with code
    1.  ``CLIValidationError`` (validation failures reported as a message rather
    than printed by the tool itself) is recorded the same way.

    Args:
        tool_parse: The tool's argv parser.

    Returns:
        Whatever *tool_parse* returned, untouched.

    Raises:
        SystemExit: With code 1 when parsing refuses the arguments.
    """
    script = _launcher_name()
    clear_launch_failure(script)

    captured = io.StringIO()
    try:
        with contextlib.redirect_stderr(captured):
            parsed = tool_parse()
    except SystemExit as exc:
        text = captured.getvalue()
        reason = " ".join(text.split())
        if reason:
            logger.error("CLI argument parsing failed: %s - %s", exc, reason)
        else:
            logger.error("CLI argument parsing failed: %s", exc)
        record_launch_failure(script, reason)
        _replay(text)
        sys.exit(1)
    except CLIValidationError as exc:
        logger.error("CLI validation error: %s", exc)
        record_launch_failure(script, str(exc))
        _replay(captured.getvalue())
        sys.exit(1)

    _replay(captured.getvalue())
    return parsed
