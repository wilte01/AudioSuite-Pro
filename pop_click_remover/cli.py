"""CLI command for Pop/Click Remover.

Changed in 1.4.0: emits and locks the shared CLI JSON schema (PLAN D82).
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
)


@cli.command()
@_opt_dir
@_opt_dry_run
@_opt_json
@click.option(
    "--sensitivity",
    default=0.25,
    type=float,
    help="Click detection sensitivity (default 0.25).",
)
@click.option(
    "--max-width", default=5, type=int, help="Max click width in ms (default 5)."
)
def declick(
    directory: str, dry_run: bool, json: bool, sensitivity: float, max_width: int
) -> None:
    """Remove pops and clicks from audio."""
    from pop_click_remover.core.file_processor import run_declicking

    with active_batch("pop_click_remover", "tag_edit"):
        result = _run_tool(
            "Pop/Click Remover",
            run_declicking,
            dir_path=directory,
            is_dry_run=dry_run,
            sensitivity=sensitivity,
            max_width=max_width,
        )
    if json:
        click.echo(
            _json_mod.dumps(result.to_payload("declick", dry_run=dry_run), indent=2)
        )
    else:
        succeeded = result.extra.get("succeeded", 0)
        click.echo(
            f"  Summary: {result.processed} files, {succeeded} fixed, "
            f"{result.skipped} clean, "
            f"{result.errors} errors in {result.duration_secs:.1f}s"
        )
