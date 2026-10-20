"""CLI command for Audio Enhancer.
Changed in 1.1.0: added the Sprint 1 effect flags (--reverse,
--karaoke/--no-karaoke, --karaoke-strength, --phaser, --flanger,
--chorus) and fixed the --preset Custom KeyError (D14a).

Changed in 1.4.0: emits and locks the shared CLI JSON schema (PLAN D82).
"""

from __future__ import annotations

import json as _json_mod
import sys
from dataclasses import replace
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
def enhance(
    directory: str,
    dry_run: bool,
    json: bool,
    output_dir: str,
    preset: str,
    karaoke: bool,
    karaoke_strength: float,
    reverse: bool,
    phaser: bool,
    flanger: bool,
    chorus: bool,
) -> None:
    """Enhance audio with DSP chain."""
    from audio_enhancer.core.file_processor import run_enhancement
    from audio_enhancer.core.models import PRESETS, EnhancementParams, PresetName

    try:
        preset_enum = PresetName(preset.capitalize())
    except ValueError:
        known = ", ".join(p.value for p in PresetName)
        click.echo(f"Unknown preset '{preset}'. Known: {known}", err=True)
        sys.exit(1)

    # Custom has no PRESETS entry (its values are whatever the user sets), so
    # fall back to the neutral defaults instead of raising KeyError (D14a).
    base = PRESETS.get(preset_enum, EnhancementParams())
    params = replace(
        base,
        reverse=reverse,
        karaoke=karaoke,
        karaoke_strength=karaoke_strength,
        phaser=phaser,
        flanger=flanger,
        chorus=chorus,
    )
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
        click.echo(
            _json_mod.dumps(result.to_payload("enhance", dry_run=dry_run), indent=2)
        )
    else:
        done = result.extra.get("done", 0)
        click.echo(
            f"  Summary: {result.processed} files,"
            f" {done} enhanced, {result.errors} errors "
            f"in {result.duration_secs:.1f}s"
        )
