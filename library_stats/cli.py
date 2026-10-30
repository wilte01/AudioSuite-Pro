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
Changed in 2.2.0: ``--export {m3u,csv,html}`` adds the playlist/HTML export
surface, with ``--export-columns`` and ``--camelot`` (functional backlog
F-05/F-06).  The export runs before the ``--json`` branch so the two are not
mutually exclusive.
"""

from __future__ import annotations

import dataclasses
import os
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
@click.option(
    "--export",
    "export_format",
    type=click.Choice(["m3u", "csv", "html"]),
    default=None,
    help="Export the scan as a playlist (m3u), a column-aware CSV, or HTML.",
)
@click.option(
    "--export-path",
    default=None,
    type=click.Path(writable=True),
    help="Destination for --export; defaults to <folder>_library.<ext> in it.",
)
@click.option(
    "--export-columns",
    default=None,
    help="Comma-separated columns for --export csv/html (path,artist,title,...).",
)
@click.option(
    "--camelot",
    is_flag=True,
    default=False,
    help="Add a Camelot key column to the CSV/HTML export.",
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
    export_format: str | None,
    export_path: str | None,
    export_columns: str | None,
    camelot: bool,
) -> None:
    """Scan library and show aggregate tag statistics (read-only).

    By default performs a full directory walk reading every file's tags.
    Use --incremental to skip unchanged files via the SQLite cache.
    Use --refresh to rebuild the cache from scratch.

    Use --export-csv PATH to write per-file metadata as a CSV spreadsheet.
    Use --export-json PATH to write the full StatsReport as a JSON file.

    Use --export {m3u,csv,html} for the playlist/report export surface: an
    extended M3U a player opens, the same column-aware CSV, or a
    self-contained HTML page.  --export-columns picks the columns and
    --camelot adds the harmonic-mixing (Camelot) key column.

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

    columns = _parse_columns(export_columns)
    if export_format is not None:
        _run_export(
            report,
            export_format,
            export_path,
            directory=directory,
            columns=columns,
            camelot=camelot,
        )
    elif camelot:
        click.echo("  Warning: --camelot applies to --export csv/html only.", err=True)

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
            _export_csv(report, export_csv, columns=columns, camelot=camelot)
            click.echo(f"\n  CSV exported to: {export_csv}", err=True)
        except (AudioSuiteError, OSError, ValueError) as exc:
            click.echo(f"  CSV export failed: {exc}", err=True)

    if export_json:
        try:
            _export_json(report, export_json)
            click.echo(f"\n  JSON exported to: {export_json}", err=True)
        except (OSError, ValueError) as exc:
            click.echo(f"  JSON export failed: {exc}", err=True)


def _parse_columns(value: str | None) -> tuple[str, ...] | None:
    """Split ``--export-columns`` into a column tuple.

    Args:
        value: Comma-separated column names, or None.

    Returns:
        The requested names, or None when the flag was not given.

    Raises:
        click.UsageError: If the flag is given but names nothing, because an
            empty column set would silently produce an empty spreadsheet.
    """
    if value is None:
        return None
    names = tuple(part.strip() for part in value.split(",") if part.strip())
    if not names:
        raise click.UsageError("--export-columns needs at least one column name.")
    return names


def _default_export_path(directory: str, export_format: str) -> str:
    """Return the default destination for ``--export``.

    Args:
        directory: The scanned folder.
        export_format: ``m3u``, ``csv`` or ``html``.

    Returns:
        ``<folder>/<folder-name>_library<ext>``, so the artefact sits with the
        library it describes and is named after it.
    """
    root = os.path.normpath(directory)
    name = os.path.basename(root) or "library"
    return os.path.join(root, f"{name}_library.{export_format}")


def _run_export(
    report: Any,
    export_format: str,
    export_path: str | None,
    *,
    directory: str,
    columns: tuple[str, ...] | None,
    camelot: bool,
) -> None:
    """Write one ``--export`` artefact and report it on stderr.

    Args:
        report: The completed scan report.
        export_format: ``m3u``, ``csv`` or ``html``.
        export_path: Destination, or None for the default name.
        directory: The scanned folder (used for the default name).
        columns: Requested CSV/HTML columns, or None for the default set.
        camelot: Whether to add the Camelot column.

    Raises:
        click.UsageError: If columns are requested for a playlist export, which
            has no columns to choose; silently ignoring them would leave the
            caller believing their selection took effect.
    """
    from library_stats.core.playlist_export import export_html, export_m3u
    from library_stats.library_stats import export_csv as _export_csv

    if export_format == "m3u" and (columns is not None or camelot):
        raise click.UsageError(
            "--export-columns/--camelot apply to csv and html exports, not to m3u."
        )

    destination = export_path or _default_export_path(directory, export_format)
    try:
        if export_format == "m3u":
            count = export_m3u(report.scan_path, destination)
        elif export_format == "html":
            count = export_html(
                report.scan_path, destination, columns=columns, camelot=camelot
            )
        else:
            # The writer's own count, not the scan's total: an unreadable file
            # is skipped by the export, so quoting the total would overstate it.
            count = _export_csv(report, destination, columns=columns, camelot=camelot)
    except (OSError, ValueError) as exc:
        click.echo(f"  Export failed: {exc}", err=True)
        return
    click.echo(f"\n  Exported {count} file(s) to: {destination}", err=True)


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
