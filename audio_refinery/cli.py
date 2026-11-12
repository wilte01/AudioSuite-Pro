"""CLI command for Audio Refinery pipeline.
Changed in 1.1.0: added the six Sprint 1 effect flags; effect fields
are carried on the CLI-provided enhancement params.

Changed in 1.4.0: emits and locks the shared CLI JSON schema (PLAN D82).

Changed in 1.4.1: a fatal run now exits 1 instead of 0 (``finish_run``), while a
run whose only failures were per-file keeps its exit status (PLAN D92).

Changed in 2.3.1: carries this window's change for its module (see
CHANGELOG.md and TECHNICAL_CHANGELOG.md).

Changed in 2.5.0: ``--album-mode`` (F-E1) switches the normalise stage from a
per-file measurement to one gain measured across the whole folder.

Changed in 2.5.0: ``--trim-mode exact`` with ``--trim-start``/``--trim-end`` (or
``--trim-duration``) keeps a millisecond range instead of detected silence, and
``--trim-copy`` cuts it with a stream copy instead of a re-encode (F-E3).

Changed in 2.6.0: ``--target-mode peak`` with ``--target-peak`` (F-E2) targets
the true peak with one static gain instead of pushing integrated loudness to a
LUFS figure, and the pair is refused beside ``--album-mode``.
"""

from __future__ import annotations

import json as _json_mod
from pathlib import Path

import click

from audio_refinery.core.models import (
    NORMALISATION_MODES,
    NORMALISATION_TARGET_MODES,
    TRIM_MODES,
)
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_base import (
    _opt_dir,
    _opt_dry_run,
    _opt_json,
    _run_tool,
    cli,
    finish_run,
)
from audio_suite_shared.cli_dataclasses import validate_target_lufs


def _validate_lufs(ctx: click.Context, param: click.Parameter, value: float) -> float:
    """Reject a --target-lufs that is not a permitted preset (M4)."""
    errors = validate_target_lufs(value)
    if errors:
        raise click.BadParameter(errors[0])
    return value


def _validate_trim_range(
    mode: str,
    start: int | None,
    end: int | None,
    duration: int | None,
    copy_mode: bool,
) -> None:
    """Refuse an exact-trim combination that cannot mean one thing.

    A range without the mode would otherwise be silently ignored by the silence
    stage, and both an end and a duration would make the cut depend on argument
    order.

    Raises:
        click.BadParameter: A range option was given without
            ``--trim-mode exact``, or the mode is missing its range.
    """
    if mode != "exact":
        given = [
            name
            for name, value in (
                ("--trim-start", start),
                ("--trim-end", end),
                ("--trim-duration", duration),
                ("--trim-copy", copy_mode or None),
            )
            if value is not None
        ]
        if given:
            raise click.BadParameter(
                f"{', '.join(given)} needs --trim-mode exact.",
                param_hint="--trim-mode",
            )
        return

    if start is not None and start < 0:
        raise click.BadParameter(
            "--trim-start must be zero or later.", param_hint="--trim-start"
        )
    if end is not None and duration is not None:
        raise click.BadParameter(
            "Use either --trim-end or --trim-duration, not both.",
            param_hint="--trim-duration",
        )
    if end is None and duration is None:
        raise click.BadParameter(
            "--trim-mode exact needs --trim-end or --trim-duration.",
            param_hint="--trim-mode",
        )


@cli.command()
@click.pass_context
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
    "--eq-band",
    "eq_bands",
    multiple=True,
    metavar="BAND",
    help=(
        "Parametric EQ band 'kind,freq,gain,q' (repeatable, up to 8); "
        "implies the eq stage."
    ),
)
@click.option(
    "--comp-threshold",
    default=-18.0,
    type=float,
    help="Compressor threshold in dBFS, -60 to 0; implies the dynamics stage.",
)
@click.option(
    "--comp-ratio",
    default=4.0,
    type=float,
    help="Compressor ratio, 1 to 20.",
)
@click.option(
    "--comp-attack",
    default=10.0,
    type=float,
    help="Compressor attack in ms, 0.1 to 200.",
)
@click.option(
    "--comp-release",
    default=100.0,
    type=float,
    help="Compressor release in ms, 1 to 2000.",
)
@click.option(
    "--comp-makeup",
    default=0.0,
    type=float,
    help="Makeup gain after compression, -24 to 24 dB.",
)
@click.option(
    "--limiter-ceiling",
    default=-1.0,
    type=float,
    help="True-peak ceiling in dBTP, -24 to 0.",
)
@click.option(
    "--limiter-lookahead",
    default=5.0,
    type=float,
    help="Limiter lookahead in ms, 0 to 20.",
)
@click.option(
    "--limiter-release",
    default=100.0,
    type=float,
    help="Limiter release in ms, 1 to 2000.",
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
    "--trim-mode",
    type=click.Choice(TRIM_MODES),
    default="silence",
    help=(
        "silence trims detected leading/trailing silence; exact keeps a "
        "millisecond range (default silence)."
    ),
)
@click.option(
    "--trim-start",
    type=int,
    default=None,
    help="Exact trim start in ms (default 0).",
)
@click.option("--trim-end", type=int, default=None, help="Exact trim end in ms.")
@click.option(
    "--trim-duration",
    type=int,
    default=None,
    help="Exact trim length in ms; use instead of --trim-end.",
)
@click.option(
    "--trim-copy/--no-trim-copy",
    default=False,
    help=(
        "Cut the exact range with a stream copy instead of a re-encode "
        "(frame-accurate, and it cannot run beside another stage)."
    ),
)
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
    default=-14.0,
    type=float,
    callback=_validate_lufs,
    help=("Normalisation target LUFS (default -14.0; one of -12, -14, -16, -18, -23)."),
)
@click.option(
    "--tolerance",
    default=0.5,
    type=float,
    help="Normalisation tolerance LUFS (default 0.5).",
)
@click.option(
    "--true-peak",
    default=-1.5,
    type=click.FloatRange(-9.0, 0.0),
    help="loudnorm true-peak ceiling in dBTP (default -1.5).",
)
@click.option(
    "--lra",
    default=11.0,
    type=click.FloatRange(1.0, 20.0),
    help="loudnorm loudness-range target in LU (default 11).",
)
@click.option(
    "--album-mode/--no-album-mode",
    default=False,
    help=(
        "Measure the whole folder as one album and apply that single gain to "
        "every track (default off)."
    ),
)
@click.option(
    "--normalise-mode",
    type=click.Choice(NORMALISATION_MODES),
    default="normalise",
    help=(
        "normalise re-encodes through loudnorm; lossless rewrites an MP3's "
        "global gain instead (default normalise)."
    ),
)
@click.option(
    "--target-mode",
    type=click.Choice(NORMALISATION_TARGET_MODES),
    default="lufs",
    help="lufs targets integrated loudness; peak targets the true peak.",
)
@click.option(
    "--target-peak",
    default=-1.0,
    type=click.FloatRange(-9.0, 0.0),
    help="True-peak target in dBTP for --target-mode peak (default -1.0).",
)
def refine(
    ctx: click.Context,
    directory: str,
    output: str | None,
    dry_run: bool,
    json: bool,
    stages: str,
    eq_bands: tuple[str, ...],
    comp_threshold: float,
    comp_ratio: float,
    comp_attack: float,
    comp_release: float,
    comp_makeup: float,
    limiter_ceiling: float,
    limiter_lookahead: float,
    limiter_release: float,
    sensitivity: float,
    width: int,
    threshold: int,
    fade: bool,
    fade_in: int,
    fade_out: int,
    trim_mode: str,
    trim_start: int | None,
    trim_end: int | None,
    trim_duration: int | None,
    trim_copy: bool,
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
    true_peak: float,
    lra: float,
    album_mode: bool,
    normalise_mode: str,
    target_mode: str,
    target_peak: float,
) -> None:
    """Run the multi-stage audio refinement pipeline."""
    _validate_trim_range(trim_mode, trim_start, trim_end, trim_duration, trim_copy)
    # A peak target is per file and album mode is one gain for a folder, so the
    # pair is refused rather than letting one silently win (F-E2).
    if target_mode == "peak" and album_mode:
        raise click.BadParameter(
            "--album-mode cannot be combined with --target-mode peak; "
            "a peak target is per file",
            param_hint="--album-mode",
        )

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
    # Changed in 2.7.0: --eq-band builds the rack the engine validates, and
    # implies the eq stage - a flag that selected no stage would do nothing
    # while its bands round-tripped into a preset (F-S1).
    from audio_suite_shared.dsp_eq import EqSettings, parse_band
    from audio_suite_shared.exceptions import AudioConfigurationError

    try:
        eq_settings = EqSettings(bands=tuple(parse_band(band) for band in eq_bands))
    except AudioConfigurationError as exc:
        raise click.BadParameter(exc.message, param_hint="--eq-band") from exc

    from click.core import ParameterSource

    from audio_suite_shared.dsp_dynamics import (
        CompressorSettings,
        LimiterSettings,
    )

    # Changed in 2.7.0: every dynamics flag carries its engine default, so a
    # documented default stays click's real one, and the stage is selected by
    # whether the operator typed a flag rather than by a None sentinel (F-S2).
    dynamics_given = any(
        ctx.get_parameter_source(name) is ParameterSource.COMMANDLINE
        for name in (
            "comp_threshold",
            "comp_ratio",
            "comp_attack",
            "comp_release",
            "comp_makeup",
            "limiter_ceiling",
            "limiter_lookahead",
            "limiter_release",
        )
    )
    try:
        compressor = CompressorSettings(
            threshold_db=comp_threshold,
            ratio=comp_ratio,
            attack_ms=comp_attack,
            release_ms=comp_release,
            makeup_db=comp_makeup,
        )
        limiter = LimiterSettings(
            ceiling_dbtp=limiter_ceiling,
            lookahead_ms=limiter_lookahead,
            release_ms=limiter_release,
        )
    except AudioConfigurationError as exc:
        raise click.BadParameter(exc.message, param_hint="--dynamics") from exc

    config = StageConfig(
        # Changed in 2.7.0: --dry is a run mode, and the pipeline reads it from
        # the config; passing it to the JSON payload alone ran a live rewrite
        # that reported "dry_run": true (F-S2 follow-up).
        dry_run=dry_run,
        declick="declick" in active,
        trim="trim" in active,
        enhance="enhance" in active,
        normalise="normalise" in active,
        reduce_noise="reduce_noise" in active,
        eq="eq" in active or bool(eq_bands),
        dynamics="dynamics" in active or dynamics_given,
        declick_params=DeclickParams(sensitivity=sensitivity, max_width_ms=width),
        trim_params=TrimParams(
            threshold=threshold,
            apply_fade=fade,
            fade_in_ms=fade_in,
            fade_out_ms=fade_out,
            mode=trim_mode,
            start_ms=trim_start,
            end_ms=trim_end,
            duration_ms=trim_duration,
            copy_mode=trim_copy,
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
        normalise_params=NormaliseParams(
            target_lufs=target_lufs,
            tolerance=tolerance,
            true_peak=true_peak,
            lra=lra,
            mode=normalise_mode,
            album_mode=album_mode,
            target_mode=target_mode,
            target_peak_dbtp=target_peak,
        ),
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
        eq_params=eq_settings,
        compressor_params=compressor,
        limiter_params=limiter,
    )

    registry = CompletionRegistry(source_dir)
    from audio_refinery.core.trim import check_copy_mode

    try:
        check_copy_mode(config)
    except AudioConfigurationError as exc:
        # The run would refuse every file for the same reason; say it once,
        # before any file is opened.
        raise click.UsageError(exc.message) from exc

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
    finish_run(result)
