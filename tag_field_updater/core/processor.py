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
Changed in 2.2.0: the processor hosts a second *source*.  With patterns
configured, each file's name is parsed into tag fields and written through
the shared editable-tag API; with none, the slash rule is unchanged (F-01).  The
format dispatch moved into ``_dispatch_by_format`` so both sources reach the
same plugin-processor seam.
Changed in 2.2.1: :func:`run_scan` is the GUI's entry point (maintenance item
U4).  It owns the three callbacks every tool's processor exposes —
``on_progress`` / ``on_complete`` / ``on_error`` — and builds the per-file lines
the run report is written from, so the window no longer drives the scan itself
and the run leaves a report in the scanned folder like every peer's.
"""

import logging
import os
import time
from collections.abc import Callable
from pathlib import Path

from audio_suite_shared.batch_undo import active_batch
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

from .filename_patterns import parse_filename, validate_patterns
from .filename_tags import apply_filename_fields
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
    "count_scanned_files",
    "process_aiff_file",
    "process_flac_file",
    "process_mp3_file",
    "process_mp4_file",
    "process_ogg_file",
    "process_opus_file",
    "process_wav_file",
    "process_wma_file",
    "run_scan",
    "should_update_value",
    "update_value",
]

logger = logging.getLogger(__name__)

#: A resolved plugin contribution: its manifest-declared spec and its callable.
PluginHook = tuple[ContributionSpec, Callable[..., object]]


class TagProcessor:
    """Core processor for tag field updates. Orchestrates scanning and dispatching.

    Two sources share this one engine.  With no *patterns* the run is the
    slash rule this tool has always applied (``TAG_MAPPINGS`` fields).  With
    patterns it is the filename source: each file's name is parsed into fields
    and those fields are written (functional backlog F-01).

    Args:
        plugins: Whether enabled plugins' tag processors run after the built-in
            rules.  A caller that wants the suite's own behaviour only — and
            the deterministic output a plugin could otherwise change — passes
            False; the CLI's ``--no-plugin-tags`` flag is that switch.
        patterns: Ordered filename patterns.  Empty (the default) keeps the
            slash rule.
        only_fill_blanks: In filename mode, leave a field that already has a
            value alone.  Previous behaviour did not exist for these fields, so
            the safe default is on; overwriting is an explicit choice.
    """

    SUPPORTED_EXTENSIONS = SUPPORTED_EXTENSIONS
    TAG_MAPPINGS = TAG_MAPPINGS

    def __init__(
        self,
        *,
        plugins: bool = True,
        patterns: tuple[str, ...] = (),
        only_fill_blanks: bool = True,
    ) -> None:
        """Initialize the tag processor with zeroed stats and a clear stop flag.

        Args:
            plugins: Whether plugin tag processors run at all.
            patterns: Filename patterns, tried in order; empty selects the
                slash rule.  Validated here so a typo cannot half-tag a
                library before it surfaces.
            only_fill_blanks: In filename mode, never overwrite a non-empty
                field.
        """
        self.stats = ProcessingStats()
        self.stop_flag = False
        self.plugins = plugins
        #: Validated filename patterns; empty means the slash rule.
        self.patterns: tuple[str, ...] = validate_patterns(patterns)
        #: Whether a parsed field may overwrite an existing one.
        self.only_fill_blanks = only_fill_blanks
        #: Files whose tags a plugin processor changed.
        self.plugin_changes = 0
        #: Plugin processors that raised (counted, never fatal to the scan).
        self.plugin_errors = 0
        self._hooks: tuple[PluginHook, ...] | None = None

    def use_filename_patterns(
        self, patterns: tuple[str, ...] | list[str], *, only_fill_blanks: bool = True
    ) -> None:
        """Switch this processor to the filename source (or back to the slash rule).

        Args:
            patterns: Patterns to use, in order.  An empty sequence restores
                the slash rule.
            only_fill_blanks: Whether a parsed field may overwrite an existing
                tag value.

        Raises:
            PatternError: If a pattern is invalid; nothing is applied to the
                processor in that case, so a bad list cannot half-configure it.
        """
        self.patterns = validate_patterns(tuple(patterns))
        self.only_fill_blanks = only_fill_blanks

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

            if self.patterns:
                result = self._process_filename_source(file_path, dry_run=dry_run)
            else:
                result = self._dispatch_by_format(file_path, dry_run=dry_run)

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

    def _dispatch_by_format(self, file_path: Path, dry_run: bool) -> ProcessingResult:
        """Route one file to the rule for its container (the slash rule).

        Args:
            file_path: Audio file whose extension selects the rule.
            dry_run: Whether the rule may save.

        Returns:
            The rule's result, or an empty result for an unsupported extension
            (counted as skipped).
        """
        extension = file_path.suffix.lower()
        if extension == ".mp3":
            return self._process_mp3(file_path, dry_run=dry_run)
        if extension == ".flac":
            return self._process_flac(file_path, dry_run=dry_run)
        if extension in [".mp4", ".m4a"]:
            return self._process_mp4(file_path, dry_run=dry_run)
        if extension == ".ogg":
            return self._process_ogg(file_path, dry_run=dry_run)
        if extension == ".opus":
            return self._process_opus(file_path, dry_run=dry_run)
        if extension == ".wav":
            return self._process_wav(file_path, dry_run=dry_run)
        if extension in (".aiff", ".aif"):
            return self._process_aiff(file_path, dry_run=dry_run)
        if extension == ".wma":
            return self._process_wma(file_path, dry_run=dry_run)
        self.stats.skipped_files += 1
        logger.info("Skipped %s: unsupported format (%s)", file_path.name, extension)
        return ProcessingResult(file_path=file_path)

    def _process_filename_source(
        self, file_path: Path, dry_run: bool = False
    ) -> ProcessingResult:
        """Parse *file_path*'s name and write the captured fields.

        A file whose name matches no pattern is counted as skipped and left
        exactly as it is: guessing a split is the one outcome this source must
        not produce, because a wrong tag looks like a successful run.

        Args:
            file_path: Audio file to parse and tag.
            dry_run: Report the rewrites without saving any of them.

        Returns:
            A :class:`ProcessingResult` carrying the parsed fields, the
            fields written and the ones left alone.
        """
        parsed = parse_filename(file_path.name, self.patterns)
        if parsed is None:
            self.stats.skipped_files += 1
            logger.info(
                "Skipped %s: no filename pattern matched (%s)",
                file_path.name,
                " | ".join(self.patterns),
            )
            return ProcessingResult(file_path=file_path, filename_pattern="")

        outcome = apply_filename_fields(
            file_path,
            parsed.fields,
            only_fill_blanks=self.only_fill_blanks,
            dry_run=dry_run,
        )
        return ProcessingResult(
            file_path=file_path,
            updated=outcome.updated,
            tags_updated=outcome.written,
            filename_fields=tuple(parsed.fields.items()),
            filename_pattern=parsed.pattern,
            skipped_fields=outcome.skipped_existing,
        )

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


def count_scanned_files(directory: str) -> int:
    """Count the files a scan of *directory* will visit, recursively.

    ``scan_directory`` walks the tree and reports progress per file, so a
    caller cannot know the total up front.  This is the same walk without
    opening anything — cheap next to tagging — and it is what makes the
    progress bar a fraction of a known total instead of a decoration.

    The count is of **every** file, not only the supported extensions:
    ``ProcessingStats.processed_files`` is incremented for each file the walk
    visits, including the ones skipped for an unsupported extension.
    Counting only audio files sized the bar to a smaller denominator than the
    value it was fed, so a folder holding artwork or notes beside a few tracks
    read as complete while most of it was still unvisited.

    Args:
        directory: Root directory the scan will walk.

    Returns:
        The number of files the walk will visit; ``0`` when the directory
        cannot be listed, which leaves the bar empty rather than failing the
        run.
    """
    total = 0
    try:
        for _root, _dirs, files in os.walk(directory):
            total += len(files)
    except OSError as exc:  # pragma: no cover - os.walk swallows these
        logger.warning("Could not count files in %s: %s", directory, exc)
        return 0
    return total


def _log_line(
    result: ProcessingResult, *, is_dry_run: bool, filename_mode: bool
) -> str:
    """Render one file's outcome as a line for the run report.

    The report is the run's own record, so it says what happened to every file
    the walk visited — including the ones that needed nothing — and, in
    filename mode, what the name parsed to.  A dry run says *would*, because
    nothing was written.

    Args:
        result: The per-file result the scan returned.
        is_dry_run: Whether the run wrote nothing.
        filename_mode: Whether the run parsed names instead of applying the
            slash rule, which decides how a no-match file is described.

    Returns:
        One report line, newline-terminated.
    """
    name = result.file_path.name
    if result.error:
        return f"[ERROR]   {name}: {result.error}\n"

    if result.file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return f"[SKIP]    {name} (unsupported format)\n"

    parsed = ""
    if result.filename_fields:
        rendered = " ".join(f"{key}='{value}'" for key, value in result.filename_fields)
        parsed = f" ({rendered})"

    if filename_mode and not result.filename_pattern:
        return f"[NO MATCH] {name}: no pattern matched, left unchanged\n"

    if result.updated:
        verb = "WOULD UPDATE" if is_dry_run else "UPDATED"
        fields = ", ".join(result.tags_updated) or "no tag names reported"
        line = f"[{verb}] {name}{parsed} -> {fields}\n"
        if result.skipped_fields:
            line += f"             kept existing: {', '.join(result.skipped_fields)}\n"
        return line

    return f"[UNCHANGED] {name}{parsed}\n"


def run_scan(
    directory: str,
    *,
    is_dry_run: bool,
    patterns: tuple[str, ...] = (),
    only_fill_blanks: bool = True,
    plugins: bool = True,
    on_progress: Callable[..., None],
    on_complete: Callable[..., None],
    on_error: Callable[[str], None],
    processor: TagProcessor | None = None,
) -> None:
    """Scan *directory* and drive a GUI run through the shared callbacks.

    This is the tool's ``run_*`` entry point, the shape every GUI tool's
    processor exposes (AGENTS.md "GUI Callback Contract"): the processor owns
    the three payloads and the window's handlers mirror them.

    Args:
        directory: Root directory to walk.
        is_dry_run: When True the rewrites are computed and reported but
            nothing is saved, and no undo record is created.
        patterns: Filename patterns, tried in order; empty selects the slash
            rule.
        only_fill_blanks: In filename mode, never overwrite a non-empty field.
        plugins: Whether enabled plugins' tag processors run after the built-in
            rules.
        on_progress: Called after each file with ``processed``, ``total``,
            ``skipped``, ``errors``, ``display_text`` and ``updated``.
        on_complete: Called once at the end with ``total``, ``processed``,
            ``skipped``, ``errors``, ``duration_secs``, ``log_entries``,
            ``updated``, ``audio_files``, ``skipped_files`` and
            ``error_files``.
        on_error: Called with one user-facing message if the scan itself
            fails; per-file failures are counted and reported instead.
        processor: The instance to scan with, so the window that shows a Stop
            button can signal the run it started.  A fresh processor is built
            when omitted.

    Raises:
        PatternError: If *patterns* is invalid.  Raised before any walk, so a
            typo cannot half-tag a library; the GUI validates first and shows
            a dialog instead of starting a run.
    """
    engine = processor if processor is not None else TagProcessor(plugins=plugins)
    engine.use_filename_patterns(patterns, only_fill_blanks=only_fill_blanks)

    total = count_scanned_files(directory)
    started = time.monotonic()

    def _progress(filename: str, stats: ProcessingStats) -> None:
        """Adapt the processor's per-file ping to the shared payload."""
        on_progress(
            processed=stats.processed_files,
            total=total,
            skipped=stats.skipped_files,
            errors=stats.error_files,
            display_text=filename,
            updated=stats.updated_files,
        )

    try:
        with active_batch("tag_field_updater", "tag_edit"):
            results = engine.scan_directory(
                directory, dry_run=is_dry_run, progress_callback=_progress
            )
    except Exception as exc:  # noqa: BLE001 - the UI reports, never raises
        mapped = map_to_audio_error(exc, context={"directory": directory})
        logger.error(
            "[%s] Scan failed for %s: %s",
            type(mapped).__name__,
            directory,
            mapped,
            exc_info=True,
        )
        on_error(user_message_for(mapped))
        return

    stats = engine.stats
    on_complete(
        total=total,
        processed=stats.processed_files,
        skipped=stats.skipped_files,
        errors=stats.error_files,
        duration_secs=time.monotonic() - started,
        log_entries=[
            _log_line(
                result, is_dry_run=is_dry_run, filename_mode=bool(engine.patterns)
            )
            for result in results
        ],
        updated=stats.updated_files,
        audio_files=stats.total_files,
        skipped_files=[
            {"filename": r.file_path.name, "reason": "no supported audio tags"}
            for r in results
            if not r.updated and r.error is None
        ],
        error_files=[
            {"filename": r.file_path.name, "error": r.error}
            for r in results
            if r.error is not None
        ],
    )
