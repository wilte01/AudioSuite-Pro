"""
Tests for audio_suite_shared.tag_helper_art

embed_artwork is a thin facade over TagHandlerFactory; tests mock the
handler so no real audio files or ffmpeg are required.

Changed in 2.6.0: the read half (F-E10) — magic-byte sniffing, pixel
measurement, extraction and the sidecar writer's keep/force contract.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from audio_suite_shared.exceptions import AudioSuiteError
from audio_suite_shared.tag_helper_art import (
    UNKNOWN_IMAGE_MIME,
    embed_artwork,
    extract_artwork,
    image_dimensions,
    sniff_image_format,
    write_artwork_sidecar,
)


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


def _png_bytes(width: int = 600, height: int = 400) -> bytes:
    """Build PNG bytes carrying a complete IHDR chunk."""
    ihdr = (
        b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x06\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )
    return b"\x89PNG\r\n\x1a\n" + (13).to_bytes(4, "big") + ihdr


class TestEmbedArtwork:
    def test_delegates_to_handler_factory(self) -> None:
        """embed_artwork must resolve a handler for the path and forward the
        JPEG bytes to its embed_artwork method."""
        handler = MagicMock()
        with patch(
            "audio_suite_shared.tag_helper_art.TagHandlerFactory.get_handler",
            return_value=handler,
        ) as mock_factory:
            embed_artwork("song.flac", b"jpeg-bytes")

        mock_factory.assert_called_once_with("song.flac")
        handler.embed_artwork.assert_called_once_with(b"jpeg-bytes")

    def test_handler_error_is_mapped_and_reraisable(self) -> None:
        """A handler failure must bubble up as an AudioSuiteError (the
        decorator re-raises by default)."""
        handler = MagicMock()
        handler.embed_artwork.side_effect = OSError("file locked")
        with patch(
            "audio_suite_shared.tag_helper_art.TagHandlerFactory.get_handler",
            return_value=handler,
        ):
            with pytest.raises(AudioSuiteError):
                embed_artwork("song.mp3", b"jpeg-bytes")

    def test_snapshots_before_embedding(self) -> None:
        """embed_artwork must snapshot current tags before embedding when an
        active undo batch is present."""
        handler = MagicMock()
        with (
            patch(
                "audio_suite_shared.tag_helper_art.record_tag_edit_snapshot"
            ) as mock_snap,
            patch(
                "audio_suite_shared.tag_helper_art.TagHandlerFactory.get_handler",
                return_value=handler,
            ),
        ):
            embed_artwork("song.flac", b"jpeg-bytes")

        mock_snap.assert_called_once_with("song.flac", "embed_artwork")
        handler.embed_artwork.assert_called_once_with(b"jpeg-bytes")


class TestSniffImageFormat:
    def test_jpeg_signature_is_named_from_the_bytes(self) -> None:
        assert sniff_image_format(_jpeg_bytes()) == ("image/jpeg", ".jpg")

    def test_png_signature_is_named_from_the_bytes(self) -> None:
        assert sniff_image_format(_png_bytes()) == ("image/png", ".png")

    def test_a_format_the_suite_cannot_name_is_not_guessed(self) -> None:
        """GIF is a real image format, but choosing ``.jpg`` for it would be a
        mislabel the user only discovers in a player."""
        assert sniff_image_format(b"GIF89a" + b"\x00" * 20) is None


class TestImageDimensions:
    def test_jpeg_frame_header_gives_the_pixel_size(self) -> None:
        assert image_dimensions(_jpeg_bytes(1080, 800)) == (1080, 800)

    def test_png_ihdr_gives_the_pixel_size(self) -> None:
        assert image_dimensions(_png_bytes(600, 400)) == (600, 400)

    def test_a_truncated_png_has_no_measurable_size(self) -> None:
        assert image_dimensions(b"\x89PNG\r\n\x1a\n\x00") is None

    def test_a_truncated_jpeg_has_no_measurable_size(self) -> None:
        assert image_dimensions(_jpeg_bytes()[:6]) is None

    def test_unknown_bytes_have_no_measurable_size(self) -> None:
        assert image_dimensions(b"GIF89a" + b"\x00" * 20) is None


class TestExtractArtwork:
    def test_returns_the_bytes_and_a_sniffed_mime(self) -> None:
        handler = MagicMock()
        handler.extract_artwork.return_value = _jpeg_bytes()
        with patch(
            "audio_suite_shared.tag_helper_art.TagHandlerFactory.get_handler",
            return_value=handler,
        ) as mock_factory:
            art = extract_artwork("song.flac")

        mock_factory.assert_called_once_with("song.flac")
        assert art == (_jpeg_bytes(), "image/jpeg")

    def test_png_bytes_are_named_png_whatever_the_container_claims(self) -> None:
        """Some writers store ``image/jpeg`` over PNG data; the bytes decide."""
        handler = MagicMock()
        handler.extract_artwork.return_value = _png_bytes()
        with patch(
            "audio_suite_shared.tag_helper_art.TagHandlerFactory.get_handler",
            return_value=handler,
        ):
            art = extract_artwork("song.mp3")

        assert art is not None
        assert art[1] == "image/png"

    def test_an_unnamed_picture_is_returned_with_the_generic_mime(self) -> None:
        handler = MagicMock()
        handler.extract_artwork.return_value = b"GIF89a" + b"\x00" * 20
        with patch(
            "audio_suite_shared.tag_helper_art.TagHandlerFactory.get_handler",
            return_value=handler,
        ):
            art = extract_artwork("song.flac")

        assert art == (b"GIF89a" + b"\x00" * 20, UNKNOWN_IMAGE_MIME)

    def test_no_artwork_returns_none(self) -> None:
        handler = MagicMock()
        handler.extract_artwork.return_value = None
        with patch(
            "audio_suite_shared.tag_helper_art.TagHandlerFactory.get_handler",
            return_value=handler,
        ):
            assert extract_artwork("song.flac") is None


class TestWriteArtworkSidecar:
    def test_jpeg_is_written_as_cover_jpg(self, tmp_path: Path) -> None:
        written = write_artwork_sidecar(tmp_path, _jpeg_bytes())

        assert written == tmp_path / "cover.jpg"
        assert written is not None
        assert written.read_bytes() == _jpeg_bytes()

    def test_png_is_written_as_cover_png(self, tmp_path: Path) -> None:
        written = write_artwork_sidecar(tmp_path, _png_bytes())

        assert written == tmp_path / "cover.png"
        assert written is not None
        assert written.read_bytes() == _png_bytes()

    def test_the_name_option_changes_the_stem_not_the_extension(
        self, tmp_path: Path
    ) -> None:
        written = write_artwork_sidecar(tmp_path, _png_bytes(), name="folder")

        assert written == tmp_path / "folder.png"

    def test_an_existing_sidecar_is_kept_untouched_without_force(
        self, tmp_path: Path
    ) -> None:
        """The curated ``cover.jpg`` must survive: bytes and mtime both."""
        curated = tmp_path / "cover.jpg"
        curated.write_bytes(b"curated-art")
        before = curated.stat().st_mtime_ns

        assert write_artwork_sidecar(tmp_path, _jpeg_bytes()) is None
        assert curated.read_bytes() == b"curated-art"
        assert curated.stat().st_mtime_ns == before

    def test_force_replaces_the_existing_sidecar(self, tmp_path: Path) -> None:
        curated = tmp_path / "cover.jpg"
        curated.write_bytes(b"curated-art")

        written = write_artwork_sidecar(tmp_path, _jpeg_bytes(), force=True)

        assert written == curated
        assert curated.read_bytes() == _jpeg_bytes()

    def test_a_name_carrying_a_path_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="bare file name"):
            write_artwork_sidecar(tmp_path, _jpeg_bytes(), name="../escape")

    def test_an_unnamed_image_is_refused_instead_of_mislabelled(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(ValueError, match="not JPEG or PNG"):
            write_artwork_sidecar(tmp_path, b"GIF89a" + b"\x00" * 20)


class TestRealFlacRoundTrip:
    def test_embedded_bytes_survive_extraction_and_sidecar_write(
        self, tmp_path: Path
    ) -> None:
        """The outcome the user sees: the same picture, on disk, as ``.jpg``."""
        from pydub import AudioSegment

        audio = tmp_path / "a.flac"
        try:
            AudioSegment.silent(duration=500).export(str(audio), format="flac")
        except Exception as exc:  # pragma: no cover - host without the encoder
            pytest.skip(f"this host cannot encode FLAC ({type(exc).__name__})")

        embed_artwork(str(audio), _jpeg_bytes())
        art = extract_artwork(str(audio))

        assert art is not None
        assert art[0] == _jpeg_bytes()
        assert image_dimensions(art[0]) == (1080, 800)
        sidecar = write_artwork_sidecar(tmp_path, art[0])
        assert sidecar is not None
        assert sidecar.read_bytes() == _jpeg_bytes()
