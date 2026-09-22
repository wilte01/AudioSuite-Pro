"""
launcher.py — Shared CLI argument parsing for .pyw entry points.

Each standalone tool's ``*.pyw`` calls ``parse_cli_args(tool_parse)`` to parse
the command-line arguments passed by the Master Driver (or a direct invocation)
before the Tk root is created.  The *tool_parse* callable reads ``sys.argv``
and returns a typed args dataclass.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Callable

from audio_suite_shared.cli_dataclasses import CLIValidationError

logger = logging.getLogger(__name__)


def parse_cli_args(tool_parse: Callable[..., Any]) -> Any:
    """Parse CLI arguments using the given *tool_parse* function.

    *tool_parse* is typically a module's ``cli_args.parse()`` function that
    reads ``sys.argv``, validates the values, and returns a typed args
    dataclass (e.g. ``ArtArgs``, ``BpmArgs``).

    If validation raises ``SystemExit`` (e.g. invalid flags), the error is
    logged and the process exits with code 1.  If it raises
    ``CLIValidationError`` (validation failures reported as a message rather
    than printed by the tool itself), the reason is written to stderr,
    logged, and the process exits with code 1.
    """
    try:
        return tool_parse()
    except SystemExit as exc:
        logger.error("CLI argument parsing failed: %s", exc)
        sys.exit(1)
    except CLIValidationError as exc:
        logger.error("CLI validation error: %s", exc)
        sys.exit(1)
