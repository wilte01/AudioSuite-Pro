"""
tag_helper_art.py — Artwork facade functions for audio files.

Part of audio_suite_shared.

When an active undo batch exists for the current thread, the current
tags are automatically snapshotted before embedding so the operation
can be reverted.

Changed in 2.4.1: imports ``TagHandlerFactory`` from the leaf
``tag_handler_factory`` module rather than from ``tag_helper_base`` (WP-2).

Changed in 2.6.0: the read half (F-E10).  ``extract_artwork`` returns the
embedded picture and its mime type, ``image_dimensions`` measures it, and
``write_artwork_sidecar`` writes it beside the album as ``cover.jpg`` or
``cover.png``.  The extension and the mime both come from the image's **magic
bytes**, never from the mime the container claims: some writers store
``image/jpeg`` over PNG data, and a ``.jpg`` file holding PNG bytes is the kind
of lie a user only discovers when a player rejects it.
"""

from __future__ import annotations

import os
from pathlib import Path

from .batch_undo import record_tag_edit_snapshot
from .exceptions import handle_audio_errors
from .tag_handler_factory import TagHandlerFactory

#: Recognised image signatures as ``(magic, mime, extension)``, checked in
#: order.  Only the two containers the suite writes itself are named.
IMAGE_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
)

#: The mime an extractor reports for a picture whose bytes match no signature.
UNKNOWN_IMAGE_MIME = "application/octet-stream"

#: JPEG start-of-frame markers that carry the frame's height and width.
_JPEG_SOF_MARKERS = frozenset(
    {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
)


def sniff_image_format(data: bytes) -> tuple[str, str] | None:
    """Return ``(mime, extension)`` for *data*, or None for an unknown image.

    Args:
        data: The picture bytes as they were stored in the file.

    Returns:
        The mime type and file extension the bytes themselves declare, or None
        when the signature is not one this suite writes.
    """
    for magic, mime, extension in IMAGE_SIGNATURES:
        if data.startswith(magic):
            return mime, extension
    return None


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    """Return a PNG's ``(width, height)`` from its IHDR chunk.

    Args:
        data: PNG bytes beginning with the eight-byte signature.

    Returns:
        The pixel size, or None when the IHDR chunk is truncated.
    """
    if len(data) < 24 or data[12:16] != b"IHDR":
        return None
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if width <= 0 or height <= 0:
        return None
    return width, height


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    """Return a JPEG's ``(width, height)`` from its first start-of-frame marker.

    Args:
        data: JPEG bytes beginning with ``\\xff\\xd8\\xff``.

    Returns:
        The pixel size, or None when no complete frame header is present.
    """
    offset = 2
    size = len(data)
    while offset + 3 < size:
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 1 >= size:
            return None
        length = int.from_bytes(data[offset : offset + 2], "big")
        if length < 2 or offset + length > size:
            return None
        if marker in _JPEG_SOF_MARKERS and offset + 7 <= size:
            height = int.from_bytes(data[offset + 3 : offset + 5], "big")
            width = int.from_bytes(data[offset + 5 : offset + 7], "big")
            if width <= 0 or height <= 0:
                return None
            return width, height
        offset += length
    return None


def image_dimensions(data: bytes) -> tuple[int, int] | None:
    """Return the pixel size of an embedded picture, or None if it cannot.

    Args:
        data: JPEG or PNG bytes.

    Returns:
        ``(width, height)``, or None when the format is unknown or the header
        is incomplete.
    """
    fmt = sniff_image_format(data)
    if fmt is None:
        return None
    if fmt[1] == ".png":
        return _png_dimensions(data)
    return _jpeg_dimensions(data)


@handle_audio_errors(reraise=True, context="artwork_extract")
def extract_artwork(path: str) -> tuple[bytes, str] | None:
    """Return the file's embedded cover picture and its mime type.

    The bytes are read through the format's own handler, so this is the one
    extraction path (a second mutagen read would be a private copy of the
    container's artwork logic).

    Args:
        path: Path to the audio file.

    Returns:
        ``(picture_bytes, mime)``: the mime is sniffed from the bytes, and is
        :data:`UNKNOWN_IMAGE_MIME` for a picture this suite cannot name.  None
        when the file carries no artwork at all.

    Raises:
        AudioSuiteError: If the file cannot be read or its tags are corrupt.
    """
    data = TagHandlerFactory.get_handler(path).extract_artwork()
    if not data:
        return None
    fmt = sniff_image_format(data)
    return data, fmt[0] if fmt else UNKNOWN_IMAGE_MIME


def write_artwork_sidecar(
    folder: str | os.PathLike[str],
    data: bytes,
    *,
    name: str = "cover",
    force: bool = False,
) -> Path | None:
    """Write *data* beside the album as ``<name>.<ext>``, chosen by its bytes.

    Args:
        folder: The album folder the audio file lives in.
        data: The picture bytes to write.
        name: Base name without an extension; must be a bare file name, so a
            value can never redirect the write outside *folder*.
        force: Replace an existing sidecar.  When False an existing file is
            left exactly as it is (its bytes and mtime untouched).

    Returns:
        The path written, or None when a sidecar already existed and *force*
        was not given.  None therefore means "kept what was there", never "no
        artwork": a file with no artwork has nothing to pass here.

    Raises:
        ValueError: If *name* is not a bare file name, or *data* is not a JPEG
            or PNG, because then no extension could be chosen honestly.
        OSError: If the sidecar cannot be written.
    """
    if not name or Path(name).name != name:
        raise ValueError(f"sidecar name must be a bare file name, got {name!r}")
    fmt = sniff_image_format(data)
    if fmt is None:
        raise ValueError(
            "the embedded artwork is not JPEG or PNG, so no sidecar extension "
            "can be chosen"
        )
    target = Path(folder) / f"{name}{fmt[1]}"
    if target.exists() and not force:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


@handle_audio_errors(reraise=True, context="artwork_embed")
def embed_artwork(path: str, jpeg_bytes: bytes) -> None:
    """Embed JPEG cover art in any supported audio file.

    Args:
        path:       Path to the audio file.
        jpeg_bytes: Raw JPEG image bytes to embed.
    """
    record_tag_edit_snapshot(path, "embed_artwork")
    TagHandlerFactory.get_handler(path).embed_artwork(jpeg_bytes)
