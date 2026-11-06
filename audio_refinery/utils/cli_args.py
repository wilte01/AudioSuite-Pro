"""
utils/cli_args.py
Command-line argument parser for Audio Refinery.

All individual stage arguments mirror the argument names used by the
standalone tools so that existing scripts and suite launchers can be
adapted with minimal changes.

Unknown arguments are silently discarded (parse_known_args) so that
GUI launcher injection does not cause errors.

Display-only flags: --clear-logs|--no-clear-logs,
                    --parallel-run|--no-parallel-run

Changed in 2.3.1: carries this window's change for its module (see
CHANGELOG.md and TECHNICAL_CHANGELOG.md).

Changed in 2.5.0: ``--album-mode`` (F-E1) reaches the GUI launch path, so a
Master Driver run and a typed command configure album mode the same way.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from audio_suite_shared.cli_dataclasses import validate_target_lufs
from audio_suite_shared.cli_helpers import (
    was_launched_from_driver as was_launched_from_driver,
)

from ..core.models import NORMALISATION_MODES


@dataclass(frozen=True)
class RefineryArgs:
    """CLI arguments for Audio Refinery."""

    # Paths
    source: str = ""
    output: str = ""

    # Automation
    auto_start: bool = False
    auto_end: bool = False

    # Processing mode
    dry_run: bool = False

    # Display-only driver orchestration flags
    clear_logs: bool = False
    parallel_run: bool = False

    # Stage toggles
    stages: str = "declick,trim,enhance,normalise"  # comma-separated

    # Declick
    sensitivity: float = 0.31
    width: int = 2

    # Trim
    threshold: int = -50
    fade: bool = False
    fade_in: int = 500
    fade_out: int = 1000

    # Noise Reduction
    reduce_hum: bool = False
    hum_frequency: int = 60
    hum_harmonics: int = 8
    hum_quality: float = 30.0
    reduce_broadband: bool = False
    noise_start_ms: int = 0
    noise_end_ms: int = 500
    gate_threshold_db: float = 3.0

    # Enhance
    preset: str = "Moderate"

    # Normalise
    target_lufs: float = -14.0
    tolerance: float = 0.5
    true_peak: float = -1.5
    lra: float = 11.0
    normalise_mode: str = "normalise"
    album_mode: bool = False


def parse(argv: list[str] | None = None) -> RefineryArgs:
    """Parse command-line arguments into a RefineryArgs instance.

    Args:
        argv: Argument list to parse. Defaults to sys.argv when None.

    Returns:
        Populated RefineryArgs.

    Raises:
        SystemExit: If --target-lufs is not one of the permitted presets.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Audio Refinery — single-pass four-stage audio processing pipeline."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  Audio_Refinery.pyw\n"
            "  Audio_Refinery.pyw --source D:/Music"
            " --output D:/Refined"
            " --auto-start --auto-end\n"
            "  Audio_Refinery.pyw --source D:/Music"
            " --stages declick,enhance --preset Mild\n"
            "  Audio_Refinery.pyw --source D:/Music"
            " --target-lufs -14 --tolerance 0.3\n"
        ),
    )

    # Paths
    parser.add_argument(
        "--source", default="", metavar="PATH", help="Source file or folder."
    )
    parser.add_argument(
        "--output",
        default="",
        metavar="PATH",
        help="Output folder (blank = in-place replacement).",
    )

    # Automation
    parser.add_argument(
        "--auto-start",
        action="store_true",
        help="Begin processing automatically after launch.",
    )
    parser.add_argument(
        "--auto-end",
        action="store_true",
        help="Close automatically when processing completes.",
    )

    # Processing mode
    parser.add_argument(
        "--dry",
        action="store_true",
        help="Run in dry run mode (simulate operations without writing files).",
    )

    # Stages
    parser.add_argument(
        "--stages",
        default="declick,trim,enhance,normalise",
        metavar="LIST",
        help="Comma-separated list of stages to run (default: all four).",
    )

    # Declick params
    parser.add_argument(
        "--sensitivity",
        type=float,
        default=0.31,
        metavar="FLOAT",
        help="Click detection sensitivity (0.01–0.40, default 0.31).",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=2,
        metavar="MS",
        help="Max click width to repair in ms (default 2).",
    )

    # Trim params
    parser.add_argument(
        "--threshold",
        type=int,
        default=-50,
        metavar="DB",
        help="Silence threshold in dBFS (default -50).",
    )
    parser.add_argument(
        "--fade", action="store_true", help="Apply fade-in/out after trimming."
    )
    parser.add_argument(
        "--fade-in",
        type=int,
        default=500,
        metavar="MS",
        help="Fade-in duration in ms (default 500).",
    )
    parser.add_argument(
        "--fade-out",
        type=int,
        default=1000,
        metavar="MS",
        help="Fade-out duration in ms (default 1000).",
    )

    # Noise Reduction params
    parser.add_argument(
        "--reduce-hum",
        action="store_true",
        dest="reduce_hum",
        default=False,
        help="Enable hum removal.",
    )
    parser.add_argument(
        "--hum-frequency",
        type=int,
        default=60,
        choices=[50, 60],
        help="Mains frequency (50 or 60 Hz). Default: 60.",
    )
    parser.add_argument(
        "--hum-harmonics",
        type=int,
        default=8,
        metavar="N",
        help="Number of harmonics to filter (1-20). Default: 8.",
    )
    parser.add_argument(
        "--hum-quality",
        type=float,
        default=30.0,
        metavar="Q",
        help="Q factor for notch filters (1.0-100.0). Default: 30.0.",
    )
    parser.add_argument(
        "--reduce-broadband",
        action="store_true",
        dest="reduce_broadband",
        default=False,
        help="Enable broadband noise reduction.",
    )
    parser.add_argument(
        "--noise-start",
        type=int,
        default=0,
        dest="noise_start_ms",
        metavar="MS",
        help="Noise profile start (ms). Default: 0.",
    )
    parser.add_argument(
        "--noise-end",
        type=int,
        default=500,
        dest="noise_end_ms",
        metavar="MS",
        help="Noise profile end (ms). Default: 500.",
    )
    parser.add_argument(
        "--gate-threshold",
        type=float,
        default=3.0,
        dest="gate_threshold_db",
        metavar="DB",
        help="Gate threshold above noise floor (dB). Default: 3.0.",
    )

    # Enhance params
    parser.add_argument(
        "--preset",
        default="Moderate",
        choices=["Mild", "Moderate", "Aggressive", "Custom"],
        help="Enhancement preset (default: Moderate).",
    )

    # Display-only driver orchestration flags
    parser.add_argument(
        "--clear-logs",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--no-clear-logs",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--parallel-run",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--no-parallel-run",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    # Normalise params
    parser.add_argument(
        "--target-lufs",
        type=float,
        default=-14.0,
        metavar="LUFS",
        help=(
            "Normalisation target in LUFS. Must be one of: -12, -14, -16, -18, -23 "
            "(default -14.0)."
        ),
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.5,
        metavar="DB",
        help="Skip normalisation if within this tolerance (default 0.5).",
    )
    parser.add_argument(
        "--true-peak",
        type=float,
        default=-1.5,
        metavar="DBTP",
        help="loudnorm true-peak ceiling in dBTP, -9.0..0.0 (default -1.5).",
    )
    parser.add_argument(
        "--lra",
        type=float,
        default=11.0,
        metavar="LU",
        help="loudnorm loudness-range target in LU, 1..20 (default 11).",
    )
    parser.add_argument(
        "--normalise-mode",
        default="normalise",
        choices=list(NORMALISATION_MODES),
        help=(
            "normalise re-encodes through loudnorm; lossless rewrites an MP3's "
            "global gain instead (default normalise)."
        ),
    )
    parser.add_argument(
        "--album-mode",
        action="store_true",
        dest="album_mode",
        default=False,
        help=(
            "Measure the whole folder as one album and apply that single gain "
            "to every track."
        ),
    )
    parser.add_argument(
        "--no-album-mode",
        action="store_false",
        dest="album_mode",
        help=argparse.SUPPRESS,
    )

    args, _ = parser.parse_known_args(args=argv)

    # Validate target LUFS against permitted presets.
    lufs_errors = validate_target_lufs(args.target_lufs)
    if lufs_errors:
        parser.error(lufs_errors[0])

    # The delivery targets are bounded the same way the standalone normalizer's
    # CLI bounded them, so an impossible ceiling is refused before a run.
    if not -9.0 <= args.true_peak <= 0.0:
        parser.error(
            f"--true-peak must be between -9.0 and 0.0 dBTP, got {args.true_peak}"
        )
    if not 1.0 <= args.lra <= 20.0:
        parser.error(f"--lra must be between 1 and 20 LU, got {args.lra}")

    return RefineryArgs(
        source=args.source,
        output=args.output,
        auto_start=args.auto_start,
        auto_end=args.auto_end,
        dry_run=args.dry,
        stages=args.stages,
        sensitivity=args.sensitivity,
        width=args.width,
        threshold=args.threshold,
        fade=args.fade,
        fade_in=args.fade_in,
        fade_out=args.fade_out,
        reduce_hum=args.reduce_hum,
        hum_frequency=args.hum_frequency,
        hum_harmonics=args.hum_harmonics,
        hum_quality=args.hum_quality,
        reduce_broadband=args.reduce_broadband,
        noise_start_ms=args.noise_start_ms,
        noise_end_ms=args.noise_end_ms,
        gate_threshold_db=args.gate_threshold_db,
        preset=args.preset,
        target_lufs=args.target_lufs,
        tolerance=args.tolerance,
        true_peak=args.true_peak,
        lra=args.lra,
        normalise_mode=args.normalise_mode,
        album_mode=args.album_mode,
        clear_logs=args.clear_logs and not args.no_clear_logs,
        parallel_run=args.parallel_run and not args.no_parallel_run,
    )
