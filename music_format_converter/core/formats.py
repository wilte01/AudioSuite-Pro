"""
formats.py
Audio format classification, conversion validity rules, and input
directory scanning.

Pure module — no tkinter, no subprocess, no FFmpeg.
All business rules for which conversions are allowed live here.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from audio_suite_shared.exceptions import map_to_audio_error

logger = logging.getLogger(__name__)

# ── Format lists ──────────────────────────────────────────────────────────────

LOSSY_FORMATS: list[str] = ["mp3", "aac", "m4a", "ogg", "opus", "mp4", "wma"]
LOSSLESS_FORMATS: list[str] = ["flac", "wav", "alac", "ape", "aiff", "aif", "wv"]
ALL_FORMATS: list[str] = LOSSY_FORMATS + LOSSLESS_FORMATS

# Formats that can be detected/read as input but cannot be correctly
# *produced* as output by this tool. FFmpeg has no Monkey's Audio (APE)
# encoder (decode-only), so an "ape" output target would silently fall
# back to stream-copy and mislabel the source codec as APE. Excluded
# from every output-format list below; left in LOSSLESS_FORMATS so APE
# files are still correctly detected and read as input.
UNSUPPORTED_OUTPUT_FORMATS: list[str] = ["ape"]

# All formats minus those that cannot be produced as output (see above).
# Used as the "no input scanned yet / no files detected" fallback.
ALL_OUTPUT_FORMATS: list[str] = [
    f for f in ALL_FORMATS if f not in UNSUPPORTED_OUTPUT_FORMATS
]


# ── Per-format descriptive metadata ──────────────────────────────────────────


def format_info(fmt: str) -> str:
    """
    Return a human-readable description line for a given output format,
    including quality type, notable metadata notes, and any conversion
    restriction reminder.
    """
    if fmt in LOSSLESS_FORMATS:
        base = (
            f"📊 {fmt.upper()} is a lossless format - preserves original audio quality"
        )
    else:
        base = f"📊 {fmt.upper()} is a lossy format - compressed with high quality"

    notes = {
        "aac": (
            "\n⚠ Raw AAC has limited metadata support. Use M4A for full "
            "tag preservation."
        ),
        "m4a": "\n✓ M4A fully supports metadata tags (artist, title, album, etc.)",
        "mp3": "\n✓ MP3 fully supports ID3 tags for metadata",
        "flac": "\n✓ FLAC fully supports Vorbis comments for metadata",
    }
    base += notes.get(fmt, "")

    if fmt in LOSSLESS_FORMATS:
        base += (
            "\n⚠ Only lossless and uncompressed sources can be converted to this format"
        )

    return base


# ── Conversion rules ──────────────────────────────────────────────────────────


def is_lossy(fmt: str) -> bool:
    """Return True if fmt is a lossy format."""
    return fmt.lower() in LOSSY_FORMATS


def detect_format(filename: str) -> Optional[str]:
    """
    Return the lowercase extension (without dot) if it is a known format,
    otherwise None.
    """
    ext = os.path.splitext(filename)[1].lower().replace(".", "")
    return ext if ext in ALL_FORMATS else None


def can_convert(input_fmt: str, output_fmt: str) -> tuple[bool, str]:
    """
    Check whether converting input_fmt → output_fmt is allowed.

    Rules:
        - Converting a format to itself is prohibited (nothing to do;
          also avoids FFmpeg's "Output same as Input" failure when the
          output directory defaults to the input directory).
        - lossy → lossless is prohibited (no quality can be recovered).
        - Output formats with no available encoder (see
          UNSUPPORTED_OUTPUT_FORMATS) are prohibited as a target,
          regardless of input format.

    Returns:
        (True,  "OK")             if allowed.
        (False, reason_string)    if not allowed.
    """
    if input_fmt.lower() == output_fmt.lower():
        return False, "Input and output formats are the same"
    if output_fmt in UNSUPPORTED_OUTPUT_FORMATS:
        return False, f"{output_fmt.upper()} is not a supported output format"
    if is_lossy(input_fmt) and not is_lossy(output_fmt):
        return False, "Cannot convert lossy to lossless (no quality improvement)"
    return True, "OK"


def available_output_formats(input_fmt: str) -> list[str]:
    """
    Return the list of valid output formats for a given input format,
    excluding the input format itself, any lossy→lossless violations,
    and any format with no available encoder (UNSUPPORTED_OUTPUT_FORMATS).
    """
    if is_lossy(input_fmt):
        candidates = [f for f in LOSSY_FORMATS if f != input_fmt]
    else:
        candidates = [f for f in ALL_FORMATS if f != input_fmt]
    return [f for f in candidates if f not in UNSUPPORTED_OUTPUT_FORMATS]


# ── Directory scan ─────────────────────────────────────────────────────────────


@dataclass
class ScanResult:
    """Outcome of scanning an input directory for audio files."""

    ok: bool
    input_format: Optional[str] = None  # single detected format
    file_count: int = 0
    mixed_formats: list[str] = field(default_factory=list)
    output_formats: list[str] = field(default_factory=list)
    error_message: Optional[str] = None

    # Convenience label for the detected-format indicator in the UI
    @property
    def status_text(self) -> str:
        if not self.ok:
            if self.mixed_formats:
                return (
                    f"⚠ ERROR: Mixed formats detected "
                    f"({', '.join(sorted(self.mixed_formats))})"
                )
            return f"⚠ {self.error_message or 'Unknown error'}"
        if self.input_format:
            return f"✓ Detected: {self.file_count} {self.input_format.upper()} file(s)"
        return "⚠ No audio files found in directory"


def scan_input_directory(input_dir: str) -> ScanResult:
    """
    Scan input_dir for audio files and determine valid output formats.

    Returns a ScanResult describing what was found and what output
    formats are available.  Never raises.
    """
    if not input_dir or not os.path.isdir(input_dir):
        return ScanResult(ok=True, output_formats=ALL_OUTPUT_FORMATS)

    detected: set[str] = set()
    count = 0
    try:
        for entry in os.scandir(input_dir):
            if entry.is_file():
                fmt = detect_format(entry.name)
                if fmt:
                    detected.add(fmt)
                    count += 1
    except Exception as exc:
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        return ScanResult(
            ok=False, error_message=str(exc), output_formats=ALL_OUTPUT_FORMATS
        )

    if not detected:
        return ScanResult(ok=True, output_formats=ALL_OUTPUT_FORMATS)

    if len(detected) > 1:
        mixed = sorted(detected)
        return ScanResult(ok=False, mixed_formats=mixed, output_formats=[])

    input_fmt = next(iter(detected))
    return ScanResult(
        ok=True,
        input_format=input_fmt,
        file_count=count,
        output_formats=available_output_formats(input_fmt),
    )
