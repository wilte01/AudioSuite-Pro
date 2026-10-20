"""CLI command for Audio Refinery pipeline.
Changed in 1.1.0: added the six Sprint 1 effect flags; effect fields
are carried on the CLI-provided enhancement params.

Changed in 1.4.0: emits and locks the shared CLI JSON schema (PLAN D82).
"""

from __future__ import annotations

import json as _json_mod
from pathlib import Path

import click

from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_base import (
    _opt_dir,
    _opt_dry_run,
    _opt_json,
    _run_tool,
    cli,
)
from audio_suite_shared.cli_dataclasses import validate_target_lufs


def _validate_lufs(ctx: click.Context, param: click.Parameter, value: float) -> float:
    """Reject a --target-lufs that is not a permitted preset (M4)."""
    errors = validate_target_lufs(value)
    if errors:
        raise click.BadParameter(errors[0])
    return value


@cli.command()
@_opt_dir
@click.option(
    "--output",
    default=None,
    type=click.Path(),
    help="Output directory (default: source dir).",
)
@_opt_dry_run
@_opt_json
@click.option(
    "--stages",
    default="declick,trim,enhance,normalise",
    help="Comma-separated pipeline stages.",
)
@click.option(
    "--sensitivity",
    default=0.31,
    type=float,
    help="Declick sensitivity 0.0-0.4 (default 0.31).",
)
@click.option(
    "--width", default=2, type=int, help="Declick max defect width ms (default 2)."
)
@click.option(
    "--threshold",
    default=-50,
    type=int,
    help="Trim silence threshold dBFS (default -50).",
)
@click.option("--fade/--no-fade", default=False, help="Apply fade in/out during trim.")
@click.option("--fade-in", default=500, type=int, help="Fade-in ms (default 500).")
@click.option("--fade-out", default=1000, type=int, help="Fade-out ms (default 1000).")
@click.option(
    "--reduce-hum",
    is_flag=True,
    default=False,
    help="Enable hum removal.",
)
@click.option(
    "--hum-frequency",
    default=60,
    type=click.IntRange(50, 60),
    help="Mains frequency 50 or 60 Hz (default 60).",
)
@click.option(
    "--hum-harmonics",
    default=8,
    type=click.IntRange(1, 20),
    help="Harmonics to filter 1-20 (default 8).",
)
@click.option(
    "--hum-quality",
    default=30.0,
    type=float,
    help="Notch Q factor 1.0-100.0 (default 30.0).",
)
@click.option(
    "--reduce-broadband",
    is_flag=True,
    default=False,
    help="Enable broadband noise reduction.",
)
@click.option("--noise-start", default=0, type=int, help="Noise profile start ms.")
@click.option("--noise-end", default=500, type=int, help="Noise profile end ms.")
@click.option(
    "--gate-threshold",
    default=3.0,
    type=float,
    help="Gate threshold above noise floor dB (default 3.0).",
)
@click.option(
    "--preset",
    default="Moderate",
    help="Enhancement preset (Mild, Moderate, Aggressive, Custom).",
)
@click.option(
    "--karaoke/--no-karaoke",
    default=False,
    help="Remove centre-panned content (lead vocals).",
)
@click.option(
    "--karaoke-strength",
    default=1.0,
    type=click.FloatRange(0.0, 1.0),
    help="Karaoke removal strength 0.0-1.0 (default 1.0).",
)
@click.option("--reverse", is_flag=True, default=False, help="Reverse the audio.")
@click.option("--phaser", is_flag=True, default=False, help="Apply a phaser effect.")
@click.option("--flanger", is_flag=True, default=False, help="Apply a flanger effect.")
@click.option("--chorus", is_flag=True, default=False, help="Apply a chorus effect.")
@click.option(
    "--target-lufs",
    default=-16.0,
    type=float,
    callback=_validate_lufs,
    help=("Normalisation target LUFS (default -16.0; one of -12, -14, -16, -18, -23)."),
)
@click.option(
    "--tolerance",
    default=0.5,
    type=float,
    help="Normalisation tolerance LUFS (default 0.5).",
)
def refine(
    directory: str,
    output: str | None,
    dry_run: bool,
    json: bool,
    stages: str,
    sensitivity: float,
    width: int,
    threshold: int,
    fade: bool,
    fade_in: int,
    fade_out: int,
    reduce_hum: bool,
    hum_frequency: int,
    hum_harmonics: int,
    hum_quality: float,
    reduce_broadband: bool,
    noise_start: int,
    noise_end: int,
    gate_threshold: float,
    preset: str,
    karaoke: bool,
    karaoke_strength: float,
    reverse: bool,
    phaser: bool,
    flanger: bool,
    chorus: bool,
    target_lufs: float,
    tolerance: float,
) -> None:
    """Run the multi-stage audio refinement pipeline."""
    from audio_refinery.core.file_processor import run_pipeline
    from audio_refinery.core.models import (
        DeclickParams,
        EnhanceParams,
        NormaliseParams,
        StageConfig,
        TrimParams,
    )
    from audio_refinery.core.registry import CompletionRegistry
    from noise_reduction.core.models import NoiseReductionParams

    source_dir = Path(directory)
    out_dir = Path(output) if output else source_dir

    active = {s.strip().lower() for s in stages.split(",")}
    config = StageConfig(
        declick="declick" in active,
        trim="trim" in active,
        enhance="enhance" in active,
        normalise="normalise" in active,
        reduce_noise="reduce_noise" in active,
        declick_params=DeclickParams(sensitivity=sensitivity, max_width_ms=width),
        trim_params=TrimParams(
            threshold=threshold,
            apply_fade=fade,
            fade_in_ms=fade_in,
            fade_out_ms=fade_out,
        ),
        enhance_params=EnhanceParams(
            preset=preset,
            reverse=reverse,
            karaoke=karaoke,
            karaoke_strength=karaoke_strength,
            phaser=phaser,
            flanger=flanger,
            chorus=chorus,
        ),
        normalise_params=NormaliseParams(target_lufs=target_lufs, tolerance=tolerance),
        noise_reduction_params=NoiseReductionParams(
            reduce_hum=reduce_hum,
            hum_frequency=hum_frequency,
            hum_harmonics=hum_harmonics,
            hum_quality=hum_quality,
            reduce_broadband=reduce_broadband,
            noise_start_ms=noise_start,
            noise_end_ms=noise_end,
            gate_threshold_db=gate_threshold,
        ),
    )

    registry = CompletionRegistry(source_dir)
    with active_batch("audio_refinery", "tag_edit"):
        result = _run_tool(
            "Audio Refinery",
            run_pipeline,
            source_dir=source_dir,
            output_dir=out_dir,
            config=config,
            registry=registry,
        )
    if json:
        click.echo(
            _json_mod.dumps(result.to_payload("refine", dry_run=dry_run), indent=2)
        )
    else:
        succeeded = result.extra.get("succeeded", 0)
        click.echo(
            f"  Summary: {result.processed} files,"
            f" {succeeded} processed,"
            f" {result.skipped} skipped, "
            f"{result.errors} errors"
            f" in {result.duration_secs:.1f}s"
        )
