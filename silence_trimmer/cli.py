"""CLI command for Silence Trimmer."""

from __future__ import annotations

import json as _json_mod

import click

from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_base import (
    _opt_dir,
    _opt_dry_run,
    _opt_json,
    _opt_parallel,
    _opt_workers,
    _run_tool,
    cli,
)


@cli.command(name="silence-trim")
@_opt_dir
@_opt_dry_run
@_opt_json
@_opt_parallel
@_opt_workers
@click.option(
    "--threshold",
    default=-50,
    type=int,
    help="Silence threshold in dBFS (default -50).",
)
@click.option("--fade/--no-fade", default=False, help="Apply fade in/out.")
@click.option("--fade-in", default=25, type=int, help="Fade-in ms (default 25).")
@click.option("--fade-out", default=25, type=int, help="Fade-out ms (default 25).")
def silence_trim(
    directory: str,
    dry_run: bool,
    json: bool,
    threshold: int,
    fade: bool,
    fade_in: int,
    fade_out: int,
    parallel: bool,
    workers: int,
) -> None:
    """Trim silence from audio files."""
    from silence_trimmer.core.file_processor import run_trimming

    with active_batch("silence_trimmer", "tag_edit"):
        result = _run_tool(
            "Silence Trimmer",
            run_trimming,
            dir_path=directory,
            is_dry_run=dry_run,
            threshold=threshold,
            apply_fade=fade,
            fade_in_ms=fade_in,
            fade_out_ms=fade_out,
            parallel_mode=parallel,
            max_workers=workers,
        )
    if json:
        click.echo(_json_mod.dumps(result.to_dict(), indent=2))
    else:
        click.echo(
            f"  Summary: {result.processed} files, "
            f"{result.skipped} skipped, {result.errors} errors "
            f"in {result.duration_secs:.1f}s"
        )
