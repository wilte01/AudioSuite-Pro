"""CLI command for the Tag Editor."""

from __future__ import annotations

import json as json_mod
import sys
from pathlib import Path

import click

from audio_suite_shared.cli_base import _opt_dry_run, _opt_json, cli
from audio_suite_shared.exceptions import AudioSuiteError
from tag_editor.core.processor import (
    FIELD_LABELS,
    FieldEdit,
    TagEditorProcessor,
    summarize_results,
)


@cli.command("tag-edit")
@click.argument(
    "path",
    type=click.Path(exists=True, dir_okay=False, path_type=str),
)
@_opt_dry_run
@_opt_json
@click.option(
    "--field",
    required=True,
    type=click.Choice(list(FIELD_LABELS)),
    help="Editable tag field to write.",
)
@click.option("--value", default=None, help="New field value.")
@click.option("--clear", is_flag=True, default=False, help="Remove the field.")
def tag_edit_cli(
    path: str,
    dry_run: bool,
    json: bool,
    field: str,
    value: str | None,
    clear: bool,
) -> None:
    """Edit one common tag field in a single audio file.

    \b
    Examples:
        audiosuite tag-edit /Music/track.mp3 --field title --value "New Title"
        audiosuite tag-edit /Music/track.mp3 --field comment --clear --dry
    """
    if not clear and value is None:
        raise click.UsageError("--value is required unless --clear is set.")
    edit_value = None if clear else value
    processor = TagEditorProcessor()
    try:
        results = processor.apply_edits(
            [FieldEdit(path=Path(path), field=field, value=edit_value)],
            dry_run=dry_run,
        )
    except AudioSuiteError as exc:
        if json:
            click.echo(json_mod.dumps({"error": str(exc)}, indent=2))
        else:
            click.echo(f"  ERROR: {exc}", err=True)
        sys.exit(1)
    stats = summarize_results(results)
    result = results[0]

    payload = {
        "path": path,
        "field": field,
        "old_value": result.old_value,
        "new_value": result.new_value,
        "changed": result.changed,
        "written": result.written,
        "dry_run": dry_run,
        "error": result.error,
    }
    if json:
        click.echo(json_mod.dumps(payload, indent=2))
    else:
        mode = "Dry run" if dry_run else "Live update"
        click.echo(f"  Mode:    {mode}")
        click.echo(f"  Changed: {stats.changed}")
        click.echo(f"  Written: {stats.written}")
        click.echo(f"  Errors:  {stats.errors}")
        if result.error is not None:
            click.echo(f"  ERROR: {result.error}", err=True)

    if stats.errors:
        sys.exit(1)
