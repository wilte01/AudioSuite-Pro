"""
art_writer.py
=============
Unified artwork write API for all supported audio files.

Provides :func:`embed_artwork_into_file` which accepts pre-encoded JPEG
bytes and writes them into the target file's metadata structure, delegating
the actual write to the shared ``audio_suite_shared.tag_helper_art`` facade
so the suite's single canonical embed path (including undo snapshots) is
used for every format.
"""

import io
from pathlib import Path

from PIL import Image

from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.exceptions import AudioFormatError
from audio_suite_shared.tag_helper_art import embed_artwork


def embed_artwork_into_file(path: Path, jpeg_bytes: bytes, file_extension: str) -> str:
    """Write *jpeg_bytes* as embedded artwork into *path*.

    The appropriate metadata container is created or replaced with the
    supplied image data.  Existing metadata other than the artwork is
    preserved.

    Args:
        path: Absolute path to the audio file.
        jpeg_bytes: JPEG-encoded image bytes to embed.
        file_extension: Any extension in ``SUPPORTED_EXTENSIONS`` (case-insensitive).

    Returns:
        A human-readable one-line status string.

    Raises:
        AudioFormatError: When *file_extension* is not in SUPPORTED_EXTENSIONS.
        AudioSuiteError: When the shared facade fails to open, write, or
            save the tags (mapped from mutagen/OSError by the facade).
    """
    ext = file_extension.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        msg = f"Unsupported file extension: {file_extension}"
        raise AudioFormatError(msg)

    embed_artwork(str(path), jpeg_bytes)

    with Image.open(io.BytesIO(jpeg_bytes)) as img:
        size_str = f"{img.size[0]}\u00d7{img.size[1]}"
    return f"Embedded artwork written ({size_str})."
