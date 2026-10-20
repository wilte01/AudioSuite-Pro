"""CLI command for Music Format Converter.

Changed in 1.4.0: emits and locks the shared CLI JSON schema (PLAN D82).
Changed in 1.4.1: an unknown ``--preset`` or an unsupported ``--format``
raises ``click.UsageError`` (exit 2) instead of exiting 1 after an echo, so
``--json`` gets the schema's error document (PLAN D91).

Changed in 1.4.1: a fatal run now exits 1 instead of 0 (``finish_run``), while a
run whose only failures were per-file keeps its exit status (PLAN D92).
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
from audio_suite_shared.suite_config import list_presets, load_preset


@cli.command()
@_opt_dir
@_opt_dry_run
@_opt_json
@click.option("--format", "output_format", default="flac", help="Output format.")
@click.option(
    "--quality",
    default="highest",
    help="Encoding quality: highest, high, medium, low (or numeric 0-10).",
)
@click.option(
    "--sample-rate",
    default="source",
    type=click.Choice(
        ["source", "44100", "48000", "88200", "96000", "176400", "192000"]
    ),
    help="Output sample rate (source keeps the input's rate).",
)
@click.option(
    "--bit-depth",
    default="auto",
    type=click.Choice(["auto", "16", "24", "32", "float"]),
    help="Bit depth for WAV output (auto preserves the source depth).",
)
@click.option("--output-dir", default=None, type=click.Path(), help="Output directory.")
@click.option(
    "--normalize-mp3/--no-normalize-mp3",
    default=False,
    help="Losslessly adjust MP3 output to a target loudness (-16 LUFS by default).",
)
@click.option(
    "--target-lufs",
    default=-16.0,
    type=float,
    help="Target integrated loudness in LUFS when --normalize-mp3 is set.",
)
@click.option("--delete-originals/--keep-originals", default=False)
@click.option(
    "--dither/--no-dither",
    default=True,
    show_default=True,
    help=(
        "Apply TPDF dither when the output depth is lower than the source "
        "(WAV/AIFF). Clear only for bit-identical legacy output."
    ),
)
@click.option("--preset", default=None, help="Load settings from a named preset.")
def convert(
    directory: str,
    dry_run: bool,
    json: bool,
    output_format: str,
    quality: str,
    sample_rate: str,
    bit_depth: str,
    output_dir: str | None,
    delete_originals: bool,
    preset: str | None,
    normalize_mp3: bool,
    target_lufs: float,
    dither: bool,
) -> None:
    """Convert audio files between formats."""
    from music_format_converter.core.file_processor import run_conversion
    from music_format_converter.core.formats import ALL_FORMATS

    if preset:
        settings = load_preset("music_format_converter", preset)
        if settings is None:
            # A bad ``--preset`` value is a usage error, so JSON consumers get
            # the schema's error document rather than an empty stdout (D91).
            known = ", ".join(list_presets("music_format_converter"))
            raise click.UsageError(f"Unknown preset '{preset}'. Known: {known}")
        output_format = settings.get("output_format", output_format)
        quality = settings.get("quality_preset", quality)
        sample_rate = settings.get("sample_rate", sample_rate)
        bit_depth = settings.get("bit_depth", bit_depth)
        delete_originals = settings.get("delete_originals", delete_originals)
        dither = settings.get("dither", dither)

    _WORD_QUALITY: dict[str, str] = {
        "highest": "highest",
        "high": "high",
        "medium": "medium",
        "low": "medium",
    }
    q = quality.lower().strip() if quality else "highest"
    if q in _WORD_QUALITY:
        quality = _WORD_QUALITY[q]
    elif q.isdigit() and int(q) <= 2:
        quality = "highest"
    elif q.isdigit() and int(q) <= 5:
        quality = "high"
    else:
        quality = "medium"

    if output_format not in ALL_FORMATS:
        raise click.UsageError(
            f"Unsupported format '{output_format}'. "
            f"Supported: {', '.join(sorted(ALL_FORMATS))}"
        )

    out_dir = output_dir or directory
    lossy = [f for f in ALL_FORMATS if f not in ("flac", "wav", "aiff", "aif")]

    with active_batch("music_format_converter", "file_delete"):
        result = _run_tool(
            "Music Format Converter",
            run_conversion,
            input_dir=directory,
            output_dir=out_dir,
            output_format=output_format,
            quality=quality,
            delete_originals=delete_originals,
            is_dry_run=dry_run,
            lossy_formats=lossy,
            sample_rate=sample_rate,
            bit_depth=bit_depth,
            normalize_mp3=normalize_mp3,
            target_lufs=target_lufs,
            dither=dither,
        )
    if json:
        click.echo(
            _json_mod.dumps(result.to_payload("convert", dry_run=dry_run), indent=2)
        )
    else:
        converted = result.extra.get("converted", 0)
        click.echo(
            f"  Summary: {result.processed} files, {converted} converted, "
            f"{result.skipped} skipped, "
            f"{result.errors} errors in {result.duration_secs:.1f}s"
        )
    finish_run(result)
