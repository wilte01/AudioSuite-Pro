"""CLI command for Tag Field Updater."""

from __future__ import annotations

import json as _json_mod

import click

from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_base import (
    _opt_dir,
    _opt_dry_run,
    _opt_json,
    cli,
)


@cli.command("tag-update")
@_opt_dir
@_opt_dry_run
@_opt_json
def tag_update_cli(directory: str, dry_run: bool, json: bool) -> None:
    """Scan and update tag fields (replace bare '/' with '; ' in tag values).

    With ``--dry`` the rewrites are computed and reported but nothing is
    written: no file is saved and no undo record is created.

    \b
    Examples:
        audiosuite tag-update /Music --dry
        audiosuite tag-update /Music --live
        audiosuite tag-update /Music --json
    """
    from tag_field_updater.core.processor import TagProcessor

    processor = TagProcessor()

    with active_batch("tag_field_updater", "tag_edit"):
        processor.scan_directory(directory, dry_run=dry_run)

    stats = processor.stats

    result_data = {
        "directory": directory,
        "dry_run": dry_run,
        "processed": stats.processed_files,
        "updated": stats.updated_files,
        "skipped": stats.skipped_files,
        "errors": stats.error_files,
    }

    if json:
        click.echo(_json_mod.dumps(result_data, indent=2))
    else:
        updated_label = "would update" if dry_run else "updated"
        click.echo(
            f"  Files processed: {stats.processed_files}\n"
            f"  Files {updated_label}: {stats.updated_files}\n"
            f"  Files skipped:   {stats.skipped_files}\n"
            f"  Errors:          {stats.error_files}"
        )
