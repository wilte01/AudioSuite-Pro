"""Tests for the Artwork Gaps engine (``library_stats.core.artwork_gaps``).

The outcome is read from disk: the sidecar's bytes, its absence after a dry run,
and the run report's text.  A test that read back the counters the pass just
computed could not see a cover written from the wrong picture.

Changed in 2.6.0: new module — the Artwork Gaps engine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from audio_suite_shared.tag_helper_art import embed_artwork
from library_stats.core.artwork_gaps import (
    ARTWORK_REPORT_NAME,
    STATUS_ERROR,
    STATUS_EXTRACTED,
    STATUS_KEPT,
    STATUS_NO_ART,
    missing_artwork_albums,
    run_cover_extraction,
)
from library_stats.core.completeness import analyse_completeness

_JPEG = (
    b"\xff\xd8"
    + b"\xff\xe0"
    + (16).to_bytes(2, "big")
    + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    + b"\xff\xc0"
    + (17).to_bytes(2, "big")
    + b"\x08"
    + (800).to_bytes(2, "big")
    + (1080).to_bytes(2, "big")
    + b"\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
)


def _flac(path: Path, *, album: str, art: bool = False) -> None:
    """Write a real FLAC with the album tag, optionally carrying the JPEG."""
    from mutagen.flac import FLAC
    from pydub import AudioSegment

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        AudioSegment.silent(duration=300).export(str(path), format="flac")
    except Exception as exc:  # pragma: no cover - host without the encoder
        pytest.skip(f"this host cannot encode FLAC ({type(exc).__name__})")
    audio = FLAC(str(path))
    audio["album"] = [album]
    audio.save()
    if art:
        embed_artwork(str(path), _JPEG)


def _library(tmp_path: Path) -> Path:
    """Two albums: one half-covered, one with no artwork at all."""
    _flac(tmp_path / "Covered" / "01.flac", album="Covered", art=True)
    _flac(tmp_path / "Covered" / "02.flac", album="Covered")
    _flac(tmp_path / "Bare" / "01.flac", album="Bare")
    return tmp_path


class TestAlbumSelection:
    def test_lists_only_albums_with_missing_artwork(self, tmp_path: Path) -> None:
        root = _library(tmp_path)
        completeness = analyse_completeness(str(root))

        gaps = missing_artwork_albums(completeness)

        assert [(gap.album, gap.missing_files, gap.total_files) for gap in gaps] == [
            ("Bare", 1, 1),
            ("Covered", 1, 2),
        ]

    def test_each_gap_names_the_folder_to_write_into(self, tmp_path: Path) -> None:
        root = _library(tmp_path)

        gaps = missing_artwork_albums(analyse_completeness(str(root)))

        folders = {gap.album: gap.folders for gap in gaps}
        assert folders["Bare"] == (str(root / "Bare"),)
        assert folders["Covered"] == (str(root / "Covered"),)

    def test_a_fully_covered_library_has_no_gaps(self, tmp_path: Path) -> None:
        _flac(tmp_path / "Album" / "01.flac", album="Album", art=True)

        assert missing_artwork_albums(analyse_completeness(str(tmp_path))) == ()


class TestTheCoverPass:
    def _run(self, root: Path, **kwargs: Any) -> Any:
        return run_cover_extraction(
            missing_artwork_albums(analyse_completeness(str(root))),
            source=str(root),
            **kwargs,
        )

    def test_the_sidecar_is_the_picture_a_file_already_has(
        self, tmp_path: Path
    ) -> None:
        root = _library(tmp_path)

        run = self._run(root)

        sidecar = root / "Covered" / "cover.jpg"
        assert sidecar.read_bytes() == _JPEG
        assert not (root / "Bare" / "cover.jpg").exists()
        statuses = {r.album: r.status for r in run.results}
        assert statuses == {"Covered": STATUS_EXTRACTED, "Bare": STATUS_NO_ART}
        assert (run.extracted, run.kept, run.no_art, run.errors) == (1, 0, 1, 0)

    def test_a_dry_run_writes_the_report_and_no_sidecar(self, tmp_path: Path) -> None:
        root = _library(tmp_path)

        run = self._run(root, dry_run=True)

        assert run.dry_run is True
        assert not (root / "Covered" / "cover.jpg").exists()
        assert run.extracted == 1
        text = Path(run.report_path).read_text(encoding="utf-8")
        assert "Mode: DRY RUN" in text

    def test_an_existing_sidecar_is_kept_without_force(self, tmp_path: Path) -> None:
        root = _library(tmp_path)
        curated = root / "Covered" / "cover.jpg"
        curated.write_bytes(b"curated-art")

        run = self._run(root)

        assert curated.read_bytes() == b"curated-art"
        covered = [r for r in run.results if r.album == "Covered"][0]
        assert covered.status == STATUS_KEPT

    def test_force_replaces_an_existing_sidecar(self, tmp_path: Path) -> None:
        root = _library(tmp_path)
        curated = root / "Covered" / "cover.jpg"
        curated.write_bytes(b"curated-art")

        run = self._run(root, force=True)

        assert curated.read_bytes() == _JPEG
        assert [r.status for r in run.results if r.album == "Covered"] == [
            STATUS_EXTRACTED
        ]

    def test_the_report_records_the_run(self, tmp_path: Path) -> None:
        root = _library(tmp_path)

        run = self._run(root)

        report = Path(run.report_path)
        assert report.name == ARTWORK_REPORT_NAME
        text = report.read_text(encoding="utf-8")
        assert text.startswith("LIBRARY STATISTICS ARTWORK REPORT")
        assert "Mode: LIVE UPDATE" in text
        assert "Covered | EXTRACTED" in text
        bare_line = next(
            line for line in text.splitlines() if line.startswith("  Bare |")
        )
        assert "| NO_ART |" in bare_line
        assert bare_line.endswith("| no embedded artwork")
        assert "SUMMARY: albums=2 extracted=1 kept=0 no_art=1 errors=0" in text

    def test_progress_is_published_per_folder(self, tmp_path: Path) -> None:
        root = _library(tmp_path)
        payloads: list[dict[str, Any]] = []

        self._run(root, on_progress=lambda **kw: payloads.append(kw))

        assert [p["processed"] for p in payloads] == [1, 2]
        assert all(p["total"] == 2 for p in payloads)

    def test_an_album_with_no_folder_recorded_is_an_error(self, tmp_path: Path) -> None:
        from library_stats.core.artwork_gaps import AlbumArtworkGap

        gap = AlbumArtworkGap(album="Ghost", folders=(), total_files=1, missing_files=1)

        run = run_cover_extraction([gap], source=str(tmp_path))

        assert run.errors == 1
        assert run.results[0].status == STATUS_ERROR
