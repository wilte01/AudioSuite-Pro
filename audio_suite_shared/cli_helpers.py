"""
cli_helpers.py — Shared CLI argument parsing and application
logic for Audio Suite applications.

Provides standardized implementations for common CLI operations:
- Argument parsing for source/output paths
- Stage toggles and parameters
- Auto-start functionality
- Common CLI patterns

This reduces code duplication across all 19 Audio Suite applications.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable, Optional

# Type aliases for common patterns
TkinterVar = Any  # tkinter variable types (StringVar, IntVar, etc.)
AutoStartFunc = Optional[Callable[[], None]]
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


def create_standard_parser(
    description: str, add_stages: bool = True
) -> argparse.ArgumentParser:
    """
    Create a standard argument parser for Audio Suite applications.

    Args:
        description: Application description
        add_stages: Whether to add stage-related arguments

    Returns:
        Configured ArgumentParser
    """
    parser = argparse.ArgumentParser(
        description=description, formatter_class=argparse.RawDescriptionHelpFormatter
    )

    # Standard arguments
    parser.add_argument(
        "--source", "-s", type=str, help="Source directory containing audio files"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        help="Output directory (defaults to source if not specified)",
    )
    parser.add_argument(
        "--auto-start",
        action="store_true",
        help="Start processing automatically after loading",
    )
    parser.add_argument(
        "--auto-end",
        action="store_true",
        help="Close application automatically when processing completes",
    )

    # Stage-related arguments (for applications that support stages)
    if add_stages:
        parser.add_argument(
            "--stages",
            type=str,
            default="",
            help=(
                "Comma-separated list of stages to enable "
                "(e.g., 'declick,trim,enhance,normalise')"
            ),
        )

        # Common stage parameters
        parser.add_argument(
            "--sensitivity",
            type=float,
            default=5.0,
            help="Declick sensitivity threshold (0.0-10.0)",
        )
        parser.add_argument(
            "--width",
            type=float,
            default=10.0,
            help="Maximum click width in milliseconds",
        )
        parser.add_argument(
            "--threshold",
            type=float,
            default=-40.0,
            help="Silence detection threshold in dB",
        )
        parser.add_argument(
            "--fade", action="store_true", help="Apply fade in/out during trimming"
        )
        parser.add_argument(
            "--fade-in", type=int, default=100, help="Fade in duration in milliseconds"
        )
        parser.add_argument(
            "--fade-out",
            type=int,
            default=100,
            help="Fade out duration in milliseconds",
        )
        parser.add_argument(
            "--preset",
            type=str,
            default="Moderate",
            choices=["Mild", "Moderate", "Aggressive", "Custom"],
            help="Enhancement preset",
        )
        parser.add_argument(
            "--target-lufs",
            type=float,
            default=-16.0,
            help="Target loudness in LUFS for normalization",
        )
        parser.add_argument(
            "--tolerance",
            type=float,
            default=1.0,
            help="Loudness tolerance for normalization",
        )

    return parser


class StandardCLIHandler:
    """
    Standard CLI argument handler for Audio Suite applications.

    Provides common functionality for applying CLI arguments to application state.
    """

    def __init__(self, app_instance: Any):
        self.app = app_instance

    def apply_source_output_args(
        self,
        args: argparse.Namespace,
        source_var: TkinterVar,
        output_var: TkinterVar,
        auto_start_func: AutoStartFunc = None,
        auto_end_var: Optional[TkinterVar] = None,
    ) -> bool:
        """
        Apply source and output arguments to the application.

        Args:
            args: Parsed command line arguments
            source_var: Tkinter StringVar for source path
            output_var: Tkinter StringVar for output path
            auto_start_func: Function to call for auto-start
            auto_end_var: Variable to set for auto-end

        Returns:
            True if auto-start should be triggered
        """
        should_auto_start = False

        if args.source:
            source_var.set(args.source)
            # Load registry if the app has this method
            if hasattr(self.app, "_load_registry"):
                self.app._load_registry(args.source)

        if args.output:
            output_var.set(args.output)

        if auto_end_var is not None:
            self.app.auto_end = args.auto_end

        if getattr(args, "auto_start", False) and auto_start_func:
            should_auto_start = True

        return should_auto_start

    def apply_stage_args(self, args: argparse.Namespace, config: Any) -> None:
        """
        Apply stage-related arguments to the configuration.

        Args:
            args: Parsed command line arguments
            config: Application configuration object
        """
        if not hasattr(args, "stages"):
            return

        # Parse stage toggles
        if args.stages:
            active_stages = {s.strip().lower() for s in args.stages.split(",")}

            # Common stage names
            stage_mappings = {
                "declick": "declick",
                "trim": "trim",
                "enhance": "enhance",
                "normalise": "normalise",
                "normalize": "normalise",  # Handle both spellings
            }

            for stage_name, config_attr in stage_mappings.items():
                if stage_name in active_stages and hasattr(config, config_attr):
                    setattr(config, config_attr, True)

        # Apply stage parameters if they exist in config
        param_mappings = {
            "sensitivity": ("declick_params", "sensitivity"),
            "width": ("declick_params", "max_width_ms"),
            "threshold": ("trim_params", "threshold"),
            "fade": ("trim_params", "apply_fade"),
            "fade_in": ("trim_params", "fade_in_ms"),
            "fade_out": ("trim_params", "fade_out_ms"),
            "preset": ("enhance_params", "preset"),
            "target_lufs": ("normalise_params", "target_lufs"),
            "tolerance": ("normalise_params", "tolerance"),
        }

        for arg_name, (config_section, config_attr) in param_mappings.items():
            if hasattr(args, arg_name):
                arg_value = getattr(args, arg_name)
                if hasattr(config, config_section):
                    section_obj = getattr(config, config_section)
                    if hasattr(section_obj, config_attr):
                        setattr(section_obj, config_attr, arg_value)


class SourceOutputCLIHandler(StandardCLIHandler):
    """
    Specialized CLI handler for applications that only need source/output handling.

    Used by simpler applications that don't have stage-based processing.
    """

    def apply_basic_args(
        self,
        args: argparse.Namespace,
        source_var: TkinterVar,
        output_var: TkinterVar,
        auto_start_func: AutoStartFunc = None,
    ) -> bool:
        """
        Apply basic source/output arguments.

        Returns:
            True if auto-start should be triggered
        """
        return self.apply_source_output_args(
            args, source_var, output_var, auto_start_func
        )


def parse_cli_args(description: str, add_stages: bool = True) -> argparse.Namespace:
    """
    Parse command line arguments using standard configuration.

    Args:
        description: Application description
        add_stages: Whether to add stage-related arguments

    Returns:
        Parsed arguments namespace
    """
    parser = create_standard_parser(description, add_stages)
    return parser.parse_args()


def validate_cli_args(args: argparse.Namespace) -> list[str]:
    """
    Validate CLI arguments and return list of errors.

    Args:
        args: Parsed command line arguments

    Returns:
        List of validation error messages
    """
    errors = []

    # Validate source directory
    if getattr(args, "source", None):
        source_path = Path(args.source)
        if not source_path.exists():
            errors.append(f"Source directory does not exist: {args.source}")
        elif not source_path.is_dir():
            errors.append(f"Source path is not a directory: {args.source}")

    # Validate output directory
    if getattr(args, "output", None):
        output_path = Path(args.output)
        if not output_path.exists():
            errors.append(f"Output directory does not exist: {args.output}")
        elif not output_path.is_dir():
            errors.append(f"Output path is not a directory: {args.output}")

    # Validate stage parameters
    if hasattr(args, "sensitivity") and not (0 <= args.sensitivity <= 10):
        errors.append("Sensitivity must be between 0.0 and 10.0")

    if hasattr(args, "width") and args.width <= 0:
        errors.append("Width must be greater than 0")

    if hasattr(args, "threshold") and args.threshold > 0:
        errors.append("Threshold must be less than or equal to 0 dB")

    if hasattr(args, "fade_in") and args.fade_in < 0:
        errors.append("Fade-in duration must be non-negative")

    if hasattr(args, "fade_out") and args.fade_out < 0:
        errors.append("Fade-out duration must be non-negative")

    if hasattr(args, "target_lufs"):
        from audio_suite_shared.cli_dataclasses import validate_target_lufs

        errors.extend(validate_target_lufs(args.target_lufs))

    if hasattr(args, "tolerance") and args.tolerance < 0:
        errors.append("Tolerance must be non-negative")

    return errors


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
