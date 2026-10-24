"""CLI command for Library Statistics Dashboard.

Changed in 1.3.0: completeness covers the five primary fields (title, artist,
album, track number, year), each completeness run records a trend snapshot in
``LibraryCache``, and ``--trend`` / ``--history-limit`` / ``--no-history``
expose the recorded series (PLAN D41).

Changed in 1.4.0: emits and locks the shared CLI JSON schema (PLAN D82).
Changed in 1.4.1: a fatal scan failure raises ``RunFailure`` so ``--json``
publishes the schema's error document instead of an empty stdout, and still
exits 1 (PLAN D91).
Changed in 2.1.0: ``--no-plugin-analysis`` keeps the plugin system's analysis
contributions out of the report, and ``--json`` publishes their metrics under
``plugin_analysis`` / ``plugin_analysis_errors`` (Sprint 7).
"""

from __future__ import annotations

import dataclasses
import sqlite3
import time
from typing import Any

import click

from audio_suite_shared.cli_base import RunFailure, _opt_dir, _opt_json, cli
from audio_suite_shared.cli_schema import build_payload
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
        [
            "title",
            "artist",
            "album",
            "track_number",
            "year",
            "bpm",
            "key",
            "genre",
            "mood",
            "tempo_marking",
            "album_art",
            "replaygain",
        ]
    ),
    help="With --completeness, list files missing the given tag.",
)
@click.option(
    "--trend",
    is_flag=True,
    default=False,
    help="Show the recorded completeness trend for this directory.",
)
@click.option(
    "--history-limit",
    default=12,
    show_default=True,
    type=click.IntRange(1, 100),
    help="Snapshots to show with --trend.",
)
@click.option(
    "--no-history",
    is_flag=True,
    default=False,
    help="Do not record this run's completeness snapshot.",
)
@click.option(
    "--no-plugin-analysis",
    is_flag=True,
    default=False,
    help="Skip analysis contributions from enabled plugins.",
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
    trend: bool,
    history_limit: int,
    no_history: bool,
    no_plugin_analysis: bool,
) -> None:
    """Scan library and show aggregate tag statistics (read-only).

    By default performs a full directory walk reading every file's tags.
    Use --incremental to skip unchanged files via the SQLite cache.
    Use --refresh to rebuild the cache from scratch.

    Use --export-csv PATH to write per-file metadata as a CSV spreadsheet.
    Use --export-json PATH to write the full StatsReport as a JSON file.

    Use --completeness to additionally report what percentage of files carry
    each tag.  Add --detail <tag> to list the specific files missing a tag.
    Each completeness run records a snapshot (used by --trend), unless
    --no-history is given or --incremental/--refresh already skips no work;
    --trend prints the newest --history-limit snapshots for this directory.
    """
    from library_stats.core.completeness import (
        analyse_completeness,
    )
    from library_stats.library_stats import export_csv as _export_csv
    from library_stats.library_stats import export_json as _export_json
    from library_stats.library_stats import scan_directory

    want_completeness = completeness or detail is not None or trend

    use_cache = incremental or refresh
    # History needs the cache even without --incremental: reading a trend is
    # enough reason to open it, and `--no-history` keeps a plain completeness
    # run free of writes.
    needs_cache = use_cache or (want_completeness and (not no_history or trend))
    cache: LibraryCache | None = LibraryCache() if needs_cache else None

    if refresh and cache is not None:
        cache.clear_dir(directory)

    click.echo(
        "Scanning library for statistics..."
        + (" (incremental)" if incremental else "")
        + (" (full refresh)" if refresh else ""),
        err=True,
    )
    start = time.monotonic()
    cache_info = ""
    try:
        report = scan_directory(
            directory,
            use_cache=use_cache,
            refresh_cache=refresh,
            cache=cache,
            plugins=not no_plugin_analysis,
        )
        completeness_report = (
            analyse_completeness(directory) if want_completeness else None
        )
        history: list[dict[str, Any]] = []
        if completeness_report is not None and cache is not None:
            if not no_history:
                try:
                    cache.record_completeness_snapshot(completeness_report)
                except sqlite3.Error as exc:
                    click.echo(
                        f"  Warning: completeness history not recorded: {exc}",
                        err=True,
                    )
            if trend:
                history = cache.completeness_history(directory, limit=history_limit)
        elapsed = time.monotonic() - start
        if cache is not None and use_cache:
            cache_info = f" | {cache.row_count(directory)} cached"
    except (OSError, ValueError, sqlite3.Error, AudioSuiteError) as exc:
        # Before S5-1 this echoed FATAL and called ``sys.exit(1)``, so a
        # ``--json`` run failed with an empty stdout.  The group handler turns
        # the raise into the schema's error document and keeps exit 1, and the
        # ``FATAL:`` wording survives on stderr (PLAN D91).
        raise RunFailure(f"FATAL: {exc}") from exc
    finally:
        # The CLI owns the cache it created: close it or its SQLite
        # connection stays open for the lifetime of the process.
        if cache is not None:
            cache.close()

    if json:
        import json as _json

        report_fields = dataclasses.asdict(report)
        # The report's duration is the library's audio length, not the run's
        # wall-clock time; publish it under the distinct library_* names so
        # the shared duration_secs keeps one meaning in every payload.
        library_secs = float(report_fields.pop("duration_secs"))
        payload = build_payload(
            "stats",
            dry_run=False,
            total=report.total_files,
            processed=report.total_files,
            duration_secs=elapsed,
            log_entries=[],
            library_duration_secs=library_secs,
            library_duration_str=f"{library_secs:.1f}s",
            **report_fields,
        )
        if completeness_report is not None:
            payload["completeness"] = completeness_report.to_dict()
        if trend:
            payload["trend"] = history
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

    if trend:
        _echo_trend(history)

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


def _echo_trend(history: list[dict[str, Any]]) -> None:
    """Print the recorded completeness trend, oldest first."""
    click.echo("")
    if not history:
        click.echo(
            "  Completeness Trend: no snapshots recorded yet for this directory."
        )
        return
    click.echo(f"  Completeness Trend (last {len(history)} scans):")
    for snapshot in history:
        recorded = str(snapshot.get("recorded_at", ""))[:19]
        click.echo(
            f"    {recorded:<19} {int(snapshot.get('total_files', 0)):>6} files"
            f"   {float(snapshot.get('overall_pct', 0.0)):>6.1f}% complete"
        )


def _completeness_status(pct: float) -> str:
    """Return a green/amber/red label for a completeness percentage."""
    if pct > 80.0:
        return "complete"
    if pct >= 50.0:
        return "partial"
    return "needs work"
