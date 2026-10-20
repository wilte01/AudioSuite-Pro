"""CLI command for the Tag Editor.

Changed in 1.4.0: emits and locks the shared CLI JSON schema (PLAN D82).
"""

from __future__ import annotations

import json as json_mod
import sys
from pathlib import Path

import click

from audio_suite_shared.cli_base import _opt_dry_run, _opt_json, cli
from audio_suite_shared.cli_schema import build_payload, error_payload
from audio_suite_shared.exceptions import AudioSuiteError
from tag_editor.core.csv_io import CsvImportPlan, build_import_plan
from tag_editor.core.processor import (
    FIELD_LABELS,
    EditResult,
    FieldEdit,
    TagEditorProcessor,
    summarize_results,
)


def _echo_error(message: str, as_json: bool, dry_run: bool = False) -> None:
    """Report a fatal error in the requested output format.

    JSON mode still emits the shared schema's core keys (with ``errors`` at 1)
    so a script has one parser for success and failure.
    """
    if as_json:
        click.echo(
            json_mod.dumps(
                error_payload("tag-edit", message, dry_run=dry_run), indent=2
            )
        )
    else:
        click.echo(f"  ERROR: {message}", err=True)


def _run_import(
    directory: str,
    csv_path: str,
    dry_run: bool,
    as_json: bool,
) -> int:
    """Import a CSV of per-file edits against a library directory.

    Args:
        directory: Library directory used to resolve relative CSV file values.
        csv_path: CSV file holding a file column plus one column per field.
        dry_run: Report planned changes without writing.
        as_json: Emit machine-readable output.

    Returns:
        Process exit code.
    """
    processor = TagEditorProcessor()
    try:
        plan = build_import_plan(csv_path, directory)
        results = processor.apply_edits(plan.edits, dry_run=dry_run)
    except AudioSuiteError as exc:
        _echo_error(str(exc), as_json, dry_run)
        return 1
    return _report_import(plan, results, csv_path, dry_run, as_json)


def _report_import(
    plan: CsvImportPlan,
    results: list[EditResult],
    csv_path: str,
    dry_run: bool,
    as_json: bool,
) -> int:
    """Print the CSV import summary and return the exit code."""
    stats = summarize_results(results)
    failures = stats.errors + len(plan.row_errors)
    if as_json:
        # One shape for both edit modes: the single-file fields are null here,
        # so a consumer reads the same keys from --csv and --field runs.
        payload = build_payload(
            "tag-edit",
            dry_run=dry_run,
            total=len(plan.edits) + len(plan.row_errors),
            processed=len(plan.edits),
            errors=failures,
            log_entries=[],
            path=None,
            field=None,
            old_value=None,
            new_value=None,
            changed=stats.changed,
            written=stats.written,
            error=None,
            csv=csv_path,
            rows_read=plan.row_count,
            edits_planned=len(plan.edits),
            unchanged=stats.unchanged,
            row_errors=plan.row_errors,
            ignored_columns=plan.ignored_columns,
        )
        click.echo(json_mod.dumps(payload, indent=2))
    else:
        mode = "Dry run" if dry_run else "Live update"
        click.echo(f"  Mode:      {mode}")
        click.echo(f"  Rows read: {plan.row_count}")
        click.echo(f"  Edits:     {len(plan.edits)}")
        click.echo(f"  Changed:   {stats.changed}")
        click.echo(f"  Written:   {stats.written}")
        click.echo(f"  Errors:    {failures}")
        for row_error in plan.row_errors:
            click.echo(f"  ERROR: {row_error}", err=True)
        for result in results:
            if result.error is not None:
                click.echo(f"  ERROR: {result.error}", err=True)
    return 1 if failures else 0


@cli.command("tag-edit")
@click.argument(
    "path",
    type=click.Path(exists=True, path_type=str),
)
@_opt_dry_run
@_opt_json
@click.option(
    "--field",
    type=click.Choice(list(FIELD_LABELS)),
    help="Editable tag field to write (single-file mode).",
)
@click.option("--value", default=None, help="New field value.")
@click.option("--clear", is_flag=True, default=False, help="Remove the field.")
@click.option(
    "--csv",
    "csv_path",
    type=click.Path(exists=True, dir_okay=False, path_type=str),
    default=None,
    help="Import a CSV of per-file edits; PATH must be a library directory.",
)
def tag_edit_cli(
    path: str,
    dry_run: bool,
    json: bool,
    field: str | None,
    value: str | None,
    clear: bool,
    csv_path: str | None,
) -> None:
    """Edit common tag fields, or import a CSV of per-file edits.

    \b
    Examples:
        audiosuite tag-edit /Music/track.mp3 --field title --value "New Title"
        audiosuite tag-edit /Music/track.mp3 --field comment --clear --dry
        audiosuite tag-edit /Music --csv /Music/edits.csv --dry
    """
    if csv_path is not None:
        if not Path(path).is_dir():
            raise click.UsageError("--csv requires PATH to be a library directory.")
        if field is not None or value is not None or clear:
            raise click.UsageError(
                "--field/--value/--clear cannot be combined with --csv."
            )
        sys.exit(_run_import(path, csv_path, dry_run, json))

    if Path(path).is_dir():
        raise click.UsageError(
            "PATH is a directory; pass --csv FILE to import a batch of edits."
        )
    if field is None:
        raise click.UsageError("--field is required unless --csv is set.")
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
        _echo_error(str(exc), json, dry_run)
        sys.exit(1)
    stats = summarize_results(results)
    result = results[0]

    payload = build_payload(
        "tag-edit",
        dry_run=dry_run,
        total=1,
        processed=1,
        errors=stats.errors,
        log_entries=[],
        path=path,
        field=field,
        old_value=result.old_value,
        new_value=result.new_value,
        changed=result.changed,
        written=result.written,
        error=result.error,
        csv=None,
        rows_read=0,
        edits_planned=1,
        unchanged=0,
        row_errors=[],
        ignored_columns=[],
    )
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
