"""CLI command for Album Art Sync.

Changed in 1.4.0: emits and locks the shared CLI JSON schema (PLAN D82).

Changed in 1.4.1: a fatal run now exits 1 instead of 0 (``finish_run``), while a
run whose only failures were per-file keeps its exit status (PLAN D92).
"""

from __future__ import annotations

import json as _json
import logging
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
    finish_run,
)

logger = logging.getLogger(__name__)


def run_cli_art_sync(
    dir_path: str,
    is_dry_run: bool = False,
    size: int = 800,
    purge: bool = True,
    min_dimension: int = 500,
    match_threshold: float = 0.85,
    on_progress: Callable[..., Any] | None = None,
    on_complete: Callable[..., Any] | None = None,
    on_error: Callable[..., Any] | None = None,
    **kwargs: Any,
) -> None:
    """Run album art sync with CLI progress callbacks.

    Delegates to ``resolve_and_apply()`` which handles filtering, ranking,
    and audit logging uniformly across all run modes.
    """
    from .core.pipeline import resolve_and_apply

    if on_progress is None:

        def _no_op(**_: Any) -> None:
            pass

        on_progress = _no_op
    if on_complete is None:

        def _on_complete(**_: Any) -> None:
            pass

        on_complete = _on_complete
    if on_error is None:

        def _on_error(msg: str) -> None:
            pass

        on_error = _on_error

    log_entries: list[str] = []

    def _log(display_text: str) -> None:
        log_entries.append(display_text + "\n")
        on_progress(display_text=display_text)

    with active_batch("album_art_sync", "tag_edit"):
        report = resolve_and_apply(
            directory=dir_path,
            embed_size=size,
            purge=purge,
            auto_select=True,
            dry_run=is_dry_run,
            min_art_dimension=min_dimension,
            album_match_threshold=match_threshold,
            progress_callback=on_progress,
            log_callback=_log,
        )

    on_complete(
        total=report.total_files,
        processed=report.processed,
        skipped=report.skipped,
        errors=report.errors,
        duration_secs=report.duration_secs,
        log_entries=report.log_entries,
        source=report.source or "none",
        selection_audit=report.selection_audit,
    )


@cli.command("album-art")
@_opt_dir
@click.option(
    "--embed-size", "size", default=800, type=int, help="Embedded resolution (px)"
)
@click.option("--purge/--no-purge", default=True, help="Purge hidden thumbnails")
@click.option(
    "--min-dimension",
    default=500,
    type=int,
    help="Minimum image dimension (px); smaller candidates rejected",
)
@click.option(
    "--match-threshold",
    default=0.85,
    type=float,
    help="Album name fuzzy-match threshold (0.0–1.0)",
)
@_opt_dry_run
@_opt_json
def album_art(
    directory: str,
    size: int,
    purge: bool,
    min_dimension: int,
    match_threshold: float,
    dry_run: bool,
    json: bool,
) -> None:
    """Fetch and embed album artwork from multiple sources.

    Candidates are automatically filtered by album-name fuzzy matching and
    quality-ranked by resolution.  The best match is selected without user
    interaction.
    """
    result = _run_tool(
        "Album Art Sync",
        run_cli_art_sync,
        dir_path=directory,
        is_dry_run=dry_run,
        size=size,
        purge=purge,
        min_dimension=min_dimension,
        match_threshold=match_threshold,
    )
    if json:
        click.echo(
            _json.dumps(result.to_payload("album-art", dry_run=dry_run), indent=2)
        )
    else:
        source = result.extra.get("source", "unknown")
        click.echo(
            f"  Summary: {result.processed} files, from {source}, "
            f"{result.errors} errors in {result.duration_secs:.1f}s"
        )
    finish_run(result)
