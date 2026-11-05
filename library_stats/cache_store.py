"""
cache_store.py - the library cache's rows and scope queries (2.4.3).

WP-9 #5 moved these methods off ``LibraryCache`` into ``CacheStoreMixin``;
bodies are unchanged and ``library_cache`` still re-exports every name.

Changed in 2.4.3: split out of ``library_stats.library_cache``
(PLAN_2026-11-03_2.4.3_structure.md WP-9).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

from .cache_schema import (
    _CLEAR_SCOPE_SQL,
    _POPULATE_SCOPE_INDEXED,
    _POPULATE_SCOPE_SEQUENTIAL,
    _SCOPE_COUNT_SQL,
    _SCOPE_PLAN_CACHE_LIMIT,
    _SCOPE_RANGE_HIGH,
    _SCOPED_CLEAR_INDEXED,
    _SCOPED_CLEAR_SEQUENTIAL,
    _SCOPED_HASHES_INDEXED,
    _SCOPED_HASHES_SEQUENTIAL,
    _SCOPED_MTIMES_INDEXED,
    _SCOPED_MTIMES_SEQUENTIAL,
    _SCOPED_STAMPS_INDEXED,
    _SCOPED_STAMPS_SEQUENTIAL,
    _path_fold,
    _path_hash,
)

logger = logging.getLogger(f"audio_suite.{__name__}")

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
    """Return (root, mode) e.g. ('C', 'major') or None."""
    k = key.strip()
    if k in _MAJOR_KEYS:
        return (k, "major")
    if k in _MINOR_KEYS:
        return (k, "minor")
    lower = k.lower().replace("\u266d", "b").replace("\u266f", "#")
    for suffix in (" major", " minor"):
        if lower.endswith(suffix):
            root = k[: -len(suffix)]
            mode = suffix.strip()
            return (root, mode)
    return None


def _classify_keys(keys: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for k in keys:
        c = _classify_key_mode(k)
        if c:
            result[c[1]] = result.get(c[1], 0) + 1
    return result


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


def _decade_bins(years: list[int | None]) -> dict[str, int]:
    result: dict[str, int] = {}
    for y in years:
        b = _decade_bin(y)
        result[b] = result.get(b, 0) + 1
    return result


class CacheStoreMixin:
    """File rows and scope selection half of ``LibraryCache``."""

    _conn: sqlite3.Connection | None
    _batch_depth: int
    _path: Path
    _scope_plans: dict[str, str]

    def _connect(self) -> sqlite3.Connection:
        """Provided by ``LibraryCache`` itself; composed ahead of this mixin."""
        raise NotImplementedError

    def _commit(self) -> None:
        """Provided by ``LibraryCache`` itself; composed ahead of this mixin."""
        raise NotImplementedError

    @staticmethod
    def _path_prefix(dir_path: str) -> str:
        """Normalize a directory path into a prefix for INSTR matching.

        Ensures a trailing separator so that ``D:\\Music`` becomes
        ``D:\\Music\\`` and correctly matches only files under that tree.
        """
        normalized = os.path.normpath(dir_path)
        if not normalized.endswith(os.sep):
            normalized += os.sep
        return normalized

    def scope_plan_kind(self, dir_path: str) -> str:
        """Return which scope plan *dir_path* would use: ``indexed``/``sequential``.

        An index only pays off when the scope is a small slice of the cache; at
        whole-library selectivity a sequential scan is faster (measured 9.9 ms
        vs 13.5 ms over 20 000 rows), so the plan is chosen from the actual row
        counts — never unconditionally.  This always re-counts, because a
        caller asking the question wants the current answer; the hot callers
        below go through :meth:`_plan_for`, which memoises it.
        """
        conn = self._connect()
        prefix = _path_fold(self._path_prefix(dir_path))
        total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        if total:
            scoped = conn.execute(
                "SELECT COUNT(*) FROM files WHERE path_fold >= ? AND path_fold < ?",
                [prefix, prefix + _SCOPE_RANGE_HIGH],
            ).fetchone()[0]
            if scoped * 2 < total:
                return "indexed"
        return "sequential"

    def _plan_for(self, dir_path: str) -> str:
        """Return the cached plan for *dir_path*, deciding it at most once.

        The decision costs two ``COUNT(*)`` queries (measured **15.91 ms** on a
        200 000-row cache) and every scoped single-statement operation used to
        pay it: three calls for the same directory during one cached scan ran
        the counts three times.  The memo keeps one decision per directory for
        this instance's lifetime.

        A stale plan is safe, and that is why this can be a plain memo: the
        plan chooses a *path* to the same rows, never which rows are returned
        (both statements are equality-equivalent and the suite asserts it).  A
        write from another connection can therefore make the memo suboptimal,
        never wrong; :meth:`invalidate_scope_plans` is for a caller that knows
        the shape changed and wants the faster side of the threshold back.

        Args:
            dir_path: The directory whose scope is about to be queried.

        Returns:
            ``"indexed"`` or ``"sequential"``.
        """
        key = self._path_prefix(dir_path)
        cached = self._scope_plans.get(key)
        if cached is not None:
            return cached
        plan = self.scope_plan_kind(dir_path)
        if len(self._scope_plans) >= _SCOPE_PLAN_CACHE_LIMIT:
            # Evict the oldest decision (dicts keep insertion order); a scan
            # touching more directories than this re-decides, which is correct
            # and still cheaper than never caching.
            self._scope_plans.pop(next(iter(self._scope_plans)))
        self._scope_plans[key] = plan
        return plan

    def invalidate_scope_plans(self) -> None:
        """Forget every memoised plan decision.

        Call after a bulk change whose row distribution no longer resembles the
        one the decisions were made on.  Not required for correctness - a stale
        plan still returns the same rows - only to get the faster side of the
        threshold back.
        """
        self._scope_plans.clear()

    def select_scope(self, dir_path: str) -> None:
        """Copy *dir_path*'s rows into ``temp._scope_files`` for the next queries.

        Both plans produce the same table, so they return the same rows and
        differ only in how it is filled.  The copy is rebuilt on every call:
        another connection (or a second process) can change ``files`` between
        two calls, and a cache must never serve a stale scope just to save a
        cheap copy.
        """
        conn = self._connect()
        conn.execute(_CLEAR_SCOPE_SQL)
        if self._plan_for(dir_path) == "indexed":
            prefix = _path_fold(self._path_prefix(dir_path))
            conn.execute(_POPULATE_SCOPE_INDEXED, [prefix, prefix + _SCOPE_RANGE_HIGH])
        else:
            conn.execute(_POPULATE_SCOPE_SEQUENTIAL, [self._path_prefix(dir_path)])

    def file_is_cached(
        self, filepath: str, mtime: float, size: int | None = None
    ) -> bool:
        """Return True if *filepath* is cached and its stamp matches.

        A freshness stamp is ``(mtime, size)``, not the mtime alone: a file
        replaced by a copy that preserves its timestamps keeps its mtime, so an
        mtime-only comparison answers "cached" for a file whose tags were never
        read (R-13).

        Args:
            filepath: The file whose row is being checked.
            mtime: The current ``st_mtime``.
            size: The current ``st_size``.  Pass it - omitting it keeps the
                coarse mtime-only answer, which is only appropriate when the
                size is genuinely unknown.

        Returns:
            True when the stored row matches.  A stored ``size`` of NULL never
            matches a supplied size, so a legacy row is re-read once and heals.
        """
        conn = self._connect()
        if size is None:
            cur = conn.execute(
                "SELECT 1 FROM files WHERE path_hash = ? AND mtime = ?",
                [_path_hash(filepath), mtime],
            )
        else:
            cur = conn.execute(
                "SELECT 1 FROM files WHERE path_hash = ? AND mtime = ? AND size = ?",
                [_path_hash(filepath), mtime, size],
            )
        return cur.fetchone() is not None

    def get_cached_mtimes(self, dir_path: str) -> dict[str, float]:
        """Return ``{filepath: mtime}`` for all cached files under *dir_path*.

        Deliberately a single statement against ``files`` rather than a
        materialised scope: copying the scope costs more than this scan saves
        (70 ms against 17 ms for 20 000 rows), and every cached scan runs it
        once.  Only the multi-statement reports pay for a scope copy.

        The statement follows :meth:`scope_plan_kind`: a narrow scope reads the
        ``path_fold`` index, a wide one keeps the sequential predicate.

        This is the mtime *view*, and that is all it is: a freshness decision
        made from it alone is the R-13 defect.  A scan compares
        :meth:`get_cached_stamps` instead; the two share one plan and one row
        set, so this costs nothing extra where only the mtime is wanted.
        """
        conn = self._connect()
        if self._plan_for(dir_path) == "indexed":
            prefix = _path_fold(self._path_prefix(dir_path))
            cur = conn.execute(
                _SCOPED_MTIMES_INDEXED, [prefix, prefix + _SCOPE_RANGE_HIGH]
            )
        else:
            cur = conn.execute(_SCOPED_MTIMES_SEQUENTIAL, [self._path_prefix(dir_path)])
        return {row[0]: row[1] for row in cur}

    def get_cached_stamps(self, dir_path: str) -> dict[str, tuple[float, int | None]]:
        """Return ``{filepath: (mtime, size)}`` for the files under *dir_path*.

        The shape a cached scan needs: one scoped read of the whole stamp, so a
        file that was replaced with its timestamps preserved is a miss rather
        than a stale hit (R-13).  The stored ``size`` may be NULL on a row
        written before the column was filled, which never equals a real size -
        that file is re-read once and the row heals.

        Plan selection, cost and scope are identical to
        :meth:`get_cached_mtimes`; the only difference is one column.
        """
        conn = self._connect()
        if self._plan_for(dir_path) == "indexed":
            prefix = _path_fold(self._path_prefix(dir_path))
            cur = conn.execute(
                _SCOPED_STAMPS_INDEXED, [prefix, prefix + _SCOPE_RANGE_HIGH]
            )
        else:
            cur = conn.execute(_SCOPED_STAMPS_SEQUENTIAL, [self._path_prefix(dir_path)])
        return {row[0]: (row[1], row[2]) for row in cur}

    def upsert_file(
        self,
        filepath: str,
        mtime: float,
        size: int,
        format_ext: str,
        bpm: int | None = None,
        key: str | None = None,
        genre: str | None = None,
        mood: str | None = None,
        tempo_marking: str | None = None,
        album_artist: str | None = None,
        artist_album: tuple[str, str] | None = None,
        year: int | None = None,
    ) -> None:
        """Insert or replace a single file's cached metadata.

        Args:
            filepath: Absolute path to the audio file.
            mtime: Last modification timestamp (from ``os.path.getmtime``).
            size: File size in bytes.
            format_ext: File extension including dot, e.g. ``.mp3``.
            bpm: Detected BPM, or None.
            key: Musical key, or None.
            genre: Genre tag, or None.
            mood: Mood tag, or None.
            tempo_marking: Tempo marking text, or None.
            album_artist: Album artist, or None.
            artist_album: ``(artist, album)`` tuple, or None.
            year: Release year extracted from tags, or None.
        """
        artist_album_json: str | None = None
        if artist_album is not None:
            artist_album_json = json.dumps(list(artist_album), ensure_ascii=False)

        conn = self._connect()
        norm_path = os.path.normpath(filepath)
        conn.execute(
            """INSERT OR REPLACE INTO files
               (path_hash, path, path_fold, dir_path, mtime, size, format,
                bpm, key, genre, mood, tempo_marking,
                album_artist, artist_album, year)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                _path_hash(filepath),
                norm_path,
                _path_fold(filepath),
                os.path.dirname(norm_path),
                mtime,
                size,
                format_ext,
                bpm,
                key,
                genre,
                mood,
                tempo_marking,
                album_artist,
                artist_album_json,
                year,
            ],
        )
        self._commit()

    def remove_orphans(self, dir_path: str, known_paths: set[str]) -> int:
        """Delete cache rows for files under *dir_path* that no longer exist.

        Returns the number of rows removed.  The candidate scan follows
        :meth:`scope_plan_kind`, like every other scoped statement.
        """
        conn = self._connect()
        if self._plan_for(dir_path) == "indexed":
            prefix = _path_fold(self._path_prefix(dir_path))
            cur = conn.execute(
                _SCOPED_HASHES_INDEXED, [prefix, prefix + _SCOPE_RANGE_HIGH]
            )
        else:
            cur = conn.execute(_SCOPED_HASHES_SEQUENTIAL, [self._path_prefix(dir_path)])
        known_hashes = {_path_hash(p) for p in known_paths}
        orphan_hashes = [row[0] for row in cur if row[0] not in known_hashes]
        if orphan_hashes:
            conn.executemany(
                "DELETE FROM files WHERE path_hash = ?",
                [(h,) for h in orphan_hashes],
            )
            self._commit()
        return len(orphan_hashes)

    def clear_dir(self, dir_path: str) -> None:
        """Delete all cached entries under a specific directory (recursive).

        The scope follows :meth:`scope_plan_kind`, so a narrow directory is
        cleared through the ``path_fold`` index.
        """
        conn = self._connect()
        if self._plan_for(dir_path) == "indexed":
            prefix = _path_fold(self._path_prefix(dir_path))
            conn.execute(_SCOPED_CLEAR_INDEXED, [prefix, prefix + _SCOPE_RANGE_HIGH])
        else:
            conn.execute(_SCOPED_CLEAR_SEQUENTIAL, [self._path_prefix(dir_path)])
        self._commit()

    def row_count(self, dir_path: str | None = None) -> int:
        """Return the number of cached rows, optionally scoped to *dir_path*."""
        conn = self._connect()
        if dir_path is not None:
            cur = conn.execute(
                "SELECT COUNT(*) FROM files WHERE INSTR(LOWER(path), LOWER(?)) = 1",
                [self._path_prefix(dir_path)],
            )
        else:
            cur = conn.execute("SELECT COUNT(*) FROM files")
        row = cur.fetchone()
        if row is None:
            return 0
        return int(row[0])

    def query_aggregate(self, dir_path: str) -> dict[str, Any] | None:
        """Return aggregated statistics from the cache as a flat dict.

        This avoids loading all rows into Python memory.  Returns None
        when no cached data exists for *dir_path*.

        The returned dict is compatible with ``StatsReport(**d)`` and
        includes::

            scan_path, total_files, total_albums, total_artists,
            format_breakdown, genre_distribution, key_distribution,
            key_mode_distribution, mood_distribution,
            tempo_marking_distribution, year_distribution,
            top_artists, top_genres, missing_data

        Note it does **not** populate ``bpm_distribution`` (the cached-scan
        report path builds that separately in
        ``library_stats.core.file_processor``); ``StatsReport`` defaults it
        to an empty dict, so ``StatsReport(**d)`` still succeeds.
        """
        conn = self._connect()
        self.select_scope(dir_path)

        result: dict[str, Any] = {}
        result["scan_path"] = dir_path

        total_files = conn.execute(_SCOPE_COUNT_SQL).fetchone()[0]
        if total_files == 0:
            return None

        # ── Counts ────────────────────────────────────────────────────
        result["total_files"] = total_files

        cur = conn.execute(
            "SELECT COUNT(DISTINCT artist_album) FROM temp._scope_files "
            "WHERE artist_album IS NOT NULL"
        )
        result["total_albums"] = cur.fetchone()[0] or 0

        cur = conn.execute(
            "SELECT COUNT(DISTINCT album_artist) FROM temp._scope_files "
            "WHERE album_artist IS NOT NULL"
        )
        result["total_artists"] = cur.fetchone()[0] or 0

        # ── Format breakdown ──────────────────────────────────────────
        cur = conn.execute(
            "SELECT format, COUNT(*) AS cnt FROM temp._scope_files "
            "WHERE format IS NOT NULL "
            "GROUP BY format ORDER BY cnt DESC"
        )
        result["format_breakdown"] = dict(cur)

        # ── Genre distribution ────────────────────────────────────────
        cur = conn.execute(
            "SELECT genre, COUNT(*) AS cnt FROM temp._scope_files "
            "WHERE genre IS NOT NULL "
            "GROUP BY genre ORDER BY cnt DESC"
        )
        result["genre_distribution"] = dict(cur)

        # ── Key distribution ──────────────────────────────────────────
        cur = conn.execute(
            "SELECT key, COUNT(*) AS cnt FROM temp._scope_files "
            "WHERE key IS NOT NULL "
            "GROUP BY key ORDER BY cnt DESC"
        )
        result["key_distribution"] = dict(cur)

        # ── Key mode distribution (loaded into Python for classification) ─
        cur = conn.execute("SELECT key FROM temp._scope_files WHERE key IS NOT NULL")
        result["key_mode_distribution"] = dict(_classify_keys([r[0] for r in cur]))

        # ── Mood distribution ─────────────────────────────────────────
        cur = conn.execute(
            "SELECT mood, COUNT(*) AS cnt FROM temp._scope_files "
            "WHERE mood IS NOT NULL "
            "GROUP BY mood ORDER BY cnt DESC"
        )
        result["mood_distribution"] = dict(cur)

        # ── Tempo marking distribution ────────────────────────────────
        cur = conn.execute(
            "SELECT tempo_marking, COUNT(*) AS cnt FROM temp._scope_files "
            "WHERE tempo_marking IS NOT NULL "
            "GROUP BY tempo_marking ORDER BY cnt DESC"
        )
        result["tempo_marking_distribution"] = dict(cur)

        # ── Year distribution (binned via Python helper) ──────────────
        cur = conn.execute("SELECT year FROM temp._scope_files")
        result["year_distribution"] = dict(_decade_bins([r[0] for r in cur]))

        # ── Top artists ───────────────────────────────────────────────
        cur = conn.execute(
            "SELECT album_artist, COUNT(*) AS cnt FROM temp._scope_files "
            "WHERE album_artist IS NOT NULL "
            "GROUP BY album_artist ORDER BY cnt DESC LIMIT 50"
        )
        result["top_artists"] = list(cur)

        # ── Top genres ────────────────────────────────────────────────
        cur = conn.execute(
            "SELECT genre, COUNT(*) AS cnt FROM temp._scope_files "
            "WHERE genre IS NOT NULL "
            "GROUP BY genre ORDER BY cnt DESC LIMIT 50"
        )
        result["top_genres"] = list(cur)

        # ── Missing data counts ──────────────────────────────────────
        missing: dict[str, int] = {}
        missing["no_bpm"] = conn.execute(
            "SELECT COUNT(*) FROM temp._scope_files WHERE bpm IS NULL"
        ).fetchone()[0]
        missing["no_key"] = conn.execute(
            "SELECT COUNT(*) FROM temp._scope_files WHERE key IS NULL"
        ).fetchone()[0]
        missing["no_genre"] = conn.execute(
            "SELECT COUNT(*) FROM temp._scope_files WHERE genre IS NULL"
        ).fetchone()[0]
        missing["no_mood"] = conn.execute(
            "SELECT COUNT(*) FROM temp._scope_files WHERE mood IS NULL"
        ).fetchone()[0]
        missing["no_tempo_marking"] = conn.execute(
            "SELECT COUNT(*) FROM temp._scope_files WHERE tempo_marking IS NULL"
        ).fetchone()[0]
        result["missing_data"] = missing

        return result
