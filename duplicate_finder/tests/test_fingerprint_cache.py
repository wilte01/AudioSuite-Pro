"""Tests for the fingerprint cache.

The cache is what makes the tool usable on a real library, so every rule that
decides whether a stored row may be trusted is pinned here: the ``(mtime, size)``
stamp (a same-mtime replacement is *not* fresh), the directory scope, orphan
sweeping, and one write per scan rather than one per file.

Changed in 2.3.0: new duplicate-detection tool (backlog F-02): fingerprint distance,
clustering, cache and quarantine.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from duplicate_finder.core.fingerprint_cache import (
    CACHE_PATH_ENV,
    FingerprintCache,
    default_cache_path,
)
from duplicate_finder.core.models import FingerprintRecord


def record(
    path: str,
    *,
    mtime: float = 1000.0,
    size: int = 500,
    words: tuple[int, ...] = (1, 2, 3),
) -> FingerprintRecord:
    """Return a record with the stamp a test compares against.

    Args:
        path: Absolute path the record describes.
        mtime: Modification time half of the stamp.
        size: Size half of the stamp.
        words: The fingerprint words.

    Returns:
        The record.
    """
    return FingerprintRecord(
        path=path,
        duration=12.5,
        words=words,
        size=size,
        mtime=mtime,
        sample_rate=44100,
        channels=2,
        bitrate_kbps=320.0,
        lossless=False,
        artist="Artist",
        title="Title",
    )


@pytest.fixture()
def cache(tmp_path: Path) -> FingerprintCache:
    """An open cache in *tmp_path*, closed when the test ends."""
    with FingerprintCache(tmp_path / "cache.db") as opened:
        yield opened


class TestDefaultPath:
    """One canonical location, overridable for tests."""

    def test_the_environment_override_wins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "elsewhere.db"
        monkeypatch.setenv(CACHE_PATH_ENV, str(target))

        assert default_cache_path() == target

    def test_without_an_override_it_is_one_canonical_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(CACHE_PATH_ENV, raising=False)

        path = default_cache_path()

        assert path.name == "duplicate_cache.db"
        assert path.parent.name == ".audiosuite"

    def test_a_blank_override_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CACHE_PATH_ENV, "   ")

        assert default_cache_path().name == "duplicate_cache.db"


class TestRoundTrip:
    """What is stored is what comes back."""

    def test_a_stored_record_round_trips_every_field(
        self, cache: FingerprintCache
    ) -> None:
        stored = record("D:/music/song.flac", words=(7, 8, 9))

        cache.upsert(stored)
        loaded = cache.load_under("D:/music")

        # The path is normalised on the way in, so it is the only field that
        # differs from the record that was handed over.
        assert list(loaded) == ["D:\\music\\song.flac"]
        assert loaded["D:\\music\\song.flac"] == replace(
            stored, path="D:\\music\\song.flac"
        )

    def test_an_upsert_replaces_the_previous_row(self, cache: FingerprintCache) -> None:
        cache.upsert(record("D:/music/a.flac", words=(1,)))
        cache.upsert(record("D:/music/a.flac", words=(2, 3)))

        loaded = cache.load_under("D:/music")

        assert cache.count() == 1
        assert loaded["D:\\music\\a.flac"].words == (2, 3)

    def test_a_batch_writes_once_and_rolls_back_on_error(
        self, cache: FingerprintCache
    ) -> None:
        with pytest.raises(RuntimeError):
            with cache.batch():
                cache.upsert(record("D:/music/a.flac"))
                raise RuntimeError("scan failed")

        assert cache.count() == 0

    def test_a_completed_batch_keeps_its_rows(self, cache: FingerprintCache) -> None:
        with cache.batch():
            cache.upsert(record("D:/music/a.flac"))
            cache.upsert(record("D:/music/b.flac"))

        assert cache.count() == 2


class TestFreshness:
    """The stamp rule: both halves must match (the R-13 lesson)."""

    def test_an_unchanged_file_is_fresh(self, cache: FingerprintCache) -> None:
        stored = record("D:/music/a.flac", mtime=1000.0, size=500)

        assert cache.is_fresh(stored, 1000.0, 500)

    def test_a_new_size_is_stale_even_with_the_same_mtime(
        self, cache: FingerprintCache
    ) -> None:
        # A copy that preserves timestamps keeps the mtime, so an mtime-only
        # comparison would answer "cached" for a file whose audio changed.
        stored = record("D:/music/a.flac", mtime=1000.0, size=500)

        assert not cache.is_fresh(stored, 1000.0, 501)

    def test_a_touched_file_is_stale(self, cache: FingerprintCache) -> None:
        stored = record("D:/music/a.flac", mtime=1000.0, size=500)

        assert not cache.is_fresh(stored, 1001.0, 500)


class TestScope:
    """``load_under`` and ``remove_orphans`` stay inside their directory."""

    def test_a_sibling_directory_with_a_shared_prefix_is_not_loaded(
        self, cache: FingerprintCache
    ) -> None:
        cache.upsert(record("D:/music/a.flac"))
        cache.upsert(record("D:/musicology/b.flac"))

        loaded = cache.load_under("D:/music")

        assert list(loaded) == ["D:\\music\\a.flac"]

    def test_nested_directories_are_loaded(self, cache: FingerprintCache) -> None:
        cache.upsert(record("D:/music/album/one/a.flac"))

        assert list(cache.load_under("D:/music")) == ["D:\\music\\album\\one\\a.flac"]

    def test_an_orphan_row_is_removed_and_a_visited_one_kept(
        self, cache: FingerprintCache
    ) -> None:
        cache.upsert(record("D:/music/a.flac"))
        cache.upsert(record("D:/music/gone.flac"))

        removed = cache.remove_orphans("D:/music", {"D:\\music\\a.flac"})

        assert removed == 1
        assert list(cache.load_under("D:/music")) == ["D:\\music\\a.flac"]

    def test_removing_nothing_is_not_an_error(self, cache: FingerprintCache) -> None:
        cache.upsert(record("D:/music/a.flac"))

        assert cache.remove_orphans("D:/music", {"D:\\music\\a.flac"}) == 0

    def test_clear_empties_the_cache(self, cache: FingerprintCache) -> None:
        cache.upsert(record("D:/music/a.flac"))

        cache.clear()

        assert cache.count() == 0


class TestCorruption:
    """A damaged row is a cache miss, never a crash."""

    def test_an_unparseable_word_list_is_skipped(self, cache: FingerprintCache) -> None:
        cache.upsert(record("D:/music/a.flac"))
        cache.upsert(record("D:/music/b.flac"))
        connection = cache._connect()
        connection.execute(
            "UPDATE fingerprints SET words = 'not,numbers' WHERE path = ?",
            ["D:\\music\\a.flac"],
        )
        connection.commit()

        loaded = cache.load_under("D:/music")

        assert list(loaded) == ["D:\\music\\b.flac"]

    def test_the_file_is_a_real_sqlite_database(self, cache: FingerprintCache) -> None:
        cache.upsert(record("D:/music/a.flac"))

        with sqlite3.connect(str(cache.db_path)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }

        assert "fingerprints" in tables

    def test_auto_vacuum_is_enabled(self, cache: FingerprintCache) -> None:
        cache.upsert(record("D:/music/a.flac"))

        with sqlite3.connect(str(cache.db_path)) as connection:
            mode = connection.execute("PRAGMA auto_vacuum").fetchone()

        assert mode is not None and mode[0] == 1
