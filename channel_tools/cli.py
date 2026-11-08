"""cli.py — ``audiosuite channels``: apply a channel operation in place.

Changed in 2.5.0: new module (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E6).
"""

from __future__ import annotations

import json as _json

import click

from audio_suite_shared import channel_ops
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_base import (
    _opt_dir,
    _opt_dry_run,
    _opt_json,
    _run_tool,
    cli,
    finish_run,
)

from .core.processor import UNDO_OPERATION, run_channels


@cli.command()
@_opt_dir
@_opt_dry_run
@_opt_json
@click.option(
    "--operation",
    type=click.Choice(channel_ops.OPERATION_IDS),
    default=channel_ops.DEFAULT_OPERATION,
    show_default=True,
    help="The channel rule to apply.",
)
@click.option(
    "--width",
    "width_percent",
    type=click.FloatRange(
        min=channel_ops.MIN_WIDTH_PERCENT, max=channel_ops.MAX_WIDTH_PERCENT
    ),
    default=channel_ops.DEFAULT_WIDTH_PERCENT,
    show_default=True,
    help="Stereo width in percent: 0 mono, 100 unity, 200 double side.",
)
@click.option(
    "--source-channel",
    type=click.Choice(channel_ops.CHANNEL_SIDES),
    default="left",
    show_default=True,
    help="Channel the dual-mono operation copies to both sides.",
)
@click.option(
    "--invert",
    "invert_target",
    type=click.Choice(channel_ops.INVERT_TARGETS),
    default="both",
    show_default=True,
    help="Side the invert-phase operation negates.",
)
def channels(
    directory: str,
    dry_run: bool,
    json: bool,
    operation: str,
    width_percent: float,
    source_channel: str,
    invert_target: str,
) -> None:
    """Apply a channel operation to every audio file in DIRECTORY, in place.

    The operations are the documented channel rules: a mono downmix (the
    arithmetic mean, or the centre-preserving ``(L + R) / sqrt(2)``), dual
    mono, phase inversion, mid/side encode or decode, and a stereo-width
    control.  Each file is rewritten through the shared in-place workflow, so
    tags survive, a lossless source keeps its bit depth, a live write is
    recorded for Undo, and an operation that changes nothing leaves the file
    untouched.

    Use --dry to see which files would change without writing anything, and
    --json for the machine-readable summary.
    """
    from .core.models import ChannelSettings

    settings = ChannelSettings(
        operation=operation,
        width_percent=width_percent,
        source_channel=source_channel,
        invert_target=invert_target,
    )
    with active_batch("channel_tools", UNDO_OPERATION):
        result = _run_tool(
            "Channel Tools",
            run_channels,
            directory=directory,
            settings=settings,
            dry_run=dry_run,
        )
    if json:
        click.echo(
            _json.dumps(result.to_payload("channels", dry_run=dry_run), indent=2)
        )
    else:
        click.echo(
            f"  Summary: {result.processed} files, "
            f"{result.extra.get('succeeded', 0)} changed, "
            f"{result.skipped} unchanged, {result.errors} errors "
            f"in {result.duration_secs:.1f}s"
        )
        click.echo(f"  Rule: {settings.rule}")
    finish_run(result)
