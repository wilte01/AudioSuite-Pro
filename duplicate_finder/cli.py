"""CLI command for the Duplicate Finder.

A live run moves the duplicates it found into the quarantine folder and records
each move in the suite's undo journal, so the command is reversible; nothing is
deleted at any point.

Changed in 2.3.0: initial version (``PLAN_functional_backlog.md`` item F-02).
"""

from __future__ import annotations

import json as _json_mod

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

from .core.models import DEFAULT_THRESHOLD, ScanSettings


@cli.command()
@_opt_dir
@_opt_dry_run
@_opt_json
@click.option(
    "--threshold",
    default=DEFAULT_THRESHOLD,
    show_default=True,
    type=float,
    help="Maximum bit-error rate for two fingerprints to count as one recording.",
)
@click.option(
    "--quarantine-dir",
    default="",
    help="Where a live run moves duplicates (default: <folder>/duplicate_quarantine).",
)
@click.option(
    "--cache",
    "cache_path",
    default="",
    help="Fingerprint cache file (default: ~/.audiosuite/duplicate_cache.db).",
)
def duplicates(
    directory: str,
    dry_run: bool,
    json: bool,
    threshold: float,
    quarantine_dir: str,
    cache_path: str,
) -> None:
    """Find duplicate recordings by fingerprint and quarantine the extra copies."""
    from duplicate_finder.core.file_processor import run_duplicate_scan

    if not 0.0 < threshold <= 1.0:
        # A bit-error rate is a fraction, so a value outside (0, 1] is a usage
        # error.  ScanSettings refuses it too, but raising there would surface
        # as a traceback instead of Click's own exit-2 message.
        raise click.BadParameter(
            "must be greater than 0 and at most 1",
            param_hint="'--threshold'",
        )
    settings = ScanSettings(threshold=threshold, quarantine_dir=quarantine_dir)
    with active_batch("duplicate_finder", "file_reorg"):
        result = _run_tool(
            "Duplicate Finder",
            run_duplicate_scan,
            dir_path=directory,
            is_dry_run=dry_run,
            settings=settings,
            cache_path=cache_path or None,
        )
    if json:
        click.echo(
            _json_mod.dumps(result.to_payload("duplicates", dry_run=dry_run), indent=2)
        )
    else:
        click.echo(
            f"  Summary: {result.total} files, {result.extra.get('groups', 0)} groups, "
            f"{result.extra.get('duplicates', 0)} duplicates, "
            f"{result.extra.get('quarantined', 0)} quarantined, "
            f"{result.skipped} without a fingerprint, "
            f"{result.errors} errors in {result.duration_secs:.1f}s"
        )
    finish_run(result)
