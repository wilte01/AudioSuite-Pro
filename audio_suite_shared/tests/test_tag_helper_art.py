"""
Tests for audio_suite_shared.tag_helper_art

embed_artwork is a thin facade over TagHandlerFactory; tests mock the
handler so no real audio files or ffmpeg are required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from audio_suite_shared.exceptions import AudioSuiteError
from audio_suite_shared.tag_helper_art import embed_artwork


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
