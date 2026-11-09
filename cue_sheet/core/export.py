"""export.py — the CUE Sheet Generator's one run.

The sheet itself is rendered by ``audio_suite_shared.cue_generator``: the same
``build_folder_cue`` the CLI's ``cue generate`` calls, so the window and
``audiosuite`` cannot describe one folder two ways.  This module owns only what
a window adds — the run report, the dry run's decision, and the three callback
payloads.

Changed in 2.6.0: new module (PLAN_2026-11-03_2.6.0_feature_wave_2.md F-E8).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from audio_suite_shared.cue_generator import (
    build_folder_cue,
    scan_audio_files,
    write_cue,
)

logger = logging.getLogger(f"audio_suite.{__name__}")

#: Tool name as the run report's heading prints it.
TOOL_TITLE = "CUE SHEET GENERATOR"

#: The run report's filename, by mode.  A dry run and a live run write
#: different files, so a preview can never be mistaken for the last real write.
REPORT_NAMES: dict[bool, str] = {
    False: "cue_sheet_sync_log.txt",
    True: "cue_sheet_dry_run_log.txt",
}

_DEFAULT_SHEET_NAME = "album.cue"
_RULE = "=" * 60

ProgressCallback = Callable[..., None]


def report_name(dry_run: bool) -> str:
    """Return the run report's filename for *dry_run*.

    Args:
        dry_run: Whether the run is a dry run.

    Returns:
        ``cue_sheet_dry_run_log.txt`` or ``cue_sheet_sync_log.txt``.
    """
    return REPORT_NAMES[dry_run]


def default_output(folder: Path) -> Path:
    """Return the sheet path a run writes when the user names none.

    Args:
        folder: The scanned folder.

    Returns:
        ``<folder>/album.cue``.
    """
    return folder / _DEFAULT_SHEET_NAME


def _report_text(
    *,
    folder: Path,
    cue_path: Path,
    files: list[Path],
    title: str,
    performer: str,
    dry_run: bool,
    sheet: str,
    elapsed: float,
) -> str:
    """Render the run report's text.

    Args:
        folder: The scanned folder.
        cue_path: The sheet path the run used or would use.
        files: The tracks the sheet describes, in album order.
        title: Album title given to the sheet (may be empty).
        performer: Album artist given to the sheet (may be empty).
        dry_run: Whether the run wrote nothing.
        sheet: The rendered sheet text.
        elapsed: Wall-clock seconds the run took.

    Returns:
        The report, ending with one newline.
    """
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    lines = [
        TOOL_TITLE,
        f"Mode: {'DRY RUN' if dry_run else 'LIVE UPDATE'}",
        f"Source folder: {folder}",
        f"Sheet: {cue_path}",
        f"Album title: {title or '(from the file name)'}",
        f"Album artist: {performer or '(none given)'}",
        _RULE,
    ]
    lines.extend(f"  {path.name}" for path in files)
    lines.append(_RULE)
    lines.append(sheet.rstrip("\n"))
    lines.append(_RULE)
    lines.append(
        "SUMMARY: "
        f"tracks={len(files)} written={0 if dry_run else 1} errors=0 "
        f"Time: {minutes:02d}:{seconds:02d}"
    )
    return "\n".join(lines) + "\n"


def _write_report(path: Path, text: str) -> None:
    """Write the run report, logging rather than raising on failure.

    Args:
        path: Destination report path inside the scanned folder.
        text: The report text.
    """
    try:
        path.write_text(text, encoding="utf-8", newline="")
    except OSError as exc:
        logger.warning("Could not write the CUE Sheet Generator report: %s", exc)


def run_export(
    folder: str,
    *,
    output: str = "",
    title: str = "",
    performer: str = "",
    dry_run: bool = False,
    on_progress: ProgressCallback | None = None,
    on_complete: Callable[..., None] | None = None,
    on_error: Callable[[str], None] | None = None,
) -> None:
    """Build the folder's CUE sheet, write it unless dry, and publish the run.

    Args:
        folder: The folder of track files, or one audio file.
        output: Sheet path; empty means ``album.cue`` beside the source.
        title: Album title for the sheet's ``TITLE``.
        performer: Album artist for the sheet's ``PERFORMER``.
        dry_run: Report the sheet without writing it.
        on_progress: Receives one ``(processed, total, display_text)`` payload.
        on_complete: Receives the run's counters and its own fields.
        on_error: Receives one user-facing failure message.
    """
    started = time.monotonic()
    source = Path(folder).resolve()
    scan_dir = source if source.is_dir() else source.parent
    report_path = scan_dir / report_name(dry_run)
    fail = on_error or (lambda message: None)

    files = scan_audio_files(source)
    if not files:
        fail(f"No supported audio files found in {source}.")
        return

    cue_path = Path(output).expanduser() if output else default_output(scan_dir)
    if on_progress is not None:
        on_progress(
            processed=0,
            total=len(files),
            display_text=f"Planned {len(files)} track(s): {cue_path.name}",
        )

    try:
        sheet = build_folder_cue(files, title=title, performer=performer)
    except ValueError as exc:
        # A duplicate track number is a refusal, not a renumbering: the sheet
        # names the album the files claim to be.
        fail(str(exc))
        return

    if not dry_run:
        try:
            write_cue(cue_path, sheet)
        except OSError as exc:
            fail(f"Could not write {cue_path}: {exc}")
            return

    elapsed = time.monotonic() - started
    _write_report(
        report_path,
        _report_text(
            folder=scan_dir,
            cue_path=cue_path,
            files=files,
            title=title,
            performer=performer,
            dry_run=dry_run,
            sheet=sheet,
            elapsed=elapsed,
        ),
    )
    if on_complete is None:
        return
    payload: dict[str, Any] = {
        "total": len(files),
        "processed": len(files),
        "skipped": 0,
        "errors": 0,
        "duration_secs": elapsed,
    }
    on_complete(
        **payload,
        output=str(cue_path),
        tracks=len(files),
        dry_run=dry_run,
        report_path=str(report_path),
    )
