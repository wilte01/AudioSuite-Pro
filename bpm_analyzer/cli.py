"""CLI command for BPM Analyzer.

Changed in 1.4.0: ``--json`` flattens the collector's tool-specific fields so
``skipped_files`` (filename, reason, onset-periodicity score) is a top-level
key next to the processed/skipped/errors counts.
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
)


@cli.command()
@_opt_dir
@_opt_dry_run
@_opt_json
@_opt_parallel
@_opt_workers
@click.option("--bpm-min", default=60, type=int, help="Minimum BPM (default 60).")
@click.option("--bpm-max", default=200, type=int, help="Maximum BPM (default 200).")
@click.option(
    "--duration",
    default=30,
    type=int,
    help="Analysis duration in seconds (default 30).",
)
def bpm(
    directory: str,
    dry_run: bool,
    json: bool,
    bpm_min: int,
    bpm_max: int,
    duration: int,
    parallel: bool,
    workers: int,
) -> None:
    """Detect and tag BPM for audio files."""
    from bpm_analyzer.core.file_processor import run_analysis

    with active_batch("bpm_analyzer", "tag_edit"):
        result = _run_tool(
            "BPM Analyzer",
            run_analysis,
            dir_path=directory,
            is_dry_run=dry_run,
            min_bpm=bpm_min,
            max_bpm=bpm_max,
            analysis_duration=duration,
            parallel_mode=parallel,
            max_workers=workers,
        )
    if json:
        # ``extra`` carries ``skipped_files`` / ``error_files``; to_payload
        # publishes them at the top level under the shared CLI schema.
        click.echo(_json_mod.dumps(result.to_payload("bpm", dry_run=dry_run), indent=2))
    else:
        click.echo(
            f"  Summary: {result.processed} files, "
            f"{result.skipped} skipped, {result.errors} errors "
            f"in {result.duration_secs:.1f}s"
        )
