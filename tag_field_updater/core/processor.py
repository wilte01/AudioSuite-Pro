"""
processor.py — Tag processing orchestration (decomposed).

Business logic lives in mapping_engine.py and transformation_rules.py.
This module re-exports the public API for backward compatibility.

Changed in 2.1.0: :class:`TagProcessor` is the host for the plugin system's
``tag_processor`` extension point.  An enabled plugin's processors run after
the built-in rules for each file, honour the run's dry-run flag, and their
outcomes are counted separately from the built-in edits (Sprint 7).
Changed in 2.1.4: ``scan_directory`` no longer increments ``error_files`` for a
failed result as well as ``process_file`` having already counted it, so the
summary and JSON reported one corrupt file as two errors (found while wiring
the R-06 exit contract, which reads the same count).
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

from audio_suite_shared.plugin_system import (
    ContributionSpec,
    PluginError,
    context_for,
    get_plugins,
    resolved_contributions,
    run_tag_processor,
)

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

#: A resolved plugin contribution: its manifest-declared spec and its callable.
PluginHook = tuple[ContributionSpec, Callable[..., object]]


class TagProcessor:
    """Core processor for tag field updates. Orchestrates scanning and dispatching.

    Args:
        plugins: Whether enabled plugins' tag processors run after the built-in
            rules.  A caller that wants the suite's own behaviour only — and
            the deterministic output a plugin could otherwise change — passes
            False; the CLI's ``--no-plugin-tags`` flag is that switch.
    """

    SUPPORTED_EXTENSIONS = SUPPORTED_EXTENSIONS
    TAG_MAPPINGS = TAG_MAPPINGS

    def __init__(self, *, plugins: bool = True) -> None:
        """Initialize the tag processor with zeroed stats and a clear stop flag.

        Args:
            plugins: Whether plugin tag processors run at all.
        """
        self.stats = ProcessingStats()
        self.stop_flag = False
        self.plugins = plugins
        #: Files whose tags a plugin processor changed.
        self.plugin_changes = 0
        #: Plugin processors that raised (counted, never fatal to the scan).
        self.plugin_errors = 0
        self._hooks: tuple[PluginHook, ...] | None = None

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
        dry_run: bool = False,
    ) -> list[ProcessingResult]:
        """Recursively scan a directory tree and update qualifying tag fields.

        Resets ``self.stats`` and ``self.stop_flag`` at the start of each call.

        Args:
            directory: Root directory path to walk recursively.
            progress_callback: Optional callable invoked after each file is
                processed.  Signature: ``callback(filename: str,
                stats: ProcessingStats) -> None``.
            dry_run: When True, report the tag rewrites each file *would* get
                without persisting any of them — no undo snapshot is recorded
                and no file is saved.  The returned results still carry
                ``updated=True`` for the files that would change.

        Returns:
            A list of :class:`ProcessingResult` — one entry per file visited,
            including skipped and errored files.
        """
        results: list[ProcessingResult] = []
        self.stats = ProcessingStats()
        self.stop_flag = False
        self.plugin_changes = 0
        self.plugin_errors = 0
        # A scan resolves the plugin processors once, not once per file, and a
        # fresh scan re-resolves them: a plugin enabled between runs must take
        # effect without restarting the interpreter.
        self._hooks = None

        logger.info(
            "Starting scan of directory: %s (mode: %s)",
            directory,
            "dry run" if dry_run else "live",
        )

        try:
            for root, _dirs, files in os.walk(directory):
                if self.stop_flag:
                    break

                for file in files:
                    if self.stop_flag:
                        break

                    file_path = Path(root) / file
                    result = self.process_file(file_path, dry_run=dry_run)
                    results.append(result)

                    self.stats.processed_files += 1
                    if result.updated:
                        self.stats.updated_files += 1
                    # ``process_file`` already counts its own errors (the format
                    # delegates and its own except branch); counting the
                    # returned flag again reported one corrupt file as two
                    # errors in the CLI summary and JSON payload.

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

    def process_file(self, file_path: Path, dry_run: bool = False) -> ProcessingResult:
        """Dispatch a single audio file to the appropriate format processor.

        Files whose extension is not in :attr:`SUPPORTED_EXTENSIONS` are skipped
        without error.

        Args:
            file_path: Absolute or relative :class:`~pathlib.Path` to the audio
                file.
            dry_run: When True, the format rule reports the rewrites it would
                apply without persisting them.

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
                result = self._process_mp3(file_path, dry_run=dry_run)
            elif extension == ".flac":
                result = self._process_flac(file_path, dry_run=dry_run)
            elif extension in [".mp4", ".m4a"]:
                result = self._process_mp4(file_path, dry_run=dry_run)
            elif extension == ".ogg":
                result = self._process_ogg(file_path, dry_run=dry_run)
            elif extension == ".opus":
                result = self._process_opus(file_path, dry_run=dry_run)
            elif extension == ".wav":
                result = self._process_wav(file_path, dry_run=dry_run)
            elif extension in (".aiff", ".aif"):
                result = self._process_aiff(file_path, dry_run=dry_run)
            elif extension == ".wma":
                result = self._process_wma(file_path, dry_run=dry_run)
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

        if self.plugins and not result.error:
            self._run_plugin_processors(file_path, dry_run=dry_run)

        return result

    # ------------------------------------------------------------------
    # Plugin tag processors (the ``tag_processor`` extension point)
    # ------------------------------------------------------------------

    def _plugin_hooks(self) -> tuple[PluginHook, ...]:
        """Return the enabled plugins' tag processors, resolved once.

        Returns:
            ``(spec, callable)`` pairs; empty when no plugin contributes one or
            when discovery itself fails, because tagging must not be blocked by
            a plugin directory problem.
        """
        if self._hooks is None:
            try:
                registry = get_plugins()
                self._hooks = resolved_contributions(
                    registry.tag_processors(), registry.resolve_spec
                )
            except PluginError as exc:  # pragma: no cover - discovery is total
                logger.warning("Plugin tag processors unavailable: %s", exc)
                self._hooks = ()
        return self._hooks

    def _run_plugin_processors(self, file_path: Path, *, dry_run: bool) -> None:
        """Run every enabled plugin's tag processor against one file.

        A processor that raises is logged and counted; it never fails the file,
        because its plugin is not part of the suite's own contract.

        Args:
            file_path: The file just processed by the built-in rules.
            dry_run: Whether the run may write anything at all.
        """
        for spec, hook in self._plugin_hooks():
            try:
                outcome = run_tag_processor(
                    hook,
                    file_path,
                    dry_run=dry_run,
                    context=context_for(spec.plugin_id),
                )
            except Exception as exc:  # noqa: BLE001 - a plugin must not abort a run
                self.plugin_errors += 1
                logger.warning(
                    "Plugin %r tag processor %s failed on %s: %s: %s",
                    spec.plugin_id,
                    spec.id,
                    file_path.name,
                    type(exc).__name__,
                    exc,
                )
                continue
            if outcome.changed:
                self.plugin_changes += 1
                logger.info(
                    "Plugin %r tag processor %s changed %s: %s",
                    spec.plugin_id,
                    spec.id,
                    file_path.name,
                    outcome.message or "no reason given",
                )

    # ------------------------------------------------------------------
    # Private delegate methods (backward-compatible dispatch targets)
    # ------------------------------------------------------------------

    def _process_mp3(self, file_path: Path, dry_run: bool = False) -> ProcessingResult:
        """Process an MP3 file via the standalone transformation rule.

        Handles skip/error stats that the standalone function cannot
        because it has no reference to ``self.stats``.
        """
        try:
            result = process_mp3_file(file_path, dry_run=dry_run)
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

    def _process_flac(self, file_path: Path, dry_run: bool = False) -> ProcessingResult:
        """Process a FLAC file via the standalone transformation rule."""
        result = process_flac_file(file_path, dry_run=dry_run)
        if result.error:
            self.stats.error_files += 1
        return result

    def _process_mp4(self, file_path: Path, dry_run: bool = False) -> ProcessingResult:
        """Process an MP4/M4A file via the standalone transformation rule."""
        result = process_mp4_file(file_path, dry_run=dry_run)
        if result.error:
            self.stats.error_files += 1
        return result

    def _process_ogg(self, file_path: Path, dry_run: bool = False) -> ProcessingResult:
        """Process an OGG file via the standalone transformation rule."""
        result = process_ogg_file(file_path, dry_run=dry_run)
        if result.error:
            self.stats.error_files += 1
        return result

    def _process_opus(self, file_path: Path, dry_run: bool = False) -> ProcessingResult:
        """Process an Opus file via the standalone transformation rule."""
        result = process_opus_file(file_path, dry_run=dry_run)
        if result.error:
            self.stats.error_files += 1
        return result

    def _process_wav(self, file_path: Path, dry_run: bool = False) -> ProcessingResult:
        """Process a WAV file via the standalone transformation rule."""
        try:
            result = process_wav_file(file_path, dry_run=dry_run)
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

    def _process_aiff(self, file_path: Path, dry_run: bool = False) -> ProcessingResult:
        """Process an AIFF file via the standalone transformation rule."""
        try:
            result = process_aiff_file(file_path, dry_run=dry_run)
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

    def _process_wma(self, file_path: Path, dry_run: bool = False) -> ProcessingResult:
        """Process a WMA file via the standalone transformation rule."""
        result = process_wma_file(file_path, dry_run=dry_run)
        if result.error:
            self.stats.error_files += 1
        return result
