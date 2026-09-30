"""CLI command for Album Art Normalizer."""

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
    "--size", default=800, type=int, help="Embedded image size in pixels (default 800)."
)
def artnormalize(directory: str, dry_run: bool, json: bool, size: int) -> None:
    """Normalise embedded album artwork in MP3, FLAC, OGG, Opus, M4A, MP4, WAV,
    AIFF and AIF files."""
    from album_art_normalizer.core.file_processor import run_normalization

    target_size = (size, size)

    with active_batch("album_art_normalizer", "tag_edit"):
        result = _run_tool(
            "Album Art Normalizer",
            run_normalization,
            dir_path=directory,
            target_size=target_size,
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
