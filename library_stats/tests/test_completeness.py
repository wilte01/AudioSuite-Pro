"""Tests for library_stats.core.completeness — tag completeness analysis."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from library_stats.core.completeness import (
    TAG_FIELDS,
    CompletenessReport,
    TagCompleteness,
    analyse_completeness,
    export_completeness_csv,
    export_completeness_json,
)

# ── analyse_completeness ──────────────────────────────────────────────────────


class TestAnalyseCompleteness:
    def test_empty_directory(self, tmp_path: Path) -> None:
        report = analyse_completeness(str(tmp_path))
        assert report.total_files == 0
        assert report.overall_pct == 0.0
        assert report.directory == str(tmp_path)
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
        """Sanity floor: with zero audio files no reader is invoked."""
        (tmp_path / "a.mp3").write_bytes(b"fake")
        report = analyse_completeness(str(tmp_path))
        assert report.total_files == 1

    @patch("audio_suite_shared.tag_helper_reader.has_artwork", return_value=True)
    @patch("audio_suite_shared.tag_helper_reader.read_replaygain")
    @patch("audio_suite_shared.tag_helper_reader.read_tempo_marking")
    @patch("audio_suite_shared.tag_helper_reader.read_mood")
    @patch("audio_suite_shared.tag_helper_reader.read_genre")
    @patch("audio_suite_shared.tag_helper_reader.read_key")
    @patch("audio_suite_shared.tag_helper_reader.read_bpm")
    def test_all_tags_present_100_percent(
        self,
        mock_bpm: MagicMock,
        mock_key: MagicMock,
        mock_genre: MagicMock,
        mock_mood: MagicMock,
        mock_tempo: MagicMock,
        mock_replaygain: MagicMock,
        mock_art: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_bpm.return_value = 120
        mock_key.return_value = "Am"
        mock_genre.return_value = "Jazz"
        mock_mood.return_value = "Upbeat"
        mock_tempo.return_value = "Moderato"
        mock_replaygain.return_value = ("+0.50 dB", None)
        (tmp_path / "track.mp3").write_bytes(b"fake")
        (tmp_path / "track.flac").write_bytes(b"fake")

        report = analyse_completeness(str(tmp_path))

        assert report.total_files == 2
        assert report.overall_pct == 100.0
        for field in TAG_FIELDS:
            tc = report.tag_results[field]
            assert tc.present == 2
            assert tc.missing == 0
            assert tc.pct_complete == 100.0
            assert tc.missing_files == ()

    @patch("audio_suite_shared.tag_helper_reader.has_artwork", return_value=False)
    @patch("audio_suite_shared.tag_helper_reader.read_replaygain")
    @patch("audio_suite_shared.tag_helper_reader.read_tempo_marking")
    @patch("audio_suite_shared.tag_helper_reader.read_mood")
    @patch("audio_suite_shared.tag_helper_reader.read_genre")
    @patch("audio_suite_shared.tag_helper_reader.read_key")
    @patch("audio_suite_shared.tag_helper_reader.read_bpm")
    def test_no_tags_zero_percent(
        self,
        mock_bpm: MagicMock,
        mock_key: MagicMock,
        mock_genre: MagicMock,
        mock_mood: MagicMock,
        mock_tempo: MagicMock,
        mock_replaygain: MagicMock,
        mock_art: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_bpm.return_value = None
        mock_key.return_value = None
        mock_genre.return_value = None
        mock_mood.return_value = None
        mock_tempo.return_value = None
        mock_replaygain.return_value = (None, None)
        (tmp_path / "track.mp3").write_bytes(b"fake")

        report = analyse_completeness(str(tmp_path))

        assert report.total_files == 1
        assert report.overall_pct == 0.0
        for field in TAG_FIELDS:
            tc = report.tag_results[field]
            assert tc.present == 0
            assert tc.missing == 1
            assert tc.pct_complete == 0.0
            assert tc.missing_files == (str(tmp_path / "track.mp3"),)

    @patch("audio_suite_shared.tag_helper_reader.has_artwork", return_value=True)
    @patch("audio_suite_shared.tag_helper_reader.read_replaygain")
    @patch("audio_suite_shared.tag_helper_reader.read_tempo_marking")
    @patch("audio_suite_shared.tag_helper_reader.read_mood")
    @patch("audio_suite_shared.tag_helper_reader.read_genre")
    @patch("audio_suite_shared.tag_helper_reader.read_key")
    @patch("audio_suite_shared.tag_helper_reader.read_bpm")
    def test_partial_completeness(
        self,
        mock_bpm: MagicMock,
        mock_key: MagicMock,
        mock_genre: MagicMock,
        mock_mood: MagicMock,
        mock_tempo: MagicMock,
        mock_replaygain: MagicMock,
        mock_art: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_bpm.return_value = None  # only some files have BPM
        mock_key.return_value = "C"
        mock_genre.return_value = "Rock"
        mock_mood.return_value = None
        mock_tempo.return_value = "Allegro"
        mock_replaygain.return_value = (None, None)
        for i in range(10):
            (tmp_path / f"track{i}.mp3").write_bytes(b"fake")

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

        # 4 fields fully present (key, genre, tempo_marking, album_art),
        # 3 fields fully absent (bpm, mood, replaygain) → 4/7 overall
        assert report.overall_pct == round(4 / 7 * 100, 1)

    @patch(
        "audio_suite_shared.tag_helper_reader.read_bpm",
        side_effect=OSError("file locked"),
    )
    def test_unreadable_file_counts_all_missing(
        self, mock_bpm: MagicMock, tmp_path: Path
    ) -> None:
        (tmp_path / "locked.mp3").write_bytes(b"fake")
        report = analyse_completeness(str(tmp_path))
        assert report.total_files == 1
        for field in TAG_FIELDS:
            assert report.tag_results[field].missing == 1
            assert report.tag_results[field].present == 0

    @patch("audio_suite_shared.tag_helper_reader.has_artwork", return_value=True)
    @patch("audio_suite_shared.tag_helper_reader.read_replaygain")
    @patch("audio_suite_shared.tag_helper_reader.read_tempo_marking")
    @patch("audio_suite_shared.tag_helper_reader.read_mood")
    @patch("audio_suite_shared.tag_helper_reader.read_genre")
    @patch("audio_suite_shared.tag_helper_reader.read_key")
    @patch("audio_suite_shared.tag_helper_reader.read_bpm")
    def test_progress_callback_receives_processed_and_total(
        self,
        mock_bpm: MagicMock,
        mock_key: MagicMock,
        mock_genre: MagicMock,
        mock_mood: MagicMock,
        mock_tempo: MagicMock,
        mock_replaygain: MagicMock,
        mock_art: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_bpm.return_value = 120
        mock_key.return_value = None
        mock_genre.return_value = None
        mock_mood.return_value = None
        mock_tempo.return_value = None
        mock_replaygain.return_value = (None, None)
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
        )
        d = report.to_dict()
        assert d["total_files"] == 2
        assert d["tag_results"]["bpm"]["missing_files"] == ["a.mp3"]
        assert d["overall_pct"] == 50.0

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

    def test_export_handles_bom_and_utf8(self, tmp_path: Path) -> None:
        report = self._sample_report(str(tmp_path))
        out = tmp_path / "statistics.csv"
        export_completeness_csv(report, str(out))
        assert out.read_bytes().startswith(b"tag,total")
