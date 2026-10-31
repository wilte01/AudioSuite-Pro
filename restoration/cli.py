"""CLI command for the Restoration (declip) tool.

Changed in 2.3.0: initial version (``PLAN_functional_backlog.md`` item F-08a).
"""

from __future__ import annotations

import json as _json_mod

import click

from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_base import (
    _opt_dir,
    _opt_dry_run,
    _opt_json,
    _run_tool,
    cli,
    finish_run,
)

from .core.declipper import DEFAULT_MAX_RUN_MS, DEFAULT_THRESHOLD


@cli.command()
@_opt_dir
@_opt_dry_run
@_opt_json
@click.option(
    "--threshold",
    default=DEFAULT_THRESHOLD,
    show_default=True,
    type=float,
    help="Fraction of a file's own peak that counts as clipped.",
)
@click.option(
    "--max-run-ms",
    default=DEFAULT_MAX_RUN_MS,
    show_default=True,
    type=int,
    help="Longest clipped plateau to reconstruct, in milliseconds.",
)
def declip(
    directory: str, dry_run: bool, json: bool, threshold: float, max_run_ms: int
) -> None:
    """Reconstruct clips: rebuild flat-topped peaks lost to a limiter or master."""
    from restoration.core.file_processor import run_declipping

    if not 0.0 < threshold <= 1.0:
        # The DSP refuses these too (AudioConfigurationError), but raising there
        # would surface as a traceback instead of Click's exit-2 usage message.
        raise click.BadParameter(
            "must be greater than 0 and at most 1", param_hint="'--threshold'"
        )
    if max_run_ms < 1:
        raise click.BadParameter("must be at least 1", param_hint="'--max-run-ms'")

    with active_batch("restoration", "declip_edit"):
        result = _run_tool(
            "Restoration (declip)",
            run_declipping,
            dir_path=directory,
            is_dry_run=dry_run,
            threshold=threshold,
            max_run_ms=max_run_ms,
        )
    if json:
        click.echo(
            _json_mod.dumps(result.to_payload("declip", dry_run=dry_run), indent=2)
        )
    else:
        succeeded = result.extra.get("succeeded", 0)
        click.echo(
            f"  Summary: {result.processed} files, {succeeded} repaired, "
            f"{result.skipped} clean, {result.errors} errors "
            f"in {result.duration_secs:.1f}s"
        )
    finish_run(result)
