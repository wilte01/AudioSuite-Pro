"""
core/integrity.py
File Integrity Checker for Audio Refinery.

Validates audio files before expensive DSP processing to prevent wasting
computational resources on corrupt, truncated, or otherwise invalid files.

Checks performed:
  1. File existence and readability
  2. File size validation (non-empty, reasonable bounds)
  3. Magic bytes / container header validation
  4. Decode test via pydub (catches codec corruption)
  5. Audio property validation (sample rate, duration, channels)

Failure model:
  Any check failure produces an IntegrityResult with status=FAIL and a
  human-readable message.  The pipeline skips the file rather than
  attempting expensive DSP on an invalid input.

Changed in 2.1.6: existence, regular-file-ness and size now come from one
``Path.stat()`` call guarded by ``OSError``, instead of ``Path.exists()`` and
``Path.is_file()``. Those two only swallow a stat failure on 3.13+, so on the
3.11/3.12 legs an unreadable or locked file raised out of ``validate_file``
while a 3.14 host reported the same file as merely absent.
"""

from __future__ import annotations

import logging
import stat
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.exceptions import map_to_audio_error

logger = logging.getLogger(__name__)

# ── Minimum acceptable audio properties ──────────────────────────────────────
MIN_FILE_SIZE_BYTES: int = 100  # smallest valid audio file is ~100 bytes
MAX_FILE_SIZE_BYTES: int = 4 * 1024 * 1024 * 1024  # 4 GB sanity upper bound
MIN_DURATION_MS: int = 10  # files shorter than 10 ms are likely corrupt
MAX_DURATION_MS: int = 24 * 60 * 60 * 1000  # 24 hours upper bound
MIN_SAMPLE_RATE: int = 8000  # minimum usable sample rate
MAX_SAMPLE_RATE: int = 192000  # maximum expected sample rate
MIN_CHANNELS: int = 1
MAX_CHANNELS: int = 8  # surround sound upper bound

# ── Magic bytes for common audio containers ──────────────────────────────────
# Maps extension → (offset, alternatives). A file passes when its header at
# *offset* starts with ANY of the alternative signatures.
_MAGIC_BYTES: dict[str, tuple[int, tuple[bytes, ...]]] = {
    ".wav": (0, (b"RIFF",)),
    ".aiff": (0, (b"FORM",)),
    ".aif": (0, (b"FORM",)),
    ".flac": (0, (b"fLaC",)),
    ".ogg": (0, (b"OggS",)),
    # Raw MPEG frame sync, or an ID3v2 tag header — virtually every tagged
    # MP3 starts with b"ID3", not the frame sync byte.
    ".mp3": (0, (b"\xff", b"ID3")),
    ".m4a": (4, (b"ftyp",)),
    ".mp4": (4, (b"ftyp",)),
    ".opus": (0, (b"OggS",)),  # Opus is inside an Ogg container
}


class IntegrityStatus(str, Enum):
    """Outcome of an integrity check."""

    PASS = "pass"  # nosec B105 — status string, not a credential
    FAIL = "fail"
    WARN = "warn"


@dataclass
class IntegrityResult:
    """Result of validating a single audio file."""

    path: Path
    status: IntegrityStatus = IntegrityStatus.PASS
    checks: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    file_size_bytes: int = 0
    duration_ms: float = 0.0
    sample_rate: int = 0
    channels: int = 0

    @property
    def is_valid(self) -> bool:
        """True if all critical checks passed."""
        return self.status != IntegrityStatus.FAIL

    @property
    def summary(self) -> str:
        """One-line human-readable summary."""
        if self.is_valid:
            return (
                f"OK ({self.file_size_bytes:,} bytes, "
                f"{self.duration_ms / 1000:.1f}s, "
                f"{self.sample_rate} Hz, {self.channels}ch)"
            )
        return f"FAIL: {'; '.join(self.failures)}"

    def add_check(self, name: str) -> None:
        """Record a passed check."""
        self.checks.append(name)

    def add_failure(self, name: str, detail: str) -> None:
        """Record a failed check — sets status to FAIL."""
        self.status = IntegrityStatus.FAIL
        msg = f"{name}: {detail}"
        self.failures.append(msg)
        logger.warning("[Integrity] %s — %s", self.path.name, msg)

    def add_warning(self, name: str, detail: str) -> None:
        """Record a non-fatal warning."""
        msg = f"{name}: {detail}"
        self.warnings.append(msg)
        if self.status == IntegrityStatus.PASS:
            self.status = IntegrityStatus.WARN
        logger.info("[Integrity] %s — %s", self.path.name, msg)


def check_magic_bytes(path: Path, result: IntegrityResult) -> None:
    """Validate file header against known magic bytes for the extension."""
    ext = path.suffix.lower()
    if ext not in _MAGIC_BYTES:
        result.add_check("magic_bytes:skipped (unknown extension)")
        return

    offset, alternatives = _MAGIC_BYTES[ext]
    read_len = max(len(alt) for alt in alternatives)
    try:
        with open(path, "rb") as fh:
            fh.seek(offset)
            header = fh.read(read_len)
        if not any(header.startswith(alt) for alt in alternatives):
            result.add_failure(
                "magic_bytes",
                f"Expected one of {alternatives!r} at offset {offset}, got {header!r}",
            )
            return
    except OSError as exc:
        result.add_failure("magic_bytes", f"Could not read header: {exc}")
        return

    result.add_check("magic_bytes")


def check_decode(path: Path, result: IntegrityResult) -> None:
    """Attempt to decode the file with pydub; this catches codec corruption."""
    try:
        from pydub import AudioSegment

        audio = AudioSegment.from_file(str(path))
        result.sample_rate = audio.frame_rate
        result.channels = audio.channels
        result.duration_ms = float(len(audio))
    except Exception as exc:
        # Broad net is intentional: pydub raises several distinct types for
        # a corrupt file, and decode must be flagged, not crash the scan.
        # add_failure() below logs the failure unconditionally.
        mapped = map_to_audio_error(exc)
        result.add_failure("decode", f"pydub could not decode: {mapped.message}")
        return

    result.add_check("decode")


def check_audio_properties(result: IntegrityResult) -> None:
    """Validate decoded audio properties against acceptable bounds."""
    if result.sample_rate < MIN_SAMPLE_RATE:
        result.add_failure(
            "sample_rate",
            f"{result.sample_rate} Hz is below minimum {MIN_SAMPLE_RATE} Hz",
        )
    elif result.sample_rate > MAX_SAMPLE_RATE:
        result.add_failure(
            "sample_rate",
            f"{result.sample_rate} Hz exceeds maximum {MAX_SAMPLE_RATE} Hz",
        )
    else:
        result.add_check("sample_rate")

    if result.duration_ms < MIN_DURATION_MS:
        result.add_failure(
            "duration",
            f"{result.duration_ms:.1f} ms is below minimum {MIN_DURATION_MS} ms",
        )
    elif result.duration_ms > MAX_DURATION_MS:
        result.add_failure(
            "duration",
            f"{result.duration_ms / 1000:.1f}s exceeds"
            f" maximum {MAX_DURATION_MS / 1000:.0f}s",
        )
    else:
        result.add_check("duration")

    if result.channels < MIN_CHANNELS:
        result.add_failure(
            "channels",
            f"{result.channels} channels is below minimum {MIN_CHANNELS}",
        )
    elif result.channels > MAX_CHANNELS:
        result.add_failure(
            "channels",
            f"{result.channels} channels exceeds maximum {MAX_CHANNELS}",
        )
    else:
        result.add_check("channels")


def validate_file(path: Path) -> IntegrityResult:
    """
    Run the full integrity check suite on a single audio file.

    Parameters
    ----------
    path : Path to the audio file.

    Returns
    -------
    IntegrityResult with status PASS, WARN, or FAIL.
    """
    result = IntegrityResult(path=path)

    # 1. Existence and readability
    # One stat decides existence, regular-file-ness and size. ``Path.exists()``
    # and ``Path.is_file()`` must not be the ones stat-ing for us: 3.13+ swallow
    # a stat OSError and report False, while 3.11/3.12 re-raise anything that is
    # not ENOENT/ENOTDIR - so a locked or unreadable path crashed the check on
    # the older supported legs instead of failing that file with a reason.
    try:
        file_stat = path.stat()
    except FileNotFoundError:
        result.add_failure("existence", "File does not exist")
        return result
    except OSError as exc:
        result.add_failure("existence", f"Cannot stat: {exc}")
        return result

    if not stat.S_ISREG(file_stat.st_mode):
        result.add_failure("existence", "Path is not a regular file")
        return result
    result.add_check("existence")

    try:
        with open(path, "rb") as fh:
            fh.read(1)
    except PermissionError as exc:
        result.add_failure("readability", f"Permission denied: {exc}")
        return result
    except OSError as exc:
        result.add_failure("readability", f"Cannot read: {exc}")
        return result
    result.add_check("readability")

    # 2. File size validation
    file_size = file_stat.st_size
    result.file_size_bytes = file_size

    if file_size == 0:
        result.add_failure("file_size", "File is empty (0 bytes)")
        return result
    if file_size < MIN_FILE_SIZE_BYTES:
        result.add_failure(
            "file_size",
            f"{file_size} bytes is below minimum {MIN_FILE_SIZE_BYTES} bytes",
        )
        return result
    if file_size > MAX_FILE_SIZE_BYTES:
        result.add_failure(
            "file_size",
            f"{file_size:,} bytes exceeds maximum {MAX_FILE_SIZE_BYTES:,} bytes",
        )
        return result
    result.add_check("file_size")

    # 3. Extension check
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        result.add_warning(
            "extension",
            f"'{ext}' is not a recognised audio extension",
        )
    else:
        result.add_check("extension")

    # 4. Magic bytes
    check_magic_bytes(path, result)
    if not result.is_valid:
        return result

    # 5. Decode test + property extraction
    check_decode(path, result)
    if not result.is_valid:
        return result

    # 6. Audio property validation
    check_audio_properties(result)

    return result


def validate_files(paths: list[Path]) -> list[IntegrityResult]:
    """
    Validate multiple audio files.

    Parameters
    ----------
    paths : List of file paths to validate.

    Returns
    -------
    List of IntegrityResult, one per input path.
    """
    return [validate_file(p) for p in paths]


def filter_valid(results: list[IntegrityResult]) -> list[Path]:
    """Return paths of files that passed integrity validation."""
    return [r.path for r in results if r.is_valid]


def filter_invalid(results: list[IntegrityResult]) -> list[IntegrityResult]:
    """Return results of files that failed integrity validation."""
    return [r for r in results if not r.is_valid]
