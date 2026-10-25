"""CLI command for Tag Field Updater.

Changed in 1.4.0: emits and locks the shared CLI JSON schema (PLAN D82).
Changed in 2.1.0: ``--no-plugin-tags`` turns off the plugin system's enabled
tag processors, and the payload counts their edits separately (Sprint 7).
Changed in 2.1.4: the command exits 1 when it reports per-file errors, the
same contract ``finish_run`` applies to the ``_run_tool`` commands (PLAN D9).
"""

from __future__ import annotations

import json as _json_mod
import time

import click

from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_base import (
    _opt_dir,
    _opt_dry_run,
    _opt_json,
    cli,
    finish_batch,
)
from audio_suite_shared.cli_schema import build_payload


@cli.command("tag-update")
@_opt_dir
@_opt_dry_run
@_opt_json
@click.option(
    "--no-plugin-tags",
    is_flag=True,
    default=False,
    help="Skip tag processors contributed by enabled plugins.",
)
def tag_update_cli(
    directory: str, dry_run: bool, json: bool, no_plugin_tags: bool
) -> None:
    """Scan and update tag fields (replace bare '/' with '; ' in tag values).

    With ``--dry`` the rewrites are computed and reported but nothing is
    written: no file is saved and no undo record is created.

    \b
    Examples:
        audiosuite tag-update /Music --dry
        audiosuite tag-update /Music --live
        audiosuite tag-update /Music --no-plugin-tags
        audiosuite tag-update /Music --json
    """
    from tag_field_updater.core.processor import TagProcessor

    processor = TagProcessor(plugins=not no_plugin_tags)

    started = time.monotonic()
    with active_batch("tag_field_updater", "tag_edit"):
        processor.scan_directory(directory, dry_run=dry_run)

    stats = processor.stats

    # processed_files counts every file the scan attempted, so skipped and
    # failed files are already inside it (the shared schema's rule).
    payload = build_payload(
        "tag-update",
        dry_run=dry_run,
        total=stats.processed_files,
        processed=stats.processed_files,
        skipped=stats.skipped_files,
        errors=stats.error_files,
        duration_secs=time.monotonic() - started,
        log_entries=[],
        directory=directory,
        updated=stats.updated_files,
        plugin_updates=processor.plugin_changes,
        plugin_errors=processor.plugin_errors,
    )

    if json:
        click.echo(_json_mod.dumps(payload, indent=2))
    else:
        updated_label = "would update" if dry_run else "updated"
        click.echo(
            f"  Files processed: {stats.processed_files}\n"
            f"  Files {updated_label}: {stats.updated_files}\n"
            f"  Files skipped:   {stats.skipped_files}\n"
            f"  Errors:          {stats.error_files}"
        )
    # The payload's ``errors`` is what the status reports; a plugin failure is
    # counted in ``plugin_errors`` and is never fatal by contract.
    finish_batch(stats.error_files)
