"""Tests for the CUE Sheet Generator's run and its report.

Every lock here reads the artefact the user opens: the ``.cue`` through the
shared parser, the report from its file.  Asserting the run's own return value
would only prove the run agrees with itself.

Changed in 2.6.0: new module (PLAN_2026-11-03_2.6.0_feature_wave_2.md F-E8).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from audio_suite_shared import cue_generator
from audio_suite_shared.cue_parser import parse_cue_file
from cue_sheet.core.export import REPORT_NAMES, report_name, run_export


def _tracks(folder: Path, names: tuple[str, ...] = ("01 - One.flac", "02 - Two.flac")):
    """Create placeholder audio files the sheet can describe."""
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in names:
        path = folder / name
        path.write_bytes(b"not-a-flac")
        paths.append(path)
    return paths


class TestReportNames:
    def test_each_mode_has_its_own_report(self) -> None:
        assert report_name(True) == "cue_sheet_dry_run_log.txt"
        assert report_name(False) == "cue_sheet_sync_log.txt"
        assert REPORT_NAMES[True] != REPORT_NAMES[False]


class TestLiveRun:
    def test_it_writes_the_sheet_the_parser_reads_back(self, tmp_path: Path) -> None:
        _tracks(tmp_path)

        run_export(str(tmp_path), title="Gig", performer="The Band")

        parsed = parse_cue_file(tmp_path / "album.cue")
        assert parsed.title == "Gig"
        assert parsed.performer == "The Band"
        assert [entry.filename for entry in parsed.files] == [
            "01 - One.flac",
            "02 - Two.flac",
        ]
        # One FILE block per track: each offset is relative to its own file.
        for entry in parsed.files:
            assert len(entry.tracks) == 1
            assert entry.tracks[0].index01.start_ms == 0
        assert [entry.tracks[0].number for entry in parsed.files] == [1, 2]

    def test_the_report_records_the_run_and_the_sheet(self, tmp_path: Path) -> None:
        _tracks(tmp_path)

        run_export(str(tmp_path), title="Gig")

        text = (tmp_path / REPORT_NAMES[False]).read_text(encoding="utf-8")
        assert text.startswith("CUE SHEET GENERATOR")
        assert "Mode: LIVE UPDATE" in text
        assert f"Sheet: {tmp_path / 'album.cue'}" in text
        assert "SUMMARY: tracks=2 written=1 errors=0" in text
        # The sheet itself is part of the report, so the record shows what was
        # written rather than only that something was.
        assert 'FILE "01 - One.flac" FLAC' in text

    def test_it_honours_a_named_output_path(self, tmp_path: Path) -> None:
        _tracks(tmp_path)
        target = tmp_path / "named.cue"

        run_export(str(tmp_path), output=str(target))

        assert target.exists()
        assert not (tmp_path / "album.cue").exists()

    def test_the_completion_payload_names_what_was_written(
        self, tmp_path: Path
    ) -> None:
        _tracks(tmp_path)
        payloads: list[dict[str, Any]] = []

        run_export(str(tmp_path), on_complete=lambda **kw: payloads.append(kw))

        assert len(payloads) == 1
        payload = payloads[0]
        assert payload["tracks"] == 2
        assert payload["processed"] == payload["total"] == 2
        assert payload["errors"] == 0
        assert payload["dry_run"] is False
        assert payload["output"] == str(tmp_path / "album.cue")


class TestDryRun:
    def test_it_writes_the_report_and_no_sheet(self, tmp_path: Path) -> None:
        _tracks(tmp_path)
        payloads: list[dict[str, Any]] = []

        run_export(
            str(tmp_path), dry_run=True, on_complete=lambda **kw: payloads.append(kw)
        )

        assert not (tmp_path / "album.cue").exists()
        text = (tmp_path / REPORT_NAMES[True]).read_text(encoding="utf-8")
        assert "Mode: DRY RUN" in text
        assert "SUMMARY: tracks=2 written=0 errors=0" in text
        assert payloads[0]["dry_run"] is True


class TestRefusals:
    def test_a_duplicate_track_number_is_refused_and_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _tracks(tmp_path)
        monkeypatch.setattr(
            cue_generator,
            "read_editable_tags",
            lambda _path: {"track": "1"},
        )
        errors: list[str] = []

        run_export(str(tmp_path), on_error=errors.append)

        assert len(errors) == 1
        assert "Track number 01" in errors[0]
        assert not (tmp_path / "album.cue").exists()
        assert not (tmp_path / REPORT_NAMES[False]).exists()

    def test_an_empty_folder_is_refused(self, tmp_path: Path) -> None:
        folder = tmp_path / "empty"
        folder.mkdir()
        errors: list[str] = []

        run_export(str(folder), on_error=errors.append)

        assert errors and "No supported audio files" in errors[0]
        assert not (folder / "album.cue").exists()
