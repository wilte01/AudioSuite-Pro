"""
formats.py
Audio format classification, conversion validity rules, and input
directory scanning.

Pure module — no tkinter, no subprocess, no FFmpeg.
All business rules for which conversions are allowed live here.

Changed in 1.1.0: classified the new formats (spx lossy; wv/ape/mpc/dsf lossless) and
added the unsupported-output set.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from audio_suite_shared.exceptions import map_to_audio_error

logger = logging.getLogger(__name__)

# ── Format lists ──────────────────────────────────────────────────────────────

LOSSY_FORMATS: list[str] = ["mp3", "aac", "m4a", "ogg", "opus", "mp4", "wma", "spx"]
LOSSLESS_FORMATS: list[str] = [
    "flac",
    "wav",
    "alac",
    "ape",
    "aiff",
    "aif",
    "wv",
    "mpc",
    "dsf",
]
ALL_FORMATS: list[str] = LOSSY_FORMATS + LOSSLESS_FORMATS

# Formats that can be detected/read as input but cannot be correctly
# *produced* as output by this tool. FFmpeg has no encoder and no muxer
# for Monkey's Audio (APE), Musepack (MPC), or DSD Store (DSF), so an
# output target in this set would silently fall back to stream-copy (or
# worse, the MP3 fallback of shared get_export_args) and mislabel the
# source codec. Excluded from every output-format list below; left in
# the LOSSY/LOSSLESS lists so their files are still detected as input.
UNSUPPORTED_OUTPUT_FORMATS: list[str] = ["ape", "mpc", "dsf"]

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


def available_output_formats_for(inputs: list[str]) -> list[str]:
    """
    Return every output format reachable from *at least one* of the given
    input formats, preserving ALL_FORMATS order and without duplicates.

    A mixed-format tree offers the union of its members' valid targets:
    a FLAC + MP3 tree can still target FLAC (the MP3 files are skipped as
    lossy→lossless), so no target is lost by allowing mixed input.
    """
    seen: set[str] = set()
    for input_fmt in inputs:
        seen.update(available_output_formats(input_fmt))
    return [f for f in ALL_OUTPUT_FORMATS if f in seen]


# ── Directory scan ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScanResult:
    """Outcome of scanning an input directory for audio files."""

    ok: bool
    input_format: Optional[str] = None  # set only when a single format was found
    file_count: int = 0
    mixed_formats: list[str] = field(default_factory=list)
    output_formats: list[str] = field(default_factory=list)
    error_message: Optional[str] = None
    # Per-source-format file counts, keyed by lowercase format extension.
    format_counts: dict[str, int] = field(default_factory=dict)

    # Convenience label for the detected-format indicator in the UI
    @property
    def status_text(self) -> str:
        if not self.ok:
            return f"⚠ {self.error_message or 'Unknown error'}"
        if not self.file_count:
            return "⚠ No audio files found in directory"
        if self.format_counts:
            breakdown = ", ".join(
                f"{fmt.upper()}: {count}"
                for fmt, count in sorted(self.format_counts.items(), key=_by_count_name)
            )
            return f"✓ Detected: {self.file_count} file(s) — {breakdown}"
        if self.input_format:
            return f"✓ Detected: {self.file_count} {self.input_format.upper()} file(s)"
        return f"✓ Detected: {self.file_count} file(s)"


def _by_count_name(item: tuple[str, int]) -> tuple[int, str]:
    """Sort breakdown entries by descending count, then format name."""
    fmt, count = item
    return (-count, fmt)


def discover_input_files(input_dir: str, recursive: bool = True) -> list[str]:
    """
    Return every supported audio file under *input_dir* as a list of paths
    relative to *input_dir*.

    Entries are sorted by name within each directory and subdirectories are
    traversed in sorted order, so repeated scans of an unchanged tree
    always yield the same list.

    With ``recursive=False`` only the top level is inspected (the legacy
    flat behaviour).  With ``recursive=True`` the whole tree is walked and
    returned entries keep their relative subdirectory, so a caller can
    mirror that structure when writing output.

    Unreadable *nested* directories are logged and skipped so one bad
    subtree never aborts a scan; an unreadable *root* re-raises so callers
    can report the failure.
    """
    if not input_dir or not os.path.isdir(input_dir):
        return []
    if recursive:
        return _discover_recursive(input_dir)
    return _discover_flat(input_dir)


def _discover_flat(input_dir: str) -> list[str]:
    files: list[str] = []
    with os.scandir(input_dir) as entries:
        for entry in entries:
            if entry.is_file() and detect_format(entry.name):
                files.append(entry.name)
    return sorted(files)


def _discover_recursive(input_dir: str) -> list[str]:
    """Walk *input_dir* top-down, returning relative paths of audio files.

    Explicit recursion (rather than ``os.walk``) so an unreadable directory
    is attributed precisely: the root re-raises so callers report the
    failure, any nested directory is logged and skipped.
    """
    root = os.path.abspath(input_dir)
    files: list[str] = []
    # (path relative to input_dir, absolute directory path)
    pending: list[tuple[str, str]] = [("", input_dir)]

    while pending:
        rel_dir, current = pending.pop(0)
        try:
            with os.scandir(current) as entries:
                children = sorted(entries, key=lambda e: e.name)
        except OSError as exc:
            if os.path.abspath(current) == root:
                raise
            logger.warning(
                "Skipping unreadable directory %s during scan: %s", current, exc
            )
            continue

        subdirs: list[tuple[str, str]] = []
        for entry in children:
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                is_dir = False
            if is_dir:
                subdirs.append(
                    (os.path.join(rel_dir, entry.name), entry.path)
                    if rel_dir
                    else (entry.name, entry.path)
                )
            elif detect_format(entry.name):
                files.append(
                    os.path.join(rel_dir, entry.name) if rel_dir else entry.name
                )
        pending.extend(sorted(subdirs))

    return files


def scan_input_directory(input_dir: str, recursive: bool = True) -> ScanResult:
    """
    Scan input_dir for audio files and determine valid output formats.

    Subdirectories are included by default.  Mixed source formats are
    supported: each file is converted against its own detected format and
    the counts are reported per format.

    Returns a ScanResult describing what was found and what output
    formats are available.  Never raises.
    """
    if not input_dir or not os.path.isdir(input_dir):
        return ScanResult(ok=True, output_formats=ALL_OUTPUT_FORMATS)

    counts: dict[str, int] = {}
    try:
        for rel_path in discover_input_files(input_dir, recursive=recursive):
            fmt = detect_format(rel_path)
            if fmt:
                counts[fmt] = counts.get(fmt, 0) + 1
    except Exception as exc:
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        return ScanResult(
            ok=False, error_message=str(exc), output_formats=ALL_OUTPUT_FORMATS
        )

    if not counts:
        return ScanResult(ok=True, output_formats=ALL_OUTPUT_FORMATS)

    total = sum(counts.values())
    detected = sorted(counts)
    return ScanResult(
        ok=True,
        input_format=detected[0] if len(detected) == 1 else None,
        file_count=total,
        mixed_formats=detected if len(detected) > 1 else [],
        output_formats=available_output_formats_for(detected),
        format_counts=counts,
    )
