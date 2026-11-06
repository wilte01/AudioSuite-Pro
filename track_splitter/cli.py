"""cli.py — ``audiosuite split``: split recordings at their silent gaps.

Changed in 2.5.0: new module (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E4).
"""

from __future__ import annotations

import json as _json

import click

from audio_suite_shared.cli_base import _opt_dir, _opt_json, _run_tool, cli, finish_run
from track_splitter.core.models import (
    BOUNDARY_RULES,
    DEFAULT_BOUNDARY,
    DEFAULT_NAMING,
    SplitSettings,
)
from track_splitter.core.splitter import run_split


@cli.command()
@_opt_dir
@_opt_json
@click.option(
    "--output-dir",
    default=None,
    type=click.Path(file_okay=False),
    help="Folder the tracks are written to (default: <directory>/split).",
)
@click.option(
    "--min-silence",
    default=700,
    show_default=True,
    type=click.IntRange(1, 600_000),
    help="Shortest silent run treated as a track boundary, in ms.",
)
@click.option(
    "--silence-db",
    default=-45.0,
    show_default=True,
    type=click.FloatRange(max=0.0, max_open=True),
    help="Level at or below which audio counts as silence, in dBFS.",
)
@click.option(
    "--min-track",
    default=5000,
    show_default=True,
    type=click.IntRange(1, 3_600_000),
    help="Shortest track kept; a shorter fragment merges into its neighbour.",
)
@click.option(
    "--boundary",
    type=click.Choice(list(BOUNDARY_RULES)),
    default=DEFAULT_BOUNDARY,
    show_default=True,
    help="Where inside a silent run the cut lands.",
)
@click.option(
    "--naming",
    default=DEFAULT_NAMING,
    show_default=True,
    help="Output filename pattern ({track}, {title}, {album}, {artist}).",
)
@click.option(
    "--cue/--no-cue",
    "write_cue",
    default=True,
    show_default=True,
    help="Write a CUE sheet describing the source image's track starts.",
)
@click.option(
    "--dry/--live",
    "dry_run",
    default=False,
    help="Plan the tracks and report them without writing any audio.",
)
def split(
    directory: str,
    json: bool,
    output_dir: str | None,
    min_silence: int,
    silence_db: float,
    min_track: int,
    boundary: str,
    naming: str,
    write_cue: bool,
    dry_run: bool,
) -> None:
    """Split every recording in DIRECTORY at its detected silent gaps.

    The gaps come from FFmpeg's own ``silencedetect`` filter, so
    ``--silence-db`` is a level relative to full scale and ``--min-silence`` a
    minimum run length.  Each track is cut sample-accurately by re-encoding;
    ``--boundary`` chooses whether a gap's silence stays with the track before
    it (``end``), the one after it (``start``), or is halved (``midpoint``).

    Use --dry to see the plan without writing anything, and --json for the
    machine-readable summary.
    """
    settings = SplitSettings(
        min_silence_ms=min_silence,
        silence_db=silence_db,
        min_track_ms=min_track,
        boundary=boundary,
        naming_pattern=naming,
        write_cue=write_cue,
    )
    result = _run_tool(
        "track splitter",
        run_split,
        directory=directory,
        output_dir=output_dir,
        settings=settings,
        dry_run=dry_run,
    )

    if json:
        payload = result.to_payload("split", dry_run=dry_run)
        click.echo(_json.dumps(payload, indent=2, default=str))
    else:
        click.echo(
            f"\n  Files: {result.total}  Tracks: {result.extra.get('tracks', 0)}"
            f"  Written: {result.extra.get('files_written', 0)}"
            f"  Errors: {result.errors}"
        )
        click.echo(f"  Output: {result.extra.get('output_dir', '')}")
    finish_run(result)
