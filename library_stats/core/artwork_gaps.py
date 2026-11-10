"""artwork_gaps.py — the albums missing embedded artwork, and their cover pass.

Library Statistics is a read-only scanner; this module is the one write the
dashboard offers.  For an album whose files lack embedded art, it takes the
picture that *is* embedded in one of them and writes it beside the album as a
sidecar, so a player shows a cover without any file being retagged.

The reading and the writing are :mod:`audio_suite_shared.tag_helper_art`'s — the
same functions the Artwork Extractor and ``audiosuite artwork extract`` call —
so this view cannot disagree with either about a file's cover, its format or the
sidecar name.  This module owns only the album grouping, the one-cover-per-folder
choice and the run report; the album groups themselves come from the
completeness scan, which already measured every file's artwork.

Changed in 2.6.0: new module — the Artwork Gaps view's engine.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from audio_suite_shared.cue_generator import scan_audio_files
from audio_suite_shared.exceptions import map_to_audio_error, user_message_for
from audio_suite_shared.tag_helper_art import (
    extract_artwork,
    sniff_image_format,
    write_artwork_sidecar,
)
from library_stats.core.completeness import CompletenessReport

logger = logging.getLogger(f"audio_suite.{__name__}")

#: The run report's filename, written into the scanned folder.
ARTWORK_REPORT_NAME = "library_stats_artwork_log.txt"

#: The report's heading, as the guide quotes it.
TOOL_TITLE = "LIBRARY STATISTICS ARTWORK REPORT"

#: The per-album outcomes the report and the view print.
STATUS_EXTRACTED = "extracted"
STATUS_KEPT = "kept"
STATUS_NO_ART = "no_art"
STATUS_ERROR = "error"

_RULE = "=" * 60

ProgressCallback = Callable[..., None]


@dataclass(frozen=True)
class AlbumArtworkGap:
    """One album whose files are missing embedded artwork.

    ``folders`` is where the files live; a cover is written into each, because
    one album can span several folders (a multi-disc set, say) and a sidecar
    beside the tracks is what a player reads.
    """

    album: str
    folders: tuple[str, ...]
    total_files: int
    missing_files: int

    @property
    def files_with_art(self) -> int:
        """Return how many of the album's files carry artwork."""
        return max(0, self.total_files - self.missing_files)

    @property
    def pct_missing(self) -> float:
        """Return the percentage of the album's files with no artwork."""
        if not self.total_files:
            return 0.0
        return self.missing_files / self.total_files * 100.0


@dataclass(frozen=True)
class AlbumCoverResult:
    """What the cover pass did for one album folder."""

    album: str
    folder: str
    status: str
    sidecar: str = ""
    detail: str = ""


@dataclass(frozen=True)
class CoverRun:
    """The whole cover pass: its per-album outcomes, counters and report."""

    results: tuple[AlbumCoverResult, ...] = ()
    extracted: int = 0
    kept: int = 0
    no_art: int = 0
    errors: int = 0
    dry_run: bool = False
    elapsed: float = 0.0
    report_path: str = ""
    settings: dict[str, object] = field(default_factory=dict)

    @property
    def total(self) -> int:
        """Return the number of album folders the pass considered."""
        return len(self.results)


def missing_artwork_albums(report: CompletenessReport) -> tuple[AlbumArtworkGap, ...]:
    """Return the albums in *report* with at least one file lacking artwork.

    The completeness scan already measured ``album_art`` for every file, so this
    selection costs no second read of the library.  Worst-covered first, because
    that is the order worth fixing in.

    Args:
        report: A completed completeness report.

    Returns:
        One :class:`AlbumArtworkGap` per album with missing artwork, ordered by
        missing files (most first) then album label.  Empty when every file in
        every album has a cover.
    """
    gaps = [
        AlbumArtworkGap(
            album=album.album,
            folders=album.folders,
            total_files=album.total_files,
            missing_files=album.missing.get("album_art", 0),
        )
        for album in report.album_results
        if album.missing.get("album_art", 0) > 0
    ]
    return tuple(sorted(gaps, key=lambda gap: (-gap.missing_files, gap.album)))


def _failure(exc: Exception) -> str:
    """Return the user-facing sentence for a per-file failure."""
    return user_message_for(map_to_audio_error(exc))


def _first_picture(folder: Path) -> tuple[bytes | None, str | None]:
    """Return the first embedded picture found in *folder*'s files.

    Args:
        folder: An album folder.

    Returns:
        ``(picture_bytes, error_message)``.  The picture is ``None`` when no file
        in the folder embeds one; the error is the last read failure, or
        ``None`` when every file was readable.
    """
    error: str | None = None
    for path in sorted(scan_audio_files(folder, recursive=False)):
        try:
            art = extract_artwork(str(path))
        except Exception as exc:  # noqa: BLE001 - one unreadable file is a counted outcome
            error = f"{path.name}: {_failure(exc)}"
            logger.debug("Could not read artwork from %s", path, exc_info=True)
            continue
        if art is not None:
            return art[0], None
    return None, error


def _cover_one(
    album: str, folder: Path, *, name: str, force: bool, dry_run: bool
) -> AlbumCoverResult:
    """Write (or plan) one folder's cover from a file's embedded picture."""
    data, error = _first_picture(folder)
    if data is None:
        if error is not None:
            return AlbumCoverResult(
                album=album,
                folder=str(folder),
                status=STATUS_ERROR,
                detail=error,
            )
        return AlbumCoverResult(
            album=album,
            folder=str(folder),
            status=STATUS_NO_ART,
            detail="no embedded artwork",
        )

    fmt = sniff_image_format(data)
    sidecar = folder / f"{name}{fmt[1] if fmt else ''}"
    try:
        if dry_run:
            written: Path | None = None if sidecar.exists() and not force else sidecar
        else:
            written = write_artwork_sidecar(folder, data, name=name, force=force)
    except Exception as exc:  # noqa: BLE001 - one folder's failure is counted
        return AlbumCoverResult(
            album=album,
            folder=str(folder),
            status=STATUS_ERROR,
            detail=_failure(exc),
        )
    if written is None:
        return AlbumCoverResult(
            album=album,
            folder=str(folder),
            status=STATUS_KEPT,
            sidecar=str(sidecar),
            detail="existing sidecar kept",
        )
    return AlbumCoverResult(
        album=album,
        folder=str(folder),
        status=STATUS_EXTRACTED,
        sidecar=str(written),
    )


def _report_text(
    *,
    source: str,
    name: str,
    force: bool,
    dry_run: bool,
    results: Sequence[AlbumCoverResult],
    extracted: int,
    kept: int,
    no_art: int,
    errors: int,
    elapsed: float,
) -> str:
    """Render the cover pass's run report."""
    lines = [
        TOOL_TITLE,
        f"Mode: {'DRY RUN' if dry_run else 'LIVE UPDATE'}",
        f"Source folder: {source}",
        f"Sidecar name: {name} (extension from the image's own format)",
        f"Replace existing: {'yes' if force else 'no'}",
        _RULE,
    ]
    for result in results:
        detail = f" -> {result.sidecar}" if result.sidecar else ""
        if result.detail:
            detail = f"{detail} | {result.detail}" if detail else f" | {result.detail}"
        lines.append(
            f"  {result.album} | {result.status.upper()} | {result.folder}{detail}"
        )
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    lines.append(_RULE)
    lines.append(
        "SUMMARY: "
        f"albums={len(results)} extracted={extracted} kept={kept} "
        f"no_art={no_art} errors={errors} "
        f"Time: {minutes:02d}:{seconds:02d}"
    )
    return "\n".join(lines) + "\n"


def _write_report(path: Path, text: str) -> str:
    """Write the run report, logging rather than raising on failure."""
    try:
        path.write_text(text, encoding="utf-8", newline="")
    except OSError as exc:
        logger.warning("Could not write the artwork report: %s", exc)
        return ""
    return str(path)


def run_cover_extraction(
    gaps: Sequence[AlbumArtworkGap],
    *,
    source: str,
    name: str = "cover",
    force: bool = False,
    dry_run: bool = False,
    on_progress: ProgressCallback | None = None,
) -> CoverRun:
    """Write a cover beside each album in *gaps*, and record the run.

    One sidecar per folder, taken from the first file in it that embeds a
    picture: writing one per track would leave the same image behind whichever
    track happened to be read last, and a folder needs one cover.  A dry run
    decides the same keep/replace outcome without writing anything.

    Args:
        gaps: The albums to work on, from :func:`missing_artwork_albums`.
        source: The scanned folder; the run report is written into it.
        name: Sidecar base name; the extension follows the image's format.
        force: Replace an existing sidecar instead of keeping it.
        dry_run: Report what would be written without writing a sidecar.
        on_progress: Receives one ``(processed, total, display_text)`` payload
            per folder.

    Returns:
        The populated :class:`CoverRun`, whose ``report_path`` is the file the
        view's View Log opens.
    """
    started = time.monotonic()
    results: list[AlbumCoverResult] = []
    extracted = kept = no_art = errors = 0

    queue: list[tuple[str, Path]] = []
    for gap in gaps:
        if not gap.folders:
            results.append(
                AlbumCoverResult(
                    album=gap.album,
                    folder="",
                    status=STATUS_ERROR,
                    detail="no folder recorded for this album",
                )
            )
            errors += 1
            continue
        queue.extend((gap.album, Path(folder)) for folder in gap.folders)

    for processed, (album, folder) in enumerate(queue, start=1):
        result = _cover_one(album, folder, name=name, force=force, dry_run=dry_run)
        results.append(result)
        if result.status == STATUS_EXTRACTED:
            extracted += 1
        elif result.status == STATUS_KEPT:
            kept += 1
        elif result.status == STATUS_NO_ART:
            no_art += 1
        else:
            errors += 1
        if on_progress is not None:
            on_progress(
                processed=processed,
                total=len(queue),
                display_text=f"{album} | {result.status.upper()}",
            )

    elapsed = time.monotonic() - started
    report_path = ""
    if source:
        report_path = _write_report(
            Path(source) / ARTWORK_REPORT_NAME,
            _report_text(
                source=source,
                name=name,
                force=force,
                dry_run=dry_run,
                results=results,
                extracted=extracted,
                kept=kept,
                no_art=no_art,
                errors=errors,
                elapsed=elapsed,
            ),
        )

    return CoverRun(
        results=tuple(results),
        extracted=extracted,
        kept=kept,
        no_art=no_art,
        errors=errors,
        dry_run=dry_run,
        elapsed=elapsed,
        report_path=report_path,
        settings={"name": name, "force": force, "source": source},
    )
