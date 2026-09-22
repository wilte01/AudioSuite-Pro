"""cli_base.py — Shared CLI infrastructure for audiosuite click commands.

Houses the click Group, shared options, the _Result collector, and the
_run_tool helper that every tool CLI handler uses.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from queue import Queue
from typing import Any, Callable

import click

logger = logging.getLogger(__name__)


# ── tkinter-free shims ────────────────────────────────────────────────────


class _NullStringVar:
    """Drop-in for tk.StringVar that discards all values."""

    def set(self, value: Any) -> None:
        pass

    def get(self) -> str:
        return ""


def _make_slot_vars(n: int = 4) -> list[_NullStringVar]:
    return [_NullStringVar() for _ in range(n)]


def _make_slot_queue(n: int = 4) -> Queue[Any]:
    q: Queue[Any] = Queue()
    for i in range(n):
        q.put(i)
    return q


# ── Result collector ──────────────────────────────────────────────────────


@dataclass
class _Result:
    """Collects the on_complete summary from a tool run."""

    total: int = 0
    processed: int = 0
    skipped: int = 0
    errors: int = 0
    duration_secs: float = 0.0
    log_entries: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["duration_str"] = f"{self.duration_secs:.1f}s"
        return d


# ── Run helper ────────────────────────────────────────────────────────────


def _run_tool(
    tool_name: str,
    run_fn: Callable[..., None],
    **kwargs: Any,
) -> _Result:
    """Execute a tool's run_* function with terminal callbacks."""
    result = _Result()
    slot_vars = _make_slot_vars()
    slot_queue = _make_slot_queue()
    error_msg: list[str] = []

    def on_progress(**cb_kwargs: Any) -> None:
        processed = cb_kwargs.get("processed", 0)
        total = cb_kwargs.get("total", 0)
        display = cb_kwargs.get("display_text", "")
        if display:
            click.echo(f"  {display}", err=True)
        elif total:
            click.echo(f"  [{processed}/{total}]", err=True)

    def on_complete(**cb_kwargs: Any) -> None:
        result.total = cb_kwargs.get("total", 0)
        result.processed = cb_kwargs.get("processed", 0)
        result.skipped = cb_kwargs.get("skipped", 0)
        result.errors = cb_kwargs.get("errors", 0)
        result.duration_secs = cb_kwargs.get("duration_secs", 0.0)
        result.log_entries = cb_kwargs.get("log_entries", [])
        for k, v in cb_kwargs.items():
            if k not in (
                "total",
                "processed",
                "skipped",
                "errors",
                "duration_secs",
                "log_entries",
            ):
                result.extra[k] = v

    def on_error(msg: str) -> None:
        error_msg.append(msg)
        click.echo(f"  ERROR: {msg}", err=True)

    kwargs.setdefault("slot_vars", slot_vars)
    kwargs.setdefault("slot_queue", slot_queue)
    kwargs.setdefault("on_progress", on_progress)
    kwargs.setdefault("on_complete", on_complete)
    kwargs.setdefault("on_error", on_error)

    click.echo(f"Starting {tool_name}...", err=True)
    start = time.monotonic()
    try:
        run_fn(**kwargs)
    except Exception as exc:
        logger.error("FATAL error in %s: %s", tool_name, exc, exc_info=True)
        click.echo(f"  FATAL: {exc}", err=True)
        result.errors = -1
        result.duration_secs = time.monotonic() - start
        return result

    result.duration_secs = time.monotonic() - start
    if error_msg:
        click.echo(f"Finished with errors: {', '.join(error_msg)}", err=True)
    else:
        click.echo(f"Finished in {result.duration_secs:.1f}s.", err=True)
    return result


# ── Shared CLI options ────────────────────────────────────────────────────


_opt_dry_run = click.option(
    "--dry/--live", "dry_run", default=False, help="Analyse only, do not write tags."
)
_opt_json = click.option("--json/--text", default=False, help="Output results as JSON.")
_opt_parallel = click.option(
    "--parallel/--no-parallel",
    default=False,
    help="Use process-level parallelism for CPU-bound stages (bypasses GIL).",
)
_opt_workers = click.option(
    "--workers",
    default=None,
    type=int,
    help="Number of parallel workers (default: 4).",
)
_opt_dir = click.argument("directory", type=click.Path(exists=True, file_okay=False))


@click.group()
@click.option(
    "--log-level",
    default="WARNING",
    help="Logging level (DEBUG, INFO, WARNING, ERROR).",
)
@click.version_option(prog_name="audiosuite", package_name="audiosuite-pro")
def cli(log_level: str) -> None:
    """AudioSuite-Pro — headless audio processing toolkit."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.WARNING),
        format="%(levelname)s [%(name)s] %(message)s",
    )
