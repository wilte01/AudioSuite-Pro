"""
processor.py — Tag processing orchestration (decomposed).

Business logic lives in mapping_engine.py and transformation_rules.py.
This module re-exports the public API for backward compatibility.
"""

import logging
import os
from collections.abc import Callable
from pathlib import Path

from audio_suite_shared.exceptions import (
    AudioMissingDependencyError,
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)

try:
    from mutagen.aiff import AIFF  # noqa: F401
    from mutagen.asf import ASF  # noqa: F401
    from mutagen.flac import FLAC  # noqa: F401
    from mutagen.id3 import TCON, TIT1, TXXX, ID3NoHeaderError  # noqa: F401
    from mutagen.mp3 import MP3  # noqa: F401
    from mutagen.mp4 import MP4  # noqa: F401
    from mutagen.oggopus import OggOpus  # noqa: F401
    from mutagen.oggvorbis import OggVorbis  # noqa: F401
    from mutagen.wave import WAVE  # noqa: F401
# mutagen is a declared hard dependency (pyproject); this typed failure exists
# only to give a broken install an actionable message, so it cannot run in a
# correctly installed suite (plan D2).
except ImportError as e:  # pragma: no cover
    raise AudioMissingDependencyError(
        "Mutagen library not found. Please install with: pip install mutagen",
        dependency="mutagen",
    ) from e

from .mapping_engine import (
    SUPPORTED_EXTENSIONS,
    TAG_MAPPINGS,
    ProcessingResult,
    ProcessingStats,
    should_update_value,
    update_value,
)
from .transformation_rules import (
    _SkipFile,
    process_aiff_file,
    process_flac_file,
    process_mp3_file,
    process_mp4_file,
    process_ogg_file,
    process_opus_file,
    process_wav_file,
    process_wma_file,
)

__all__ = [
    "AIFF",
    "ASF",
    "FLAC",
    "ID3NoHeaderError",
    "MP3",
    "MP4",
    "OggOpus",
    "OggVorbis",
    "ProcessingResult",
    "ProcessingStats",
    "SUPPORTED_EXTENSIONS",
    "TAG_MAPPINGS",
    "TCON",
    "TIT1",
    "TXXX",
    "WAVE",
    "TagProcessor",
    "process_aiff_file",
    "process_flac_file",
    "process_mp3_file",
    "process_mp4_file",
    "process_ogg_file",
    "process_opus_file",
    "process_wav_file",
    "process_wma_file",
    "should_update_value",
    "update_value",
]

logger = logging.getLogger(__name__)


class TagProcessor:
    """Core processor for tag field updates. Orchestrates scanning and dispatching."""

    SUPPORTED_EXTENSIONS = SUPPORTED_EXTENSIONS
    TAG_MAPPINGS = TAG_MAPPINGS

    def __init__(self) -> None:
        """Initialize the tag processor with zeroed stats and a clear stop flag."""
        self.stats = ProcessingStats()
        self.stop_flag = False

    def should_update_value(self, value: str) -> bool:
        """Determine if a tag value contains a bare slash and requires updating.

        Args:
            value: The tag value string to inspect.

        Returns:
            True if ``value`` contains at least one ``'/'`` character.
        """
        return should_update_value(value)

    def update_value(self, value: str) -> str:
        """Transform a tag value by replacing bare slashes with ``'; '``.

        Segments separated by ``' / '`` (space-slash-space) are left intact;
        only bare ``'/'`` characters within each segment are replaced.

        Args:
            value: The original tag value string.

        Returns:
            The transformed string with bare ``'/'`` replaced by ``'; '``.
            Values containing no ``'/'`` are returned unchanged.
        """
        return update_value(value)

    @handle_audio_errors(reraise=False, context="tag_updater_scan_directory")
    def scan_directory(
        self,
        directory: str,
        progress_callback: Callable[[str, ProcessingStats], None] | None = None,
    ) -> list[ProcessingResult]:
        """Recursively scan a directory tree and update qualifying tag fields.

        Resets ``self.stats`` and ``self.stop_flag`` at the start of each call.

        Args:
            directory: Root directory path to walk recursively.
            progress_callback: Optional callable invoked after each file is
                processed.  Signature: ``callback(filename: str,
                stats: ProcessingStats) -> None``.

        Returns:
            A list of :class:`ProcessingResult` — one entry per file visited,
            including skipped and errored files.
        """
        results: list[ProcessingResult] = []
        self.stats = ProcessingStats()
        self.stop_flag = False

        logger.info("Starting scan of directory: %s", directory)

        try:
            for root, _dirs, files in os.walk(directory):
                if self.stop_flag:
                    break

                for file in files:
                    if self.stop_flag:
                        break

                    file_path = Path(root) / file
                    result = self.process_file(file_path)
                    results.append(result)

                    self.stats.processed_files += 1
                    if result.updated:
                        self.stats.updated_files += 1
                    if result.error:
                        self.stats.error_files += 1

                    if progress_callback:
                        progress_callback(file_path.name, self.stats)

        except Exception as exc:
            mapped = map_to_audio_error(exc, context={"directory": str(directory)})
            logger.error(
                "[%s] Error scanning directory %s: %s",
                type(mapped).__name__,
                directory,
                mapped,
                exc_info=True,
            )
            self.stats.error_files += 1

        return results

    def stop(self) -> None:
        """Signal the processor to abort the current scan on the next iteration."""
        self.stop_flag = True

    def process_file(self, file_path: Path) -> ProcessingResult:
        """Dispatch a single audio file to the appropriate format processor.

        Files whose extension is not in :attr:`SUPPORTED_EXTENSIONS` are skipped
        without error.

        Args:
            file_path: Absolute or relative :class:`~pathlib.Path` to the audio
                file.

        Returns:
            A :class:`ProcessingResult` describing the outcome.  ``error`` is
            ``None`` on success or skip; non-``None`` on failure.
        """
        result = ProcessingResult(file_path=file_path)

        try:
            if file_path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
                self.stats.skipped_files += 1
                return result

            self.stats.total_files += 1

            extension = file_path.suffix.lower()
            if extension == ".mp3":
                result = self._process_mp3(file_path)
            elif extension == ".flac":
                result = self._process_flac(file_path)
            elif extension in [".mp4", ".m4a"]:
                result = self._process_mp4(file_path)
            elif extension == ".ogg":
                result = self._process_ogg(file_path)
            elif extension == ".opus":
                result = self._process_opus(file_path)
            elif extension == ".wav":
                result = self._process_wav(file_path)
            elif extension in (".aiff", ".aif"):
                result = self._process_aiff(file_path)
            elif extension == ".wma":
                result = self._process_wma(file_path)
            else:
                self.stats.skipped_files += 1
                logger.info(
                    "Skipped %s: unsupported format (%s)", file_path.name, extension
                )

        except Exception as exc:
            mapped = map_to_audio_error(exc, context={"file": str(file_path)})
            logger.error(
                "[%s] Error processing file %s: %s",
                type(mapped).__name__,
                file_path.name,
                mapped,
                exc_info=True,
            )
            result = ProcessingResult(
                file_path=file_path, error=user_message_for(mapped)
            )
            self.stats.error_files += 1

        return result

    # ------------------------------------------------------------------
    # Private delegate methods (backward-compatible dispatch targets)
    # ------------------------------------------------------------------

    def _process_mp3(self, file_path: Path) -> ProcessingResult:
        """Process an MP3 file via the standalone transformation rule.

        Handles skip/error stats that the standalone function cannot
        because it has no reference to ``self.stats``.
        """
        try:
            result = process_mp3_file(file_path)
        except ID3NoHeaderError:
            self.stats.skipped_files += 1
            logger.info("Skipped %s: no ID3 header", file_path.name)
            return ProcessingResult(file_path=file_path)
        except _SkipFile as skip:
            self.stats.skipped_files += 1
            logger.info("Skipped %s: %s", file_path.name, skip.reason)
            return ProcessingResult(file_path=file_path)

        if result.error:
            self.stats.error_files += 1

        return result

    def _process_flac(self, file_path: Path) -> ProcessingResult:
        """Process a FLAC file via the standalone transformation rule."""
        result = process_flac_file(file_path)
        if result.error:
            self.stats.error_files += 1
        return result

    def _process_mp4(self, file_path: Path) -> ProcessingResult:
        """Process an MP4/M4A file via the standalone transformation rule."""
        result = process_mp4_file(file_path)
        if result.error:
            self.stats.error_files += 1
        return result

    def _process_ogg(self, file_path: Path) -> ProcessingResult:
        """Process an OGG file via the standalone transformation rule."""
        result = process_ogg_file(file_path)
        if result.error:
            self.stats.error_files += 1
        return result

    def _process_opus(self, file_path: Path) -> ProcessingResult:
        """Process an Opus file via the standalone transformation rule."""
        result = process_opus_file(file_path)
        if result.error:
            self.stats.error_files += 1
        return result

    def _process_wav(self, file_path: Path) -> ProcessingResult:
        """Process a WAV file via the standalone transformation rule."""
        try:
            result = process_wav_file(file_path)
        except ID3NoHeaderError:
            self.stats.skipped_files += 1
            logger.info("Skipped %s: no ID3 header", file_path.name)
            return ProcessingResult(file_path=file_path)
        except _SkipFile as skip:
            self.stats.skipped_files += 1
            logger.info("Skipped %s: %s", file_path.name, skip.reason)
            return ProcessingResult(file_path=file_path)

        if result.error:
            self.stats.error_files += 1

        return result

    def _process_aiff(self, file_path: Path) -> ProcessingResult:
        """Process an AIFF file via the standalone transformation rule."""
        try:
            result = process_aiff_file(file_path)
        except ID3NoHeaderError:
            self.stats.skipped_files += 1
            logger.info("Skipped %s: no ID3 header", file_path.name)
            return ProcessingResult(file_path=file_path)
        except _SkipFile as skip:
            self.stats.skipped_files += 1
            logger.info("Skipped %s: %s", file_path.name, skip.reason)
            return ProcessingResult(file_path=file_path)

        if result.error:
            self.stats.error_files += 1

        return result

    def _process_wma(self, file_path: Path) -> ProcessingResult:
        """Process a WMA file via the standalone transformation rule."""
        result = process_wma_file(file_path)
        if result.error:
            self.stats.error_files += 1
        return result
