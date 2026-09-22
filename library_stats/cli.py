"""CLI command for Library Statistics Dashboard."""

from __future__ import annotations

import dataclasses
import sqlite3
import sys
import time
from typing import Any

import click

from audio_suite_shared.cli_base import _opt_dir, _opt_json, cli
from audio_suite_shared.exceptions import AudioSuiteError
from library_stats.library_cache import LibraryCache


@cli.command()
@_opt_dir
@_opt_json
@click.option(
    "--incremental/--full",
    default=False,
    help="Incremental scan using cache (only re-reads changed files).",
)
@click.option(
    "--refresh",
    is_flag=True,
    default=False,
    help="Full re-scan that rebuilds the cache from scratch.",
)
@click.option(
    "--export-csv",
    default=None,
    type=click.Path(writable=True),
    help="Export per-file metadata to CSV at this path.",
)
@click.option(
    "--export-json",
    default=None,
    type=click.Path(writable=True),
    help="Export full StatsReport as JSON at this path.",
)
@click.option(
    "--completeness",
    is_flag=True,
    default=False,
    help="Also report tag completeness (BPM, key, genre, mood, artwork, ReplayGain).",
)
@click.option(
    "--detail",
    default=None,
    type=click.Choice(
        ["bpm", "key", "genre", "mood", "tempo_marking", "album_art", "replaygain"]
    ),
    help="With --completeness, list files missing the given tag.",
)
def stats(
    directory: str,
    json: bool,
    incremental: bool,
    refresh: bool,
    export_csv: str | None,
    export_json: str | None,
    completeness: bool,
    detail: str | None,
) -> None:
    """Scan library and show aggregate tag statistics (read-only).

    By default performs a full directory walk reading every file's tags.
    Use --incremental to skip unchanged files via the SQLite cache.
    Use --refresh to rebuild the cache from scratch.

    Use --export-csv PATH to write per-file metadata as a CSV spreadsheet.
    Use --export-json PATH to write the full StatsReport as a JSON file.

    Use --completeness to additionally report what percentage of files carry
    each tag.  Add --detail <tag> to list the specific files missing a tag.
    """
    from library_stats.core.completeness import (
        analyse_completeness,
    )
    from library_stats.library_stats import export_csv as _export_csv
    from library_stats.library_stats import export_json as _export_json
    from library_stats.library_stats import scan_directory

    want_completeness = completeness or detail is not None

    use_cache = incremental or refresh
    cache: LibraryCache | None = LibraryCache() if use_cache else None

    if refresh and cache is not None:
        cache.clear_dir(directory)

    click.echo(
        "Scanning library for statistics..."
        + (" (incremental)" if incremental else "")
        + (" (full refresh)" if refresh else ""),
        err=True,
    )
    start = time.monotonic()
    try:
        report = scan_directory(
            directory,
            use_cache=use_cache,
            refresh_cache=refresh,
            cache=cache,
        )
        completeness_report = (
            analyse_completeness(directory) if want_completeness else None
        )
    except (OSError, ValueError, sqlite3.Error, AudioSuiteError) as exc:
        click.echo(f"  FATAL: {exc}", err=True)
        sys.exit(1)

    elapsed = time.monotonic() - start

    cache_info = ""
    if cache is not None:
        cached_count = cache.row_count(directory)
        cache_info = f" | {cached_count} cached"

    if json:
        import json as _json

        payload = dataclasses.asdict(report)
        if completeness_report is not None:
            payload["completeness"] = completeness_report.to_dict()
        click.echo(_json.dumps(payload, indent=2, default=str))
        return

    click.echo("")
    click.echo(f"  Total files scanned   : {report.total_files}")
    click.echo(f"  Total albums          : {report.total_albums}")
    click.echo(f"  Total artists         : {report.total_artists}")
    click.echo(f"  Unique genres         : {len(report.genre_distribution)}")
    click.echo(f"  Unique keys           : {len(report.key_distribution)}")
    click.echo(f"  Scan duration         : {elapsed:.1f}s{cache_info}")
    click.echo("")
    if report.format_breakdown:
        click.echo("  Format breakdown:")
        for ext, count in sorted(report.format_breakdown.items(), key=lambda x: -x[1]):
            click.echo(f"    {ext:>8}: {count}")
    if report.missing_data:
        click.echo("")
        click.echo("  Missing data:")
        total = report.total_files or 1
        for label, key in (
            ("BPM", "no_bpm"),
            ("Key", "no_key"),
            ("Genre", "no_genre"),
            ("Mood", "no_mood"),
            ("Tempo Marking", "no_tempo_marking"),
        ):
            count = report.missing_data.get(key, 0)
            click.echo(f"    {label:<20}: {count:>5}  ({count / total * 100:5.1f}%)")

    if completeness_report is not None:
        _echo_completeness(completeness_report, detail)

    if export_csv:
        try:
            _export_csv(report, export_csv)
            click.echo(f"\n  CSV exported to: {export_csv}", err=True)
        except (AudioSuiteError, OSError, ValueError) as exc:
            click.echo(f"  CSV export failed: {exc}", err=True)

    if export_json:
        try:
            _export_json(report, export_json)
            click.echo(f"\n  JSON exported to: {export_json}", err=True)
        except (OSError, ValueError) as exc:
            click.echo(f"  JSON export failed: {exc}", err=True)


def _echo_completeness(report: Any, detail: str | None = None) -> None:
    """Print the completeness table and, optionally, per-tag missing files."""
    from library_stats.core.completeness import TAG_FIELDS

    click.echo("")
    click.echo("  Tag Completeness:")
    click.echo(
        f"    {'Tag':<15} {'Total':>6} {'Present':>8} {'Missing':>8} {'%':>8}   Status"
    )
    for field in TAG_FIELDS:
        tc = report.tag_results[field]
        status = _completeness_status(tc.pct_complete)
        click.echo(
            f"    {tc.label:<15} {tc.total:>6} {tc.present:>8} "
            f"{tc.missing:>8} {tc.pct_complete:>7.1f}%   {status}"
        )
    click.echo(
        f"    {'Overall':<15} {'':>6} {'':>8} {'':>8} {report.overall_pct:>7.1f}%"
    )
    if report.total_files:
        click.echo(f"    {report.duration_secs:.1f}s")

    if detail is not None:
        tc = report.tag_results[detail]
        click.echo("")
        click.echo(f"  Files missing {tc.label} ({tc.missing}):")
        for path in tc.missing_files:
            click.echo(f"    {path}")


def _completeness_status(pct: float) -> str:
    """Return a green/amber/red label for a completeness percentage."""
    if pct > 80.0:
        return "complete"
    if pct >= 50.0:
        return "partial"
    return "needs work"
