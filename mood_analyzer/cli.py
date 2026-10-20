"""CLI command for Mood Analyzer.

Changed in 1.4.0: emits and locks the shared CLI JSON schema (PLAN D82).

Changed in 1.4.1: a fatal run now exits 1 instead of 0 (``finish_run``), while a
run whose only failures were per-file keeps its exit status (PLAN D92).
"""

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
    finish_run,
)


@cli.command()
@_opt_dir
@_opt_dry_run
@_opt_json
@_opt_parallel
@_opt_workers
@click.option(
    "--duration",
    default=90,
    type=int,
    help="Analysis duration in seconds (default 90).",
)
def mood_analyzer(
    directory: str,
    dry_run: bool,
    json: bool,
    duration: int,
    parallel: bool,
    workers: int,
) -> None:
    """Detect and tag mood from the audio signal itself."""
    from mood_analyzer.core.file_processor import run_analysis

    with active_batch("mood_analyzer", "tag_edit"):
        result = _run_tool(
            "Mood Analyzer",
            run_analysis,
            dir_path=directory,
            is_dry_run=dry_run,
            analysis_duration=duration,
            parallel_mode=parallel,
            max_workers=workers,
        )
    if json:
        click.echo(
            _json_mod.dumps(
                result.to_payload("mood-analyzer", dry_run=dry_run), indent=2
            )
        )
    else:
        click.echo(
            f"  Summary: {result.processed} files, "
            f"{result.skipped} skipped, {result.errors} errors "
            f"in {result.duration_secs:.1f}s"
        )
    finish_run(result)
