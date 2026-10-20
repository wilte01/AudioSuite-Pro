"""CLI command for the Spectral Viewer.

``audiosuite spectrogram <path>`` renders one PNG per audio file: the whole
file by default, or the window selected with ``--start``/``--end``. The command
is the batch/export path — the GUI shows one image at a time — and it honours
``--dry`` by printing the exact paths it would write and writing nothing, so a
Master Driver Dry Run cannot leave images behind.

Changed in 1.3.0: initial version (PLAN_feature_expansion.md Item 3.1 / D42).

Changed in 1.4.0: emits and locks the shared CLI JSON schema (PLAN D82).
"""

from __future__ import annotations

import json as _json_mod
import sys
import time

import click

from audio_suite_shared.cli_base import _opt_dry_run, _opt_json, cli
from audio_suite_shared.cli_schema import build_payload
from audio_suite_shared.exceptions import AudioSuiteError
from spectral_viewer.core.spectrogram import (
    DEFAULT_CMAP,
    DEFAULT_DB_RANGE,
    DEFAULT_HOP_LENGTH,
    DEFAULT_N_FFT,
    iter_audio_files,
    output_path_for,
    render_spectrogram,
)


@cli.command()
@click.argument("path", type=click.Path(exists=True, readable=True))
@_opt_dry_run
@_opt_json
@click.option(
    "--output-dir",
    default=None,
    type=click.Path(file_okay=False),
    help="Directory for the PNGs. Default: beside each source file.",
)
@click.option(
    "--n-fft",
    default=DEFAULT_N_FFT,
    type=click.IntRange(min=256, max=16384),
    help="FFT window size in samples.",
)
@click.option(
    "--hop-length",
    default=DEFAULT_HOP_LENGTH,
    type=click.IntRange(min=64, max=8192),
    help="Samples between successive frames.",
)
@click.option(
    "--start",
    default=0.0,
    type=click.FloatRange(min=0.0),
    help="Window start in seconds.",
)
@click.option(
    "--end",
    default=0.0,
    type=click.FloatRange(min=0.0),
    help="Window end in seconds (0 = to the end, capped at 600s).",
)
@click.option(
    "--max-freq",
    default=0.0,
    type=click.FloatRange(min=0.0),
    help="Highest frequency to show in Hz (0 = Nyquist).",
)
@click.option(
    "--db-range",
    default=DEFAULT_DB_RANGE,
    type=click.FloatRange(min=10.0, max=140.0),
    help="Colour floor in dB below the peak.",
)
@click.option("--cmap", default=DEFAULT_CMAP, help="Matplotlib colour map name.")
def spectrogram(
    path: str,
    dry_run: bool,
    json: bool,
    output_dir: str | None,
    n_fft: int,
    hop_length: int,
    start: float,
    end: float,
    max_freq: float,
    db_range: float,
    cmap: str,
) -> None:
    """Render FFT spectrograms for an audio file or a directory of them.

    Read-only with respect to the audio: nothing is retagged or re-encoded, and
    the only files ever written are the PNG images. ``--dry`` lists the images
    that would be written and writes none of them.
    """
    start_time = time.monotonic()
    try:
        sources = iter_audio_files(path)
    except OSError as exc:
        click.echo(f"  FATAL: {exc}", err=True)
        sys.exit(1)

    if not sources:
        click.echo(f"  No supported audio files found in {path}", err=True)
        sys.exit(1)

    images: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    for source in sources:
        destination = str(output_path_for(source, output_dir))
        # Progress lines go to stderr in JSON mode so stdout stays parseable.
        if dry_run:
            click.echo(f"  [DRY] would write {destination}", err=json)
            images.append(
                {"source": source, "output": destination, "status": "planned"}
            )
            continue
        try:
            render_spectrogram(
                source,
                destination,
                start=start,
                end=end,
                n_fft=n_fft,
                hop_length=hop_length,
                max_freq=max_freq,
                dynamic_range_db=db_range,
                cmap=cmap,
            )
        except (AudioSuiteError, OSError, ValueError) as exc:
            errors.append({"source": source, "error": str(exc)})
            click.echo(f"  [ERROR] {source}: {exc}", err=True)
            continue
        click.echo(f"  [OK] {destination}", err=json)
        images.append({"source": source, "output": destination, "status": "written"})

    elapsed = time.monotonic() - start_time
    written = sum(1 for image in images if image["status"] == "written")

    if json:
        # processed counts everything attempted — planned/written images plus
        # the files that failed — which is the shared schema's rule.
        click.echo(
            _json_mod.dumps(
                build_payload(
                    "spectrogram",
                    dry_run=dry_run,
                    total=len(sources),
                    processed=len(images) + len(errors),
                    errors=len(errors),
                    duration_secs=elapsed,
                    log_entries=[],
                    path=path,
                    written=written,
                    images=images,
                    error_messages=errors,
                ),
                indent=2,
            )
        )
    else:
        click.echo("")
        click.echo(
            f"  Summary: {len(images)} image(s)"
            + ("" if dry_run else f", {written} written")
            + f", {len(errors)} error(s) in {elapsed:.1f}s"
        )

    if errors:
        sys.exit(1)
