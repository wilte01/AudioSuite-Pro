"""artwork_cli.py — the ``artwork`` command group (extract, report).

Two read-side jobs on embedded cover art, neither of which the suite had a
surface for before 2.6.0 (F-E10):

* ``extract`` writes the picture beside its album as ``cover.jpg`` or
  ``cover.png``, choosing the extension from the image's magic bytes.
* ``report`` names the files with no artwork, and the ones whose artwork is
  larger than a caller's threshold.

Both read through :mod:`audio_suite_shared.tag_helper_art`, so the mime,
the dimensions and the sidecar writer exist once.  Like ``cue``, this is a
suite utility rather than a tool: there is no window, no manifest entry and no
Master Driver card, which is why its payload's tool id is ``artwork``.

Changed in 2.6.0: new file - F-E10's ``artwork`` command group.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import click

from audio_suite_shared.cli_base import cli
from audio_suite_shared.cli_schema import build_payload
from audio_suite_shared.cue_generator import scan_audio_files
from audio_suite_shared.exceptions import map_to_audio_error, user_message_for
from audio_suite_shared.tag_helper_art import (
    extract_artwork,
    image_dimensions,
    sniff_image_format,
    write_artwork_sidecar,
)

_EXIT_ERROR = 1

#: Bracketed per-file tokens, interpolated directly (a guide quotes the literal,
#: so an f-string that adds the brackets itself would never match it).
STATUS_EXTRACTED = "[EXTRACTED]"
STATUS_KEPT = "[KEPT]"
STATUS_NO_ART = "[NO ART]"
STATUS_OVERSIZE = "[OVERSIZE]"
STATUS_ERROR = "[ERROR]"


@cli.group("artwork")
def artwork_group() -> None:
    """Artwork tools: extract embedded covers to sidecar files, and report
    files with missing or oversized artwork."""


def _files(directory: str, recursive: bool) -> list[Path]:
    """Return the supported audio files under *directory*.

    Args:
        directory: Folder to scan.
        recursive: Include sub-folders.

    Returns:
        The files, in the order the shared scan returns them.
    """
    return scan_audio_files(Path(directory), recursive=recursive)


def _emit(json_output: bool, line: str) -> None:
    """Print a per-file line in text mode only.

    ``--json`` must put the payload on stdout by itself: a consumer parses the
    whole stream, so a progress line ahead of it makes the output unreadable.

    Args:
        json_output: Whether the run asked for JSON.
        line: The line to print in text mode.
    """
    if not json_output:
        click.echo(line)


def _failure(exc: Exception) -> str:
    """Return the user-facing sentence for a per-file failure.

    Args:
        exc: The exception a picture read or write raised.

    Returns:
        The shared message for the mapped error.
    """
    return user_message_for(map_to_audio_error(exc))


@artwork_group.command("extract")
@click.argument("directory", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--name",
    default="cover",
    show_default=True,
    help="Sidecar base name; the extension follows the image format.",
)
@click.option("--force", is_flag=True, help="Replace an existing sidecar.")
@click.option("--recursive", is_flag=True, help="Also read sub-folders.")
@click.option("--json/--text", "json_output", default=False, help="Emit JSON output.")
def artwork_extract_cli(
    directory: str, name: str, force: bool, recursive: bool, json_output: bool
) -> None:
    """Write each file's embedded cover art beside it as a sidecar.

    A file with no artwork is reported, not failed, and a sidecar that already
    exists is kept unless ``--force`` is given — an extractor that overwrote a
    curated ``cover.jpg`` would be destroying the better copy.
    """
    files = _files(directory, recursive)
    if not files:
        click.echo("  Error: no supported audio files found.", err=True)
        raise SystemExit(_EXIT_ERROR)

    started = time.monotonic()
    log_entries: list[str] = []
    extracted = 0
    kept = 0
    no_art = 0
    error_count = 0

    for path in files:
        try:
            art = extract_artwork(str(path))
        except Exception as exc:  # noqa: BLE001 - a counted per-file outcome
            error_count += 1
            log_entries.append(f"{STATUS_ERROR} {path} | {_failure(exc)}\n")
            _emit(json_output, f"  {STATUS_ERROR} {path}")
            continue
        if art is None:
            no_art += 1
            log_entries.append(f"{STATUS_NO_ART} {path} | no embedded artwork\n")
            _emit(json_output, f"  {STATUS_NO_ART} {path}")
            continue

        data = art[0]
        fmt = sniff_image_format(data)
        sidecar = path.parent / f"{name}{fmt[1] if fmt else ''}"
        try:
            written = write_artwork_sidecar(path.parent, data, name=name, force=force)
        except Exception as exc:  # noqa: BLE001 - a counted per-file outcome
            error_count += 1
            log_entries.append(f"{STATUS_ERROR} {path} | {_failure(exc)}\n")
            _emit(json_output, f"  {STATUS_ERROR} {path}")
            continue
        if written is None:
            kept += 1
            log_entries.append(f"{STATUS_KEPT} {path} | kept existing {sidecar}\n")
            _emit(json_output, f"  {STATUS_KEPT} {path}")
            continue

        extracted += 1
        log_entries.append(f"{STATUS_EXTRACTED} {path} -> {written}\n")
        _emit(json_output, f"  {STATUS_EXTRACTED} {path}")

    duration = time.monotonic() - started
    if json_output:
        click.echo(
            json.dumps(
                build_payload(
                    "artwork extract",
                    dry_run=False,
                    total=len(files),
                    processed=len(files),
                    # A kept sidecar is a handled file: build_payload derives
                    # ``succeeded`` from processed/skipped/errors.
                    skipped=no_art,
                    errors=error_count,
                    duration_secs=duration,
                    log_entries=log_entries,
                    extracted=extracted,
                    kept=kept,
                    no_art=no_art,
                    sidecar_name=name,
                ),
                indent=2,
            )
        )
    else:
        click.echo(
            f"\n  {extracted} extracted, {kept} kept, {no_art} without art, "
            f"{error_count} error(s) in {duration:.1f}s."
        )
    if error_count:
        raise SystemExit(_EXIT_ERROR)


@artwork_group.command("report")
@click.argument("directory", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--min-bytes",
    type=int,
    default=0,
    show_default=True,
    help="Also flag artwork at or above this many bytes (0 = no byte flag).",
)
@click.option(
    "--min-dimension",
    type=int,
    default=0,
    show_default=True,
    help="Also flag artwork whose larger side reaches this many pixels "
    "(0 = no dimension flag).",
)
@click.option("--recursive", is_flag=True, help="Also read sub-folders.")
@click.option("--json/--text", "json_output", default=False, help="Emit JSON output.")
def artwork_report_cli(
    directory: str,
    min_bytes: int,
    min_dimension: int,
    recursive: bool,
    json_output: bool,
) -> None:
    """Report files with no artwork, and artwork above a size threshold.

    A read-only command: it changes no file.  It has no ``--dry`` flag, so its
    payload reports ``dry_run`` as false, the way every command without a mode
    does; the read-only promise is in this docstring, not the flag.
    """
    files = _files(directory, recursive)
    if not files:
        click.echo("  Error: no supported audio files found.", err=True)
        raise SystemExit(_EXIT_ERROR)

    started = time.monotonic()
    log_entries: list[str] = []
    missing: list[dict[str, Any]] = []
    oversized: list[dict[str, Any]] = []
    error_count = 0

    for path in files:
        try:
            art = extract_artwork(str(path))
        except Exception as exc:  # noqa: BLE001 - a counted per-file outcome
            error_count += 1
            log_entries.append(f"{STATUS_ERROR} {path} | {_failure(exc)}\n")
            _emit(json_output, f"  {STATUS_ERROR} {path}")
            continue
        if art is None:
            missing.append({"path": str(path)})
            log_entries.append(f"{STATUS_NO_ART} {path} | no embedded artwork\n")
            _emit(json_output, f"  {STATUS_NO_ART} {path}")
            continue

        data = art[0]
        size = len(data)
        dimensions = image_dimensions(data)
        width = dimensions[0] if dimensions else None
        height = dimensions[1] if dimensions else None
        longest = max(width or 0, height or 0)
        too_many_bytes = bool(min_bytes) and size >= min_bytes
        too_many_pixels = bool(min_dimension) and longest >= min_dimension
        if too_many_bytes or too_many_pixels:
            oversized.append(
                {
                    "path": str(path),
                    "bytes": size,
                    "width": width,
                    "height": height,
                }
            )
            log_entries.append(
                f"{STATUS_OVERSIZE} {path} | {size} bytes, "
                f"{width}x{height} | {art[1]}\n"
            )
            _emit(json_output, f"  {STATUS_OVERSIZE} {path}")

    duration = time.monotonic() - started
    if json_output:
        click.echo(
            json.dumps(
                build_payload(
                    "artwork report",
                    dry_run=False,
                    total=len(files),
                    processed=len(files),
                    skipped=len(missing),
                    errors=error_count,
                    duration_secs=duration,
                    log_entries=log_entries,
                    without_art=len(missing),
                    oversized=len(oversized),
                    missing_art=missing,
                    oversized_art=oversized,
                    min_bytes=min_bytes,
                    min_dimension=min_dimension,
                ),
                indent=2,
            )
        )
    else:
        click.echo(
            f"\n  {len(missing)} file(s) without artwork, {len(oversized)} "
            f"above the threshold, {error_count} error(s) in {duration:.1f}s."
        )
    if error_count:
        raise SystemExit(_EXIT_ERROR)
