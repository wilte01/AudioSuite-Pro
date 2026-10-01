"""Tests for audio_fingerprinter.core.tag_writer."""

from __future__ import annotations

from unittest.mock import patch

from audio_fingerprinter.core.tag_writer import write_acoustid_tags
from audio_suite_shared.exceptions import AudioSuiteError, AudioTagError


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
    def test_mapped_base_error_keeps_tuple_contract(self, mock_write):
        # Regression: an error the shared layer maps to the AudioSuiteError
        # base (not the AudioTagError subclass — e.g. mutagen's
        # FLACNoHeaderError) used to escape the narrow catch and be
        # swallowed into None by the decorator, crashing every caller that
        # unpacks the declared (ok, message) tuple.
        mock_write.side_effect = AudioSuiteError("mapped base error")
        ok, msg = write_acoustid_tags("/x/track.mp3", "FP123", "acoustid_1")
        assert ok is False
        assert "mapped base error" in msg.lower()

    @patch("audio_fingerprinter.core.tag_writer._write_acoustid")
    def test_unexpected_exception_swallowed_by_decorator(self, mock_write):
        mock_write.side_effect = RuntimeError("unexpected")
        result = write_acoustid_tags("/x/track.mp3", "FP123", "acoustid_1")
        assert result is None
