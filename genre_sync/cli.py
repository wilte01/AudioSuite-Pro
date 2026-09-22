"""CLI command for Genre Sync."""

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


@cli.command(name="genre-sync")
@_opt_dir
@_opt_dry_run
@_opt_json
def genre_sync(directory: str, dry_run: bool, json: bool) -> None:
    """Sync genre tags from custom field hierarchy."""
    from genre_sync.core.file_processor import run_processing

    with active_batch("genre_sync", "tag_edit"):
        result = _run_tool(
            "Genre Sync",
            run_processing,
            dir_path=directory,
            is_dry_run=dry_run,
        )
    if json:
        click.echo(_json_mod.dumps(result.to_dict(), indent=2))
    else:
        updated = result.extra.get("updated", 0)
        no_genre = result.extra.get("no_genre", 0)
        click.echo(
            f"  Summary: {result.processed} files, {updated} updated, "
            f"{result.skipped} skipped, "
            f"{no_genre} no genre, {result.errors} errors "
            f"in {result.duration_secs:.1f}s"
        )
