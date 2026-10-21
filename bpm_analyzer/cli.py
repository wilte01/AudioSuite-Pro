"""CLI command for BPM Analyzer.

Changed in 1.4.0: ``--json`` flattens the collector's tool-specific fields so
``skipped_files`` (filename, reason, onset-periodicity score) is a top-level
key next to the processed/skipped/errors counts.

Changed in 1.4.1: a fatal run now exits 1 instead of 0 (``finish_run``), while a
run whose only failures were per-file keeps its exit status (PLAN D92).

Changed in 1.4.1: ``--bpm-min``/``--bpm-max`` default to 75/175, matching the
GUI and ``BPMArgs``; the band chooses between octave-equivalent readings and no
longer overwrites a measurement, so a 60 BPM track is tagged 60 rather than
120 (PLAN D108). The text summary counts the files whose tempo landed
outside that band, and ``--json`` publishes them as ``outside_range_files``
(D109).
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
    "--bpm-min",
    default=75,
    type=int,
    help="Lower bound for choosing between octave readings (default 75).",
)
@click.option(
    "--bpm-max",
    default=175,
    type=int,
    help="Upper bound for choosing between octave readings (default 175).",
)
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
        outside = result.extra.get("outside_range_files") or []
        if outside:
            # A measured tempo outside the band was still tagged, so it is
            # neither a skip nor an error: it gets its own line, so nobody has
            # to diff the log to notice the band did not match the library.
            first = outside[0]
            low = first.get("min_bpm")
            high = first.get("max_bpm")
            has_band = low is not None and high is not None
            band = f" (band {low}-{high})" if has_band else ""
            click.echo(
                f"  Outside BPM range: {len(outside)} of {result.processed} files{band}"
            )
    finish_run(result)
