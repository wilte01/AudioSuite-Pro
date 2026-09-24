"""CLI command for CD Ripper."""

from __future__ import annotations

import json
from typing import Any

import click

from audio_suite_shared.cli_base import cli


@cli.command("cd-rip")
@click.argument("drive", type=str)
@click.option(
    "--output-dir",
    required=True,
    type=click.Path(),
    help="Destination directory for ripped files.",
)
@click.option(
    "--format",
    "fmt",
    default="flac",
    type=click.Choice(["wav", "mp3", "flac", "ogg", "m4a", "opus"]),
    help="Output audio format.",
)
@click.option(
    "--tracks",
    default=None,
    type=str,
    help="Comma-separated track numbers to rip (default: all).",
)
@click.option(
    "--quality",
    default=None,
    type=str,
    help="Quality preset string (format-specific).",
)
@click.option(
    "--cue/--no-cue",
    "write_cue",
    default=False,
    help="Write a CUE sheet alongside the ripped tracks.",
)
@click.option(
    "--verify",
    "verify_mode",
    default="twice",
    type=click.Choice(["off", "twice", "accuraterip"]),
    help=(
        "Track verification: 'twice' re-reads each track for accuracy; "
        "'accuraterip' additionally cross-checks against the AccurateRip "
        "database; 'off' disables verification."
    ),
)
@click.option(
    "--dry/--live",
    default=False,
    help="Show what would be ripped without writing files.",
)
@click.option(
    "--json/--text",
    "json_output",
    default=False,
    help="Output results as JSON.",
)
def cd_rip_cli(
    drive: str,
    output_dir: str,
    fmt: str,
    tracks: str | None,
    quality: str | None,
    write_cue: bool,
    verify_mode: str,
    dry: bool,
    json_output: bool,
) -> None:
    """Rip audio CD tracks to files.

    DRIVE is the drive letter (e.g. D:).

    \b
    Examples:
        audiosuite cd-rip D: --output-dir /output/flac --format flac
        audiosuite cd-rip D: --output-dir /output/mp3 --format mp3 --tracks 1,2,3
        audiosuite cd-rip D: --output-dir /output/flac --cue
    """
    from cd_ripper.core.metadata_resolver import FORMAT_OPTIONS, get_quality_options
    from cd_ripper.core.ripper import RipSession

    if dry:
        click.echo("DRY RUN — would rip with these settings:", err=True)
        click.echo(f"  Drive:     {drive}", err=True)
        click.echo(f"  Output:    {output_dir}", err=True)
        click.echo(f"  Format:    {fmt}", err=True)
        click.echo(f"  Tracks:    {tracks or 'all'}", err=True)
        click.echo(f"  CUE sheet: {'yes' if write_cue else 'no'}", err=True)
        click.echo(f"  Verify:    {verify_mode}", err=True)
        return

    # The --format Choice uses lowercase values ('wav', 'opus') while
    # FORMAT_OPTIONS and the quality presets are keyed by display name
    # ('WAV', 'Opus'). Resolve to the display key before any lookup and
    # pass it to RipSession so defaults and RipTask resolution agree.
    fmt_key = next((k for k in FORMAT_OPTIONS if k.lower() == fmt.lower()), fmt)

    codec_args = None
    if quality:
        opts = get_quality_options(fmt_key)
        if opts is not None:
            codec_args = opts.get(quality)

    track_list: list[dict[str, Any]] = []
    if tracks:
        for t in tracks.split(","):
            t = t.strip()
            if t.isdigit():
                track_list.append({"number": int(t)})
        if not track_list:
            click.echo("ERROR: No valid track numbers provided.", err=True)
            return

    log_lines: list[str] = []

    def log_cb(msg: str) -> None:
        click.echo(f"  {msg}", err=True)
        log_lines.append(msg)

    def progress_cb(track_num: int, pct: int, msg: str) -> None:
        click.echo(f"  Track {track_num:02d}: {msg}", err=True)

    def track_done_cb(track_num: int, success: bool, path: str, msg: str) -> None:
        status = "OK" if success else "FAIL"
        click.echo(f"  Track {track_num:02d}: [{status}] {msg}", err=True)

    done_event = __import__("threading").Event()

    def session_done_cb() -> None:
        done_event.set()

    session = RipSession(
        drive=drive,
        tracks=track_list,
        out_dir=output_dir,
        fmt=fmt_key,
        quality_args=codec_args,
        progress_cb=progress_cb,
        track_done_cb=track_done_cb,
        session_done_cb=session_done_cb,
        log_cb=log_cb,
        write_cue=write_cue,
        verify_mode=verify_mode,
    )
    session.start()
    done_event.wait()

    result = {
        "drive": drive,
        "output_dir": output_dir,
        "format": fmt,
        "tracks": tracks or "all",
        "verify": verify_mode,
        "log": log_lines,
    }

    if json_output:
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(f"Rip session complete. {len(log_lines)} log entries.", err=True)
