"""CLI command for Noise Reduction.

Changed in 1.4.0: emits and locks the shared CLI JSON schema (PLAN D82).
"""

from __future__ import annotations

import json as _json_mod

import click

from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_base import (
    _opt_dir,
    _opt_dry_run,
    _opt_json,
    _run_tool,
    cli,
)


@cli.command()
@_opt_dir
@_opt_dry_run
@_opt_json
@click.option("--reduce-hum", is_flag=True, help="Enable hum removal.")
@click.option(
    "--hum-frequency",
    type=click.Choice(["50", "60"]),
    default="60",
    help="Mains frequency Hz.",
)
@click.option(
    "--hum-harmonics", type=int, default=8, help="Harmonics to filter (1-20)."
)
@click.option(
    "--hum-quality", type=float, default=30.0, help="Q factor for notch filters."
)
@click.option(
    "--reduce-broadband", is_flag=True, help="Enable broadband noise reduction."
)
@click.option("--noise-start", type=int, default=0, help="Noise profile start (ms).")
@click.option("--noise-end", type=int, default=500, help="Noise profile end (ms).")
@click.option("--gate-threshold", type=float, default=3.0, help="Gate threshold (dB).")
def reduce(
    directory: str,
    dry_run: bool,
    json: bool,
    reduce_hum: bool,
    hum_frequency: str,
    hum_harmonics: int,
    hum_quality: float,
    reduce_broadband: bool,
    noise_start: int,
    noise_end: int,
    gate_threshold: float,
) -> None:
    """Remove hum and broadband noise from audio files."""
    from noise_reduction.core.file_processor import run_noise_reduction
    from noise_reduction.core.models import NoiseReductionParams

    params = NoiseReductionParams(
        reduce_hum=reduce_hum,
        hum_frequency=int(hum_frequency),
        hum_harmonics=hum_harmonics,
        hum_quality=hum_quality,
        reduce_broadband=reduce_broadband,
        noise_start_ms=noise_start,
        noise_end_ms=noise_end,
        gate_threshold_db=gate_threshold,
        dry_run=dry_run,
    )

    with active_batch("noise_reduction", "tag_edit"):
        result = _run_tool(
            "Noise Reduction",
            run_noise_reduction,
            dir_path=directory,
            params=params,
        )
    if json:
        click.echo(
            _json_mod.dumps(result.to_payload("reduce", dry_run=dry_run), indent=2)
        )
    else:
        succeeded = result.extra.get("succeeded", 0)
        click.echo(
            f"  Summary: {result.processed} files, {succeeded} reduced, "
            f"{result.skipped} clean, {result.errors} errors "
            f"in {result.duration_secs:.1f}s"
        )
