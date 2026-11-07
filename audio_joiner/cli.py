"""cli.py — ``audiosuite join``: join a folder's segments into one file.

Changed in 2.5.0: new module (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E5).
"""

from __future__ import annotations

import json as _json

import click

from audio_joiner.core.join import run_join
from audio_joiner.core.models import (
    DEFAULT_CROSSFADE_MS,
    DEFAULT_GAP_MS,
    JoinSettings,
)
from audio_suite_shared.cli_base import _opt_dir, _opt_json, _run_tool, cli, finish_run


@cli.command()
@_opt_dir
@_opt_json
@click.option(
    "--order",
    default="",
    help=(
        "Comma-separated file names inside DIRECTORY, in join order. A name "
        "may itself contain a comma. Default: every supported file, sorted "
        "by name."
    ),
)
@click.option(
    "--output",
    default="",
    type=click.Path(file_okay=True, dir_okay=False),
    help="File the join is written to (default: <first segment>_joined<ext>).",
)
@click.option(
    "--gap-ms",
    default=DEFAULT_GAP_MS,
    show_default=True,
    type=click.IntRange(min=0, max=600_000),
    help="Silence inserted at every boundary, in ms.",
)
@click.option(
    "--crossfade-ms",
    default=DEFAULT_CROSSFADE_MS,
    show_default=True,
    type=click.IntRange(min=0, max=600_000),
    help="Equal-power overlap at every boundary, in ms.",
)
@click.option(
    "--copy/--no-copy",
    "copy_when_compatible",
    default=True,
    show_default=True,
    help="Stream-copy when every segment already matches the first file.",
)
@click.option(
    "--dry/--live",
    "dry_run",
    default=False,
    help="Report the plan without writing the joined file.",
)
def join(
    directory: str,
    json: bool,
    order: str,
    output: str,
    gap_ms: int,
    crossfade_ms: int,
    copy_when_compatible: bool,
    dry_run: bool,
) -> None:
    """Join the segments in DIRECTORY into one file.

    A straight join is a stream copy when every segment shares the first
    file's codec and stream parameters, so nothing is re-encoded; otherwise
    every segment is re-encoded to the first file's rate and channel count and
    the run report says so.  ``--gap-ms`` inserts silence at each boundary and
    ``--crossfade-ms`` overlaps them with an equal-power fade; a run may ask
    for one or the other, never both.  The joined file carries the first
    segment's tags.

    Use --dry to see the planned length without writing anything, and --json
    for the machine-readable summary.
    """
    if gap_ms and crossfade_ms:
        raise click.UsageError(
            "Set a crossfade or a gap, not both: they describe the same "
            "boundary two ways."
        )
    settings = JoinSettings(
        gap_ms=gap_ms,
        crossfade_ms=crossfade_ms,
        copy_when_compatible=copy_when_compatible,
    )
    failures: list[str] = []

    def _on_error(message: str) -> None:
        """Record a run that could not start, so the exit status says so."""
        failures.append(message)
        click.echo(f"  ERROR: {message}", err=True)

    result = _run_tool(
        "audio joiner",
        run_join,
        directory=directory,
        order=order,
        output=output,
        settings=settings,
        dry_run=dry_run,
        on_error=_on_error,
    )
    # A run that never started wrote nothing: it counts as the one failed item
    # so the shared exit contract (`finish_run`) reports 1, not a clean 0.
    if failures and result.errors == 0:
        result.errors = 1

    if json:
        payload = result.to_payload("join", dry_run=dry_run)
        click.echo(_json.dumps(payload, indent=2, default=str))
    else:
        duration_ms = result.extra.get("duration_ms", 0)
        minutes, rest = divmod(int(duration_ms), 60_000)
        seconds, millis = divmod(rest, 1000)
        click.echo(
            f"\n  Segments: {result.extra.get('segments', 0)}"
            f"  Length: {minutes:02d}:{seconds:02d}.{millis:03d}"
            f"  Errors: {result.errors}"
        )
        click.echo(f"  Output: {result.extra.get('output', '')}")
    finish_run(result)
