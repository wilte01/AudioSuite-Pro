"""Tests for album_art_sync.core.ranker — dimension detection and area ranking."""

from __future__ import annotations

import unittest.mock as mock

from album_art_sync.core.ranker import (
    RankedCandidate,
    get_image_dimensions,
    rank_by_area,
)


class TestGetImageDimensions:
    """HTTP and header-parsing edge cases for get_image_dimensions."""

    @staticmethod
    def _png_ihdr(width: int, height: int) -> bytes:
        """Build a minimal valid PNG header with given dimensions."""
        import struct
        import zlib

        sig = b"\x89PNG\r\n\x1a\n"
        # IHDR chunk: 4 bytes length, 'IHDR', 4+4 byte dims, 5 byte metadata
        ihdr_data = struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"
        crc = struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF)
        length = struct.pack(">I", 13)
        return sig + length + b"IHDR" + ihdr_data + crc

    @staticmethod
    def _jpeg_sof0(width: int, height: int) -> bytes:
        """Build a minimal valid JPEG with SOF0 marker for given dims."""
        import struct

        soi = b"\xff\xd8"
        # APP0 (JFIF) marker
        app0 = (
            b"\xff\xe0"
            + struct.pack(">H", 16)
            + b"JFIF\x00\x01\x01\x01\x00\x48\x00\x48\x00\x00"
        )
        # SOF0 marker
        sof0_data = b"\x08" + struct.pack(">HH", height, width) + b"\x03\x01\x11\x00"
        sof0_len = struct.pack(">H", 8 + 3)
        sof0 = b"\xff\xc0" + sof0_len + sof0_data
        return soi + app0 + sof0

    def test_png_dimensions(self) -> None:
        header = self._png_ihdr(800, 600)
        with mock.patch("album_art_sync.core.ranker._read_chunk", return_value=header):
            result = get_image_dimensions("https://example.com/img.png")
        assert result == (800, 600)

    def test_jpeg_dimensions(self) -> None:
        header = self._jpeg_sof0(1200, 800)
        with mock.patch("album_art_sync.core.ranker._read_chunk", return_value=header):
            result = get_image_dimensions("https://example.com/img.jpg")
        assert result == (1200, 800)

    def test_returns_none_on_http_failure(self) -> None:
        with mock.patch("album_art_sync.core.ranker._read_chunk", return_value=None):
            result = get_image_dimensions("https://example.com/missing.jpg")
        assert result is None

    def test_returns_none_on_unknown_format(self) -> None:
        with mock.patch(
            "album_art_sync.core.ranker._read_chunk", return_value=b"NOTANIMAGE"
        ):
            result = get_image_dimensions("https://example.com/file.xyz")
        assert result is None

    def test_gif_not_supported_returns_none(self) -> None:
        gif_sig = b"GIF89a" + b"\x00" * 10
        with mock.patch("album_art_sync.core.ranker._read_chunk", return_value=gif_sig):
            result = get_image_dimensions("https://example.com/file.gif")
        assert result is None


class TestRankByArea:
    """Sorting stability and edge cases for rank_by_area."""

    def test_sorts_descending_by_score(self) -> None:
        candidates = [
            RankedCandidate(0, "url_a", "Small", 200, 200, 40000.0, 1.0),
            RankedCandidate(1, "url_b", "Large", 800, 600, 480000.0, 1.0),
            RankedCandidate(2, "url_c", "Medium", 500, 500, 250000.0, 1.0),
        ]
        ranked = rank_by_area(candidates)
        assert [r.title for r in ranked] == ["Large", "Medium", "Small"]

    def test_empty_list_returns_empty(self) -> None:
        assert rank_by_area([]) == []

    def test_single_candidate_returns_solo(self) -> None:
        c = RankedCandidate(0, "u", "Solo", 300, 300, 90000.0, 1.0)
        assert rank_by_area([c]) == [c]

    def test_equal_area_sorted_by_match_score(self) -> None:
        a = RankedCandidate(
            0, "u1", "Dark Side of the Moon (Remaster)", 400, 400, 160000.0, 0.95
        )
        b = RankedCandidate(1, "u2", "Dark Side of the Moon", 400, 400, 160000.0, 1.0)
        result = rank_by_area([a, b])
        assert result[0].title == "Dark Side of the Moon"
        assert result[0].match_score == 1.0

    def test_match_score_then_area(self) -> None:
        a = RankedCandidate(0, "u1", "Abbey Road (Remaster)", 500, 500, 250000.0, 0.95)
        b = RankedCandidate(1, "u2", "Abbey Road", 800, 800, 640000.0, 0.95)
        c = RankedCandidate(2, "u3", "Abbey Road", 400, 400, 160000.0, 1.0)
        result = rank_by_area([a, b, c])
        # c has best match (1.0) despite smallest area
        assert result[0].title == "Abbey Road"
        assert result[0].match_score == 1.0
        # then by area descending among same match_score
        assert result[1].width == 800  # b, larger area first
        assert result[1].title == "Abbey Road"
        assert result[2].width == 500  # a, smaller area
