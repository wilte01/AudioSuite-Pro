"""CLI command for Lyrics Manager.

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
    _opt_parallel,
    _opt_workers,
    _run_tool,
    cli,
)

from .core.providers import get_provider_names


@cli.command()
@_opt_dir
@_opt_dry_run
@_opt_json
@_opt_parallel
@_opt_workers
@click.option(
    "--provider",
    default="lrclib",
    show_default=True,
    help=(
        "Lyric source provider. Choices: "
        + ", ".join(get_provider_names())
        + " (default lrclib)."
    ),
)
@click.option(
    "--request-timeout",
    default=10.0,
    type=float,
    show_default=True,
    help="Per-request timeout in seconds.",
)
@click.option(
    "--skip-existing/--no-skip-existing",
    default=True,
    show_default=True,
    help="Skip files that already contain lyrics.",
)
@click.option(
    "--plain-fallback/--no-plain-fallback",
    default=True,
    show_default=True,
    help="Store unsynced lyrics when no synced lyrics are available.",
)
def lyrics(
    directory: str,
    dry_run: bool,
    json: bool,
    provider: str,
    request_timeout: float,
    skip_existing: bool,
    plain_fallback: bool,
    parallel: bool,
    workers: int,
) -> None:
    """Fetch and embed lyrics for audio files in DIRECTORY.

    Files are matched to the remote lyric source by their artist and title
    tags.  Files whose tags are missing or contain "Unknown" are skipped.
    """
    from .core.file_processor import run_fetch
    from .core.providers import LyricProviderError, get_provider

    try:
        get_provider(provider)
    except LyricProviderError as exc:
        raise click.ClickException(
            f"Unknown lyric provider: '{provider}'. "
            f"Available: {', '.join(get_provider_names())}."
        ) from exc

    with active_batch("lyrics_manager", "tag_edit"):
        result = _run_tool(
            "Lyrics Manager",
            run_fetch,
            dir_path=directory,
            is_dry_run=dry_run,
            provider_name=provider,
            request_timeout=request_timeout,
            skip_existing=skip_existing,
            plain_fallback=plain_fallback,
            parallel_mode=parallel,
            max_workers=workers,
        )
    if json:
        click.echo(
            _json_mod.dumps(result.to_payload("lyrics", dry_run=dry_run), indent=2)
        )
    else:
        click.echo(
            f"  Summary: {result.processed} files, "
            f"{result.skipped} skipped, {result.errors} errors "
            f"in {result.duration_secs:.1f}s"
        )
