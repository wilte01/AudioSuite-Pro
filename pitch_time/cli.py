"""cli.py — ``audiosuite pitchtime``: batch tempo and pitch transforms.

Changed in 2.7.0: new module (PLAN_2026-11-03_2.7.0_feature_wave_3.md F-S4).
"""

from __future__ import annotations

import json as _json

import click
from click.core import ParameterSource

from audio_suite_shared.cli_base import _opt_dir, _opt_json, _run_tool, cli, finish_run
from audio_suite_shared.exceptions import AudioConfigValueError
from pitch_time.core.engine import run_pitch_time
from pitch_time.core.models import MODE_PITCH, MODE_TEMPO, PitchTimeSettings


@cli.command()
@_opt_dir
@_opt_json
@click.option(
    "--rate",
    default=None,
    type=float,
    help=(
        "Tempo mode: playback speed factor. 1.25 plays a 1.000 s file in "
        "0.800 s at the same pitch; 0.25-4.0 is the accepted range."
    ),
)
@click.option(
    "--semitones",
    default=None,
    type=float,
    help=(
        "Pitch mode: shift in semitones, length unchanged. 12 is an octave "
        "up; -24 to 24 is the accepted range."
    ),
)
@click.option(
    "--dry/--live",
    "dry_run",
    default=False,
    help="Report the measured render without writing audio or tags.",
)
@click.pass_context
def pitchtime(
    ctx: click.Context,
    directory: str,
    json: bool,
    rate: float | None,
    semitones: float | None,
    dry_run: bool,
) -> None:
    """Change a folder's playback speed or pitch, file by file.

    Each file is written beside its source under a name that carries the
    setting (``song_tempo_1.25.wav``, ``song_pitch_-2st.wav``), so a run never
    replaces the audio it read.  The source's sample rate, channel count and,
    for a lossless container, its bit depth are kept, and its tags are copied
    onto the new file.  Set exactly one of --rate (tempo) or --semitones
    (pitch); a setting that asks for no change skips every file and says so.

    Use --dry to read and measure without writing, and --json for the
    machine-readable summary.
    """
    rate_given = ctx.get_parameter_source("rate") is ParameterSource.COMMANDLINE
    semitones_given = (
        ctx.get_parameter_source("semitones") is ParameterSource.COMMANDLINE
    )
    if rate_given and semitones_given:
        raise click.UsageError(
            "Set --rate or --semitones, not both: each one is a mode, and a "
            "run does one of them."
        )
    if not rate_given and not semitones_given:
        raise click.UsageError(
            "Set --rate (tempo, pitch unchanged) or --semitones (pitch, "
            "length unchanged)."
        )
    try:
        settings = PitchTimeSettings(
            mode=MODE_PITCH if semitones_given else MODE_TEMPO,
            rate=rate if rate is not None else 1.0,
            semitones=semitones if semitones is not None else 0.0,
        )
    except AudioConfigValueError as exc:
        raise click.UsageError(exc.message) from exc

    failures: list[str] = []

    def _on_error(message: str) -> None:
        """Record a run that could not start, so the exit status says so."""
        failures.append(message)
        click.echo(f"  ERROR: {message}", err=True)

    result = _run_tool(
        "pitch / time",
        run_pitch_time,
        directory=directory,
        settings=settings,
        dry_run=dry_run,
        on_error=_on_error,
    )
    # A run that never started wrote nothing: it counts as the one failed item
    # so the shared exit contract reports 1, not a clean 0.
    if failures and result.errors == 0:
        result.errors = 1

    if json:
        payload = result.to_payload("pitchtime", dry_run=dry_run)
        click.echo(_json.dumps(payload, indent=2, default=str))
    else:
        click.echo(
            f"\n  Setting: {settings.description}"
            f"  Written: {result.extra.get('written', 0)}"
            f"  Skipped: {result.skipped}"
            f"  Errors: {result.errors}"
        )
    finish_run(result)
