"""CLI command for the ML Denoiser.

Changed in 2.0.0: initial version, registering ``audiosuite denoise`` (Sprint 6,
Item 6.2).

``--amount`` is a percentage here, the same unit the GUI slider shows: one value
in two places must not mean two things.
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
    finish_run,
)
from ml_denoiser.core.models import DEFAULT_AMOUNT, DenoiseParams


@cli.command()
@_opt_dir
@_opt_dry_run
@_opt_json
@click.option(
    "--amount",
    type=click.FloatRange(min=0.0, max=100.0, min_open=True),
    default=DEFAULT_AMOUNT * 100.0,
    show_default=True,
    metavar="PERCENT",
    help=(
        "How much of the model's output to keep, 1-100 %. Lower values blend "
        "the source back in, which suits music; RNNoise is trained on speech."
    ),
)
def denoise(directory: str, dry_run: bool, json: bool, amount: float) -> None:
    """Neural noise reduction (RNNoise) for a directory of audio files."""
    from ml_denoiser.core.file_processor import run_ml_denoise

    params = DenoiseParams(amount=amount / 100.0, dry_run=dry_run)

    with active_batch("ml_denoiser", "tag_edit"):
        result = _run_tool(
            "ML Denoiser",
            run_ml_denoise,
            dir_path=directory,
            params=params,
        )
    if json:
        click.echo(
            _json_mod.dumps(result.to_payload("denoise", dry_run=dry_run), indent=2)
        )
    else:
        succeeded = result.extra.get("succeeded", 0)
        click.echo(
            f"  Summary: {result.processed} files, {succeeded} denoised, "
            f"{result.skipped} clean, {result.errors} errors "
            f"in {result.duration_secs:.1f}s"
        )
    finish_run(result)
