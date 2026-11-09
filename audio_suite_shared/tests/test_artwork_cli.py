"""
tests/test_artwork_cli.py — the ``artwork`` command group (F-E10).

Locks the two user-visible outcomes: ``extract`` writes the album's picture
beside it as a sidecar (and never overwrites one without ``--force``), and
``report`` names the files with no artwork without touching a byte.

Changed in 2.6.0: new file - F-E10's CLI surface.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

import audio_suite_shared.artwork_cli  # noqa: F401  (registers the group)
from audio_suite_shared.cli_base import cli
from audio_suite_shared.cli_schema import validate_payload
from audio_suite_shared.tag_helper_art import embed_artwork

#: A minimal JPEG carrying a real frame header: 1080x800.
JPEG_BYTES = (
    b"\xff\xd8"
    b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xc0\x00\x11\x08\x03\x20\x04\x38\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
)


def _jpeg_bytes(width: int = 1080, height: int = 800) -> bytes:
    """Return JPEG bytes whose frame header declares *width* x *height*."""
    if (width, height) == (1080, 800):
        return JPEG_BYTES
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


def _flac(path: Path) -> Path:
    """Write a real one-second FLAC, skipping when the host cannot encode."""
    from pydub import AudioSegment

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        AudioSegment.silent(duration=1000).export(str(path), format="flac")
    except Exception as exc:  # pragma: no cover - host without the encoder
        pytest.skip(f"this host cannot encode FLAC ({type(exc).__name__})")
    return path


def _payload(result) -> dict:
    """Parse a ``--json`` run and assert it conforms to its schema."""
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert validate_payload(data["command"], data) == []
    return data


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestExtract:
    def test_writes_the_album_sidecar_from_the_embedded_picture(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        album = tmp_path / "album"
        audio = _flac(album / "01 song.flac")
        embed_artwork(str(audio), _jpeg_bytes())

        result = runner.invoke(cli, ["artwork", "extract", str(album), "--json"])

        data = _payload(result)
        assert data["tool"] == "artwork"
        assert (data["extracted"], data["kept"], data["no_art"]) == (1, 0, 0)
        sidecar = album / "cover.jpg"
        assert sidecar.read_bytes() == _jpeg_bytes()

    def test_an_existing_sidecar_is_kept_without_force(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        album = tmp_path / "album"
        audio = _flac(album / "01 song.flac")
        embed_artwork(str(audio), _jpeg_bytes())
        curated = album / "cover.jpg"
        curated.write_bytes(b"curated-art")
        before = curated.stat().st_mtime_ns

        result = runner.invoke(cli, ["artwork", "extract", str(album), "--json"])

        data = _payload(result)
        assert (data["extracted"], data["kept"]) == (0, 1)
        assert curated.read_bytes() == b"curated-art"
        assert curated.stat().st_mtime_ns == before

    def test_force_replaces_the_existing_sidecar(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        album = tmp_path / "album"
        audio = _flac(album / "01 song.flac")
        embed_artwork(str(audio), _jpeg_bytes())
        (album / "cover.jpg").write_bytes(b"curated-art")

        result = runner.invoke(
            cli, ["artwork", "extract", str(album), "--force", "--json"]
        )

        data = _payload(result)
        assert (data["extracted"], data["kept"]) == (1, 0)
        assert (album / "cover.jpg").read_bytes() == _jpeg_bytes()

    def test_a_file_without_artwork_is_reported_not_failed(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        album = tmp_path / "album"
        _flac(album / "01 song.flac")

        result = runner.invoke(cli, ["artwork", "extract", str(album), "--json"])

        data = _payload(result)
        assert data["no_art"] == 1
        assert data["extracted"] == 0
        assert not (album / "cover.jpg").exists()

    def test_a_folder_with_no_audio_is_an_error(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()

        result = runner.invoke(cli, ["artwork", "extract", str(empty)])

        assert result.exit_code == 1
        assert "no supported audio files" in result.output


class TestReport:
    def test_counts_the_files_without_artwork(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        album = tmp_path / "album"
        with_art = _flac(album / "01 song.flac")
        embed_artwork(str(with_art), _jpeg_bytes())
        _flac(album / "02 song.flac")

        result = runner.invoke(cli, ["artwork", "report", str(album), "--json"])

        data = _payload(result)
        # ``report`` has no ``--dry`` flag, so it publishes ``dry_run`` false
        # like every command without a mode; it is read-only by construction.
        assert data["dry_run"] is False
        assert data["without_art"] == 1
        assert data["oversized"] == 0
        assert data["missing_art"][0]["path"].endswith("02 song.flac")

    def test_reports_the_picture_size_and_dimensions(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        album = tmp_path / "album"
        embed_artwork(str(_flac(album / "01 song.flac")), _jpeg_bytes(3000, 3000))

        result = runner.invoke(
            cli,
            ["artwork", "report", str(album), "--min-dimension", "2000", "--json"],
        )

        data = _payload(result)
        assert data["oversized"] == 1
        assert data["oversized_art"][0]["bytes"] == len(_jpeg_bytes(3000, 3000))
        assert data["oversized_art"][0]["width"] == 3000
        assert data["oversized_art"][0]["height"] == 3000

    def test_the_report_changes_no_file(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        album = tmp_path / "album"
        embed_artwork(str(_flac(album / "01 song.flac")), _jpeg_bytes())
        audio = album / "01 song.flac"
        audio_before = (audio.read_bytes(), audio.stat().st_mtime_ns)
        listing_before = sorted(p.name for p in album.iterdir())

        runner.invoke(cli, ["artwork", "report", str(album)])

        assert (audio.read_bytes(), audio.stat().st_mtime_ns) == audio_before
        assert sorted(p.name for p in album.iterdir()) == listing_before

    def test_a_wav_without_an_artwork_container_is_not_an_error(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """WAV/AIFF must report ``has_art=False`` rather than fail the run."""
        from pydub import AudioSegment

        album = tmp_path / "album"
        album.mkdir()
        try:
            AudioSegment.silent(duration=500).export(str(album / "a.wav"), format="wav")
        except Exception as exc:  # pragma: no cover - host without ffmpeg
            pytest.skip(f"this host cannot encode WAV ({type(exc).__name__})")

        result = runner.invoke(cli, ["artwork", "report", str(album), "--json"])

        data = _payload(result)
        assert data["errors"] == 0
        assert data["without_art"] == 1
