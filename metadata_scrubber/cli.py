"""CLI command for Metadata Scrubber.

Changed in 1.4.0: emits and locks the shared CLI JSON schema (PLAN D82).
"""

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
@click.option("--preserve-lyrics/--no-preserve-lyrics", default=True)
@click.option("--preserve-album-artist/--no-preserve-album-artist", default=True)
@click.option("--preserve-embedded-art/--no-preserve-embedded-art", default=True)
def scrub(
    directory: str,
    dry_run: bool,
    json: bool,
    preserve_lyrics: bool,
    preserve_album_artist: bool,
    preserve_embedded_art: bool,
) -> None:
    """Scrub metadata from MP3 files."""
    from metadata_scrubber.core.scrubber import run_scrubbing

    preserve_list: list[str] = []
    if preserve_lyrics:
        preserve_list.append("USLT")
    if preserve_album_artist:
        preserve_list.append("TPE2")
    if preserve_embedded_art:
        preserve_list.append("APIC")

    with active_batch("metadata_scrubber", "tag_edit"):
        result = _run_tool(
            "Metadata Scrubber",
            run_scrubbing,
            dir_path=directory,
            is_dry_run=dry_run,
            preserve_list=preserve_list,
            preserve_lyrics=preserve_lyrics,
            preserve_album_artist=preserve_album_artist,
            preserve_embedded_art=preserve_embedded_art,
        )
    if json:
        click.echo(
            _json_mod.dumps(result.to_payload("scrub", dry_run=dry_run), indent=2)
        )
    else:
        click.echo(
            f"  Summary: {result.processed} files, "
            f"{result.skipped} skipped, {result.errors} errors "
            f"in {result.duration_secs:.1f}s"
        )
