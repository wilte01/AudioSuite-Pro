"""CLI command for Album Genre Tagger.

Changed in 1.4.0: emits and locks the shared CLI JSON schema (PLAN D82).
"""

from __future__ import annotations

import json as _json
from collections.abc import Callable
from typing import Any

import click

from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_base import (
    _opt_dir,
    _opt_dry_run,
    _opt_json,
    _run_tool,
    cli,
)


def _no_op(**kwargs: Any) -> None:
    pass


def _no_op_error(msg: str) -> None:
    pass


def run_cli_analysis(
    dir_path: str,
    is_dry_run: bool = False,
    min_coverage: int = 50,
    on_progress: Callable[..., None] | None = None,
    on_complete: Callable[..., None] | None = None,
    on_error: Callable[[str], None] | None = None,
    **kwargs: Any,
) -> None:
    """Run album genre analysis with CLI progress callbacks."""
    from album_genre_tagger.core.consolidator import run_analysis

    if on_progress is None:
        on_progress = _no_op
    if on_complete is None:
        on_complete = _no_op
    if on_error is None:
        on_error = _no_op_error

    def on_phase1_progress(
        processed: int,
        total: int,
        files_with_genre: int,
        errors: int,
        display_text: str,
        log_text: str,
    ) -> None:
        on_progress(
            processed=processed,
            total=total,
            display_text=display_text,
        )

    def on_phase2_progress(display_text: str, log_text: str) -> None:
        on_progress(display_text=display_text)

    def on_coverage_fail(
        total: int,
        files_with_genre: int,
        coverage_pct: float,
        min_coverage: int,
        duration_secs: float,
        log_entries: list[Any],
    ) -> None:
        on_complete(
            total=total,
            processed=0,
            skipped=0,
            errors=0,
            duration_secs=duration_secs,
            log_entries=log_entries,
            coverage_pct=coverage_pct,
            status="coverage_failed",
        )

    original_on_complete = on_complete

    def wrapped_on_complete(
        total: int,
        files_with_genre: int,
        coverage_pct: float,
        unique_genres: list[Any],
        album_genre_string: str,
        write_count: int,
        write_errors: int,
        read_errors: int,
        duration_secs: float,
        log_entries: list[Any],
    ) -> None:
        original_on_complete(
            total=total,
            processed=total,
            skipped=0,
            errors=write_errors + read_errors,
            duration_secs=duration_secs,
            log_entries=log_entries,
            coverage_pct=coverage_pct,
            album_genre=album_genre_string,
            written=write_count,
        )

    run_analysis(
        dir_path=dir_path,
        is_dry_run=is_dry_run,
        min_coverage=min_coverage,
        on_phase1_progress=on_phase1_progress,
        on_coverage_fail=on_coverage_fail,
        on_phase2_progress=on_phase2_progress,
        on_complete=wrapped_on_complete,
        on_error=on_error,
    )


@cli.command("album-genre")
@_opt_dir
@_opt_dry_run
@_opt_json
@click.option(
    "--coverage",
    default=50,
    type=int,
    help="Minimum coverage percentage (0-100) before writing.",
)
def album_genre(directory: str, dry_run: bool, json: bool, coverage: int) -> None:
    """Consolidate album-level genre tags from custom field hierarchy."""
    with active_batch("album_genre_tagger", "tag_edit"):
        result = _run_tool(
            "Album Genre Tagger",
            run_cli_analysis,
            dir_path=directory,
            is_dry_run=dry_run,
            min_coverage=coverage,
        )
    if json:
        click.echo(
            _json.dumps(result.to_payload("album-genre", dry_run=dry_run), indent=2)
        )
    else:
        album_genre = result.extra.get("album_genre", "")
        coverage_pct = result.extra.get("coverage_pct", 0)
        status = result.extra.get("status", "")
        if status == "coverage_failed":
            click.echo(
                f"  Coverage check failed: {coverage_pct:.1f}% (required {coverage}%)"
            )
        click.echo(
            f"  Summary: {result.total} files, {result.processed} processed, "
            f"{result.errors} errors in {result.duration_secs:.1f}s"
        )
        if album_genre:
            click.echo(f"  Album genre: {album_genre}")
