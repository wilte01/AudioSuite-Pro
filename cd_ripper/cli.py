"""CLI command for CD Ripper.

Changed in 1.4.0: emits and locks the shared CLI JSON schema (PLAN D82).
Changed in 1.4.0: a drive/disc failure keeps the JSON contract - `--json`
still prints one schema-conforming payload (errors 1, reason in `error`)
before exiting 1, so a script never has to parse stderr for the cause.
Changed in 1.4.1: those two paths raise ``RunFailure(already_reported=``
``json_output)`` instead of a plain ``ClickException``, so the group's
failure handler shows the human line and exits 1 without publishing a
second JSON document (PLAN D91).
Changed in 2.1.4: a session that finished with failed tracks exits 1 as well
as reporting ``errors`` in its payload, so a partial rip is not a shell
success (PLAN D9).  The drive/disc failure path keeps its ``RunFailure``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import click

from audio_suite_shared.cli_base import RunFailure, cli, finish_batch
from audio_suite_shared.cli_schema import build_payload


def _rip_payload(
    *,
    drive: str,
    output_dir: str | None,
    fmt: str | None,
    tracks: str | None,
    verify_mode: str | None,
    dry_run: bool,
    log_entries: list[str],
    succeeded: int,
    failed: int,
    duration_secs: float,
    error: str | None = None,
) -> dict[str, Any]:
    """Build the JSON payload for a rip (or a dry-run preview of one).

    A dry run attempts nothing, so it reports ``processed=0`` and the tracks it
    would have handled stay in ``total``.  ``read_offset_frames`` is null for a
    rip; the offset-detection path fills it in, so one shape covers both.

    Args:
        error: The drive/disc failure that stopped the session.  When set, the
            payload is the schema's fatal shape (``errors=1`` and the reason in
            ``error``) instead of a track tally, so a script reads the cause from
            the same document it already parses.
    """
    if error is not None:
        payload = build_payload(
            "cd-rip",
            dry_run=dry_run,
            errors=1,
            duration_secs=duration_secs,
            log_entries=log_entries,
            drive=drive,
            output_dir=output_dir,
            format=fmt,
            tracks=tracks,
            verify=verify_mode,
            read_offset_frames=None,
        )
        payload["error"] = error
        return payload

    attempted = succeeded + failed
    return build_payload(
        "cd-rip",
        dry_run=dry_run,
        total=attempted,
        processed=attempted,
        errors=failed,
        duration_secs=duration_secs,
        log_entries=log_entries,
        drive=drive,
        output_dir=output_dir,
        format=fmt,
        tracks=tracks,
        verify=verify_mode,
        read_offset_frames=None,
    )


def _offset_payload(
    *, drive: str, offset: int | None, error: str | None = None
) -> dict[str, Any]:
    """Build the JSON payload for a read-offset measurement (or its failure)."""
    payload = build_payload(
        "cd-rip",
        dry_run=False,
        errors=1 if error is not None else 0,
        log_entries=[],
        drive=drive,
        output_dir=None,
        format=None,
        tracks=None,
        verify=None,
        read_offset_frames=offset,
    )
    if error is not None:
        payload["error"] = error
    return payload


@cli.command("cd-rip")
@click.argument("drive", type=str)
@click.option(
    "--output-dir",
    required=False,
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
@click.option(
    "--detect-read-offset",
    "detect_offset",
    is_flag=True,
    default=False,
    help=(
        "Measure DRIVE's read offset against the AccurateRip database and "
        "persist it for future rips. Requires a live, lookup-present CD."
    ),
)
def cd_rip_cli(
    drive: str,
    output_dir: str | None,
    fmt: str,
    tracks: str | None,
    quality: str | None,
    write_cue: bool,
    verify_mode: str,
    dry: bool,
    json_output: bool,
    detect_offset: bool,
) -> None:
    """Rip audio CD tracks to files.

    DRIVE is the drive letter (e.g. D:).

    \b
    Examples:
        audiosuite cd-rip D: --output-dir /output/flac --format flac
        audiosuite cd-rip D: --output-dir /output/mp3 --format mp3 --tracks 1,2,3
        audiosuite cd-rip D: --output-dir /output/flac --cue
        audiosuite cd-rip D: --detect-read-offset
    """
    from cd_ripper.core.metadata_resolver import FORMAT_OPTIONS, get_quality_options
    from cd_ripper.core.ripper import RipSession

    log_lines: list[str] = []

    def log_cb(msg: str) -> None:
        click.echo(f"  {msg}", err=True)
        log_lines.append(msg)

    if detect_offset:
        _detect_read_offset(drive, log_cb, json_output)
        return

    if output_dir is None:
        raise click.MissingParameter(
            param_hint="--output-dir",
            param_type="option",
            message="--output-dir is required when ripping (use "
            "--detect-read-offset to only measure the drive).",
        )

    if dry:
        if json_output:
            click.echo(
                json.dumps(
                    _rip_payload(
                        drive=drive,
                        output_dir=output_dir,
                        fmt=fmt,
                        tracks=tracks or "all",
                        verify_mode=verify_mode,
                        dry_run=True,
                        log_entries=[],
                        succeeded=0,
                        failed=0,
                        duration_secs=0.0,
                    ),
                    indent=2,
                )
            )
            return
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
            # This used to echo and return, so an all-invalid ``--tracks`` list
            # exited 0 with an empty stdout in JSON mode: a silent success for
            # a request that ripped nothing.  It is a usage error (exit 2, and
            # a schema-valid error document in JSON mode; PLAN D91).
            raise click.UsageError("No valid track numbers provided.")

    def progress_cb(track_num: int, pct: int, msg: str) -> None:
        click.echo(f"  Track {track_num:02d}: {msg}", err=True)

    succeeded = 0
    failed = 0

    def track_done_cb(track_num: int, success: bool, path: str, msg: str) -> None:
        nonlocal succeeded, failed
        if success:
            succeeded += 1
        else:
            failed += 1
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
    started = time.monotonic()
    session.start()
    done_event.wait()

    fatal_error = getattr(session, "fatal_error", None)
    if isinstance(fatal_error, str) and fatal_error:
        # Nothing was ripped: report the drive/decoder failure instead of a
        # cheerful empty payload (a session that never started used to hang
        # here forever because its thread died before signalling completion).
        # In JSON mode the reason goes in the payload *and* stderr; the raise
        # below still exits 1, so both consumers see the failure.
        if json_output:
            click.echo(
                json.dumps(
                    _rip_payload(
                        drive=drive,
                        output_dir=output_dir,
                        fmt=fmt,
                        tracks=tracks or "all",
                        verify_mode=verify_mode,
                        dry_run=False,
                        log_entries=log_lines,
                        succeeded=0,
                        failed=0,
                        duration_secs=time.monotonic() - started,
                        error=fatal_error,
                    ),
                    indent=2,
                )
            )
        raise RunFailure(
            f"Rip session failed: {fatal_error}", already_reported=json_output
        )

    if json_output:
        click.echo(
            json.dumps(
                _rip_payload(
                    drive=drive,
                    output_dir=output_dir,
                    fmt=fmt,
                    tracks=tracks or "all",
                    verify_mode=verify_mode,
                    dry_run=False,
                    log_entries=log_lines,
                    succeeded=succeeded,
                    failed=failed,
                    duration_secs=time.monotonic() - started,
                ),
                indent=2,
            )
        )
    else:
        click.echo(f"Rip session complete. {len(log_lines)} log entries.", err=True)
    finish_batch(failed)


def _detect_read_offset(
    drive: str, log_cb: Callable[[str], None], json_output: bool
) -> None:
    """Measure and persist DRIVE's read offset, then report the result."""
    from audio_suite_shared.exceptions import AudioSuiteError
    from cd_ripper.core.offset_detect import run_read_offset_detection

    try:
        offset = run_read_offset_detection(drive, log_cb)
    except AudioSuiteError as exc:
        # Covers ReadOffsetDetectionError (no DB record / no unanimous
        # offset) and device-level AudioIOError (no disc, open failure).
        if json_output:
            click.echo(
                json.dumps(
                    _offset_payload(drive=drive, offset=None, error=str(exc)),
                    indent=2,
                )
            )
        raise RunFailure(str(exc), already_reported=json_output) from exc

    if json_output:
        click.echo(
            json.dumps(
                _offset_payload(drive=drive, offset=offset),
                indent=2,
            )
        )
    else:
        click.echo(f"Read offset measured: {offset:+d} frames for drive {drive}")
