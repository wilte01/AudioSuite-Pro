"""CLI command for ReplayGain Analyzer."""

from __future__ import annotations

import json as _json_mod
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


@cli.command()
@_opt_dir
@_opt_dry_run
@_opt_json
@click.option(
    "--target-lufs", default=-14.0, type=float, help="Target LUFS (default -14)."
)
@click.option(
    "--apply-gain/--no-apply-gain",
    default=False,
    help="Bake the track gain into MP3 files losslessly after tagging.",
)
def replaygain(
    directory: str,
    dry_run: bool,
    json: bool,
    target_lufs: float,
    apply_gain: bool,
) -> None:
    """Measure and write ReplayGain tags."""
    from replaygain_analyzer.core.file_processor import run_analysis

    def on_folder_complete(**kw: Any) -> None:
        click.echo(f"  Folder done: {kw.get('folder_path', '?')}", err=True)

    with active_batch("replaygain_analyzer", "tag_edit"):
        result = _run_tool(
            "ReplayGain Analyzer",
            run_analysis,
            dir_path=directory,
            target_lufs=target_lufs,
            is_dry_run=dry_run,
            apply_lossless_gain=apply_gain,
            on_folder_complete=on_folder_complete,
        )
    if json:
        click.echo(_json_mod.dumps(result.to_dict(), indent=2))
    else:
        click.echo(
            f"  Summary: {result.processed} files, "
            f"{result.errors} errors in {result.duration_secs:.1f}s"
        )
