"""
consolidator.py
Two-phase album genre consolidation logic.

Phase 1 — reads TITLEGENRE from every supported audio file in the directory.
Coverage gate — aborts if too few files have the tag.
Phase 2 — writes the consolidated ALBUMGENRE / ALBUMDERIVED to every file.

No tkinter imports. All progress and completion reporting via injected
callbacks so this module is independently testable.
"""

import logging
import os
import time
from collections import Counter
from typing import Callable

from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.exceptions import (
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)

from .tag_reader import read_titlegenre
from .tag_writer import write_album_genre

logger = logging.getLogger(__name__)


@handle_audio_errors(reraise=False, context="genre_tagger_run_analysis")
def run_analysis(
    dir_path: str,
    is_dry_run: bool,
    min_coverage: int,
    on_phase1_progress: Callable[..., None],
    on_coverage_fail: Callable[..., None],
    on_phase2_progress: Callable[..., None],
    on_complete: Callable[..., None],
    on_error: Callable[[str], None],
) -> None:
    """
    Run the full two-phase genre consolidation for a directory.
    Called from a background thread; never touches tkinter directly.

    Callback signatures:
        on_phase1_progress(processed, total, files_with_genre, errors,
                           display_text, log_text)
        on_coverage_fail(total, files_with_genre, coverage_pct,
                         min_coverage, duration_secs, log_entries)
        on_phase2_progress(display_text, log_text)
        on_complete(total, files_with_genre, coverage_pct,
                    unique_genres, album_genre_string,
                    write_count, write_errors, read_errors,
                    duration_secs, log_entries)
        on_error(message)
    """
    start = time.time()
    log_entries: list[str] = []

    # ── Scan directory ────────────────────────────────────────────────────────
    try:
        files = [
            f
            for f in os.listdir(dir_path)
            if os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS
        ]
    except (OSError, ValueError) as exc:
        mapped = map_to_audio_error(exc)
        logger.error("Directory scan failed: %s", mapped, exc_info=True)
        on_error(user_message_for(mapped))
        return

    if not files:
        on_error("No supported audio files found in the selected directory.")
        return

    total = len(files)

    log_entries += [
        "=" * 60 + "\n",
        "ALBUM GENRE TAGGER LOG\n",
        "=" * 60 + "\n",
        f"Mode: {'DRY RUN' if is_dry_run else 'LIVE UPDATE'}\n",
        f"Directory: {dir_path}\n",
        f"Total audio files: {total}\n",
        f"Minimum coverage required: {min_coverage}%\n",
        "\n",
        "=" * 60 + "\n",
        "PHASE 1: READING TITLEGENRE TAGS\n",
        "-" * 60 + "\n",
    ]

    # ── Phase 1: read TITLEGENRE ──────────────────────────────────────────────
    title_genres: list[str] = []
    files_with_genre = 0
    read_errors = 0

    for i, filename in enumerate(files):
        filepath = os.path.join(dir_path, filename)
        genre, error = read_titlegenre(filepath)

        if genre:
            title_genres.append(genre)
            files_with_genre += 1
            display = f"[OK] {filename}: {genre}"
            log = f"[OK] {filename}: {genre}\n"
        else:
            read_errors += 1
            display = f"[SKIP] {filename}: {error}"
            log = f"[SKIP] {filename}: {error}\n"

        log_entries.append(log)
        on_phase1_progress(
            processed=i + 1,
            total=total,
            files_with_genre=files_with_genre,
            errors=read_errors,
            display_text=display,
            log_text=log,
        )

    # ── Coverage gate ─────────────────────────────────────────────────────────
    coverage_pct = (files_with_genre / total * 100) if total > 0 else 0.0

    if coverage_pct < min_coverage:
        log_entries += [
            "\n",
            "=" * 60 + "\n",
            "COVERAGE CHECK FAILED\n",
            "-" * 60 + "\n",
            f"Files with TITLEGENRE: {files_with_genre} ({coverage_pct:.1f}%)\n",
            f"Required coverage: {min_coverage}%\n",
            "Processing aborted.\n",
            "=" * 60 + "\n",
        ]
        on_coverage_fail(
            total=total,
            files_with_genre=files_with_genre,
            coverage_pct=coverage_pct,
            min_coverage=min_coverage,
            duration_secs=time.time() - start,
            log_entries=log_entries,
        )
        return

    # ── Phase 2: consolidate and write ────────────────────────────────────────
    unique_genres = sorted(set(title_genres))
    genre_counts = Counter(title_genres)
    album_genre_string = "; ".join(unique_genres)

    log_entries += [
        "=" * 60 + "\n",
        "UNIQUE GENRES FOUND\n",
        "-" * 60 + "\n",
    ]
    for g in unique_genres:
        c = genre_counts[g]
        log_entries.append(f"  {g} ({c} file{'s' if c > 1 else ''})\n")

    log_entries += [
        "\n",
        "=" * 60 + "\n",
        "CONSOLIDATED TAGS\n",
        "-" * 60 + "\n",
        f"ALBUMGENRE: {album_genre_string}\n",
        "ALBUMDERIVED: Y\n",
        "\n",
        "=" * 60 + "\n",
        "PHASE 2: WRITING TAGS TO FILES\n",
        "-" * 60 + "\n",
    ]

    write_count = 0
    write_errors = 0

    for filename in files:
        filepath = os.path.join(dir_path, filename)
        success, message = write_album_genre(filepath, album_genre_string, is_dry_run)

        if success:
            write_count += 1
            status = "[DRY RUN]" if is_dry_run else "[UPDATED]"
            display = f"{status} {filename}"
            log = f"{status} {filename}\n"
        else:
            write_errors += 1
            display = f"[WRITE ERROR] {filename}: {message}"
            log = f"[WRITE ERROR] {filename}: {message}\n"

        log_entries.append(log)
        on_phase2_progress(display_text=display, log_text=log)

    # ── Summary ───────────────────────────────────────────────────────────────
    duration = time.time() - start
    minutes = int(duration // 60)
    seconds = int(duration % 60)

    log_entries += [
        "\n",
        "=" * 60 + "\n",
        "SUMMARY\n",
        "-" * 60 + "\n",
        f"Total files: {total}\n",
        f"Files with TITLEGENRE: {files_with_genre} ({coverage_pct:.1f}%)\n",
        f"Unique genres: {len(unique_genres)}\n",
        f"Files {'would be ' if is_dry_run else ''}updated: {write_count}\n",
    ]
    if write_errors:
        log_entries.append(f"Write errors: {write_errors}\n")
    log_entries += [
        f"Read errors: {read_errors}\n",
        f"Time: {minutes:02d}:{seconds:02d}\n",
        "=" * 60 + "\n",
    ]

    on_complete(
        total=total,
        files_with_genre=files_with_genre,
        coverage_pct=coverage_pct,
        unique_genres=unique_genres,
        album_genre_string=album_genre_string,
        write_count=write_count,
        write_errors=write_errors,
        read_errors=read_errors,
        duration_secs=duration,
        log_entries=log_entries,
    )
