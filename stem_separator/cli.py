"""CLI command for the Stem Separator.

Changed in 2.0.0: initial version, registering ``audiosuite stems`` (Sprint 6,
Item 6.1).
"""

from __future__ import annotations

import json as _json_mod

import click

from audio_suite_shared.cli_base import (
    _opt_dir,
    _opt_dry_run,
    _opt_json,
    _run_tool,
    cli,
    finish_run,
)
from stem_separator.core.models import (
    DEFAULT_MODEL,
    MODEL_CHOICES,
    STEM_NAMES,
    StemSeparationParams,
    normalise_stems,
)


def _parse_stems(
    _ctx: click.Context, _param: click.Parameter, value: str
) -> tuple[str, ...]:
    """Turn ``--stems vocals,bass`` into a validated tuple."""
    names = tuple(part.strip().lower() for part in value.split(",") if part.strip())
    try:
        return normalise_stems(names)
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc


@cli.command()
@_opt_dir
@_opt_dry_run
@_opt_json
@click.option(
    "--output-dir",
    required=True,
    type=click.Path(file_okay=False),
    help="Directory the per-track stem folders are written into.",
)
@click.option(
    "--model",
    type=click.Choice(MODEL_CHOICES),
    default=DEFAULT_MODEL,
    show_default=True,
    help="Demucs model.",
)
@click.option(
    "--stems",
    callback=_parse_stems,
    default=",".join(STEM_NAMES),
    show_default=True,
    metavar="LIST",
    help="Comma-separated stems to export.",
)
@click.option(
    "--mix/--no-mix",
    default=False,
    help="Also write mix.wav: the sum of the exported stems.",
)
@click.option(
    "--device",
    type=click.Choice(["auto", "cpu", "cuda"]),
    default="auto",
    show_default=True,
    help="Compute device; auto uses CUDA when torch reports it usable.",
)
def stems(
    directory: str,
    dry_run: bool,
    json: bool,
    output_dir: str,
    model: str,
    stems: tuple[str, ...],
    mix: bool,
    device: str,
) -> None:
    """Separate audio files into vocals, drums, bass and other stems."""
    from stem_separator.core.file_processor import run_stem_separation

    params = StemSeparationParams(
        output_dir=output_dir,
        stems=stems,
        model=model,
        write_mix=mix,
        device=device,
        dry_run=dry_run,
    )

    result = _run_tool(
        "Stem Separator",
        run_stem_separation,
        dir_path=directory,
        params=params,
    )
    if json:
        click.echo(
            _json_mod.dumps(result.to_payload("stems", dry_run=dry_run), indent=2)
        )
    else:
        separated = result.extra.get("separated", 0)
        written = result.extra.get("files_written", 0)
        click.echo(
            f"  Summary: {result.processed} files, {separated} separated into "
            f"{written} stem file(s), {result.skipped} skipped, "
            f"{result.errors} errors in {result.duration_secs:.1f}s"
        )
        click.echo(f"  Output:  {result.extra.get('output_dir', output_dir)}")
    finish_run(result)
