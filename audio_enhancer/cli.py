"""CLI command for Audio Enhancer."""

from __future__ import annotations

import json as _json_mod
import sys
from pathlib import Path

import click

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
@click.option(
    "--output-dir",
    required=True,
    type=click.Path(),
    help="Output directory (required).",
)
@click.option(
    "--preset",
    default="Moderate",
    help="Enhancement preset (Mild, Moderate, Aggressive, Custom).",
)
def enhance(
    directory: str, dry_run: bool, json: bool, output_dir: str, preset: str
) -> None:
    """Enhance audio with DSP chain."""
    from audio_enhancer.core.file_processor import run_enhancement
    from audio_enhancer.core.models import PRESETS, PresetName

    try:
        preset_enum = PresetName(preset.capitalize())
    except ValueError:
        known = ", ".join(p.value for p in PresetName)
        click.echo(f"Unknown preset '{preset}'. Known: {known}", err=True)
        sys.exit(1)

    params = PRESETS[preset_enum]
    out = Path(output_dir)

    result = _run_tool(
        "Audio Enhancer",
        run_enhancement,
        source_path=Path(directory),
        output_dir=out,
        params=params,
        is_dry_run=dry_run,
    )
    if json:
        click.echo(_json_mod.dumps(result.to_dict(), indent=2))
    else:
        done = result.extra.get("done", 0)
        click.echo(
            f"  Summary: {result.processed} files,"
            f" {done} enhanced, {result.errors} errors "
            f"in {result.duration_secs:.1f}s"
        )
