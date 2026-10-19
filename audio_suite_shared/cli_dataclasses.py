"""
cli_dataclasses.py — Standardized CLI argument structures for Audio Suite.

Provides common dataclass definitions and validation functions to eliminate
duplication across multiple applications while maintaining type safety.

Changed in 1.4.0: ``BPMArgs`` and ``LyricsArgs`` default ``max_workers`` to
``default_max_workers()`` (evaluated per instance) instead of a literal 4.
"""

from dataclasses import dataclass, field
from pathlib import Path

from .constants import default_max_workers


class CLIValidationError(ValueError):
    """Raised when parsed CLI arguments fail validation.

    Shared so launchers can catch validation failures from any tool's
    ``parse()`` with a single exception type (ValueError subclasses would
    otherwise escape ``except SystemExit`` handlers uncaught).
    """


@dataclass
class BaseCLIArgs:
    """
    Base CLI arguments common to most Audio Suite applications.

    Used by applications that follow the folder path pattern:
    - ReplayGain Analyzer, Tempo Analyzer, Silence Trimmer,
    - Album Genre Tagger, Album Art Sync, Audio Normalizer,
    - Metadata Scrubber, Genre Sync, Key Detector, BPM Analyzer,
    - Pop & Click Remover
    """

    folder_path: str = ""
    live_mode: bool = False
    auto_start: bool = False
    auto_end: bool = False


@dataclass
class SourceOutputArgs(BaseCLIArgs):
    """
    CLI arguments for applications using source/output pattern.

    Used by applications that have separate source and output directories:
    - Audio Enhancer, Audio Refinery, Music Format Converter,
    - ASX Extractor, CD Ripper
    """

    source: str = ""
    output: str = ""


@dataclass
class BPMArgs(BaseCLIArgs):
    """BPM Analyzer specific arguments extending base."""

    bpm_min: int = 75
    bpm_max: int = 175
    duration: int = 90
    parallel_mode: bool = False
    max_workers: int = field(default_factory=default_max_workers)
    clear_logs: bool = False
    parallel_run: bool = False


@dataclass
class TempoAnalyzerArgs(BaseCLIArgs):
    """Tempo Analyzer specific arguments extending base."""

    scheme: str | None = None


@dataclass
class ReplayGainArgs(BaseCLIArgs):
    """ReplayGain Analyzer specific arguments extending base."""

    target_lufs: float = -16.0


@dataclass
class LyricsArgs(BaseCLIArgs):
    """Lyrics Manager specific arguments extending base."""

    provider: str = "lrclib"
    request_timeout: float = 10.0
    skip_existing: bool = True
    plain_fallback: bool = True
    parallel_mode: bool = False
    max_workers: int = field(default_factory=default_max_workers)
    clear_logs: bool = False
    parallel_run: bool = False


def validate_folder_path(folder_path: str) -> list[str]:
    """
    Validate folder path argument.

    Args:
        folder_path: Path to validate

    Returns:
        List of validation error messages (empty if valid)
    """
    errors: list[str] = []

    if folder_path:
        p = Path(folder_path)
        if not p.exists():
            errors.append(f"Folder path does not exist: {folder_path}")
        elif not p.is_dir():
            errors.append(f"Path is not a directory: {folder_path}")

    return errors


def validate_source_output_paths(source: str, output: str) -> list[str]:
    """
    Validate source and output path arguments.

    Args:
        source: Source directory path
        output: Output directory path

    Returns:
        List of validation error messages (empty if valid)
    """
    errors: list[str] = []
    for label, path in [("Source", source), ("Output", output)]:
        for msg in validate_folder_path(path):
            errors.append(msg.replace("Folder", label))
    return errors


def validate_bpm_range(bpm_min: int, bpm_max: int) -> list[str]:
    """
    Validate BPM range arguments.

    Args:
        bpm_min: Minimum BPM value
        bpm_max: Maximum BPM value

    Returns:
        List of validation error messages (empty if valid)
    """
    errors: list[str] = []

    if bpm_min < 0 or bpm_min > 300:
        errors.append(f"BPM minimum must be between 0 and 300, got: {bpm_min}")

    if bpm_max < 0 or bpm_max > 300:
        errors.append(f"BPM maximum must be between 0 and 300, got: {bpm_max}")

    if bpm_min >= bpm_max:
        errors.append(f"BPM minimum must be less than maximum: {bpm_min} >= {bpm_max}")

    return errors


VALID_TARGET_LUFS_VALUES: tuple[float, ...] = (-12.0, -14.0, -16.0, -18.0, -23.0)
"""The only permitted Target LUFS presets across the AudioSuite-Pro suite.

Used by: Audio Normalizer, ReplayGain Analyzer, and the Audio Refinery
normalise stage (via Master Driver's REFINE tab).  Any UI or CLI entry point
that accepts a target_lufs value must validate against this tuple.
"""

_LUFS_TOLERANCE: float = 1e-6


def validate_target_lufs(target_lufs: float) -> list[str]:
    """
    Validate target LUFS argument against the permitted preset list.

    Args:
        target_lufs: Target loudness in LUFS

    Returns:
        List of validation error messages (empty if valid)
    """
    errors: list[str] = []

    if not any(
        abs(target_lufs - valid) < _LUFS_TOLERANCE for valid in VALID_TARGET_LUFS_VALUES
    ):
        valid_str = ", ".join(f"{v:.1f}" for v in VALID_TARGET_LUFS_VALUES)
        errors.append(f"Target LUFS must be one of: {valid_str}, got: {target_lufs}")

    return errors


def validate_tempo_scheme(scheme: str, valid_schemes: list[str]) -> list[str]:
    """
    Validate tempo scheme argument.

    Args:
        scheme: Scheme name to validate
        valid_schemes: List of valid scheme names

    Returns:
        List of validation error messages (empty if valid)
    """
    errors: list[str] = []

    if scheme and scheme not in valid_schemes:
        errors.append(
            f"Invalid scheme: {scheme}. Must be one of: {', '.join(valid_schemes)}"
        )

    return errors
