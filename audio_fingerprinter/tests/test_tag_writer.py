"""Tests for audio_fingerprinter.core.tag_writer."""

from __future__ import annotations

from unittest.mock import patch

from audio_fingerprinter.core.tag_writer import write_acoustid_tags
from audio_suite_shared.exceptions import AudioTagError


class TestWriteAcoustidTags:
    @patch("audio_fingerprinter.core.tag_writer._write_acoustid")
    def test_success(self, mock_write):
        ok, msg = write_acoustid_tags("/x/track.mp3", "FP123", "acoustid_1")
        assert ok is True
        assert "written" in msg.lower()
        mock_write.assert_called_once_with("/x/track.mp3", "FP123", "acoustid_1")

    @patch("audio_fingerprinter.core.tag_writer._write_acoustid")
    def test_failure_returns_false(self, mock_write):
        mock_write.side_effect = AudioTagError("mutagen missing")
        ok, msg = write_acoustid_tags("/x/track.mp3", "FP123", "acoustid_1")
        assert ok is False
        assert "mutagen" in msg.lower()

    @patch("audio_fingerprinter.core.tag_writer._write_acoustid")
    def test_unexpected_exception_swallowed_by_decorator(self, mock_write):
        mock_write.side_effect = RuntimeError("unexpected")
        result = write_acoustid_tags("/x/track.mp3", "FP123", "acoustid_1")
        assert result is None
