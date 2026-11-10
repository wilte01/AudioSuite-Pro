"""Tests for the Artwork Extractor's run (``artwork_extractor.core.extract``).

The outcome is read from disk: the sidecar's bytes, its presence or absence
after a dry run, and the run report's text.  A test that read back the counters
the run just computed could not see a sidecar written with the wrong image.

Changed in 2.6.0: new module — the Artwork Extractor's run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from artwork_extractor.core.extract import report_name, run_extraction
from audio_suite_shared.tag_helper_art import embed_artwork


def _jpeg_bytes(width: int = 1080, height: int = 800) -> bytes:
    """Build JPEG bytes carrying a real APP0 segment and SOF0 frame header."""
    app0 = (
        b"\xff\xe0"
        + (16).to_bytes(2, "big")
        + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    )
    sof = (
        b"\xff\xc0"
        + (17).to_bytes(2, "big")
        + b"\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    )
    return b"\xff\xd8" + app0 + sof


def _silent_wav(path: Path) -> None:
    """Write a short silent WAV, which carries no embedded artwork."""
    import wave

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 800)


def _tagged_flac(path: Path) -> None:
    """Write a real FLAC carrying the test JPEG, or skip without an encoder."""
    from pydub import AudioSegment

    try:
        AudioSegment.silent(duration=500).export(str(path), format="flac")
    except Exception as exc:  # pragma: no cover - host without the encoder
        pytest.skip(f"this host cannot encode FLAC ({type(exc).__name__})")
    embed_artwork(str(path), _jpeg_bytes())


class TestTheLiveRun:
    def test_the_sidecar_is_the_embedded_picture(self, tmp_path: Path) -> None:
        _tagged_flac(tmp_path / "a.flac")

        run_extraction(str(tmp_path))

        sidecar = tmp_path / "cover.jpg"
        assert sidecar.read_bytes() == _jpeg_bytes()

    def test_the_run_report_records_the_outcome(self, tmp_path: Path) -> None:
        _tagged_flac(tmp_path / "a.flac")
        payloads: list[dict[str, Any]] = []

        run_extraction(str(tmp_path), on_complete=lambda **p: payloads.append(p))

        assert payloads, "run_extraction published no completion payload"
        payload = payloads[0]
        assert payload["total"] == 1
        assert payload["extracted"] == 1
        assert payload["kept"] == 0
        assert payload["no_art"] == 0
        assert payload["errors"] == 0
        assert payload["dry_run"] is False
        report = Path(payload["report_path"])
        assert report.name == "artwork_extractor_sync_log.txt"
        text = report.read_text(encoding="utf-8")
        assert text.startswith("ARTWORK EXTRACTOR")
        assert "Mode: LIVE UPDATE" in text
        assert "[EXTRACTED]" in text
        assert "SUMMARY: files=1 extracted=1 kept=0 no_art=0 errors=0" in text

    def test_an_existing_sidecar_is_kept_without_force(self, tmp_path: Path) -> None:
        _tagged_flac(tmp_path / "a.flac")
        curated = tmp_path / "cover.jpg"
        curated.write_bytes(b"curated-art")
        before = curated.stat().st_mtime_ns

        payloads: list[dict[str, Any]] = []
        run_extraction(str(tmp_path), on_complete=lambda **p: payloads.append(p))

        assert payloads[0]["kept"] == 1
        assert payloads[0]["extracted"] == 0
        assert curated.read_bytes() == b"curated-art"
        assert curated.stat().st_mtime_ns == before

    def test_force_replaces_the_existing_sidecar(self, tmp_path: Path) -> None:
        _tagged_flac(tmp_path / "a.flac")
        (tmp_path / "cover.jpg").write_bytes(b"curated-art")

        payloads: list[dict[str, Any]] = []
        run_extraction(
            str(tmp_path), force=True, on_complete=lambda **p: payloads.append(p)
        )

        assert payloads[0]["extracted"] == 1
        assert (tmp_path / "cover.jpg").read_bytes() == _jpeg_bytes()

    def test_a_file_without_art_is_counted_not_failed(self, tmp_path: Path) -> None:
        _silent_wav(tmp_path / "a.wav")
        payloads: list[dict[str, Any]] = []

        run_extraction(str(tmp_path), on_complete=lambda **p: payloads.append(p))

        assert payloads[0]["no_art"] == 1
        assert payloads[0]["errors"] == 0
        text = Path(payloads[0]["report_path"]).read_text(encoding="utf-8")
        assert "[NO ART]" in text

    def test_recursive_reads_a_sub_folder(self, tmp_path: Path) -> None:
        sub = tmp_path / "disc1"
        sub.mkdir()
        _tagged_flac(sub / "a.flac")
        payloads: list[dict[str, Any]] = []

        run_extraction(
            str(tmp_path), recursive=True, on_complete=lambda **p: payloads.append(p)
        )

        assert payloads[0]["extracted"] == 1
        assert (sub / "cover.jpg").exists()

    def test_a_folder_of_no_audio_is_a_run_failure(self, tmp_path: Path) -> None:
        errors: list[str] = []

        run_extraction(str(tmp_path), on_error=errors.append)

        assert errors, "an empty folder must report, not publish a completion"


class TestTheDryRun:
    def test_no_sidecar_is_written(self, tmp_path: Path) -> None:
        _tagged_flac(tmp_path / "a.flac")
        payloads: list[dict[str, Any]] = []

        run_extraction(
            str(tmp_path), dry_run=True, on_complete=lambda **p: payloads.append(p)
        )

        assert payloads[0]["dry_run"] is True
        assert payloads[0]["extracted"] == 1
        assert not (tmp_path / "cover.jpg").exists(), "a dry run wrote a sidecar"

    def test_the_dry_run_report_is_its_own_file(self, tmp_path: Path) -> None:
        _tagged_flac(tmp_path / "a.flac")
        payloads: list[dict[str, Any]] = []

        run_extraction(
            str(tmp_path), dry_run=True, on_complete=lambda **p: payloads.append(p)
        )

        report = Path(payloads[0]["report_path"])
        assert report.name == "artwork_extractor_dry_run_log.txt"
        assert "Mode: DRY RUN" in report.read_text(encoding="utf-8")

    def test_an_existing_sidecar_is_reported_as_kept(self, tmp_path: Path) -> None:
        _tagged_flac(tmp_path / "a.flac")
        (tmp_path / "cover.jpg").write_bytes(b"curated-art")
        payloads: list[dict[str, Any]] = []

        run_extraction(
            str(tmp_path), dry_run=True, on_complete=lambda **p: payloads.append(p)
        )

        assert payloads[0]["kept"] == 1
        assert payloads[0]["extracted"] == 0


def test_a_read_failure_is_counted_not_raised(tmp_path: Path) -> None:
    """A corrupt file is one counted outcome; the rest of the run continues."""
    _silent_wav(tmp_path / "ok.wav")
    (tmp_path / "broken.mp3").write_bytes(b"not audio")
    payloads: list[dict[str, Any]] = []

    run_extraction(str(tmp_path), on_complete=lambda **p: payloads.append(p))

    assert payloads[0]["errors"] >= 1
    assert payloads[0]["total"] == 2


def test_the_report_name_pair_is_distinct() -> None:
    assert report_name(True) == "artwork_extractor_dry_run_log.txt"
    assert report_name(False) == "artwork_extractor_sync_log.txt"


def test_progress_is_published_per_file(tmp_path: Path) -> None:
    _silent_wav(tmp_path / "a.wav")
    _silent_wav(tmp_path / "b.wav")
    seen: list[dict[str, Any]] = []

    run_extraction(str(tmp_path), on_progress=lambda **p: seen.append(p))

    assert [item["processed"] for item in seen] == [1, 2]
