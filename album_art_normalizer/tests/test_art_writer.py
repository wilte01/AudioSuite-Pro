"""
tests/test_art_writer.py
Unit tests for album_art_normalizer/core/art_writer.py — the unified
artwork embed API for MP3 (ID3/APIC) and FLAC (Vorbis Picture).

The shared ``embed_artwork`` facade is mocked; the JPEG payload is a real
in-memory image so the reported dimensions are deterministic.

Run with:
    pytest tests/test_art_writer.py -v
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from album_art_normalizer.core.art_writer import embed_artwork_into_file
from audio_suite_shared.exceptions import AudioFormatError, AudioIOError, AudioTagError


def _jpeg_bytes(width: int = 4, height: int = 2) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buf, format="JPEG")
    return buf.getvalue()


_JPEG = _jpeg_bytes()
_PATH = Path("/fake/cover.mp3")


class TestDispatch:
    def test_mp3_extension_routes_to_shared_embed(self) -> None:
        with patch("album_art_normalizer.core.art_writer.embed_artwork") as embed:
            result = embed_artwork_into_file(_PATH, _JPEG, ".mp3")
        embed.assert_called_once_with(str(_PATH), _JPEG)
        assert result == "Embedded artwork written (4\u00d72)."

    def test_extension_is_case_insensitive(self) -> None:
        with patch("album_art_normalizer.core.art_writer.embed_artwork") as embed:
            assert embed_artwork_into_file(_PATH, _JPEG, ".MP3") == (
                "Embedded artwork written (4\u00d72)."
            )
        embed.assert_called_once_with(str(_PATH), _JPEG)

    def test_flac_extension_routes_to_shared_embed(self) -> None:
        flac_path = Path("/fake/x.flac")
        with patch("album_art_normalizer.core.art_writer.embed_artwork") as embed:
            result = embed_artwork_into_file(flac_path, _JPEG, ".flac")
        embed.assert_called_once_with(str(flac_path), _JPEG)
        assert result == "Embedded artwork written (4\u00d72)."

    def test_unsupported_extension_raises_format_error(self) -> None:
        with patch("album_art_normalizer.core.art_writer.embed_artwork") as embed:
            with pytest.raises(AudioFormatError, match="Unsupported"):
                embed_artwork_into_file(Path("/fake/x.txt"), _JPEG, ".txt")
        embed.assert_not_called()

    @pytest.mark.parametrize(
        "ext",
        [".ogg", ".opus", ".m4a", ".mp4", ".wav", ".aiff", ".aif"],
    )
    def test_all_supported_extensions_route_to_shared_embed(self, ext: str) -> None:
        path = Path(f"/fake/x{ext}")
        with patch("album_art_normalizer.core.art_writer.embed_artwork") as embed:
            result = embed_artwork_into_file(path, _JPEG, ext)
        embed.assert_called_once_with(str(path), _JPEG)
        assert result == "Embedded artwork written (4\u00d72)."


class TestSharedErrors:
    def test_io_error_propagates_unchanged(self) -> None:
        with patch(
            "album_art_normalizer.core.art_writer.embed_artwork",
            side_effect=AudioIOError("locked"),
        ):
            with pytest.raises(AudioIOError, match="locked"):
                embed_artwork_into_file(_PATH, _JPEG, ".mp3")

    def test_tag_error_propagates_unchanged(self) -> None:
        with patch(
            "album_art_normalizer.core.art_writer.embed_artwork",
            side_effect=AudioTagError("bad tags"),
        ):
            with pytest.raises(AudioTagError, match="bad tags"):
                embed_artwork_into_file(_PATH, _JPEG, ".flac")
