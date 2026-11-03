"""
tag_helper_art.py — Artwork embedding facade function for audio files.

Part of audio_suite_shared.

When an active undo batch exists for the current thread, the current
tags are automatically snapshotted before embedding so the operation
can be reverted.

Changed in 2.4.1: imports ``TagHandlerFactory`` from the leaf
``tag_handler_factory`` module rather than from ``tag_helper_base`` (WP-2).
"""

from .batch_undo import record_tag_edit_snapshot
from .exceptions import handle_audio_errors
from .tag_handler_factory import TagHandlerFactory


@handle_audio_errors(reraise=True, context="artwork_embed")
def embed_artwork(path: str, jpeg_bytes: bytes) -> None:
    """Embed JPEG cover art in any supported audio file.

    Args:
        path:       Path to the audio file.
        jpeg_bytes: Raw JPEG image bytes to embed.
    """
    record_tag_edit_snapshot(path, "embed_artwork")
    TagHandlerFactory.get_handler(path).embed_artwork(jpeg_bytes)
