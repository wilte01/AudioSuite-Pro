"""CLI command for File Reorganizer.

Changed in 1.4.0: emits and locks the shared CLI JSON schema (PLAN D82).

Changed in 1.4.1: a fatal run now exits 1 instead of 0 (``finish_run``), while a
run whose only failures were per-file keeps its exit status (PLAN D92).
"""

from __future__ import annotations

import json as _json_mod
from collections.abc import Callable
from typing import Any

import click

from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_base import (
    _opt_dir,
    _opt_json,
    _run_tool,
    cli,
    finish_run,
)

from .utils.config import load_settings


def run_reorganizer(
    source_dir: str,
    output_dir: str,
    action: str,
    dry_run: bool,
    specific_pattern: str,
    various_pattern: str,
    on_progress: Callable[..., None] | None = None,
    on_complete: Callable[..., None] | None = None,
    on_error: Callable[[str], None] | None = None,
    **kwargs: Any,
) -> None:
    """Run FileReorganizer with CLI progress callbacks."""
    from file_reorganizer.core.engine import FileReorganizer

    if on_progress is None:

        def on_progress(**kw: Any) -> None:
            return None

    if on_complete is None:

        def on_complete(**kw: Any) -> None:
            return None

    if on_error is None:

        def on_error(msg: str) -> None:
            return None

    reorganizer = FileReorganizer(
        specific_pattern=specific_pattern,
        various_pattern=various_pattern,
        base_dir=output_dir,
        action=action,
        dry_run=dry_run,
    )

    def _progress_callback(filename: str, stats: Any) -> None:
        on_progress(
            processed=stats.files_processed,
            total=stats.files_scanned,
            display_text=filename,
        )

    with active_batch("file_reorganizer", "file_reorg"):
        stats = reorganizer.run(source_dir, progress_callback=_progress_callback)

    on_complete(
        total=stats.files_scanned,
        processed=stats.files_processed,
        skipped=stats.files_skipped,
        errors=stats.errors,
    )


@cli.command()
@_opt_dir
@click.option(
    "--output-dir",
    required=True,
    type=click.Path(writable=True),
    help="Destination directory.",
)
@click.option(
    "--action",
    default=None,
    type=click.Choice(["copy", "move"]),
    help="Action to perform (defaults to saved config or 'copy').",
)
@click.option("--dry/--live", default=False, help="Preview only, do not copy/move.")
@_opt_json
@click.option(
    "--specific-pattern", default=None, help="Pattern for specific-artist albums."
)
@click.option(
    "--various-pattern", default=None, help="Pattern for Various Artists albums."
)
def reorganize(
    directory: str,
    output_dir: str,
    action: str | None,
    dry: bool,
    json: bool,
    specific_pattern: str | None,
    various_pattern: str | None,
) -> None:
    """Reorganise audio files into a tag-based folder hierarchy."""
    saved = load_settings()
    resolved_action = action or saved["action"]
    specific = specific_pattern or saved["specific_pattern"]
    various = various_pattern or saved["various_pattern"]

    result = _run_tool(
        "File Reorganizer",
        run_reorganizer,
        source_dir=directory,
        output_dir=output_dir,
        action=resolved_action,
        dry_run=dry,
        specific_pattern=specific,
        various_pattern=various,
    )

    if json:
        click.echo(
            _json_mod.dumps(result.to_payload("reorganize", dry_run=dry), indent=2)
        )
    else:
        click.echo(
            f"  Summary: {result.processed} files, "
            f"{result.skipped} skipped, {result.errors} errors "
            f"in {result.duration_secs:.1f}s"
        )
    finish_run(result)
