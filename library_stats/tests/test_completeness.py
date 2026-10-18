"""Tests for library_stats.core.completeness — tag completeness analysis.

Changed in 1.3.0: the per-file read is one ``TagHandlerFactory.get_handler``
load (PLAN D40), so the fixtures now drive a mocked handler instead of the
seven ``tag_helper_reader`` module functions. Adds coverage for the five new
primary fields, the single-load contract and the per-album tallies.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from library_stats.core.completeness import (
    TAG_FIELDS,
    UNKNOWN_ALBUM,
    AlbumCompleteness,
    CompletenessReport,
    TagCompleteness,
    analyse_completeness,
    export_completeness_csv,
    export_completeness_json,
)

_GET_HANDLER = "audio_suite_shared.tag_helper_base.TagHandlerFactory.get_handler"


def _handler(**fields: Any) -> MagicMock:
    """Return a mocked tag handler populated from keyword *fields*.

    Only the fields a test names are present; everything else is ``None`` (or
    ``(None, None)`` for ReplayGain), which is the "tag missing" shape.
    """
    handler = MagicMock()
    handler.read_editable_tags.return_value = {
        "title": fields.get("title"),
        "artist": fields.get("artist"),
        "album": fields.get("album"),
        "album_artist": fields.get("album_artist"),
        "track": fields.get("track_number"),
        "year": fields.get("year"),
        "genre": fields.get("editable_genre"),
        "comment": None,
    }
    handler.read_bpm.return_value = fields.get("bpm")
    handler.read_key.return_value = fields.get("key")
    handler.read_genre.return_value = fields.get("genre")
    handler.read_mood.return_value = fields.get("mood")
    handler.read_tempo_marking.return_value = fields.get("tempo_marking")
    handler.has_artwork.return_value = fields.get("album_art", False)
    handler.read_replaygain.return_value = fields.get("replaygain", (None, None))
    handler.read_album_artist.return_value = fields.get("album_artist")
    return handler


FULL_TAGS: dict[str, Any] = {
    "title": "Track",
    "artist": "Artist",
    "album": "Album",
    "album_artist": "Album Artist",
    "track_number": "1/10",
    "year": "1999",
    "bpm": 120,
    "key": "Am",
    "genre": "Jazz",
    "mood": "Upbeat",
    "tempo_marking": "Moderato",
    "album_art": True,
    "replaygain": ("+0.50 dB", None),
}


# ── analyse_completeness ──────────────────────────────────────────────────────


class TestAnalyseCompleteness:
    def test_empty_directory(self, tmp_path: Path) -> None:
        report = analyse_completeness(str(tmp_path))
        assert report.total_files == 0
        assert report.overall_pct == 0.0
        assert report.directory == str(tmp_path)
        assert report.album_results == ()
        for field in TAG_FIELDS:
            tc = report.tag_results[field]
            assert tc.total == 0
            assert tc.present == 0
            assert tc.missing == 0
            assert tc.pct_complete == 0.0

    def test_non_audio_files_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "readme.txt").write_text("hello")
        (tmp_path / "cover.jpg").write_bytes(b"fake")
        report = analyse_completeness(str(tmp_path))
        assert report.total_files == 0

    def test_directory_not_found(self, tmp_path: Path) -> None:
        report = analyse_completeness(str(tmp_path / "missing"))
        assert report.total_files == 0
        assert report.overall_pct == 0.0

    def test_all_tags_present_no_reader_calls(self, tmp_path: Path) -> None:
        """Sanity floor: with zero audio files no handler is built."""
        (tmp_path / "a.mp3").write_bytes(b"fake")
        with patch(_GET_HANDLER) as get_handler:
            get_handler.side_effect = OSError("unreadable fixture")
            report = analyse_completeness(str(tmp_path))
        assert report.total_files == 1

    def test_all_tags_present_100_percent(self, tmp_path: Path) -> None:
        (tmp_path / "track.mp3").write_bytes(b"fake")
        (tmp_path / "track.flac").write_bytes(b"fake")

        with patch(_GET_HANDLER, return_value=_handler(**FULL_TAGS)):
            report = analyse_completeness(str(tmp_path))

        assert report.total_files == 2
        assert report.overall_pct == 100.0
        for field in TAG_FIELDS:
            tc = report.tag_results[field]
            assert tc.present == 2
            assert tc.missing == 0
            assert tc.pct_complete == 100.0
            assert tc.missing_files == ()

    def test_no_tags_zero_percent(self, tmp_path: Path) -> None:
        (tmp_path / "track.mp3").write_bytes(b"fake")

        with patch(_GET_HANDLER, return_value=_handler()):
            report = analyse_completeness(str(tmp_path))

        assert report.total_files == 1
        assert report.overall_pct == 0.0
        for field in TAG_FIELDS:
            tc = report.tag_results[field]
            assert tc.present == 0
            assert tc.missing == 1
            assert tc.pct_complete == 0.0
            assert tc.missing_files == (str(tmp_path / "track.mp3"),)

    def test_blank_text_tags_count_as_missing(self, tmp_path: Path) -> None:
        """A whitespace-only title is not a title."""
        (tmp_path / "track.mp3").write_bytes(b"fake")

        with patch(_GET_HANDLER, return_value=_handler(title="   ", artist="")):
            report = analyse_completeness(str(tmp_path))

        assert report.tag_results["title"].missing == 1
        assert report.tag_results["artist"].missing == 1

    def test_five_primary_fields_are_tracked(self, tmp_path: Path) -> None:
        (tmp_path / "track.mp3").write_bytes(b"fake")

        with patch(_GET_HANDLER, return_value=_handler(**FULL_TAGS)):
            report = analyse_completeness(str(tmp_path))

        for field in ("title", "artist", "album", "track_number", "year"):
            assert field in report.tag_results
            assert report.tag_results[field].present == 1

    @pytest.mark.parametrize(
        "field", ["title", "artist", "album", "track_number", "year"]
    )
    def test_each_primary_field_can_be_missing(
        self, tmp_path: Path, field: str
    ) -> None:
        (tmp_path / "track.mp3").write_bytes(b"fake")
        tags = dict(FULL_TAGS)
        tags[field] = None

        with patch(_GET_HANDLER, return_value=_handler(**tags)):
            report = analyse_completeness(str(tmp_path))

        assert report.tag_results[field].missing == 1
        # Everything else is still complete: the fields are independent.
        assert report.tag_results["title"].present == (0 if field == "title" else 1)

    def test_one_handler_load_per_file(self, tmp_path: Path) -> None:
        """The whole point of D40: 12 fields, one file load."""
        (tmp_path / "a.mp3").write_bytes(b"fake")
        (tmp_path / "b.mp3").write_bytes(b"fake")

        with patch(_GET_HANDLER, return_value=_handler(**FULL_TAGS)) as get_handler:
            analyse_completeness(str(tmp_path))

        assert get_handler.call_count == 2

    def test_partial_completeness(self, tmp_path: Path) -> None:
        # Present: title, artist, album, track_number, year, key, genre,
        # tempo_marking, album_art (9 of 12); missing: bpm, mood, replaygain.
        tags = dict(FULL_TAGS)
        tags["bpm"] = None
        tags["mood"] = None
        tags["replaygain"] = (None, None)
        for i in range(10):
            (tmp_path / f"track{i}.mp3").write_bytes(b"fake")

        with patch(_GET_HANDLER, return_value=_handler(**tags)):
            report = analyse_completeness(str(tmp_path))

        bpm = report.tag_results["bpm"]
        assert bpm.total == 10
        assert bpm.present == 0
        assert bpm.missing == 10
        assert bpm.pct_complete == 0.0
        assert len(bpm.missing_files) == 10

        mood = report.tag_results["mood"]
        assert mood.present == 0
        assert mood.missing == 10

        key = report.tag_results["key"]
        assert key.present == 10
        assert key.pct_complete == 100.0

        art = report.tag_results["album_art"]
        assert art.present == 10
        assert art.pct_complete == 100.0

        assert report.overall_pct == round(9 / len(TAG_FIELDS) * 100, 1)

    def test_unreadable_file_counts_all_missing(self, tmp_path: Path) -> None:
        (tmp_path / "locked.mp3").write_bytes(b"fake")
        with patch(_GET_HANDLER, side_effect=OSError("file locked")):
            report = analyse_completeness(str(tmp_path))
        assert report.total_files == 1
        for field in TAG_FIELDS:
            assert report.tag_results[field].missing == 1
            assert report.tag_results[field].present == 0

    def test_progress_callback_receives_processed_and_total(
        self, tmp_path: Path
    ) -> None:
        with patch(_GET_HANDLER, return_value=_handler(bpm=120)):
            for i in range(3):
                (tmp_path / f"track{i}.mp3").write_bytes(b"fake")

            calls: list[tuple[int, int]] = []
            report = analyse_completeness(
                str(tmp_path), progress_callback=lambda p, t: calls.append((p, t))
            )
        assert calls == [(1, 1), (2, 2), (3, 3)]
        assert report.total_files == 3

    def test_accepts_pathlike(self, tmp_path: Path) -> None:
        report = analyse_completeness(tmp_path)
        assert report.directory == str(tmp_path)


# ── Per-album tallies (heatmap source) ────────────────────────────────────────


class TestAlbumResults:
    def _by_path(self, tmp_path: Path) -> Any:
        """Serve a different handler per file so albums differ."""
        complete = _handler(**FULL_TAGS)

        def factory(path: str) -> MagicMock:
            if "good" in path:
                return complete
            return _handler(artist="Artist", album="Album", album_artist="Artist")

        return factory

    def test_albums_are_grouped_and_ordered_worst_first(self, tmp_path: Path) -> None:
        (tmp_path / "healthy.mp3").write_bytes(b"x")
        (tmp_path / "good.mp3").write_bytes(b"x")
        (tmp_path / "bare.mp3").write_bytes(b"x")

        good = _handler(**FULL_TAGS)

        def factory(path: str) -> MagicMock:
            if path.endswith("bare.mp3"):
                return _handler(artist="Bare", album="Empty")
            return good

        with patch(_GET_HANDLER, side_effect=factory):
            report = analyse_completeness(str(tmp_path))

        assert [a.album for a in report.album_results] == [
            "Bare \u2014 Empty",
            "Album Artist \u2014 Album",
        ]
        worst = report.album_results[0]
        assert worst.total_files == 1
        assert worst.missing["bpm"] == 1
        # Only artist and album are present, so exactly 2 of 12 checks pass.
        assert worst.pct_complete == round(2 / len(TAG_FIELDS) * 100, 1)

    def test_files_without_album_are_grouped_once(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / "b.mp3").write_bytes(b"x")

        with patch(_GET_HANDLER, return_value=_handler(title="T")):
            report = analyse_completeness(str(tmp_path))

        assert len(report.album_results) == 1
        assert report.album_results[0].album == UNKNOWN_ALBUM
        assert report.album_results[0].total_files == 2
        assert report.album_results[0].missing["title"] == 0

    def test_pct_missing_and_complete(self) -> None:
        album = AlbumCompleteness(
            album="A \u2014 B",
            total_files=4,
            missing={"title": 1, "bpm": 2},
        )
        assert album.pct_missing("title") == 25.0
        assert album.pct_missing("title") == 25.0
        assert album.pct_missing("key") == 0.0
        checks = 4 * len(TAG_FIELDS)
        expected = round((checks - 3) / checks * 100.0, 1)
        assert album.pct_complete == expected

    def test_album_pct_missing_with_no_files(self) -> None:
        album = AlbumCompleteness(album=UNKNOWN_ALBUM, total_files=0)
        assert album.pct_missing("title") == 0.0
        assert album.pct_complete == 0.0


# ── Dataclass helpers ─────────────────────────────────────────────────────────


class TestDataclasses:
    def test_tag_completeness_label(self) -> None:
        tc = TagCompleteness(
            field="album_art",
            total=1,
            present=1,
            missing=0,
            pct_complete=100.0,
        )
        assert tc.label == "Album Art"

    def test_new_field_labels(self) -> None:
        for field, label in (
            ("title", "Title"),
            ("artist", "Artist"),
            ("album", "Album"),
            ("track_number", "Track Number"),
            ("year", "Year"),
        ):
            tc = TagCompleteness(
                field=field, total=1, present=1, missing=0, pct_complete=100.0
            )
            assert tc.label == label

    def test_report_to_dict(self) -> None:
        report = CompletenessReport(
            directory="/music",
            total_files=2,
            tag_results={
                "bpm": TagCompleteness(
                    field="bpm",
                    total=2,
                    present=1,
                    missing=1,
                    pct_complete=50.0,
                    missing_files=("a.mp3",),
                )
            },
            overall_pct=50.0,
            duration_secs=1.5,
            album_results=(
                AlbumCompleteness(
                    album="Artist \u2014 Album",
                    total_files=2,
                    missing={"bpm": 1},
                ),
            ),
        )
        d = report.to_dict()
        assert d["total_files"] == 2
        assert d["tag_results"]["bpm"]["missing_files"] == ["a.mp3"]
        assert d["overall_pct"] == 50.0
        assert d["album_results"][0]["album"] == "Artist \u2014 Album"
        assert d["album_results"][0]["missing"]["bpm"] == 1

    def test_frozen_dataclasses(self) -> None:
        tc = TagCompleteness(
            field="bpm", total=1, present=0, missing=1, pct_complete=0.0
        )
        with pytest.raises(FrozenInstanceError):
            tc.present = 5  # type: ignore[misc]


# ── Export ────────────────────────────────────────────────────────────────────


class TestCompletenessExports:
    def _sample_report(self, directory: str) -> CompletenessReport:
        return CompletenessReport(
            directory=directory,
            total_files=2,
            tag_results={
                field: TagCompleteness(
                    field=field,
                    total=2,
                    present=1,
                    missing=1,
                    pct_complete=50.0,
                    missing_files=tuple([f"{directory}{field}.mp3"]),
                )
                for field in TAG_FIELDS
            },
            overall_pct=50.0,
        )

    def test_export_completeness_csv(self, tmp_path: Path) -> None:
        report = self._sample_report(str(tmp_path))
        out = tmp_path / "complete.csv"
        export_completeness_csv(report, str(out))

        content = out.read_text(encoding="utf-8")
        assert "tag,total,present,missing,pct_complete" in content
        for field in TAG_FIELDS:
            assert report.tag_results[field].label in content
        assert ",2,1,1,50.0" in content

    def test_export_completeness_json(self, tmp_path: Path) -> None:
        report = self._sample_report(str(tmp_path))
        out = tmp_path / "complete.json"
        export_completeness_json(report, str(out))

        import json as json_mod

        data = json_mod.loads(out.read_text(encoding="utf-8"))
        assert data["total_files"] == 2
        assert data["tag_results"]["album_art"]["missing_files"]
        assert data["album_results"] == []

    def test_export_handles_bom_and_utf8(self, tmp_path: Path) -> None:
        report = self._sample_report(str(tmp_path))
        out = tmp_path / "statistics.csv"
        export_completeness_csv(report, str(out))
        assert out.read_bytes().startswith(b"tag,total")
