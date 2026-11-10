"""extract.py — the Artwork Extractor's one run.

The picture is read and written by :mod:`audio_suite_shared.tag_helper_art`,
the same functions ``audiosuite artwork extract`` calls, so the window and the
command line cannot disagree about a file's cover, its format or the sidecar
name.  This module owns only what a window adds: the run report, the dry run's
decision and the three callback payloads.

A dry run writes the report and no sidecar, so a report can be read before a
curated ``cover.jpg`` is at risk.  ``force`` is what allows a live run to
replace one; without it an existing sidecar is reported as kept.

Changed in 2.6.0: new module — the Artwork Extractor's run.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from audio_suite_shared.cue_generator import scan_audio_files
from audio_suite_shared.exceptions import map_to_audio_error, user_message_for
from audio_suite_shared.tag_helper_art import (
    extract_artwork,
    sniff_image_format,
    write_artwork_sidecar,
)

logger = logging.getLogger(f"audio_suite.{__name__}")

#: Tool name as the run report's heading prints it.
TOOL_TITLE = "ARTWORK EXTRACTOR"

#: The run report's filename, by mode.  A dry run and a live run write
#: different files, so a preview can never be mistaken for the last real write.
REPORT_NAMES: dict[bool, str] = {
    False: "artwork_extractor_sync_log.txt",
    True: "artwork_extractor_dry_run_log.txt",
}

#: Per-file outcome tokens, quoted literally by the user guide.
STATUS_EXTRACTED = "[EXTRACTED]"
STATUS_KEPT = "[KEPT]"
STATUS_NO_ART = "[NO ART]"
STATUS_ERROR = "[ERROR]"

_RULE = "=" * 60

ProgressCallback = Callable[..., None]


def report_name(dry_run: bool) -> str:
    """Return the run report's filename for *dry_run*.

    Args:
        dry_run: Whether the run is a dry run.

    Returns:
        ``artwork_extractor_dry_run_log.txt`` or
        ``artwork_extractor_sync_log.txt``.
    """
    return REPORT_NAMES[dry_run]


def _failure(exc: Exception) -> str:
    """Return the user-facing sentence for a per-file failure.

    Args:
        exc: The exception a picture read or write raised.

    Returns:
        The shared message for the mapped error.
    """
    return user_message_for(map_to_audio_error(exc))


def _write_report(path: Path, text: str) -> None:
    """Write the run report, logging rather than raising on failure.

    Args:
        path: Destination report path inside the scanned folder.
        text: The report text.
    """
    try:
        path.write_text(text, encoding="utf-8", newline="")
    except OSError as exc:
        logger.warning("Could not write the Artwork Extractor report: %s", exc)


def _report_text(
    *,
    folder: Path,
    name: str,
    force: bool,
    recursive: bool,
    dry_run: bool,
    outcome_lines: list[str],
    extracted: int,
    kept: int,
    no_art: int,
    errors: int,
    elapsed: float,
) -> str:
    """Render the run report's text.

    Args:
        folder: The scanned folder.
        name: Sidecar base name the run used.
        force: Whether an existing sidecar could be replaced.
        recursive: Whether sub-folders were read.
        dry_run: Whether the run wrote no sidecar.
        outcome_lines: One line per file, in scan order.
        extracted: Sidecars written (or, for a dry run, that would be written).
        kept: Existing sidecars left untouched.
        no_art: Files with no embedded artwork.
        errors: Files whose picture could not be read or written.
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
        f"Sidecar name: {name} (extension from the image's own format)",
        f"Replace existing: {'yes' if force else 'no'}",
        f"Sub-folders: {'yes' if recursive else 'no'}",
        _RULE,
    ]
    lines.extend(outcome_lines)
    lines.append(_RULE)
    lines.append(
        "SUMMARY: "
        f"files={extracted + kept + no_art + errors} extracted={extracted} "
        f"kept={kept} no_art={no_art} errors={errors} "
        f"Time: {minutes:02d}:{seconds:02d}"
    )
    return "\n".join(lines) + "\n"


def run_extraction(
    folder: str,
    *,
    name: str = "cover",
    force: bool = False,
    recursive: bool = False,
    dry_run: bool = False,
    on_progress: ProgressCallback | None = None,
    on_complete: Callable[..., None] | None = None,
    on_error: Callable[[str], None] | None = None,
) -> None:
    """Write each file's embedded cover beside it, then publish the run.

    Args:
        folder: The folder to scan.
        name: Sidecar base name; the extension follows the image's format.
        force: Replace an existing sidecar instead of keeping it.
        recursive: Also read sub-folders.
        dry_run: Report what would be written without writing a sidecar.
        on_progress: Receives one ``(processed, total, display_text)`` payload.
        on_complete: Receives the run's counters and its own fields.
        on_error: Receives one user-facing failure message.
    """
    started = time.monotonic()
    source = Path(folder).resolve()
    report_path = source / report_name(dry_run)
    fail = on_error or (lambda message: None)

    files = scan_audio_files(source, recursive=recursive)
    if not files:
        fail(f"No supported audio files found in {source}.")
        return

    total = len(files)
    outcome_lines: list[str] = []
    extracted = 0
    kept = 0
    no_art = 0
    errors = 0

    for processed, path in enumerate(files, start=1):
        try:
            art = extract_artwork(str(path))
        except Exception as exc:  # noqa: BLE001 - a counted per-file outcome
            errors += 1
            line = f"  {STATUS_ERROR} {path} | {_failure(exc)}"
        else:
            if art is None:
                no_art += 1
                line = f"  {STATUS_NO_ART} {path} | no embedded artwork"
            else:
                data = art[0]
                fmt = sniff_image_format(data)
                suffix = fmt[1] if fmt else ""
                sidecar = path.parent / f"{name}{suffix}"
                try:
                    if dry_run:
                        written = None if sidecar.exists() and not force else sidecar
                    else:
                        written = write_artwork_sidecar(
                            path.parent, data, name=name, force=force
                        )
                except Exception as exc:  # noqa: BLE001 - a counted per-file outcome
                    errors += 1
                    line = f"  {STATUS_ERROR} {path} | {_failure(exc)}"
                else:
                    if written is None:
                        kept += 1
                        line = f"  {STATUS_KEPT} {path} | kept existing {sidecar}"
                    else:
                        extracted += 1
                        line = f"  {STATUS_EXTRACTED} {path} -> {written}"
        outcome_lines.append(line)
        if on_progress is not None:
            on_progress(processed=processed, total=total, display_text=line.strip())

    elapsed = time.monotonic() - started
    _write_report(
        report_path,
        _report_text(
            folder=source,
            name=name,
            force=force,
            recursive=recursive,
            dry_run=dry_run,
            outcome_lines=outcome_lines,
            extracted=extracted,
            kept=kept,
            no_art=no_art,
            errors=errors,
            elapsed=elapsed,
        ),
    )
    if on_complete is None:
        return
    on_complete(
        total=total,
        processed=total,
        skipped=no_art,
        errors=errors,
        duration_secs=elapsed,
        extracted=extracted,
        kept=kept,
        no_art=no_art,
        dry_run=dry_run,
        report_path=str(report_path),
    )
