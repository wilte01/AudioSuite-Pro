"""
library_stats.py — Read-only library statistics engine.

Walks a directory tree, reads existing tags from every audio file
(via tag_helper_reader), and aggregates into a StatsReport.

Supports an optional SQLite-backed cache (LibraryCache) for incremental
scanning: only re-reads tags for files whose mtime has changed.

All statistics are derived from tags already written by suite tools.
No re-analysis is performed.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.exceptions import AudioFileNotFoundError
from audio_suite_shared.tag_helper_reader import (
    read_album_artist,
    read_artist_album,
    read_bpm,
    read_genre,
    read_key,
    read_mood,
    read_tags_raw,
    read_tempo_marking,
)

logger = logging.getLogger(__name__)


# ── Data model ──────────────────────────────────────────────────────────────


@dataclass
class StatsReport:
    """Aggregated library statistics from tag scanning."""

    scan_path: str = ""
    total_files: int = 0
    total_albums: int = 0
    total_artists: int = 0
    total_track_artists: int = 0
    duration_secs: float = 0.0

    format_breakdown: dict[str, int] = field(default_factory=dict)
    bpm_distribution: dict[str, int] = field(default_factory=dict)
    key_distribution: dict[str, int] = field(default_factory=dict)
    key_mode_distribution: dict[str, int] = field(default_factory=dict)
    mood_distribution: dict[str, int] = field(default_factory=dict)
    genre_distribution: dict[str, int] = field(default_factory=dict)
    tempo_marking_distribution: dict[str, int] = field(default_factory=dict)
    year_distribution: dict[str, int] = field(default_factory=dict)

    missing_data: dict[str, int] = field(default_factory=dict)
    top_artists: list[tuple[str, int]] = field(default_factory=list)
    top_genres: list[tuple[str, int]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["duration_str"] = f"{self.duration_secs:.1f}s"
        d["top_artists"] = self.top_artists[:20]
        d["top_genres"] = self.top_genres[:20]
        return d


# ── Key classification helpers ──────────────────────────────────────────────

_MAJOR_KEYS = {
    "C",
    "C#",
    "Db",
    "D",
    "D#",
    "Eb",
    "E",
    "F",
    "F#",
    "Gb",
    "G",
    "G#",
    "Ab",
    "A",
    "A#",
    "Bb",
    "B",
    "Cb",
}
_MINOR_KEYS = {
    "Cm",
    "C#m",
    "Dbm",
    "Dm",
    "D#m",
    "Ebm",
    "Em",
    "Fm",
    "F#m",
    "Gbm",
    "Gm",
    "G#m",
    "Abm",
    "Am",
    "A#m",
    "Bbm",
    "Bm",
}


def _classify_key_mode(key: str) -> tuple[str, str] | None:
    """Return (root, mode) e.g. ('C', 'major') or (None, None) if unparseable."""
    k = key.strip()
    if k in _MAJOR_KEYS:
        return (k, "major")
    if k in _MINOR_KEYS:
        return (k, "minor")
    # Handle "C major", "A minor", "C# minor" text format
    lower = k.lower().replace("\u266d", "b").replace("\u266f", "#")
    for suffix in (" major", " minor"):
        if lower.endswith(suffix):
            root = k[: -len(suffix)]
            mode = suffix.strip()
            return (root, mode)
    return None


def _bpm_bin(bpm: int | None) -> str:
    if bpm is None:
        return "Unknown"
    if bpm < 60:
        return "<60"
    if bpm < 80:
        return "60\u201379"
    if bpm < 100:
        return "80\u201399"
    if bpm < 120:
        return "100\u2013119"
    if bpm < 140:
        return "120\u2013139"
    if bpm < 160:
        return "140\u2013159"
    if bpm < 180:
        return "160\u2013179"
    return "180+"


def _decade_bin(year: int | None) -> str:
    if year is None:
        return "Unknown"
    decade = (year // 10) * 10
    return f"{decade}s"


def _extract_year_from_tags(raw_tags: Any) -> int | None:
    """Extract a 4-digit year from raw tag metadata.

    Checks ID3 TDRC/TDRL/TYER/TORY frames first, then falls back to
    Vorbis DATE field.  Returns None when no parseable year is found.

    Args:
        raw_tags: A tag object supporting ``.get(tag_id)`` (e.g. mutagen
            ID3 or Vorbis comment dict), or None.

    Returns:
        A 4-digit year as int, or None.
    """
    if raw_tags is None or not hasattr(raw_tags, "get"):
        return None
    for tag_id in ("TDRC", "TDRL", "TYER", "TORY"):
        frame = raw_tags.get(tag_id)
        if frame is not None:
            txt = str(frame)
            for part in txt.split("-"):
                if part.isdigit() and len(part) == 4:
                    return int(part)
    date_field = raw_tags.get("DATE")
    if date_field is not None:
        txt = str(date_field)
        for part in txt.split("-"):
            if part.isdigit() and len(part) == 4:
                return int(part)
    return None


def _populate_report(
    report: StatsReport,
    format_counter: Counter[str],
    bpm_counter: Counter[str],
    key_counter: Counter[str],
    key_mode_counter: Counter[str],
    mood_counter: Counter[str],
    genre_counter: Counter[str],
    tempo_counter: Counter[str],
    year_counter: Counter[str],
    artist_counter: Counter[str],
    album_set: set[tuple[str, str]],
    artist_set: set[str],
    track_artist_set: set[str],
    missing_no_bpm: int,
    missing_no_key: int,
    missing_no_genre: int,
    missing_no_mood: int,
    missing_no_tempo: int,
) -> None:
    """Aggregate counters and sets into a StatsReport."""
    report.format_breakdown = dict(format_counter.most_common())
    report.bpm_distribution = dict(bpm_counter.most_common())
    report.key_distribution = dict(sorted(key_counter.items(), key=lambda x: -x[1]))
    report.key_mode_distribution = dict(key_mode_counter.most_common())
    report.mood_distribution = dict(mood_counter.most_common())
    report.genre_distribution = dict(genre_counter.most_common())
    report.tempo_marking_distribution = dict(tempo_counter.most_common())
    report.year_distribution = dict(year_counter.most_common())
    report.top_artists = artist_counter.most_common(50)
    report.top_genres = genre_counter.most_common(50)

    report.total_albums = len(album_set)
    report.total_artists = len(artist_set)
    report.total_track_artists = len(track_artist_set)

    report.missing_data = {
        "no_bpm": missing_no_bpm,
        "no_key": missing_no_key,
        "no_genre": missing_no_genre,
        "no_mood": missing_no_mood,
        "no_tempo_marking": missing_no_tempo,
    }


@dataclass(frozen=True)
class _FileTags:
    """All tag fields read from a single audio file in one pass."""

    artist_album: tuple[str, str] | None
    album_artist: str | None
    bpm: int | None
    key: str | None
    genre: str | None
    mood: str | None
    tempo_marking: str | None
    year: int | None


def _read_file_tags(path: str) -> _FileTags:
    """Read every tag field the scanners need from *path* in one pass.

    A year-extraction failure degrades to ``year=None`` rather than
    propagating, so an unparseable year never skips the whole file.
    File-level read failures (OSError/ValueError) propagate to callers,
    which skip the file.

    Args:
        path: Absolute path to an audio file.

    Returns:
        A populated ``_FileTags``.

    Raises:
        OSError: When a tag read fails at the file level.
        ValueError: When a tag read returns an unexpected value.
    """
    artist_album = read_artist_album(path)
    album_artist = read_album_artist(path)
    bpm = read_bpm(path)
    key = read_key(path)
    genre = read_genre(path)
    mood = read_mood(path)
    tempo = read_tempo_marking(path)

    year: int | None = None
    try:
        year = _extract_year_from_tags(read_tags_raw(path))
    except (ValueError, TypeError):
        year = None

    return _FileTags(
        artist_album=artist_album,
        album_artist=album_artist,
        bpm=bpm,
        key=key,
        genre=genre,
        mood=mood,
        tempo_marking=tempo,
        year=year,
    )


# ── Full walk scanner (original, uncached) ──────────────────────────────────


def _scan_directory_full(dir_path: str, report: StatsReport) -> None:
    """Walk *dir_path* and populate *report* by reading tags from every file."""
    format_counter: Counter[str] = Counter()
    bpm_counter: Counter[str] = Counter()
    key_counter: Counter[str] = Counter()
    key_mode_counter: Counter[str] = Counter()
    mood_counter: Counter[str] = Counter()
    genre_counter: Counter[str] = Counter()
    tempo_counter: Counter[str] = Counter()
    year_counter: Counter[str] = Counter()
    artist_counter: Counter[str] = Counter()
    album_set: set[tuple[str, str]] = set()
    artist_set: set[str] = set()
    track_artist_set: set[str] = set()

    missing_no_bpm = 0
    missing_no_key = 0
    missing_no_genre = 0
    missing_no_mood = 0
    missing_no_tempo = 0

    for root, _dirs, files in os.walk(dir_path):
        for name in files:
            if not name.lower().endswith(SUPPORTED_EXTENSIONS):
                continue

            full = os.path.join(root, name)
            ext = os.path.splitext(name)[1].lower()
            format_counter[ext] += 1
            report.total_files += 1

            try:
                tags = _read_file_tags(full)
                artist_album = tags.artist_album
                album_artist = tags.album_artist
                if artist_album:
                    track_artist_set.add(artist_album[0])
                if not album_artist and artist_album:
                    album_artist = artist_album[0]
                if album_artist:
                    artist_set.add(album_artist)
                    artist_counter[album_artist] += 1
                if artist_album:
                    album_set.add((album_artist or artist_album[0], artist_album[1]))

                bpm_counter[_bpm_bin(tags.bpm)] += 1
                if tags.bpm is None:
                    missing_no_bpm += 1

                key = tags.key
                if key:
                    key_counter[key] += 1
                    classified = _classify_key_mode(key)
                    if classified:
                        key_mode_counter[classified[1]] += 1
                else:
                    missing_no_key += 1

                genre = tags.genre
                if genre:
                    genre_counter[genre] += 1
                else:
                    missing_no_genre += 1

                mood = tags.mood
                if mood:
                    for m in mood.split(";"):
                        m = m.strip()
                        if m:
                            mood_counter[m] += 1
                else:
                    missing_no_mood += 1

                tempo = tags.tempo_marking
                if tempo:
                    tempo_counter[tempo] += 1
                else:
                    missing_no_tempo += 1

                year_counter[_decade_bin(tags.year)] += 1
            except (OSError, ValueError):
                logger.debug("Skipping unreadable file: %s", name, exc_info=True)
                continue

    # ── Populate report ───────────────────────────────────────────────
    _populate_report(
        report,
        format_counter,
        bpm_counter,
        key_counter,
        key_mode_counter,
        mood_counter,
        genre_counter,
        tempo_counter,
        year_counter,
        artist_counter,
        album_set,
        artist_set,
        track_artist_set,
        missing_no_bpm,
        missing_no_key,
        missing_no_genre,
        missing_no_mood,
        missing_no_tempo,
    )


# ── Cache-backed scanner ────────────────────────────────────────────────────


def _scan_directory_cached(
    dir_path: str,
    report: StatsReport,
    cache: Any,  # LibraryCache — avoid top-level import
    refresh: bool = False,
) -> None:
    """Walk *dir_path*, using *cache* to skip unchanged files.

    When *refresh* is True the cache is cleared first (full re-scan).
    Otherwise only files whose mtime has changed are re-read.
    """
    from library_stats.library_cache import LibraryCache

    cache_obj: LibraryCache = cache

    if refresh:
        cache_obj.clear_dir(dir_path)

    # Collect current file info in a single walk
    current_files: list[tuple[str, str, float, int]] = []  # (full, ext, mtime, size)
    for root, _dirs, files in os.walk(dir_path):
        for name in files:
            if not name.lower().endswith(SUPPORTED_EXTENSIONS):
                continue
            full = os.path.join(root, name)
            ext = os.path.splitext(name)[1].lower()
            try:
                st = os.stat(full)
                current_files.append((full, ext, st.st_mtime, st.st_size))
            except OSError:
                logger.debug("Cannot stat file: %s", full)
                continue

    known_paths: set[str] = {f[0] for f in current_files}

    # Walk all files, reading tags only when cache miss
    for full, ext, mtime, size in current_files:
        if not refresh and cache_obj.file_is_cached(full, mtime):
            continue

        try:
            tags = _read_file_tags(full)
            cache_obj.upsert_file(
                filepath=full,
                mtime=mtime,
                size=size,
                format_ext=ext,
                bpm=tags.bpm,
                key=tags.key,
                genre=tags.genre,
                mood=tags.mood,
                tempo_marking=tags.tempo_marking,
                album_artist=tags.album_artist,
                artist_album=tags.artist_album,
                year=tags.year,
            )
        except (OSError, ValueError):
            logger.debug("Skipping unreadable file: %s", full, exc_info=True)
            continue

    # Remove stale cache entries
    cache_obj.remove_orphans(dir_path, known_paths)

    # Build StatsReport from cache
    _build_report_from_cache(dir_path, report, cache_obj)


def _build_report_from_cache(
    dir_path: str,
    report: StatsReport,
    cache: Any,
) -> None:
    """Build a StatsReport by aggregating cached rows."""
    from library_stats.library_cache import LibraryCache

    type_check: LibraryCache = cache  # noqa: F841

    prefix = LibraryCache._path_prefix(dir_path)
    conn = cache._connect()
    cur = conn.execute(
        """SELECT path, format, bpm, key, genre, mood, tempo_marking,
                  album_artist, artist_album, year
           FROM files WHERE INSTR(LOWER(path), LOWER(?)) = 1""",
        [prefix],
    )
    rows = cur.fetchall()

    format_counter: Counter[str] = Counter()
    bpm_counter: Counter[str] = Counter()
    key_counter: Counter[str] = Counter()
    key_mode_counter: Counter[str] = Counter()
    mood_counter: Counter[str] = Counter()
    genre_counter: Counter[str] = Counter()
    tempo_counter: Counter[str] = Counter()
    year_counter: Counter[str] = Counter()
    artist_counter: Counter[str] = Counter()
    album_set: set[tuple[str, str]] = set()
    artist_set: set[str] = set()
    track_artist_set: set[str] = set()

    missing_no_bpm = 0
    missing_no_key = 0
    missing_no_genre = 0
    missing_no_mood = 0
    missing_no_tempo = 0

    for row in rows:
        (
            _path,
            fmt,
            bpm,
            key,
            genre,
            mood,
            tempo,
            album_artist,
            artist_album_json,
            year,
        ) = row

        report.total_files += 1
        format_counter[fmt] += 1

        # Album (unique album_artist + album name) + Artist (album artist
        # → track artist)
        track_artist: str | None = None
        album_name: str | None = None
        if artist_album_json:
            try:
                aa = json.loads(artist_album_json)
                if len(aa) == 2:
                    track_artist_set.add(aa[0])
                    track_artist = aa[0]
                    album_name = aa[1]
            except json.JSONDecodeError:
                pass
        artist_name = album_artist or track_artist
        if artist_name:
            artist_set.add(artist_name)
            artist_counter[artist_name] += 1
        if album_name:
            album_set.add((artist_name or "", album_name))

        # BPM
        bpm_counter[_bpm_bin(bpm)] += 1
        if bpm is None:
            missing_no_bpm += 1

        # Key
        if key:
            key_counter[key] += 1
            classified = _classify_key_mode(key)
            if classified:
                key_mode_counter[classified[1]] += 1
        else:
            missing_no_key += 1

        # Genre
        if genre:
            genre_counter[genre] += 1
        else:
            missing_no_genre += 1

        # Mood (semicolon-separated)
        if mood:
            for m in mood.split(";"):
                m = m.strip()
                if m:
                    mood_counter[m] += 1
        else:
            missing_no_mood += 1

        # Tempo marking
        if tempo:
            tempo_counter[tempo] += 1
        else:
            missing_no_tempo += 1

        # Year
        year_counter[_decade_bin(year)] += 1

    _populate_report(
        report,
        format_counter,
        bpm_counter,
        key_counter,
        key_mode_counter,
        mood_counter,
        genre_counter,
        tempo_counter,
        year_counter,
        artist_counter,
        album_set,
        artist_set,
        track_artist_set,
        missing_no_bpm,
        missing_no_key,
        missing_no_genre,
        missing_no_mood,
        missing_no_tempo,
    )


# ── Export helpers ──────────────────────────────────────────────────────────


def export_csv(report: StatsReport, output_path: str) -> None:
    """Export per-file metadata as CSV (one row per file).

    Args:
        report: A populated StatsReport (used for *scan_path*).
        output_path: Destination CSV path (written in UTF-8).

    Raises:
        FileNotFoundError: If *report.scan_path* does not exist.
    """
    import csv as csv_mod

    if not os.path.isdir(report.scan_path):
        raise AudioFileNotFoundError(f"Scan path does not exist: {report.scan_path}")

    fieldnames = [
        "path",
        "format",
        "bpm",
        "key",
        "genre",
        "mood",
        "tempo_marking",
        "album_artist",
        "artist_album",
        "year",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv_mod.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for root, _dirs, files in os.walk(report.scan_path):
            for name in files:
                if not name.lower().endswith(SUPPORTED_EXTENSIONS):
                    continue

                full = os.path.join(root, name)
                ext = os.path.splitext(name)[1].lower()

                try:
                    bpm = read_bpm(full)
                    key = read_key(full)
                    genre = read_genre(full)
                    mood = read_mood(full)
                    tempo_marking = read_tempo_marking(full)
                    album_artist = read_album_artist(full)
                    artist_album_val = read_artist_album(full)

                    # Year from raw tags
                    raw = read_tags_raw(full)
                    year_int = _extract_year_from_tags(raw)
                    year_str = str(year_int) if year_int is not None else ""

                    artist_album_display = ""
                    if artist_album_val and len(artist_album_val) == 2:
                        artist_album_display = (
                            f"{artist_album_val[0]} / {artist_album_val[1]}"
                        )

                    writer.writerow(
                        {
                            "path": full,
                            "format": ext,
                            "bpm": bpm if bpm is not None else "",
                            "key": key if key is not None else "",
                            "genre": genre if genre is not None else "",
                            "mood": mood if mood is not None else "",
                            "tempo_marking": tempo_marking
                            if tempo_marking is not None
                            else "",
                            "album_artist": album_artist
                            if album_artist is not None
                            else "",
                            "artist_album": artist_album_display,
                            "year": year_str,
                        }
                    )
                except (OSError, ValueError):
                    logger.debug(
                        "Skipping unreadable file during CSV export: %s",
                        full,
                        exc_info=True,
                    )
                    continue


def export_json(report: StatsReport, output_path: str) -> None:
    """Export full ``StatsReport`` as a JSON object.

    Includes all distributions, missing-data tallies, and computed fields
    such as *duration_str* and the top-20 artist/genre lists.

    Args:
        report: A populated StatsReport.
        output_path: Destination JSON path (written in UTF-8).
    """
    import json as json_mod

    with open(output_path, "w", encoding="utf-8") as f:
        json_mod.dump(report.to_dict(), f, indent=2, default=str)


# ── Public API ──────────────────────────────────────────────────────────────


def scan_directory(
    dir_path: str,
    *,
    use_cache: bool = False,
    refresh_cache: bool = False,
    cache: Any = None,
) -> StatsReport:
    """Walk *dir_path* and build a StatsReport from existing tags.

    Args:
        dir_path: Root directory to scan (recursive).
        use_cache: When True, use the SQLite LibraryCache to avoid
            re-reading tags for unchanged files.
        refresh_cache: When True and *use_cache* is also True, clear the
            cache first for a full re-scan.  Ignored when *use_cache* is False.
        cache: An existing ``LibraryCache`` instance, or None to create one.

    Returns:
        Populated StatsReport.
    """
    dir_path = os.path.normpath(dir_path)
    start = time.monotonic()
    report = StatsReport(scan_path=dir_path)

    if use_cache:
        owns_cache = cache is None
        if owns_cache:
            from library_stats.library_cache import LibraryCache

            cache = LibraryCache()
        try:
            _scan_directory_cached(dir_path, report, cache, refresh=refresh_cache)
        finally:
            # A cache created here belongs to this call: close it or its
            # SQLite connection leaks until GC (ResourceWarning in the suite,
            # an open handle in production). A caller-supplied cache stays
            # open — it belongs to the caller.
            if owns_cache:
                cache.close()
    else:
        _scan_directory_full(dir_path, report)

    report.duration_secs = time.monotonic() - start
    return report
