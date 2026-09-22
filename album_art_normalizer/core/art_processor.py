"""
art_processor.py
================
Image and audio processing logic for album artwork management.

Provides image helpers (crop, resize, encode), per-format audio processors
for MP3 and FLAC, and folder.jpg normalisation.

The per-format processors (process_mp3_artwork, process_flac_artwork) import
their mutagen dependencies from ``album_art_normalizer`` at call time so that
tests can patch ``album_art_normalizer.MP3`` / ``album_art_normalizer.FLAC`` via
``unittest.mock.patch`` without requiring a circular-import workaround.
"""

import io
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    from PIL import Image, UnidentifiedImageError
except ImportError:  # pragma: no cover
    sys.exit("Pillow is not installed.  Run: pip install Pillow")

from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS  # noqa: F401
from audio_suite_shared.constants import JPEG_QUALITY
from audio_suite_shared.tag_helper_art import embed_artwork

FOLDER_JPG_TARGET: tuple[int, int] = (1000, 1000)

ALLOWED_EMBEDDED_SIZES: tuple[tuple[int, int], ...] = (
    (600, 600),
    (800, 800),
    (1000, 1000),
    (1200, 1200),
)

RESOLUTION_LABELS: tuple[str, ...] = tuple(
    f"{w}\u00d7{h}" for w, h in ALLOWED_EMBEDDED_SIZES
)

RESOLUTION_MAP: dict[str, tuple[int, int]] = {
    label: size for label, size in zip(RESOLUTION_LABELS, ALLOWED_EMBEDDED_SIZES)
}


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class AlbumArtError(Exception):
    """Base exception for all album-art processing failures."""


class AudioTagReadError(AlbumArtError):
    """Raised when audio metadata cannot be opened or parsed."""


class AudioTagWriteError(AlbumArtError):
    """Raised when updated metadata cannot be written back to disk."""


class ImageDecodeError(AlbumArtError):
    """Raised when embedded or file image data cannot be decoded."""


class FolderImageError(AlbumArtError):
    """Raised when folder.jpg cannot be read or written."""


# ---------------------------------------------------------------------------
# Immutable data containers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProcessingResult:
    """Immutable summary produced at the end of a processing run.

    Attributes:
        total_files: Number of audio files examined.
        images_updated: Number of files whose embedded artwork was rewritten.
        errors: Number of files that produced an unrecoverable error.
    """

    total_files: int
    images_updated: int
    errors: int


@dataclass(frozen=True)
class ImageResizeSpec:
    """Encapsulates a validated resize instruction.

    Attributes:
        source_size: Original (width, height) before processing.
        target_size: Desired (width, height) after processing.
        needs_crop: True when the source aspect ratio is not 1:1.
    """

    source_size: tuple[int, int]
    target_size: tuple[int, int]
    needs_crop: bool = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "needs_crop", self.source_size[0] != self.source_size[1]
        )


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------


def center_crop_to_square(img: Image.Image) -> Image.Image:
    """Crop *img* to a centred square region without stretching.

    If the image is already square, the original object is returned unchanged.

    Args:
        img: Any Pillow ``Image`` object.

    Returns:
        A square ``Image`` object cropped from the centre of *img*.
    """
    width, height = img.size
    if width == height:
        return img
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return img.crop((left, top, left + side, top + side))


def load_image_from_bytes(data: bytes) -> Image.Image:
    """Decode raw bytes into a Pillow ``Image`` (RGB mode).

    Args:
        data: Raw bytes of a JPEG, PNG, or other Pillow-supported image.

    Returns:
        RGB-mode ``Image`` object.

    Raises:
        ImageDecodeError: When the bytes cannot be decoded as a valid image.
    """
    try:
        return Image.open(io.BytesIO(data)).convert("RGB")
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ImageDecodeError(f"Cannot decode image data: {exc}") from exc


def encode_image_to_jpeg_bytes(img: Image.Image, target: tuple[int, int]) -> bytes:
    """Centre-crop *img* to square, resize to *target*, and encode as JPEG.

    Args:
        img: Source ``Image`` object (any mode; converted to RGB internally).
        target: Desired output dimensions as ``(width, height)``.  Both values
            must be equal (square target is enforced by the caller).

    Returns:
        JPEG-encoded bytes at quality 92 with Pillow optimisation enabled.
    """
    img = img.convert("RGB")
    img = center_crop_to_square(img)
    img = img.resize(target, Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Per-format audio processors
#
# NOTE: mutagen classes are imported from `album_art_normalizer` at function
# call time so that ``unittest.mock.patch("album_art_normalizer.MP3", ...)``
# (and analogues for FLAC / ID3) works correctly across the module split.
# ---------------------------------------------------------------------------


def process_mp3_artwork(path: Path, target: tuple[int, int]) -> str:
    """Inspect and, if necessary, update the embedded APIC artwork in an MP3.

    All existing ID3 tags are preserved; only the APIC frame is replaced.

    Args:
        path: Absolute path to the ``.mp3`` file.
        target: Desired embedded image size as ``(width, height)``.

    Returns:
        A human-readable one-line status string describing the outcome.

    Raises:
        AudioTagReadError: When the MP3 tags cannot be opened.
        ImageDecodeError: When the embedded image bytes are undecodable.
        AudioSuiteError: When the shared facade fails to write or save the
            resized artwork (mutagen/OSError failures mapped by the facade).
    """
    from album_art_normalizer import (  # noqa: PLC0415  # noqa: PLC0415
        APIC,
        ID3,
        MP3,
        HeaderNotFoundError,
        ID3NoHeaderError,
        ID3UnsupportedVersionError,
        InvalidMPEGHeader,
    )

    try:
        audio = MP3(path, ID3=ID3)
    except (
        HeaderNotFoundError,
        InvalidMPEGHeader,
        ID3NoHeaderError,
        ID3UnsupportedVersionError,
        OSError,
    ) as exc:
        raise AudioTagReadError(
            f"Cannot open MP3 tags for '{path.name}': {exc}"
        ) from exc

    if audio.tags is None:
        return "No ID3 tags found \u2014 skipped."

    apic_frames: list[APIC] = audio.tags.getall("APIC")
    if not apic_frames:
        return "No embedded artwork (APIC frame absent) \u2014 skipped."

    frame = apic_frames[0]
    img = load_image_from_bytes(frame.data)
    current_size: tuple[int, int] = img.size

    if current_size == target:
        return f"Embedded image already {target[0]}\u00d7{target[1]} \u2014 skipped."

    spec = ImageResizeSpec(source_size=current_size, target_size=target)
    new_data = encode_image_to_jpeg_bytes(img, target)

    embed_artwork(str(path), new_data)

    crop_note = " (centre-cropped)" if spec.needs_crop else ""
    return (
        f"Embedded image was {current_size[0]}\u00d7{current_size[1]}{crop_note}; "
        f"resized to {target[0]}\u00d7{target[1]} and saved."
    )


def process_flac_artwork(path: Path, target: tuple[int, int]) -> str:
    """Inspect and, if necessary, update the embedded Picture block in a FLAC.

    All VorbisComment tags are preserved; only the picture block is replaced.

    Args:
        path: Absolute path to the ``.flac`` file.
        target: Desired embedded image size as ``(width, height)``.

    Returns:
        A human-readable one-line status string describing the outcome.

    Raises:
        AudioTagReadError: When the FLAC metadata cannot be opened.
        ImageDecodeError: When the embedded image bytes are undecodable.
        AudioSuiteError: When the shared facade fails to write or save the
            resized artwork (mutagen/OSError failures mapped by the facade).
    """
    from album_art_normalizer import FLAC, FLACNoHeaderError, Picture  # noqa: PLC0415

    try:
        audio = FLAC(path)
    except (FLACNoHeaderError, OSError) as exc:
        raise AudioTagReadError(
            f"Cannot open FLAC tags for '{path.name}': {exc}"
        ) from exc

    pictures: list[Picture] = audio.pictures
    if not pictures:
        return "No embedded artwork (Picture block absent) \u2014 skipped."

    pic = pictures[0]
    img = load_image_from_bytes(pic.data)
    current_size: tuple[int, int] = img.size

    if current_size == target:
        return f"Embedded image already {target[0]}\u00d7{target[1]} \u2014 skipped."

    spec = ImageResizeSpec(source_size=current_size, target_size=target)
    new_data = encode_image_to_jpeg_bytes(img, target)

    embed_artwork(str(path), new_data)

    crop_note = " (centre-cropped)" if spec.needs_crop else ""
    return (
        f"Embedded image was {current_size[0]}\u00d7{current_size[1]}{crop_note}; "
        f"resized to {target[0]}\u00d7{target[1]} and saved."
    )


def process_audio_artwork(path: Path, target: tuple[int, int]) -> str:
    """Inspect and, if necessary, update the embedded artwork in any supported
    audio file (MP3, FLAC, OGG, Opus, M4A, MP4, WAV, AIFF, AIF).

    Uses :class:`TagHandlerFactory` to load the file and
    :meth:`BaseTagHandler.extract_artwork` to pull the raw image bytes,
    then resizes and re-embeds via the shared :func:`embed_artwork` facade.

    Args:
        path: Absolute path to the audio file.
        target: Desired embedded image size as ``(width, height)``.

    Returns:
        A human-readable one-line status string describing the outcome.

    Raises:
        AudioTagReadError: When the audio metadata cannot be opened.
        ImageDecodeError: When the embedded image bytes are undecodable.
        AudioSuiteError: When the shared facade fails to write or save the
            resized artwork (mutagen/OSError failures mapped by the facade).
    """
    from audio_suite_shared.tag_helper_base import (  # noqa: PLC0415
        TagHandlerFactory,
    )

    try:
        handler = TagHandlerFactory.get_handler(str(path))
    except (OSError, ValueError) as exc:
        raise AudioTagReadError(f"Cannot open tags for '{path.name}': {exc}") from exc

    raw_data = handler.extract_artwork()
    if raw_data is None:
        return "No embedded artwork \u2014 skipped."

    img = load_image_from_bytes(raw_data)
    current_size: tuple[int, int] = img.size

    if current_size == target:
        return f"Embedded image already {target[0]}\u00d7{target[1]} \u2014 skipped."

    spec = ImageResizeSpec(source_size=current_size, target_size=target)
    new_data = encode_image_to_jpeg_bytes(img, target)

    embed_artwork(str(path), new_data)

    crop_note = " (centre-cropped)" if spec.needs_crop else ""
    return (
        f"Embedded image was {current_size[0]}\u00d7{current_size[1]}{crop_note}; "
        f"resized to {target[0]}\u00d7{target[1]} and saved."
    )


# ---------------------------------------------------------------------------
# folder.jpg processor
# ---------------------------------------------------------------------------


def process_folder_jpg(directory: Path) -> str | None:
    """Normalise ``folder.jpg`` in *directory* to exactly 1000×1000 px.

    Args:
        directory: Parent directory that may contain a ``folder.jpg`` file.

    Returns:
        A human-readable status string, or ``None`` if no ``folder.jpg``
        exists in *directory*.

    Raises:
        FolderImageError: When ``folder.jpg`` exists but cannot be read or
            written.
    """
    folder_jpg: Path = directory / "folder.jpg"
    if not folder_jpg.exists():
        return None

    try:
        img = Image.open(folder_jpg).convert("RGB")
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise FolderImageError(f"Cannot read folder.jpg: {exc}") from exc

    current_size: tuple[int, int] = img.size
    target = FOLDER_JPG_TARGET

    if current_size == target:
        return f"folder.jpg already {target[0]}\u00d7{target[1]} \u2014 skipped."

    spec = ImageResizeSpec(source_size=current_size, target_size=target)
    img = center_crop_to_square(img)
    img = img.resize(target, Image.Resampling.LANCZOS)

    try:
        img.save(folder_jpg, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    except OSError as exc:
        raise FolderImageError(f"Cannot write folder.jpg: {exc}") from exc

    crop_note = " (centre-cropped)" if spec.needs_crop else ""
    return (
        f"folder.jpg was {current_size[0]}\u00d7{current_size[1]}{crop_note}; "
        f"resized to {target[0]}\u00d7{target[1]}."
    )
