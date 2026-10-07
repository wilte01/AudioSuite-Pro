"""CLI command for Audio Normalizer."""

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
from audio_suite_shared.cli_dataclasses import validate_target_lufs


def _validate_lufs(ctx: click.Context, param: click.Parameter, value: float) -> float:
    """Reject a --target-lufs that is not a permitted preset (M4)."""
    errors = validate_target_lufs(value)
    if errors:
        raise click.BadParameter(errors[0])
    return value


@cli.command()
@_opt_dir
@_opt_dry_run
@_opt_json
@click.option(
    "--target-lufs",
    default=-14.0,
    type=float,
    callback=_validate_lufs,
    help="Target LUFS (default -14; one of -12, -14, -16, -18, -23).",
)
@click.option(
    "--tolerance", default=0.5, type=float, help="Tolerance in LUFS (default 0.5)."
)
@click.option(
    "--mode",
    default="normalise",
    type=click.Choice(["normalise", "lossless"], case_sensitive=False),
    help=(
        "normalise: re-encode via FFmpeg loudnorm; "
        "lossless: adjust MP3 global_gain in-place (non-MP3 falls back to normalise)."
    ),
)
def normalise(
    directory: str,
    dry_run: bool,
    json: bool,
    target_lufs: float,
    tolerance: float,
    mode: str,
) -> None:
    """Normalise audio loudness to target LUFS."""
    from audio_normalizer.core.file_processor import run_parallel_process

    with active_batch("audio_normalizer", "tag_edit"):
        result = _run_tool(
            "Audio Normalizer",
            run_parallel_process,
            dir_path=directory,
            target_lufs=target_lufs,
            tolerance=tolerance,
            normalization_mode=mode.lower(),
            is_dry_run=dry_run,
        )
    if json:
        click.echo(_json_mod.dumps(result.to_dict(), indent=2))
    else:
        click.echo(
            f"  Summary: {result.processed} files, "
            f"{result.skipped} skipped, {result.errors} errors "
            f"in {result.duration_secs:.1f}s"
        )
