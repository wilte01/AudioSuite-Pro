"""
cue_cli.py — CUE sheet CLI commands (parse, generate, split).

Registers the nested ``cue`` command group on the shared ``cli`` group.  This
is the first nested command group in the codebase; ``cli_app.py`` imports
this module to trigger registration (see the ``import X.cli`` pattern there).

Changed in 1.4.0: emits and locks the shared CLI JSON schema (PLAN D82).
Changed in 1.4.1: ``cue generate`` publishes the shared payload, so the CLI
has no command left without ``--json`` (PLAN D95).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import click

from audio_suite_shared.audio_formats import is_supported_format
from audio_suite_shared.cli_base import cli
from audio_suite_shared.cli_schema import build_payload
from audio_suite_shared.cue_generator import (
    CueFileSpec,
    TrackSpec,
    build_cue,
    write_cue,
)
from audio_suite_shared.cue_parser import CueParseError, CueSheet
from audio_suite_shared.cue_split import split_cue_file
from audio_suite_shared.exceptions import AudioSuiteError
from audio_suite_shared.tag_helper_reader import read_artist_title

# Leading "NN - " style track-number prefixes found on ripped filenames.
_TRACK_PREFIX_RE = re.compile(r"^(\d{1,2})\s*[._\-]\s*(.+)$")

_EXT_TO_CUE_TYPE: dict[str, str] = {
    ".flac": "FLAC",
    ".wav": "WAVE",
    ".aiff": "AIFF",
    ".aif": "AIFF",
    ".mp3": "MP3",
    ".ogg": "OGG",
    ".m4a": "MP4",
    ".mp4": "MP4",
    ".opus": "OPUS",
}

_EXIT_ERROR = 1


@cli.group("cue")
def cue_group() -> None:
    """CUE sheet tools: parse sheets, generate a sheet from tracks, and split
    a single-file audio image using a sheet."""


def _natural_sort_key(name: str) -> list[str | int]:
    parts: list[str | int] = []
    for chunk in re.split(r"(\d+)", name.lower()):
        parts.append(int(chunk) if chunk.isdigit() else chunk)
    return parts


def _track_info(path: Path, fallback_number: int) -> tuple[int, str, str]:
    """Return ``(number, title, performer)`` for a single audio file.

    Tags win where present (via ``read_artist_title``); otherwise the track
    number and title fall back to a ``"NN - Title.ext"`` filename prefix.
    """
    number = fallback_number
    stem_tail = path.stem
    match = _TRACK_PREFIX_RE.match(path.stem)
    if match:
        number = int(match.group(1))
        stem_tail = match.group(2).strip()

    artist, title = read_artist_title(str(path))
    if artist in ("", "Unknown") and title in ("", "Unknown"):
        return number, stem_tail or path.stem, ""
    return number, title or path.stem, artist


def _sheet_to_json(sheet: CueSheet) -> dict[str, Any]:
    files_json: list[dict[str, Any]] = []
    for f in sheet.files:
        tracks_json: list[dict[str, Any]] = []
        for t in f.tracks:
            start = t.index01
            tracks_json.append(
                {
                    "number": t.number,
                    "mode": t.mode,
                    "title": t.title,
                    "performer": t.performer,
                    "songwriter": t.songwriter,
                    "isrc": t.isrc,
                    "pregap": t.pregap,
                    "postgap": t.postgap,
                    "start_ms": start.start_ms if start else None,
                    "indexes": [
                        {
                            "number": i.number,
                            "msf": f"{i.mm:02d}:{i.ss:02d}:{i.ff:02d}",
                            "start_ms": i.start_ms,
                        }
                        for i in t.indexes
                    ],
                }
            )
        files_json.append(
            {
                "filename": f.filename,
                "file_type": f.file_type,
                "title": f.title,
                "performer": f.performer,
                "rem": list(f.rem),
                "tracks": tracks_json,
            }
        )
    return {
        "catalog": sheet.catalog,
        "performer": sheet.performer,
        "title": sheet.title,
        "rem": list(sheet.rem),
        "files": files_json,
    }


def _print_sheet(sheet: CueSheet) -> None:
    if sheet.catalog:
        click.echo(f"CATALOG:   {sheet.catalog}")
    if sheet.performer:
        click.echo(f"PERFORMER: {sheet.performer}")
    if sheet.title:
        click.echo(f"TITLE:     {sheet.title}")
    for f in sheet.files:
        click.echo("")
        click.echo(f"[FILE] {f.filename} {f.file_type or ''}".rstrip())
        for t in f.tracks:
            start = t.index01
            start_str = (
                f"{start.mm:02d}:{start.ss:02d}:{start.ff:02d}"
                if start
                else "----:--:--"
            )
            click.echo(
                f"  {t.number:02d}  {start_str}  "
                f"{t.title or ''}  {t.performer or ''}".rstrip()
            )


@cue_group.command("parse")
@click.argument("cue_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--json/--text", "json_output", default=False, help="Emit JSON output.")
def cue_parse_cli(cue_file: str, json_output: bool) -> None:
    """Print the track layout described by CUE_FILE.

    Text mode prints a compact track table; ``--json`` emits the full parsed
    structure including REM comments, ISRC codes, PREGAP/POSTGAP and index
    timestamps in milliseconds.
    """
    started = time.monotonic()
    try:
        from audio_suite_shared.cue_parser import parse_cue_file

        sheet = parse_cue_file(cue_file)
    except (CueParseError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        data = _sheet_to_json(sheet)
        track_count = sum(len(f["tracks"]) for f in data["files"])
        click.echo(
            json.dumps(
                build_payload(
                    "cue parse",
                    dry_run=False,
                    total=track_count,
                    processed=track_count,
                    duration_secs=time.monotonic() - started,
                    log_entries=[],
                    catalog=data["catalog"],
                    performer=data["performer"],
                    title=data["title"],
                    rem=data["rem"],
                    files=data["files"],
                ),
                indent=2,
            )
        )
    else:
        _print_sheet(sheet)


@cue_group.command("generate")
@click.argument("target", type=click.Path(exists=True))
@click.option(
    "-o",
    "--output",
    "output",
    type=click.Path(dir_okay=False),
    default=None,
    help="Output .cue path (default: album.cue next to the input).",
)
@click.option("--title", default="", help="Album title for the generated sheet.")
@click.option(
    "--artist", default="", help="Album artist (PERFORMER) for the generated sheet."
)
@click.option("--json/--text", "json_output", default=False, help="Emit JSON output.")
def cue_generate_cli(
    target: str,
    output: str | None,
    title: str,
    artist: str,
    json_output: bool,
) -> None:
    """Build a CUE sheet that matches the audio at TARGET.

    TARGET is a directory of ripped track files or a single audio file.
    Track numbers, titles and artists are read from embedded tags, falling
    back to ``"NN - Title.ext"`` filename prefixes for untagged files.
    ``--json`` reports the written path and the sheet's track count, so a
    caller can split it without re-reading the sheet.
    """
    started = time.monotonic()
    target_path = Path(target)
    files = _scan_audio_files(target_path)
    if not files:
        raise click.ClickException(f"No supported audio files found at {target_path}")

    if target_path.is_dir():
        cue_name = Path(output) if output else target_path / "album.cue"
    else:
        cue_name = Path(output) if output else target_path.with_suffix(".cue")

    spec_list: list[CueFileSpec] = []
    for index, audio in enumerate(files, start=1):
        number, track_title, performer = _track_info(audio, index)
        spec_list.append(
            CueFileSpec(
                filename=audio.name,
                file_type=_EXT_TO_CUE_TYPE.get(audio.suffix.lower(), "WAVE"),
                tracks=(
                    TrackSpec(number=number, title=track_title, performer=performer),
                ),
            )
        )

    cue_text = build_cue(title=title, performer=artist, files=spec_list)
    try:
        write_cue(cue_name, cue_text)
    except OSError as exc:
        # A read-only folder or a missing parent is a run failure; raising
        # ClickException lets the group handler publish a schema payload for
        # it (PLAN D91) instead of an empty stdout.
        raise click.ClickException(f"Could not write {cue_name}: {exc}") from exc

    track_count = sum(len(f.tracks) for f in spec_list)
    if json_output:
        click.echo(
            json.dumps(
                build_payload(
                    "cue generate",
                    dry_run=False,
                    total=len(files),
                    processed=len(files),
                    duration_secs=time.monotonic() - started,
                    log_entries=[],
                    cue_path=str(cue_name),
                    tracks=track_count,
                    title=title,
                ),
                indent=2,
            )
        )
        return
    click.echo(f"Wrote CUE sheet: {cue_name}")
    click.echo(f"  {track_count} track(s)")


@cue_group.command("split")
@click.argument("cue_file", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "-o",
    "--output-dir",
    "output_dir",
    type=click.Path(file_okay=False),
    default=None,
    help="Destination folder (default: alongside the CUE sheet).",
)
@click.option(
    "--ffmpeg",
    "ffmpeg_bin",
    default="ffmpeg",
    help="FFmpeg executable (name on PATH or absolute path).",
)
@click.option("--json/--text", "json_output", default=False, help="Emit JSON output.")
def cue_split_cli(
    cue_file: str,
    output_dir: str | None,
    ffmpeg_bin: str,
    json_output: bool,
) -> None:
    """Split the single-file image referenced by CUE_FILE into per-track files.

    Each track is cut losslessly from the image (``-c copy``) at its INDEX 01
    timestamp and tagged with the sheet's title / performer.
    """
    out_dir = Path(output_dir) if output_dir else Path(cue_file).resolve().parent
    started = time.monotonic()
    try:
        written = split_cue_file(
            cue_file,
            out_dir,
            ffmpeg=ffmpeg_bin,
            progress_cb=lambda msg: click.echo(f"  {msg}", err=True),
        )
    except (CueParseError, ValueError, OSError, AudioSuiteError) as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        click.echo(
            json.dumps(
                build_payload(
                    "cue split",
                    dry_run=False,
                    total=len(written),
                    processed=len(written),
                    duration_secs=time.monotonic() - started,
                    log_entries=[],
                    cue_file=cue_file,
                    output_dir=str(out_dir),
                    tracks=written,
                ),
                indent=2,
            )
        )
        return
    for path in written:
        click.echo(f"  Created {path}")
    click.echo(f"Split {len(written)} track(s) into {out_dir}")


def _scan_audio_files(target_path: Path) -> list[Path]:
    """List supported audio files at *target_path* in natural sort order."""
    if not target_path.is_dir():
        if is_supported_format(target_path.name):
            return [target_path]
        return []
    return sorted(
        (
            p
            for p in target_path.iterdir()
            if p.is_file() and is_supported_format(p.name)
        ),
        key=lambda p: _natural_sort_key(p.name),
    )
