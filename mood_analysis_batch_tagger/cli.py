"""CLI command for Mood Analysis Batch Tagger."""

from __future__ import annotations

import json as _json_mod
import queue
import threading
from typing import Any

import click

from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_base import (
    _opt_dir,
    _opt_dry_run,
    _opt_json,
    _opt_parallel,
    _opt_workers,
    cli,
)


@cli.command("mood-analysis-batch")
@_opt_dir
@_opt_dry_run
@_opt_json
@_opt_parallel
@_opt_workers
@click.option(
    "--duration",
    default=90,
    type=int,
    help="Analysis duration in seconds (default 90).",
)
def mood_analysis_batch_cli(
    directory: str,
    dry_run: bool,
    json: bool,
    duration: int,
    parallel: bool,
    workers: int,
) -> None:
    """Recursively analyse and tag mood from the audio signal itself."""
    from mood_analysis_batch_tagger.core.batch_analysis_engine import run_batch

    out_queue: queue.Queue[Any] = queue.Queue()
    stop_event = threading.Event()
    with active_batch("mood_analysis_batch_tagger", "tag_edit"):
        run_batch(
            root=directory,
            out_queue=out_queue,
            stop_event=stop_event,
            live=not dry_run,
            analysis_duration=duration,
            parallel_mode=parallel,
            max_workers=workers,
        )

    tagged = 0
    skipped = 0
    errors = 0
    folders = 0
    log_path = ""

    while True:
        try:
            msg = out_queue.get(timeout=60)
        except queue.Empty:
            break
        kind = msg[0]
        if kind == "done":
            _, tagged, skipped, errors, folders, log_path = msg
            break

    result = {
        "directory": directory,
        "dry_run": dry_run,
        "duration": duration,
        "parallel": parallel,
        "workers": workers,
        "tagged": tagged,
        "skipped": skipped,
        "errors": errors,
        "folders": folders,
        "log_path": log_path,
    }

    if json:
        click.echo(_json_mod.dumps(result, indent=2))
    else:
        click.echo(
            f"  Folders scanned: {folders}\n"
            f"  Files tagged:    {tagged}\n"
            f"  Files skipped:   {skipped}\n"
            f"  Errors:          {errors}"
        )
        if log_path:
            click.echo(f"  Log: {log_path}", err=True)
