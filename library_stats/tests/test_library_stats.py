"""Tests for library_stats.library_stats — scan engine and helpers."""

from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from audio_suite_shared.exceptions import AudioFileNotFoundError
from library_stats.library_cache import LibraryCache
from library_stats.library_stats import (
    StatsReport,
    _bpm_bin,
    _classify_key_mode,
    _decade_bin,
    export_csv,
    export_json,
    scan_directory,
)

# ── _classify_key_mode ────────────────────────────────────────────────────────


class TestClassifyKeyMode:
    def test_major_short(self) -> None:
        assert _classify_key_mode("C") == ("C", "major")
        assert _classify_key_mode("F#") == ("F#", "major")
        assert _classify_key_mode("Bb") == ("Bb", "major")

    def test_minor_short(self) -> None:
        assert _classify_key_mode("Am") == ("Am", "minor")
        assert _classify_key_mode("C#m") == ("C#m", "minor")
        assert _classify_key_mode("Dbm") == ("Dbm", "minor")

    def test_major_text(self) -> None:
        assert _classify_key_mode("C major") == ("C", "major")
        assert _classify_key_mode("F# major") == ("F#", "major")

    def test_minor_text(self) -> None:
        assert _classify_key_mode("A minor") == ("A", "minor")
        assert _classify_key_mode("C# minor") == ("C#", "minor")

    def test_unicode_accidentals(self) -> None:
        assert _classify_key_mode("E\u266dm") is None
        r = _classify_key_mode("F\u266f minor")
        assert r is not None
        assert r[1] == "minor"

    def test_whitespace_stripped(self) -> None:
        assert _classify_key_mode("  G  ") == ("G", "major")

    def test_unparseable(self) -> None:
        assert _classify_key_mode("") is None
        assert _classify_key_mode("not a key") is None
        assert _classify_key_mode("X#") is None


# ── _bpm_bin ──────────────────────────────────────────────────────────────────


class TestBpmBin:
    def test_none(self) -> None:
        assert _bpm_bin(None) == "Unknown"

    def test_under_60(self) -> None:
        assert _bpm_bin(0) == "<60"
        assert _bpm_bin(59) == "<60"

    def test_60_to_79(self) -> None:
        assert _bpm_bin(60) == "60\u201379"
        assert _bpm_bin(79) == "60\u201379"

    def test_80_to_99(self) -> None:
        assert _bpm_bin(80) == "80\u201399"
        assert _bpm_bin(99) == "80\u201399"

    def test_100_to_119(self) -> None:
        assert _bpm_bin(100) == "100\u2013119"
        assert _bpm_bin(119) == "100\u2013119"

    def test_120_to_139(self) -> None:
        assert _bpm_bin(120) == "120\u2013139"
        assert _bpm_bin(139) == "120\u2013139"

    def test_140_to_159(self) -> None:
        assert _bpm_bin(140) == "140\u2013159"
        assert _bpm_bin(159) == "140\u2013159"

    def test_160_to_179(self) -> None:
        assert _bpm_bin(160) == "160\u2013179"
        assert _bpm_bin(179) == "160\u2013179"

    def test_180_plus(self) -> None:
        assert _bpm_bin(180) == "180+"
        assert _bpm_bin(999) == "180+"


# ── _decade_bin ───────────────────────────────────────────────────────────────


class TestDecadeBin:
    def test_none(self) -> None:
        assert _decade_bin(None) == "Unknown"

    def test_various_years(self) -> None:
        assert _decade_bin(1973) == "1970s"
        assert _decade_bin(1984) == "1980s"
        assert _decade_bin(1999) == "1990s"
        assert _decade_bin(2000) == "2000s"
        assert _decade_bin(2026) == "2020s"


# ── StatsReport ───────────────────────────────────────────────────────────────


class TestStatsReport:
    def test_default_construction(self) -> None:
        r = StatsReport()
        assert r.total_files == 0
        assert r.scan_path == ""

    def test_to_dict_default(self) -> None:
        d = StatsReport().to_dict()
        assert isinstance(d, dict)
        assert d["total_files"] == 0
        assert d["duration_str"] == "0.0s"
        assert d["top_artists"] == []
        assert d["top_genres"] == []

    def test_to_dict_populated(self) -> None:
        r = StatsReport(
            scan_path="/music",
            total_files=100,
            total_albums=10,
            total_artists=5,
            duration_secs=3.14,
            format_breakdown={".mp3": 80, ".flac": 20},
            bpm_distribution={"120\u2013139": 40, "100\u2013119": 30},
            key_distribution={"C": 25, "Am": 15},
            genre_distribution={"Rock": 50, "Jazz": 30},
            missing_data={"no_bpm": 5, "no_key": 10},
            top_artists=[("Artist A", 30), ("Artist B", 20)],
            top_genres=[("Rock", 50), ("Jazz", 30)],
        )
        d = r.to_dict()
        assert d["total_files"] == 100
        assert d["duration_str"] == "3.1s"
        assert d["top_artists"] == [("Artist A", 30), ("Artist B", 20)]
        assert d["top_genres"] == [("Rock", 50), ("Jazz", 30)]
        assert d["format_breakdown"][".mp3"] == 80

    def test_to_dict_top_artists_truncated(self) -> None:
        long = [(f"Artist {i}", i) for i in range(50)]
        r = StatsReport(top_artists=long)
        assert len(r.to_dict()["top_artists"]) == 20

    def test_asdict_roundtrip(self) -> None:
        r = StatsReport(total_files=42, scan_path="/test")
        d = asdict(r)
        r2 = StatsReport(**d)
        assert r2.total_files == 42
        assert r2.scan_path == "/test"


# ── scan_directory ────────────────────────────────────────────────────────────


class TestScanDirectory:
    """Tests scan_directory() with temp dirs and mocked tag readers."""

    def test_empty_directory(self, tmp_path: pytest.TempPathFactory) -> None:
        report = scan_directory(str(tmp_path))
        assert report.total_files == 0
        assert report.total_albums == 0
        assert report.total_artists == 0
        assert isinstance(report.duration_secs, float)

    def test_non_audio_files_ignored(self, tmp_path: pytest.TempPathFactory) -> None:
        (tmp_path / "readme.txt").write_text("hello")
        (tmp_path / "cover.jpg").write_bytes(b"fake jpeg")
        (tmp_path / "notes.pdf").write_bytes(b"%PDF")
        report = scan_directory(str(tmp_path))
        assert report.total_files == 0

    def test_directory_not_found_returns_empty_report(self) -> None:
        report = scan_directory("C:\\nonexistent_path_xyz_123")
        assert report.total_files == 0
        assert report.scan_path == "C:\\nonexistent_path_xyz_123"

    @patch("library_stats.core.file_processor.read_artist_album")
    @patch("library_stats.core.file_processor.read_album_artist")
    @patch("library_stats.core.file_processor.read_bpm")
    @patch("library_stats.core.file_processor.read_key")
    @patch("library_stats.core.file_processor.read_genre")
    @patch("library_stats.core.file_processor.read_mood")
    @patch("library_stats.core.file_processor.read_tempo_marking")
    @patch("library_stats.core.file_processor.read_tags_raw")
    def test_files_with_all_tags(
        self,
        mock_raw: MagicMock,
        mock_tempo: MagicMock,
        mock_mood: MagicMock,
        mock_genre: MagicMock,
        mock_key: MagicMock,
        mock_bpm: MagicMock,
        mock_album_artist: MagicMock,
        mock_artist_album: MagicMock,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        mock_artist_album.return_value = "Artist / Album"
        mock_album_artist.return_value = "TestArtist"
        mock_bpm.return_value = 128
        mock_key.return_value = "C"
        mock_genre.return_value = "Rock"
        mock_mood.return_value = "Energetic"
        mock_tempo.return_value = "Allegro"

        raw_tags = MagicMock()
        raw_tags.get.return_value = None
        mock_raw.return_value = raw_tags

        (tmp_path / "track1.mp3").write_bytes(b"fake mp3")
        (tmp_path / "track2.flac").write_bytes(b"fake flac")

        report = scan_directory(str(tmp_path))

        assert report.total_files == 2
        assert report.total_albums == 1
        assert report.total_artists == 1
        assert report.format_breakdown == {".mp3": 1, ".flac": 1}
        assert report.bpm_distribution == {"120\u2013139": 2}
        assert report.key_distribution == {"C": 2}
        assert report.genre_distribution == {"Rock": 2}
        assert report.missing_data["no_bpm"] == 0
        assert report.missing_data["no_key"] == 0
        assert report.missing_data["no_genre"] == 0

    @patch("library_stats.core.file_processor.read_artist_album")
    @patch("library_stats.core.file_processor.read_album_artist")
    @patch("library_stats.core.file_processor.read_bpm")
    @patch("library_stats.core.file_processor.read_key")
    @patch("library_stats.core.file_processor.read_genre")
    @patch("library_stats.core.file_processor.read_mood")
    @patch("library_stats.core.file_processor.read_tempo_marking")
    @patch("library_stats.core.file_processor.read_tags_raw")
    def test_files_with_missing_tags(
        self,
        mock_raw: MagicMock,
        mock_tempo: MagicMock,
        mock_mood: MagicMock,
        mock_genre: MagicMock,
        mock_key: MagicMock,
        mock_bpm: MagicMock,
        mock_album_artist: MagicMock,
        mock_artist_album: MagicMock,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        mock_artist_album.return_value = None
        mock_album_artist.return_value = None
        mock_bpm.return_value = None
        mock_key.return_value = None
        mock_genre.return_value = None
        mock_mood.return_value = None
        mock_tempo.return_value = None
        mock_raw.return_value = None

        (tmp_path / "song.mp3").write_bytes(b"fake mp3")

        report = scan_directory(str(tmp_path))

        assert report.total_files == 1
        assert report.total_albums == 0
        assert report.total_artists == 0
        assert report.missing_data["no_bpm"] == 1
        assert report.missing_data["no_key"] == 1
        assert report.missing_data["no_genre"] == 1
        assert report.missing_data["no_mood"] == 1
        assert report.missing_data["no_tempo_marking"] == 1
        assert report.bpm_distribution == {"Unknown": 1}

    @patch("library_stats.core.file_processor.read_artist_album")
    @patch("library_stats.core.file_processor.read_album_artist")
    @patch("library_stats.core.file_processor.read_bpm")
    @patch("library_stats.core.file_processor.read_key")
    @patch("library_stats.core.file_processor.read_genre")
    @patch("library_stats.core.file_processor.read_mood")
    @patch("library_stats.core.file_processor.read_tempo_marking")
    @patch("library_stats.core.file_processor.read_tags_raw")
    def test_mood_semicolon_splitting(
        self,
        mock_raw: MagicMock,
        mock_tempo: MagicMock,
        mock_mood: MagicMock,
        mock_genre: MagicMock,
        mock_key: MagicMock,
        mock_bpm: MagicMock,
        mock_album_artist: MagicMock,
        mock_artist_album: MagicMock,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        mock_artist_album.return_value = None
        mock_album_artist.return_value = None
        mock_bpm.return_value = None
        mock_key.return_value = None
        mock_genre.return_value = None
        mock_tempo.return_value = None
        mock_raw.return_value = None
        mock_mood.return_value = "Energetic; Upbeat; Driving"

        (tmp_path / "track.mp3").write_bytes(b"fake")

        report = scan_directory(str(tmp_path))
        assert report.mood_distribution == {"Energetic": 1, "Upbeat": 1, "Driving": 1}

    @patch("library_stats.core.file_processor.read_artist_album")
    @patch("library_stats.core.file_processor.read_album_artist")
    @patch("library_stats.core.file_processor.read_bpm")
    @patch("library_stats.core.file_processor.read_key")
    @patch("library_stats.core.file_processor.read_genre")
    @patch("library_stats.core.file_processor.read_mood")
    @patch("library_stats.core.file_processor.read_tempo_marking")
    @patch("library_stats.core.file_processor.read_tags_raw")
    def test_multiple_artists_and_albums(
        self,
        mock_raw: MagicMock,
        mock_tempo: MagicMock,
        mock_mood: MagicMock,
        mock_genre: MagicMock,
        mock_key: MagicMock,
        mock_bpm: MagicMock,
        mock_album_artist: MagicMock,
        mock_artist_album: MagicMock,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        mock_raw.return_value = None
        mock_bpm.return_value = 120
        mock_key.return_value = "G"
        mock_genre.return_value = "Jazz"
        mock_mood.return_value = None
        mock_tempo.return_value = "Moderato"

        artist_album_map: dict[str, str | None] = {}
        album_artist_map: dict[str, str | None] = {}

        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "a1.mp3").write_bytes(b"x")
        (sub / "a2.flac").write_bytes(b"x")
        (tmp_path / "b1.mp3").write_bytes(b"x")

        def _artist_album(p: str) -> str | None:
            parent = os.path.basename(os.path.dirname(p))
            return artist_album_map.get(parent)

        def _album_artist(p: str) -> str | None:
            parent = os.path.basename(os.path.dirname(p))
            return album_artist_map.get(parent)

        artist_album_map["sub"] = "ArtistA / AlbumX"
        album_artist_map["sub"] = "ArtistA"
        artist_album_map[""] = None
        album_artist_map[""] = None

        mock_artist_album.side_effect = _artist_album
        mock_album_artist.side_effect = _album_artist

        report = scan_directory(str(tmp_path))

        assert report.total_files == 3
        assert report.total_albums == 1
        assert report.total_artists == 1
        assert report.top_artists == [("ArtistA", 2)]

    @patch("library_stats.core.file_processor.read_artist_album")
    @patch("library_stats.core.file_processor.read_album_artist")
    @patch("library_stats.core.file_processor.read_bpm")
    @patch("library_stats.core.file_processor.read_key")
    @patch("library_stats.core.file_processor.read_genre")
    @patch("library_stats.core.file_processor.read_mood")
    @patch("library_stats.core.file_processor.read_tempo_marking")
    @patch("library_stats.core.file_processor.read_tags_raw")
    def test_key_mode_distribution(
        self,
        mock_raw: MagicMock,
        mock_tempo: MagicMock,
        mock_mood: MagicMock,
        mock_genre: MagicMock,
        mock_key: MagicMock,
        mock_bpm: MagicMock,
        mock_album_artist: MagicMock,
        mock_artist_album: MagicMock,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        mock_raw.return_value = None
        mock_bpm.return_value = 100
        mock_genre.return_value = None
        mock_mood.return_value = None
        mock_tempo.return_value = None
        mock_artist_album.return_value = None
        mock_album_artist.return_value = None

        key_map = {"major1.mp3": "C", "major2.mp3": "G", "minor1.mp3": "Am"}

        def _key_side_effect(path: str) -> str | None:
            fname = os.path.basename(path)
            return key_map.get(fname)

        mock_key.side_effect = _key_side_effect

        for fname in key_map:
            (tmp_path / fname).write_bytes(b"x")

        report = scan_directory(str(tmp_path))
        assert report.key_mode_distribution.get("major", 0) == 2
        assert report.key_mode_distribution.get("minor", 0) == 1


# ── Cache-backed scan ─────────────────────────────────────────────────────────


class TestScanDirectoryWithCache:
    """Tests scan_directory() with use_cache=True and mocked tag readers."""

    @patch("library_stats.core.file_processor.read_artist_album")
    @patch("library_stats.core.file_processor.read_album_artist")
    @patch("library_stats.core.file_processor.read_bpm")
    @patch("library_stats.core.file_processor.read_key")
    @patch("library_stats.core.file_processor.read_genre")
    @patch("library_stats.core.file_processor.read_mood")
    @patch("library_stats.core.file_processor.read_tempo_marking")
    @patch("library_stats.core.file_processor.read_tags_raw")
    def test_incremental_scan(
        self,
        mock_raw: MagicMock,
        mock_tempo: MagicMock,
        mock_mood: MagicMock,
        mock_genre: MagicMock,
        mock_key: MagicMock,
        mock_bpm: MagicMock,
        mock_album_artist: MagicMock,
        mock_artist_album: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_artist_album.return_value = ("Artist", "Album")
        mock_album_artist.return_value = "Artist"
        mock_bpm.return_value = 120
        mock_key.return_value = "C"
        mock_genre.return_value = "Rock"
        mock_mood.return_value = "Energetic"
        mock_tempo.return_value = "Allegro"
        raw_tags = MagicMock()
        raw_tags.get.return_value = None
        mock_raw.return_value = raw_tags

        db = tmp_path / "test_incremental.db"
        cache = LibraryCache(db)

        (tmp_path / "track.mp3").write_bytes(b"fake")

        # First scan — populates cache
        report1 = scan_directory(str(tmp_path), use_cache=True, cache=cache)
        assert report1.total_files == 1
        assert cache.row_count(str(tmp_path)) == 1

        # Second scan — uses cache (mtime unchanged), no tag re-reads
        mock_bpm.reset_mock()
        report2 = scan_directory(str(tmp_path), use_cache=True, cache=cache)
        assert report2.total_files == 1
        mock_bpm.assert_not_called()

        cache.close()

    @patch("library_stats.core.file_processor.read_artist_album")
    @patch("library_stats.core.file_processor.read_album_artist")
    @patch("library_stats.core.file_processor.read_bpm")
    @patch("library_stats.core.file_processor.read_key")
    @patch("library_stats.core.file_processor.read_genre")
    @patch("library_stats.core.file_processor.read_mood")
    @patch("library_stats.core.file_processor.read_tempo_marking")
    @patch("library_stats.core.file_processor.read_tags_raw")
    def test_incremental_scan_detects_new_files(
        self,
        mock_raw: MagicMock,
        mock_tempo: MagicMock,
        mock_mood: MagicMock,
        mock_genre: MagicMock,
        mock_key: MagicMock,
        mock_bpm: MagicMock,
        mock_album_artist: MagicMock,
        mock_artist_album: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_artist_album.return_value = ("Artist", "Album")
        mock_album_artist.return_value = "Artist"
        mock_bpm.return_value = 120
        mock_key.return_value = "C"
        mock_genre.return_value = "Rock"
        mock_mood.return_value = "Energetic"
        mock_tempo.return_value = "Allegro"
        raw_tags = MagicMock()
        raw_tags.get.return_value = None
        mock_raw.return_value = raw_tags

        db = tmp_path / "test_new.db"
        cache = LibraryCache(db)

        (tmp_path / "old.mp3").write_bytes(b"fake")
        scan_directory(str(tmp_path), use_cache=True, cache=cache)
        assert cache.row_count(str(tmp_path)) == 1

        # Add a new file
        (tmp_path / "new.mp3").write_bytes(b"fake")
        report = scan_directory(str(tmp_path), use_cache=True, cache=cache)
        assert report.total_files == 2
        assert cache.row_count(str(tmp_path)) == 2

        cache.close()

    @patch("library_stats.core.file_processor.read_artist_album")
    @patch("library_stats.core.file_processor.read_album_artist")
    @patch("library_stats.core.file_processor.read_bpm")
    @patch("library_stats.core.file_processor.read_key")
    @patch("library_stats.core.file_processor.read_genre")
    @patch("library_stats.core.file_processor.read_mood")
    @patch("library_stats.core.file_processor.read_tempo_marking")
    @patch("library_stats.core.file_processor.read_tags_raw")
    def test_refresh_clears_cache(
        self,
        mock_raw: MagicMock,
        mock_tempo: MagicMock,
        mock_mood: MagicMock,
        mock_genre: MagicMock,
        mock_key: MagicMock,
        mock_bpm: MagicMock,
        mock_album_artist: MagicMock,
        mock_artist_album: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_artist_album.return_value = ("Artist", "Album")
        mock_album_artist.return_value = "Artist"
        mock_bpm.return_value = 120
        mock_key.return_value = "C"
        mock_genre.return_value = "Rock"
        mock_mood.return_value = "Energetic"
        mock_tempo.return_value = "Allegro"
        raw_tags = MagicMock()
        raw_tags.get.return_value = None
        mock_raw.return_value = raw_tags

        db = tmp_path / "test_refresh.db"
        cache = LibraryCache(db)

        (tmp_path / "track.mp3").write_bytes(b"fake")

        # Initial scan populates cache
        scan_directory(str(tmp_path), use_cache=True, cache=cache)
        assert cache.row_count(str(tmp_path)) == 1

        # Refresh scan clears and re-populates
        mock_bpm.reset_mock()
        report = scan_directory(
            str(tmp_path), use_cache=True, refresh_cache=True, cache=cache
        )
        assert report.total_files == 1
        # With refresh, tags should be re-read even if mtime is same
        mock_bpm.assert_called_once()
        assert cache.row_count(str(tmp_path)) == 1

        cache.close()

    @patch("library_stats.core.file_processor.read_artist_album")
    @patch("library_stats.core.file_processor.read_album_artist")
    @patch("library_stats.core.file_processor.read_bpm")
    @patch("library_stats.core.file_processor.read_key")
    @patch("library_stats.core.file_processor.read_genre")
    @patch("library_stats.core.file_processor.read_mood")
    @patch("library_stats.core.file_processor.read_tempo_marking")
    @patch("library_stats.core.file_processor.read_tags_raw")
    def test_cache_removes_orphans(
        self,
        mock_raw: MagicMock,
        mock_tempo: MagicMock,
        mock_mood: MagicMock,
        mock_genre: MagicMock,
        mock_key: MagicMock,
        mock_bpm: MagicMock,
        mock_album_artist: MagicMock,
        mock_artist_album: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_artist_album.return_value = ("Artist", "Album")
        mock_album_artist.return_value = "Artist"
        mock_bpm.return_value = 120
        mock_key.return_value = "C"
        mock_genre.return_value = "Rock"
        mock_mood.return_value = "Energetic"
        mock_tempo.return_value = "Allegro"
        raw_tags = MagicMock()
        raw_tags.get.return_value = None
        mock_raw.return_value = raw_tags

        db = tmp_path / "test_orphan.db"
        cache = LibraryCache(db)

        (tmp_path / "track1.mp3").write_bytes(b"fake")
        (tmp_path / "track2.mp3").write_bytes(b"fake")

        scan_directory(str(tmp_path), use_cache=True, cache=cache)
        assert cache.row_count(str(tmp_path)) == 2

        # Delete track2.mp3 and re-scan
        (tmp_path / "track2.mp3").unlink()
        # track1 still has same mtime, so cached read is used
        mock_bpm.reset_mock()
        report = scan_directory(str(tmp_path), use_cache=True, cache=cache)
        assert report.total_files == 1
        mock_bpm.assert_not_called()  # No new tag reads for unchanged files
        assert cache.row_count(str(tmp_path)) == 1

        cache.close()

    def test_cache_disabled_falls_back_to_full_walk(self, tmp_path: Path) -> None:
        (tmp_path / "track.mp3").write_bytes(b"fake")
        report = scan_directory(str(tmp_path), use_cache=False)
        assert report.total_files == 1

    @patch("library_stats.core.file_processor.read_artist_album")
    @patch("library_stats.core.file_processor.read_album_artist")
    @patch("library_stats.core.file_processor.read_bpm")
    @patch("library_stats.core.file_processor.read_key")
    @patch("library_stats.core.file_processor.read_genre")
    @patch("library_stats.core.file_processor.read_mood")
    @patch("library_stats.core.file_processor.read_tempo_marking")
    @patch("library_stats.core.file_processor.read_tags_raw")
    def test_subdirectory_files_counted_in_parent_scan(
        self,
        mock_raw: MagicMock,
        mock_tempo: MagicMock,
        mock_mood: MagicMock,
        mock_genre: MagicMock,
        mock_key: MagicMock,
        mock_bpm: MagicMock,
        mock_album_artist: MagicMock,
        mock_artist_album: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Regression: files in subdirectories must appear in the parent report."""
        mock_artist_album.return_value = ("Artist", "Album")
        mock_album_artist.return_value = "Artist"
        mock_bpm.return_value = 120
        mock_key.return_value = "C"
        mock_genre.return_value = "Rock"
        mock_mood.return_value = "Energetic"
        mock_tempo.return_value = "Allegro"
        raw_tags = MagicMock()
        raw_tags.get.return_value = None
        mock_raw.return_value = raw_tags

        db = tmp_path / "test_subdir.db"
        cache = LibraryCache(db)

        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "track.mp3").write_bytes(b"fake")
        (tmp_path / "root.mp3").write_bytes(b"fake")

        report = scan_directory(str(tmp_path), use_cache=True, cache=cache)
        assert report.total_files == 2
        assert cache.row_count(str(tmp_path)) == 2

        cache.close()


# ── Export CSV / JSON ────────────────────────────────────────────────────────


class TestExportCsv:
    def test_export_csv_basic(self, tmp_path: Path) -> None:
        (tmp_path / "track1.mp3").write_bytes(b"fake")
        (tmp_path / "track2.flac").write_bytes(b"fake")
        report = scan_directory(str(tmp_path))

        out = tmp_path / "export.csv"
        export_csv(report, str(out))

        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert (
            "path,format,bpm,key,genre,mood,tempo_marking,album_artist,artist_album,year"
            in content
        )
        assert "track1.mp3" in content
        assert "track2.flac" in content

    def test_export_csv_empty_dir(self, tmp_path: Path) -> None:
        report = scan_directory(str(tmp_path))
        out = tmp_path / "empty.csv"
        export_csv(report, str(out))
        content = out.read_text(encoding="utf-8")
        assert content.strip() == (
            "path,format,bpm,key,genre,mood,tempo_marking,"
            "album_artist,artist_album,year"
        )

    def test_export_csv_missing_scan_path(self) -> None:
        report = StatsReport(scan_path="C:\\nonexistent_xyz_123_fail")
        with pytest.raises(AudioFileNotFoundError):
            export_csv(report, "ignored.csv")

    def test_export_utf8_paths(self, tmp_path: Path) -> None:
        sub = tmp_path / "\u00e9l\u00e9vation"
        sub.mkdir()
        (sub / "track.mp3").write_bytes(b"fake")
        report = scan_directory(str(tmp_path))

        out = tmp_path / "export.csv"
        export_csv(report, str(out))
        content = out.read_text(encoding="utf-8")
        assert "\u00e9l\u00e9vation" in content


class TestExportJson:
    def test_export_json_basic(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").write_bytes(b"fake")
        report = scan_directory(str(tmp_path))

        out = tmp_path / "stats.json"
        export_json(report, str(out))

        assert out.exists()
        import json as json_mod

        data = json_mod.loads(out.read_text(encoding="utf-8"))
        assert data["total_files"] == 1
        assert "format_breakdown" in data
        assert "missing_data" in data
        assert "duration_str" in data

    def test_export_json_empty(self, tmp_path: Path) -> None:
        report = StatsReport(scan_path=str(tmp_path), total_files=0)
        out = tmp_path / "empty.json"
        export_json(report, str(out))

        import json as json_mod

        data = json_mod.loads(out.read_text(encoding="utf-8"))
        assert data["total_files"] == 0
        assert data["top_artists"] == []
        assert data["top_genres"] == []

    def test_export_json_contains_aggregates(self, tmp_path: Path) -> None:
        report = StatsReport(
            scan_path=str(tmp_path),
            total_files=100,
            total_albums=10,
            total_artists=5,
            duration_secs=3.14,
            format_breakdown={".mp3": 80, ".flac": 20},
            bpm_distribution={"120\u2013139": 40},
            key_distribution={"C": 25},
            genre_distribution={"Rock": 50},
            missing_data={"no_bpm": 5, "no_key": 10},
            top_artists=[("Artist A", 30)],
            top_genres=[("Rock", 50)],
        )
        out = tmp_path / "stats.json"
        export_json(report, str(out))

        import json as json_mod

        data = json_mod.loads(out.read_text(encoding="utf-8"))
        assert data["total_files"] == 100
        assert data["total_albums"] == 10
        assert data["format_breakdown"][".mp3"] == 80
        assert data["missing_data"]["no_bpm"] == 5
        assert data["duration_str"] == "3.1s"
        assert data["top_artists"] == [["Artist A", 30]]
