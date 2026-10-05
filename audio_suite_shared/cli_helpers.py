"""
cli_helpers.py — Shared CLI argument parsing and application
logic for Audio Suite applications.

Provides standardized implementations for common CLI operations:
- Common CLI patterns
- The Master Driver display-flag handshake segment shared by every tool

This reduces code duplication across all Audio Suite applications.
"""

from __future__ import annotations

import sys
from typing import Any

# Parsed CLI arguments: argparse.Namespace or a per-tool args dataclass.
# UniversalCLIHandler discovers supported fields via hasattr/getattr, so any
# attribute object is accepted here; per-tool dataclasses cannot share one
# static Protocol because they each expose a different subset of fields.
ParsedCliArgs = Any


def was_launched_from_driver(argv: list[str] | None = None) -> bool:
    """
    Detect whether the application was launched by the Master Driver.

    The Master Driver always passes CLI arguments — at minimum a target path
    (or the numeric placeholder used for enrich tools) followed by the
    display-only handshake flags. A standalone launch starts with no
    arguments at all, so a full argv (index 0 = program name) holding more
    than one entry proves a driver launch.

    Args:
        argv: Full argument vector including the program name at index 0.
            Defaults to ``sys.argv`` when omitted.

    Returns:
        True when at least one CLI argument follows the program name.
    """
    if argv is None:
        argv = sys.argv
    return len(argv) > 1


#: The Master-Driver display-flag handshake pairs and the mutable state each
#: pair drives. Order matters only for documentation; parse order is content
#: driven. ``live_mode`` defaults to False (a driver "min" argv carries the
#: placeholder slot but no mode flag, and every pre-existing parser reported
#: dry/net-default in that case).
_HANDSHAKE_PAIRS: dict[str, str] = {
    "--live": "live_mode=True",
    "--dry": "live_mode=False",
    "--start": "auto_start=True",
    "--no-start": "auto_start=False",
    "--end": "auto_end=True",
    "--no-end": "auto_end=False",
    "--clear-logs": "clear_logs=True",
    "--no-clear-logs": "clear_logs=False",
    "--parallel-run": "parallel_run=True",
    "--no-parallel-run": "parallel_run=False",
}

#: The 5 flag pairs that make up the Master Driver handshake segment.
HANDSHAKE_FLAG_PAIRS: tuple[tuple[str, str], ...] = (
    ("--live", "--dry"),
    ("--start", "--no-start"),
    ("--end", "--no-end"),
    ("--clear-logs", "--no-clear-logs"),
    ("--parallel-run", "--no-parallel-run"),
)


def print_tool_usage_error(tool_label: str, error: str) -> None:
    """Print a tool-prefixed usage error to stderr.

    The single owner of the one-line ``f"{tool_label}: {error}"`` writer
    previously duplicated in every per-tool ``utils/cli_args.py``.

    Args:
        tool_label: Display name of the tool, e.g. ``"BPM Analyzer"``.
        error: The human-readable validation error text.
    """
    print(f"{tool_label}: {error}", file=sys.stderr)


def consume_handshake_token(
    token: str,
    args: Any,
    accepted: frozenset[str] | set[str] | None = None,
) -> bool | None:
    """Consume one Master-Driver handshake token against *args*.

    Attributes are only written when the token is a handshake flag the tool
    accepts, so a caller-driven token-subset contract is preserved exactly:
    a tool that never reads ``--dry`` still never gets ``live_mode`` written.

    Args:
        token: The argv token under consideration.
        args: Per-tool args object (any attribute carrier) whose fields are
            mutated in place.
        accepted: Restriction set. ``None`` (default) accepts all 10
            handshake tokens; a subset restricts which tokens may take
            effect. Tokens outside *accepted* are reported as not-here (the
            caller continues scanning past them as before).

    Returns:
        True when the token was consumed (attribute written),
        False when the token is a handshake token the tool does not accept,
        None when the token is not a handshake token at all.
    """
    if token not in _HANDSHAKE_PAIRS:
        return None
    if accepted is not None and token not in accepted:
        return False
    spec = _HANDSHAKE_PAIRS[token]
    attr_name, _, literal = spec.partition("=")
    setattr(args, attr_name, literal == "True")
    return True


def apply_handshake_segment(
    argv: list[str],
    args: Any,
    accepted: frozenset[str] | set[str] | None = None,
) -> bool:
    """Scan an argv tail for Master-Driver display-flag handshake tokens.

    The shared implementation of the flag ladder that every per-tool
    ``utils/cli_args.py`` previously re-implemented. Attributes are only
    written for pairs the tool accepts, matching each per-tool contract.

    Args:
        argv: The argv (or tail) to scan.
        args: Per-tool args object whose fields are mutated in place.
        accepted: Optional restriction to a token subset.

    Returns:
        True when *any* handshake token was consumed.
    """
    consumed = False
    for token in argv:
        if consume_handshake_token(token, args, accepted=accepted) is True:
            consumed = True
    return consumed


def read_positional_handshake(
    argv: list[str],
    args: Any,
    *,
    mode_idx: int,
    start_idx: int,
    end_idx: int,
) -> None:
    """Read the fixed positional handshake slots into *args*.

    The Master Driver's argv layout for the folder tools places the mode /
    auto-start / auto-end flags in consecutive slots (with a ``"0"``
    placeholder or a tool-specific value before them). This shared reader
    owns the ``argv[idx] == "--flag"`` equality that previously lived in
    each positional tool's parser: any token other than the exact spelling
    leaves the field at its default (False).

    Args:
        argv: Full argument vector (index 0 = program name).
        args: Per-tool args object whose fields are mutated in place.
        mode_idx: Absolute index holding ``--live`` / ``--dry``.
        start_idx: Absolute index holding ``--start`` / ``--no-start``.
        end_idx: Absolute index holding ``--end`` / ``--no-end``.
    """
    if len(argv) > mode_idx:
        args.live_mode = argv[mode_idx] == "--live"
    if len(argv) > start_idx:
        args.auto_start = argv[start_idx] == "--start"
    if len(argv) > end_idx:
        args.auto_end = argv[end_idx] == "--end"


def read_display_flag_slots(
    argv: list[str],
    args: Any,
    logs_idx: int,
    parallel_run_idx: int,
) -> None:
    """Read the display-only handshake pair at fixed indices into *args*.

    Mirrors the genre_sync / replaygain bibliography where the driver's
    launcher always appends the display flags right after the positional
    block: ``--clear-logs`` first, then ``--parallel-run``. A non-matching
    token at either slot writes False (the default), as before.

    Args:
        argv: Full argument vector (index 0 = program name).
        args: Per-tool args object whose fields are mutated in place.
        logs_idx: Absolute index holding ``--clear-logs`` /
            ``--no-clear-logs``.
        parallel_run_idx: Absolute index holding ``--parallel-run`` /
            ``--no-parallel-run``.
    """
    if len(argv) > logs_idx:
        args.clear_logs = argv[logs_idx] == "--clear-logs"
    if len(argv) > parallel_run_idx:
        args.parallel_run = argv[parallel_run_idx] == "--parallel-run"


def apply_handshake_membership(
    argv: list[str],
    args: Any,
) -> None:
    """Set the handshake flags by presence anywhere in *argv*.

    The album_art_sync / metadata_scrubber parsers used ``"--flag" in argv``
    membership semantics: the positive spelling anywhere in the vector
    turns the field on, and the ``--no-`` spelling is never consulted
    (absence leaves the False default). This shared function keeps that
    contract byte-identical, including the pathological both-spellings case
    where the positive spelling wins.

    Args:
        argv: Full argument vector (index 0 = program name).
        args: Per-tool args object whose fields are mutated in place.
    """
    args.live_mode = "--live" in argv
    args.auto_start = "--start" in argv
    args.auto_end = "--end" in argv
    args.clear_logs = "--clear-logs" in argv
    args.parallel_run = "--parallel-run" in argv


class UniversalCLIHandler:
    """
    Universal CLI argument handler that automatically detects
    and handles different CLI patterns.

    Supports three main patterns:
    1. Source/Output pattern (6 apps) - uses 'source' and 'output' arguments
    2. Folder Path pattern (13 apps) - uses 'folder_path' and app-specific arguments
    3. No Arguments pattern (3 apps) - no CLI arguments

    This provides a single source of truth for CLI handling
    across all Audio Suite applications.
    """

    def __init__(self, app_instance: Any) -> None:
        self.app = app_instance

    def apply_cli_args(self, args: ParsedCliArgs, **kwargs: Any) -> bool:
        """
        Automatically detect CLI pattern and apply arguments appropriately.

        Args:
            args: Parsed command line arguments
            **kwargs: Additional parameters (source_var, output_var, etc.)

        Returns:
            True if auto-start should be triggered
        """
        # Detect pattern based on argument structure
        if hasattr(args, "source"):
            return self._apply_source_pattern(args, **kwargs)
        elif hasattr(args, "folder_path"):
            return self._apply_folder_pattern(args, **kwargs)
        elif hasattr(args, "directory"):
            return self._apply_directory_pattern(args, **kwargs)
        else:
            return self._apply_no_args_pattern(**kwargs)

    def _apply_source_pattern(self, args: ParsedCliArgs, **kwargs: Any) -> bool:
        """
        Handle source/output pattern used by 5 applications.

        Apps: Audio Enhancer, Audio Refinery, Music Format Converter,
              ASX Extractor, CD Ripper
        """
        should_auto_start = False

        # Get required parameters
        source_var = kwargs.get("source_var")
        output_var = kwargs.get("output_var")
        auto_start_func = kwargs.get("auto_start_func")
        auto_end_var = kwargs.get("auto_end_var")

        # Apply source
        if args.source and source_var:
            source_var.set(args.source)
            # Load registry if app has this method
            if hasattr(self.app, "_load_registry"):
                self.app._load_registry(args.source)

        # Apply output
        if args.output and output_var:
            output_var.set(args.output)

        # Apply auto-end
        if auto_end_var is not None:
            self.app.auto_end = args.auto_end

        # Apply auto-start
        if getattr(args, "auto_start", False) and auto_start_func:
            should_auto_start = True

        return should_auto_start

    def _apply_folder_pattern(self, args: ParsedCliArgs, **kwargs: Any) -> bool:
        """
        Handle folder_path pattern used by 12 applications.

        Apps: ReplayGain Analyzer, Tempo Analyzer, Silence Trimmer,
              Album Genre Tagger, Album Art Sync, Audio Normalizer,
              Metadata Scrubber, Genre Sync, Key Detector, BPM Analyzer,
              Pop & Click Remover
        """
        should_auto_start = False

        # Get required parameters
        folder_var = kwargs.get("folder_var")

        # Apply folder path
        if args.folder_path and folder_var:
            folder_var.set(args.folder_path)

        # Apply common arguments
        if hasattr(args, "live_mode") and hasattr(self.app, "run_mode"):
            self.app.run_mode.set("Live Update" if args.live_mode else "Dry Run")

        if hasattr(args, "auto_end") and hasattr(self.app, "auto_end"):
            self.app.auto_end = args.auto_end

        # Apply app-specific arguments
        self._apply_app_specific_args(args)

        # Auto-start is driven purely by the parsed argument; callers do not
        # need to supply auto_start_func — the returned bool is the signal.
        if getattr(args, "auto_start", False):
            should_auto_start = True

        return should_auto_start

    def _apply_app_specific_args(self, args: ParsedCliArgs) -> None:
        """
        Apply application-specific CLI arguments based on app attributes.

        This method checks for common app-specific arguments and applies them
        if the corresponding app attributes exist.
        """
        # ReplayGain/Audio Normalizer specific
        if hasattr(args, "target_lufs") and hasattr(self.app, "target_lufs"):
            self.app.target_lufs.set(args.target_lufs)
        if hasattr(args, "tolerance") and hasattr(self.app, "tolerance"):
            self.app.tolerance.set(args.tolerance)

        # Tempo Analyzer specific
        if hasattr(args, "scheme") and hasattr(self.app, "scheme"):
            self.app.scheme.set(args.scheme)

        # Album Genre Tagger specific
        if hasattr(args, "min_coverage") and hasattr(self.app, "min_coverage"):
            self.app.min_coverage.set(args.min_coverage)

        # Album Art Sync specific
        if hasattr(args, "embed_size") and hasattr(self.app, "embed_size"):
            self.app.embed_size.set(args.embed_size)
        if hasattr(args, "purge") and hasattr(self.app, "purge"):
            self.app.purge.set(args.purge)

        # Metadata Scrubber specific
        if hasattr(args, "preserve_lyrics") and hasattr(self.app, "preserve_lyrics"):
            self.app.preserve_lyrics.set(args.preserve_lyrics)
        if hasattr(args, "preserve_album_artist") and hasattr(
            self.app, "preserve_album_artist"
        ):
            self.app.preserve_album_artist.set(args.preserve_album_artist)
        if hasattr(args, "preserve_embedded_art") and hasattr(
            self.app, "preserve_embedded_art"
        ):
            self.app.preserve_embedded_art.set(args.preserve_embedded_art)

        # BPM Analyzer specific
        if hasattr(args, "bpm_min") and hasattr(self.app, "bpm_range_min"):
            self.app.bpm_range_min.set(args.bpm_min)
        if hasattr(args, "bpm_max") and hasattr(self.app, "bpm_range_max"):
            self.app.bpm_range_max.set(args.bpm_max)
        if hasattr(args, "duration") and hasattr(self.app, "analysis_duration"):
            self.app.analysis_duration.set(args.duration)

        # General parallel processing args (BPM, Key Detector, Silence Trimmer)
        if hasattr(args, "parallel_mode") and hasattr(self.app, "parallel_mode"):
            self.app.parallel_mode.set(args.parallel_mode)
        if hasattr(args, "max_workers") and hasattr(self.app, "max_workers"):
            self.app.max_workers.set(args.max_workers)

        # Silence Trimmer specific
        if hasattr(args, "threshold") and hasattr(self.app, "threshold"):
            self.app.threshold.set(args.threshold)
        if hasattr(args, "apply_fade") and hasattr(self.app, "fade_var"):
            self.app.fade_var.set(args.apply_fade)
        if (
            hasattr(args, "fade_in_ms")
            and hasattr(self.app, "fade_in_duration")
            and args.fade_in_ms is not None
        ):
            self.app.fade_in_duration.set(args.fade_in_ms)
        if (
            hasattr(args, "fade_out_ms")
            and hasattr(self.app, "fade_out_duration")
            and args.fade_out_ms is not None
        ):
            self.app.fade_out_duration.set(args.fade_out_ms)

    def _apply_directory_pattern(self, args: ParsedCliArgs, **kwargs: Any) -> bool:
        """
        Handle directory pattern used by ASX Extractor.

        Apps: ASX Extractor
        """
        should_auto_start = False

        # Get required parameters
        directory_var = kwargs.get("directory_var")
        auto_start_func = kwargs.get("auto_start_func")

        # Apply directory
        if args.directory and directory_var:
            directory_var.set(args.directory)

        # Apply mode
        if hasattr(args, "mode") and hasattr(self.app, "asx_action_mode"):
            if args.mode:
                self.app.asx_action_mode.set(args.mode)

        # Apply auto-end
        if hasattr(args, "auto_end") and hasattr(self.app, "auto_end"):
            self.app.auto_end = args.auto_end

        # Apply auto-start
        if getattr(args, "auto_start", False) and auto_start_func:
            should_auto_start = True

        return should_auto_start

    def _apply_no_args_pattern(self, **kwargs: Any) -> bool:
        """
        Handle no-arguments pattern used by 2 applications.

        Apps: CD Ripper (no args), Master Driver
        """
        # No arguments to apply
        return False
