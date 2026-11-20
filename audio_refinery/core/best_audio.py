"""core/best_audio.py
Best Audio: per-file parameter decisions for the Audio Refinery stages.

What this module is
-------------------
Every other tool in this space ships presets, and a preset is a claim nobody
can check.  Best Audio is a decision layer over detectors that already exist in
the suite: it measures the file once, decides the parameters a person would
otherwise type, and writes down the measurement behind every decision.  It adds
no DSP and no stage.

Two properties are structural, not stylistic:

* **Additive.**  It never writes a stage toggle, a preset name, a delivery
  setting (target LUFS, true-peak ceiling, album mode, an exact trim range) or
  the broadband engine, and it never hides or replaces a control.  The plan
  contract rules A1-A10 are what the tests assert; :func:`decide` expresses
  them mechanically by rebuilding only the params of the stages it was asked
  to decide for.
* **Lazy.**  A measurement is taken only when an Auto stage needs it, so a run
  that ticked Auto nowhere performs no measurement and pays no extra decode.

The ordering rule
-----------------
Decisions are taken in chain order, on the signal each stage will receive.
Silence is measured first; when the Trim decision cuts, the slice is applied
**in memory** and hum, noise and tone are measured on the trimmed segment.
Measuring noise on an untrimmed source is a defect, not a simplification: a
leading digital-silence stretch is the flattest, quietest window in the file,
so the profile detector selects it, the floor reads about -120 dBFS, and the
gate is enabled on the strength of a window that will not exist by the time the
stage runs.

Changed in 2.9.0: created.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt
from pydub import AudioSegment

from audio_refinery.core.models import AUTO_STAGES, StageConfig
from audio_suite_shared.dsp_eq import (
    EQ_DEFAULT_Q,
    MAX_EQ_BANDS,
    EqBand,
    EqSettings,
)
from noise_reduction.core.models import SPECTRAL_ENGINE

if TYPE_CHECKING:  # pragma: no cover - typing only
    from noise_reduction.core.models import HumProfile, NoiseWindow
    from pop_click_remover.core.declicker import ClickDetection

logger = logging.getLogger(__name__)

# ── Declared constants ────────────────────────────────────────────────────────
#
# Every value below is declared once, named in the report and pinned by a test
# in ``audio_refinery/tests/test_best_audio.py``.  They are deliberate
# judgements with a recorded basis, not tuning knobs: changing one is a plan
# amendment.  See Appendix A of PLAN_2026-11-18_2.9.0_best_audio.md.

#: Below this much head+tail silence a cut is not worth a re-encode.
TRIM_MIN_HEAD_TAIL_MS: int = 200
#: A file that is mostly silence is not a trim candidate; it is broken.
TRIM_MAX_SILENCE_SHARE: float = 0.60

#: Above this level the \"floor\" is content, and a gate built from it would
#: remove music.  Measured 2026-11-18 (BA-8) on the committed corpus: music
#: floors sit at -28.8 to -5.5 dBFS, so -45 leaves 16.8 dB at the closest.
NOISE_FLOOR_CEILING_DBFS: float = -45.0
#: The floor must be this far under the content before the gate is confirmed.
NOISE_MIN_GAP_DB: float = 18.0
#: The profile must not gate the loudest stretch by more than this.
NOISE_MAX_TRIAL_DB: float = 1.0

#: The band a rumble high-pass is placed at, and how far the sub band must sit
#: above the band above it before the filter is added.
RUMBLE_BAND_HZ: float = 30.0
RUMBLE_EXCESS_DB: float = 6.0

#: How far past the delivery ceiling a predicted peak may sit before the
#: limiter is un-bypassed.  One tenth of a dB: below it the overshoot is inside
#: the measurement's own resolution.
LIMITER_MARGIN_DB: float = 0.1

#: The bounded window the spectral measurement reads, centred on the file.
TILT_WINDOW_SECONDS: float = 30.0
#: How far the top octave must sit under the mid band before a lift is
#: justified.  Measured 2026-11-18 (BA-8): the corpus tilts sit at -130.0 to
#: -0.8 dB, so the brightest track stays 2.2 dB short of a lift.
TILT_DEFICIT_DB: float = 3.0
#: The most Auto may lift either shelf.  Both shelves take the same figure,
#: so the pair's total is twice this and a separate total cap could only
#: bind at exactly twice this - it never did.
TILT_MAX_LIFT_DB: float = 2.0
#: A source whose top octave stops below this is bandwidth-limited; its missing
#: top is reported, never boosted.  2026-11-18 (BA-8): the corpus ceilings are
#: 2.5-11.5 kHz, so every corpus track is reported rather than lifted.
LOSSY_CEILING_HZ: int = 16_000

#: A sample at or beyond this magnitude counts as clipped.
CLIP_SAMPLE_THRESHOLD: float = 0.999

#: Post-write guardrail tolerances.
VERIFY_PEAK_MARGIN_DB: float = 0.1
VERIFY_LOUDNESS_MARGIN_DB: float = 0.5

#: What a stage Auto was asked for but that is switched off says.  A1 forbids
#: Auto switching it on, so none of its parameters could ever be read: the
#: request is reported rather than a measurement the stage would never use.
_STAGE_OFF_REASON = "the stage is switched off - Auto has nothing to decide"

#: Which toggle decides whether a stage runs at all.  Auto never writes these
#: (contract rule A1); this table only lets the decision layer skip the work a
#: stage that cannot run would never use.
_STAGE_ENABLED: dict[str, Any] = {
    "declick": lambda c: c.declick,
    "trim": lambda c: c.trim,
    "reduce_noise": lambda c: c.reduce_noise,
    "eq": lambda c: c.eq,
    "dynamics": lambda c: c.dynamics,
    "enhance": lambda c: c.enhance,
}

#: The spectral bands the tilt rule compares, in Hz.
_BAND_LOW: tuple[float, float] = (40.0, 100.0)
_BAND_SUB: tuple[float, float] = (20.0, 30.0)
_BAND_MID: tuple[float, float] = (300.0, 3000.0)
_BAND_HIGH: tuple[float, float] = (6000.0, 16000.0)

#: How far below the loudest 1 kHz band a frequency still counts as \"present\"
#: when the brightness ceiling is measured.
_CEILING_DYNAMIC_RANGE_DB: float = 40.0
_CEILING_STEP_HZ: float = 500.0


# ── Result types ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Evidence:
    """One measurement, with the threshold it was compared against.

    Attributes:
        name: What was measured, e.g. ``\"head+tail silence\"``.
        value: The measured figure, already formatted with its unit.
        threshold: The rule it was tested against, e.g. ``\">= 200 ms\"``.
    """

    name: str
    value: str
    threshold: str


@dataclass(frozen=True)
class SourceProfile:
    """What was measured on one file.  Every field is a measurement.

    ``None`` means \"not measured\", which is different from zero.  A field is
    ``None`` whenever no Auto stage needed it, so a run that ticked Auto on one
    stage pays for one measurement.  A field is declared here only when a
    decision or the report reads it: the wider forensics block (LUFS, LRA,
    crest, per-channel peak, DC offset) is measured by the probe for other
    tools and deliberately not stored.
    """

    file_name: str
    true_peak_dbtp: float | None = None
    clipped_sample_share: float | None = None
    hum: "HumProfile | None" = None
    noise_window: "NoiseWindow | None" = None
    noise_floor_dbfs: float | None = None
    content_rms_dbfs: float | None = None
    clicks: "ClickDetection | None" = None
    head_silence_ms: int = 0
    tail_silence_ms: int = 0
    band_energy_db: dict[str, float] = field(default_factory=dict)
    tilt_high_over_mid_db: float | None = None
    brightness_ceiling_hz: int | None = None
    measured_at: str = ""


@dataclass(frozen=True)
class StageDecision:
    """What Auto decided for one stage, and why.

    Attributes:
        stage: One of :data:`AUTO_STAGES`.
        auto: Whether the run asked for Auto on this stage.
        active: Whether Auto produced an instruction (parameters or a
            confirmed no-op decision).
        reason: The sentence a person reads, naming the measurement.
        evidence: Every measurement the decision rests on.
        params: The parameter values Auto supplies (empty when it supplies
            none because the configured values already fit).
        detail: The compact form used in the per-file report line.
        failure: The measurement failure that disabled Auto, when there was
            one.
    """

    stage: str
    auto: bool
    active: bool
    reason: str
    evidence: tuple[Evidence, ...] = ()
    params: dict[str, Any] = field(default_factory=dict)
    detail: str = ""
    failure: str | None = None


@dataclass(frozen=True)
class BestAudioPlan:
    """One file's complete Best Audio outcome.

    Attributes:
        source: The profile measured on this file.
        decisions: One decision per declared stage, in ``AUTO_STAGES`` order.
        config: The effective configuration: a copy of the run's config with
            only the Auto stages' parameters replaced.
        caveats: Measured limitations the user should know about.
        skipped_reason: Why nothing was decided, when nothing was.
        verify: The post-write verification outcome (set by
            :func:`verify_written` on a written file).
    """

    source: SourceProfile
    decisions: dict[str, StageDecision]
    config: StageConfig
    caveats: tuple[str, ...] = ()
    skipped_reason: str | None = None
    verify: "VerificationResult | None" = None

    @property
    def active_stages(self) -> tuple[str, ...]:
        """Return the stages Auto actually decided for, in declared order."""
        return tuple(
            stage
            for stage in AUTO_STAGES
            if self.decisions.get(stage) is not None
            and self.decisions[stage].active
            and self.decisions[stage].auto
        )


@dataclass(frozen=True)
class VerificationResult:
    """What the written file achieved, against what the plan claimed.

    Attributes:
        caveats: One sentence per violated guardrail, empty on a clean run.
        message: The report line, or ``\"\"`` when everything held.
    """

    caveats: tuple[str, ...] = ()
    message: str = ""


# ── Small measurement helpers ─────────────────────────────────────────────────


def _segment_samples(audio: AudioSegment) -> tuple[npt.NDArray[np.float64], int]:
    """Return ``(mono float64 samples, sample_rate)`` for *audio*.

    Args:
        audio: The decoded segment to read.

    Returns:
        The mono signal and its sample rate, for the spectral measurements that
        do not need a temp file.
    """
    from audio_suite_shared.audio_conversion import segment_to_numpy

    samples, rate = segment_to_numpy(audio)
    if samples.shape[1] == 0:
        return np.zeros(0, dtype=np.float64), int(rate)
    return samples.mean(axis=0, dtype=np.float64), int(rate)


def _bounded_window(
    mono: npt.NDArray[np.float64], rate: int
) -> npt.NDArray[np.float64]:
    """Return at most :data:`TILT_WINDOW_SECONDS` from the centre of *mono*."""
    limit = int(rate * TILT_WINDOW_SECONDS)
    if mono.size <= limit:
        return mono
    start = (mono.size - limit) // 2
    return mono[start : start + limit]


def _band_db(
    freqs: npt.NDArray[np.floating[Any]],
    power: npt.NDArray[Any],
    low: float,
    high: float,
) -> float:
    """Return the mean power density of one band, in dB."""
    mask = (freqs >= low) & (freqs < high)
    if not np.any(mask):
        return -200.0
    return float(10.0 * np.log10(float(np.mean(power[mask])) + 1e-24))


def _brightness_ceiling(
    freqs: npt.NDArray[np.floating[Any]],
    power: npt.NDArray[Any],
) -> int | None:
    """Return the highest frequency still carrying real content, in Hz.

    The spectrum is sampled in :data:`_CEILING_STEP_HZ` bands and the highest
    band within :data:`_CEILING_DYNAMIC_RANGE_DB` of the loudest band between
    1 kHz and 16 kHz is the ceiling.  A lossy source therefore reports its
    real cutoff, and a full-band recording reports the top of the measured
    range.
    """
    if freqs.size == 0:
        return None
    edges = [float(edge) for edge in np.arange(1000.0, 16000.0, _CEILING_STEP_HZ)]
    levels = [_band_db(freqs, power, low, low + _CEILING_STEP_HZ) for low in edges]
    if not levels:
        return None
    peak = max(levels)
    present = [
        edge
        for edge, level in zip(edges, levels)
        if level >= peak - _CEILING_DYNAMIC_RANGE_DB
    ]
    if not present:
        return None
    return int(present[-1] + _CEILING_STEP_HZ)


def _spectral_measurements(
    audio: AudioSegment,
) -> tuple[dict[str, float], float, int | None]:
    """Measure the band energies, the HF tilt and the brightness ceiling.

    Args:
        audio: The segment the tone stages will receive.

    Returns:
        ``(band_energy_db, tilt_high_over_mid_db, brightness_ceiling_hz)``.
        Any unavailable figure reads as ``-200.0`` or ``None`` rather than
        raising.
    """
    mono, rate = _segment_samples(audio)
    if mono.size < 1024 or rate <= 0:
        return {}, -200.0, None
    bounded = _bounded_window(mono, rate)
    window = bounded * np.hanning(bounded.size)
    power = np.abs(np.fft.rfft(window)) ** 2
    freqs = np.fft.rfftfreq(window.size, 1.0 / rate)
    bands = {
        "sub": _band_db(freqs, power, *_BAND_SUB),
        "low": _band_db(freqs, power, *_BAND_LOW),
        "mid": _band_db(freqs, power, *_BAND_MID),
        "high": _band_db(freqs, power, *_BAND_HIGH),
    }
    return (
        bands,
        bands["high"] - bands["mid"],
        _brightness_ceiling(freqs, power),
    )


def _clipped_share(audio: AudioSegment) -> float:
    """Return the share of samples at or beyond the clipping threshold."""
    mono, _rate = _segment_samples(audio)
    if mono.size == 0:
        return 0.0
    return float(np.mean(np.abs(mono) >= CLIP_SAMPLE_THRESHOLD))


def _db(value: float | None, unit: str = "dBFS", places: int = 0) -> str:
    """Format a level for a report line, reading ``-`` when it is unmeasured."""
    if value is None:
        return "-"
    return f"{value:.{places}f} {unit}".strip()


# ── Profile ───────────────────────────────────────────────────────────────────


def _empty_profile(source_path: Path | str) -> SourceProfile:
    """Return a profile that measured nothing, for a run with no Auto work."""
    return SourceProfile(
        file_name=Path(str(source_path)).name,
        measured_at=datetime.now().isoformat(timespec="seconds"),
    )


def build_profile(
    audio: AudioSegment,
    source_path: Path | str,
    config: StageConfig,
    *,
    auto: set[str],
    working: AudioSegment | None = None,
    silence: tuple[int, int] | None = None,
) -> tuple[SourceProfile, dict[str, str]]:
    """Measure everything the configured Auto stages need, and nothing else.

    Each measurement is isolated: a detector that raises records the failure in
    the returned profile's calling code rather than aborting the batch, because
    a decision layer that can stop a run is worse than the problem it solves.

    Args:
        audio: The decoded source.
        source_path: The file the audio came from (named in reports and used for
            the one FFmpeg level pass).
        config: The run's configuration: the stage parameters and thresholds
            each measurement reads.  Its ``auto_stages`` is the request, never
            the measured set, and is not consulted here.
        auto: The stages Auto may act on - the request minus the stages whose
            own switch is off.  Required: deriving it here would mean
            measuring for a stage that cannot run.
        working: The segment after any in-memory trim, when the Trim decision
            cut.  Hum, noise and tone are measured on this, never on *audio*.
        silence: The already-measured ``(head_ms, tail_ms)`` pair, when the
            caller took the trim decision itself; omitting it makes this
            function measure silence for its own account.

    Returns:
        ``(profile, failures)`` - the populated profile, plus one entry per
        stage whose measurement raised.  Unmeasured fields stay ``None`` and an
        empty mapping means every measurement that ran succeeded.
    """
    measured = working if working is not None else audio
    path = str(source_path)
    profile = _empty_profile(source_path)

    failures: dict[str, str] = {}

    if "declick" in auto:
        try:
            from pop_click_remover.core.declicker import detect_clicks

            p = config.declick_params
            profile = replace(
                profile,
                clicks=detect_clicks(measured, p.sensitivity, p.max_width_ms),
            )
        except Exception as exc:  # noqa: BLE001 - one stage's Auto is disabled
            logger.warning("Click measurement failed: %s", exc, exc_info=True)
            failures["declick"] = str(exc)

    if "trim" in auto and silence is None:
        try:
            from silence_trimmer.core.trimmer import trim_and_fade

            tp = config.trim_params
            result = trim_and_fade(
                audio, threshold=tp.threshold, is_dry_run=True, apply_fade=False
            )
            profile = replace(
                profile,
                head_silence_ms=int(result.start_trim_ms),
                tail_silence_ms=int(result.end_trim_ms),
            )
        except Exception as exc:  # noqa: BLE001 - a measurement failure disables Auto
            logger.warning("Silence measurement failed: %s", exc, exc_info=True)
            failures["trim"] = str(exc)
    elif silence is not None:
        profile = replace(
            profile, head_silence_ms=int(silence[0]), tail_silence_ms=int(silence[1])
        )

    nr = config.noise_reduction_params
    if "reduce_noise" in auto:
        try:
            from noise_reduction.core.noise_reducer import detect_hum

            profile = replace(
                profile, hum=detect_hum(measured, harmonics=nr.hum_harmonics)
            )
            profile = replace(profile, content_rms_dbfs=float(measured.dBFS))
            if nr.reduce_broadband and nr.broadband_engine == SPECTRAL_ENGINE:
                from noise_reduction.core.noise_reducer import detect_noise_profile

                window = detect_noise_profile(
                    measured, gate_threshold_db=nr.gate_threshold_db
                )
                profile = replace(
                    profile,
                    noise_window=window,
                    noise_floor_dbfs=(
                        window.rms_dbfs if window is not None else float(measured.dBFS)
                    ),
                )
            else:
                # A neural run's broadband half is the user's (A5); the floor is
                # still reported from the file so the line can name what it saw.
                profile = replace(profile, noise_floor_dbfs=float(measured.dBFS))
        except Exception as exc:  # noqa: BLE001 - a measurement failure disables Auto
            logger.warning("Noise measurement failed: %s", exc, exc_info=True)
            failures["reduce_noise"] = str(exc)

    if "eq" in auto or "enhance" in auto:
        try:
            bands, tilt_high, ceiling = _spectral_measurements(measured)
            profile = replace(
                profile,
                band_energy_db=bands,
                tilt_high_over_mid_db=tilt_high,
                brightness_ceiling_hz=ceiling,
            )
        except Exception as exc:  # noqa: BLE001 - a measurement failure disables Auto
            logger.warning("Spectral measurement failed: %s", exc, exc_info=True)
            for stage in ("eq", "enhance"):
                if stage in auto:
                    failures[stage] = str(exc)

    if "dynamics" in auto:
        try:
            from audio_suite_shared import audio_probe

            # The true peak alone: ``measure_loudness`` runs the same ebur128
            # chain as ``measure_forensics`` without the astats stage whose
            # crest, per-channel peak and DC figures nothing here reads.
            levels = audio_probe.measure_loudness(path)
            profile = replace(profile, true_peak_dbtp=levels.true_peak_dbtp)
        except Exception as exc:  # noqa: BLE001 - a measurement failure disables Auto
            logger.warning("Level measurement failed: %s", exc, exc_info=True)
            failures["dynamics"] = str(exc)

    if "enhance" in auto:
        try:
            profile = replace(profile, clipped_sample_share=_clipped_share(measured))
        except Exception as exc:  # noqa: BLE001 - a measurement failure disables Auto
            logger.warning("Clip measurement failed: %s", exc, exc_info=True)
            failures["enhance"] = str(exc)

    return profile, failures


# ── Decisions ─────────────────────────────────────────────────────────────────


def _inactive(stage: str, reason: str, auto: bool) -> StageDecision:
    """Return a decision that supplies nothing, with the reason it did not."""
    return StageDecision(stage=stage, auto=auto, active=False, reason=reason, detail="")


def _decide_declick(
    audio: AudioSegment, config: StageConfig, auto: bool
) -> StageDecision:
    """Decide whether the click repair width should be narrowed."""
    if not auto:
        return _inactive("declick", "Auto not ticked", False)
    from pop_click_remover.core.declicker import detect_clicks

    detection = detect_clicks(
        audio, config.declick_params.sensitivity, config.declick_params.max_width_ms
    )
    if detection.count == 0:
        return StageDecision(
            stage="declick",
            auto=True,
            active=False,
            reason="no clicks measured - the stage's own detector will leave the file",
            evidence=(Evidence("click count", "0", ">= 1"),),
        )
    # Auto may only narrow.  The widest detected region sets the width so the
    # repair still covers every click it counted; a wider defect stays outside
    # both the count and the repair, and is reported rather than chased.
    narrowed = min(
        config.declick_params.max_width_ms,
        max(1, int(math.ceil(detection.max_width_ms))),
    )
    evidence = [
        Evidence("click count", str(detection.count), ">= 1"),
        Evidence(
            "widest click", f"{detection.max_width_ms:.1f} ms", f"<= {narrowed} ms"
        ),
    ]
    if detection.wider_defects:
        evidence.append(
            Evidence("wider defects", str(detection.wider_defects), "left untouched")
        )
    detail = (
        f"{detection.count} clicks at {config.declick_params.sensitivity:g}, "
        f"widths to {detection.max_width_ms:.1f} ms"
    )
    return StageDecision(
        stage="declick",
        auto=True,
        active=True,
        reason=detail,
        evidence=tuple(evidence),
        params={"max_width_ms": narrowed},
        detail=detail,
    )


def _decide_trim(
    audio: AudioSegment, config: StageConfig, auto: bool
) -> tuple[StageDecision, AudioSegment | None, tuple[int, int] | None]:
    """Decide whether the detected silence is worth cutting.

    Returns:
        ``(decision, trimmed, silence)`` where *trimmed* is the in-memory slice
        the run would keep (``None`` when nothing is cut) and *silence* is the
        measured ``(head_ms, tail_ms)`` pair (``None`` when silence was never
        measured).  The slice is what the later measurements read, per the
        ordering rule.
    """
    if not auto:
        return _inactive("trim", "Auto not ticked", False), None, None
    tp = config.trim_params
    if tp.mode != "silence":
        return (
            _inactive(
                "trim",
                "exact range is yours - Auto never moves it",
                True,
            ),
            None,
            None,
        )
    from silence_trimmer.core.trimmer import trim_and_fade

    result = trim_and_fade(
        audio, threshold=tp.threshold, is_dry_run=True, apply_fade=False
    )
    total = int(result.start_trim_ms) + int(result.end_trim_ms)
    duration = len(audio)
    evidence = (
        Evidence("head+tail silence", f"{total} ms", f">= {TRIM_MIN_HEAD_TAIL_MS} ms"),
        Evidence(
            "share of file",
            f"{total / duration * 100:.0f}%" if duration else "0%",
            f"<= {TRIM_MAX_SILENCE_SHARE * 100:.0f}%",
        ),
    )
    measured = (int(result.start_trim_ms), int(result.end_trim_ms))
    if total < TRIM_MIN_HEAD_TAIL_MS:
        return (
            StageDecision(
                stage="trim",
                auto=True,
                active=False,
                reason="too little silence to justify a cut",
                evidence=evidence,
            ),
            None,
            measured,
        )
    if duration and total >= duration * TRIM_MAX_SILENCE_SHARE:
        return (
            StageDecision(
                stage="trim",
                auto=True,
                active=False,
                reason=(
                    "the file is mostly silence - that is a source problem, not a trim"
                ),
                evidence=evidence,
            ),
            None,
            measured,
        )
    detail = (
        f"head {result.start_trim_ms / 1000.0:.2f} s, "
        f"tail {result.end_trim_ms / 1000.0:.2f} s at {tp.threshold} dBFS"
    )
    trimmed = audio[int(result.start_trim_ms) : duration - int(result.end_trim_ms)]
    return (
        StageDecision(
            stage="trim",
            auto=True,
            active=True,
            reason=detail,
            evidence=evidence,
            params={},
            detail=detail,
        ),
        trimmed,
        measured,
    )


def _decide_reduce_noise(
    profile: SourceProfile, config: StageConfig, auto: bool
) -> StageDecision:
    """Decide the hum cascade, and confirm the broadband gate is safe."""
    if not auto:
        return _inactive("reduce_noise", "Auto not ticked", False)
    nr = config.noise_reduction_params
    if not (nr.reduce_hum or nr.reduce_broadband):
        return _inactive("reduce_noise", "hum and broadband are both off", True)

    evidence: list[Evidence] = []
    params: dict[str, object] = {}
    parts: list[str] = []
    confirmed = False

    if nr.reduce_hum:
        hum = profile.hum
        if hum is None:
            evidence.append(Evidence("hum partials", "none", ">= 1"))
        elif not nr.hum_auto:
            evidence.append(Evidence("hum detection", "manual cascade", "auto"))
        else:
            orders = max(hum.orders)
            params["hum_harmonics"] = orders
            evidence.append(
                Evidence(
                    "hum partials",
                    f"{hum.fundamental_hz} Hz, {orders} orders",
                    f"{hum.level_db:.0f} dB above floor",
                )
            )
            parts.append(
                f"hum {hum.fundamental_hz} Hz, {len(hum.lines)} partials, "
                f"{hum.level_db:.0f} dB above floor"
            )

    if nr.reduce_broadband:
        if nr.broadband_engine != SPECTRAL_ENGINE:
            evidence.append(
                Evidence("broadband engine", nr.broadband_engine, "spectral")
            )
        else:
            floor = profile.noise_floor_dbfs
            content = profile.content_rms_dbfs
            gap = (
                (content - floor)
                if (floor is not None and content is not None)
                else None
            )
            trial = (
                profile.noise_window.trial_db
                if profile.noise_window is not None
                else None
            )
            evidence.extend(
                [
                    Evidence(
                        "noise floor", _db(floor), f"<= {NOISE_FLOOR_CEILING_DBFS:g}"
                    ),
                    Evidence(
                        "floor vs content",
                        _db(gap, "dB", 0),
                        f">= {NOISE_MIN_GAP_DB:g}",
                    ),
                    Evidence(
                        "profile trial",
                        _db(trial, "dB", 1),
                        f"<= {NOISE_MAX_TRIAL_DB:g}",
                    ),
                ]
            )
            safe = (
                floor is not None
                and floor <= NOISE_FLOOR_CEILING_DBFS
                and gap is not None
                and gap >= NOISE_MIN_GAP_DB
                and trial is not None
                and trial <= NOISE_MAX_TRIAL_DB
            )
            confirmed = safe
            if safe:
                parts.append(
                    f"broadband floor {floor:.0f} dBFS, {gap:.0f} dB under content, "
                    f"trial {trial:.1f} dB"
                )
            else:
                parts.append(
                    f"broadband not confirmed (floor {_db(floor)}, "
                    f"{_db(gap, 'dB', 0)} under content, trial {_db(trial, 'dB', 1)})"
                )

    if params or parts:
        detail = "; ".join(parts)
        return StageDecision(
            stage="reduce_noise",
            auto=True,
            active=bool(params) or confirmed,
            reason=detail,
            evidence=tuple(evidence),
            params=params,
            detail=detail,
        )
    return StageDecision(
        stage="reduce_noise",
        auto=True,
        active=False,
        reason="nothing measured that Auto may act on",
        evidence=tuple(evidence),
    )


def _decide_eq(
    profile: SourceProfile, config: StageConfig, auto: bool
) -> StageDecision:
    """Decide whether one rumble high-pass band should be appended."""
    if not auto:
        return _inactive("eq", "Auto not ticked", False)
    bands = config.eq_params.bands
    if any(band.kind == "highpass" for band in bands):
        return _inactive("eq", "your rack already has a high-pass", True)
    if len(bands) >= MAX_EQ_BANDS:
        return _inactive("eq", f"the rack is full ({MAX_EQ_BANDS} bands)", True)
    sub = profile.band_energy_db.get("sub")
    low = profile.band_energy_db.get("low")
    if sub is None or low is None:
        return _inactive("eq", "band energy was not measured", True)
    excess = sub - low
    evidence = (
        Evidence(
            "sub-30 Hz energy", f"{excess:+.1f} dB", f">= {RUMBLE_EXCESS_DB:g} dB"
        ),
    )
    if excess < RUMBLE_EXCESS_DB:
        return StageDecision(
            stage="eq",
            auto=True,
            active=False,
            reason=f"no rumble measured ({excess:+.1f} dB)",
            evidence=evidence,
        )
    detail = (
        f"high-pass {RUMBLE_BAND_HZ:g} Hz "
        f"(rumble {excess:.0f} dB above the band above it)"
    )
    return StageDecision(
        stage="eq",
        auto=True,
        active=True,
        reason=detail,
        evidence=evidence,
        params={"band": EqBand("highpass", RUMBLE_BAND_HZ, 0.0, EQ_DEFAULT_Q)},
        detail=detail,
    )


def _decide_enhance(
    profile: SourceProfile, config: StageConfig, auto: bool
) -> StageDecision:
    """Decide whether the Custom enhancement fields should be lifted."""
    if not auto:
        return _inactive("enhance", "Auto not ticked", False)
    preset = config.enhance_params.preset
    if preset != "Custom":
        return _inactive(
            "enhance", f"preset '{preset}' is yours - Auto never changes it", True
        )
    ceiling = profile.brightness_ceiling_hz
    if ceiling is not None and ceiling < LOSSY_CEILING_HZ:
        return StageDecision(
            stage="enhance",
            auto=True,
            active=False,
            reason=f"HF limited to {ceiling / 1000.0:.1f} kHz - not boosted",
            evidence=(
                Evidence(
                    "brightness ceiling",
                    f"{ceiling / 1000.0:.1f} kHz",
                    f">= {LOSSY_CEILING_HZ // 1000} kHz",
                ),
            ),
        )
    tilt = profile.tilt_high_over_mid_db
    if tilt is None:
        return _inactive("enhance", "spectral tilt was not measured", True)
    deficit = -tilt
    evidence = (
        Evidence(
            "HF deficit vs mid", f"{deficit:+.1f} dB", f">= {TILT_DEFICIT_DB:g} dB"
        ),
    )
    if deficit < TILT_DEFICIT_DB:
        return StageDecision(
            stage="enhance",
            auto=True,
            active=False,
            reason=f"no HF deficit measured ({deficit:+.1f} dB)",
            evidence=evidence,
        )
    lift = min(TILT_MAX_LIFT_DB, deficit / 2.0)
    lift = round(lift, 1)
    detail = (
        f"presence +{lift:.1f} dB, high shelf +{lift:.1f} dB "
        f"(HF deficit {deficit:.1f} dB)"
    )
    return StageDecision(
        stage="enhance",
        auto=True,
        active=True,
        reason=detail,
        evidence=evidence,
        params={"presence_gain_db": lift, "high_shelf_gain_db": lift},
        detail=detail,
    )


def _decide_dynamics(
    profile: SourceProfile,
    config: StageConfig,
    auto: bool,
    added_gain_db: float,
) -> StageDecision:
    """Decide whether the bypassed limiter should hold the delivery ceiling."""
    if not auto:
        return _inactive("dynamics", "Auto not ticked", False)
    limiter = config.limiter_params
    if not limiter.bypass:
        return _inactive("dynamics", "your limiter is on - nothing to add", True)
    peak = profile.true_peak_dbtp
    if peak is None:
        return _inactive("dynamics", "true peak was not measured", True)
    ceiling = (
        config.normalise_params.true_peak if config.normalise else limiter.ceiling_dbtp
    )
    predicted = peak + added_gain_db
    evidence = (
        Evidence(
            "predicted peak",
            f"{predicted:+.1f} dBTP",
            f"<= {ceiling + LIMITER_MARGIN_DB:g} dBTP",
        ),
    )
    if predicted <= ceiling + LIMITER_MARGIN_DB:
        return StageDecision(
            stage="dynamics",
            auto=True,
            active=False,
            reason=(
                f"predicted peak {predicted:.1f} dBTP is inside the "
                f"{ceiling:g} dBTP ceiling"
            ),
            evidence=evidence,
        )
    detail = f"limiter at {ceiling:g} dBTP (predicted {predicted:.1f} dBTP)"
    return StageDecision(
        stage="dynamics",
        auto=True,
        active=True,
        reason=detail,
        evidence=evidence,
        params={"limiter": replace(limiter, bypass=False, ceiling_dbtp=ceiling)},
        detail=detail,
    )


def _apply_params(
    config: StageConfig, decisions: dict[str, StageDecision]
) -> StageConfig:
    """Return a copy of *config* with only the Auto stages' params replaced.

    This is the mechanical expression of contract rules A1-A5: toggles, delivery
    settings, the preset name and the engine fields are carried through
    untouched because nothing here writes them.
    """
    updates: dict[str, Any] = {}

    declick = decisions.get("declick")
    if declick is not None and declick.active and "max_width_ms" in declick.params:
        updates["declick_params"] = replace(
            config.declick_params, max_width_ms=int(declick.params["max_width_ms"])
        )

    noise = decisions.get("reduce_noise")
    if noise is not None and noise.active and "hum_harmonics" in noise.params:
        updates["noise_reduction_params"] = replace(
            config.noise_reduction_params,
            hum_harmonics=int(noise.params["hum_harmonics"]),
        )

    eq = decisions.get("eq")
    if eq is not None and eq.active and "band" in eq.params:
        band = eq.params["band"]
        assert isinstance(band, EqBand)
        current = config.eq_params
        if len(current.bands) < MAX_EQ_BANDS:
            updates["eq_params"] = EqSettings(
                bands=(*current.bands, band), bypass=current.bypass
            )

    enhance = decisions.get("enhance")
    if enhance is not None and enhance.active:
        params = config.enhance_params
        presence = float(enhance.params.get("presence_gain_db", 0.0))
        shelf = float(enhance.params.get("high_shelf_gain_db", 0.0))
        updates["enhance_params"] = replace(
            params,
            presence_gain_db=params.presence_gain_db + presence,
            high_shelf_gain_db=params.high_shelf_gain_db + shelf,
        )

    dynamics = decisions.get("dynamics")
    if dynamics is not None and dynamics.active and "limiter" in dynamics.params:
        updates["limiter_params"] = dynamics.params["limiter"]

    return replace(config, **updates) if updates else config


def _added_peak_gain(config: StageConfig, decisions: dict[str, StageDecision]) -> float:
    """Return the dB the Tone stages will add before the limiter sees the peak.

    Only the gains Auto itself supplies count, joined to the user's shelves:
    the pipeline applies the preset table when a named preset is chosen, and a
    Custom run applies the fields Auto just lifted.
    """
    enhance = decisions.get("enhance")
    if enhance is None or not enhance.active:
        return 0.0
    return float(enhance.params.get("presence_gain_db", 0.0)) + float(
        enhance.params.get("high_shelf_gain_db", 0.0)
    )


def decide(
    audio: AudioSegment,
    source_path: Path | str,
    config: StageConfig,
    working: AudioSegment | None = None,
) -> BestAudioPlan:
    """Measure *audio* and decide every configured Auto stage for this file.

    Args:
        audio: The decoded source.
        source_path: The file it came from.
        config: The run's configuration.  Its ``auto_stages`` is the whole
            request: with an empty tuple nothing is measured and the plan says
            so.
        working: The segment after an in-memory trim, when the caller already
            applied one.  Normally ``None``: :func:`decide` takes the trim
            decision itself, in chain order, and measures the rest on the slice
            it produced.

    Returns:
        The plan.  With no Auto stage the returned ``config`` is *config*
        itself, so a manual run is untouched.

    Raises:
        AudioProcessingError: Only for a programming error inside this module.
            A measurement that fails disables its stage with a reason instead.
    """
    requested = set(config.auto_stages)
    if not requested:
        return BestAudioPlan(
            source=_empty_profile(source_path),
            decisions={
                stage: _inactive(stage, "Auto not ticked", False)
                for stage in AUTO_STAGES
            },
            config=config,
            skipped_reason="no Auto stages",
        )

    # A stage Auto was ticked on but that is switched off cannot run, and its
    # parameters are not read by anything: measuring for it would buy nothing.
    # This one resolved set drives both what is measured and what each decision
    # says, and the run's config is never rebuilt, so the plan reports the
    # request as the user made it.
    auto = {stage for stage in requested if _STAGE_ENABLED[stage](config)}

    def _declined(stage: str) -> StageDecision:
        """The decision for a stage Auto took no action on, naming why."""
        if stage in requested:
            return _inactive(stage, _STAGE_OFF_REASON, True)
        return _inactive(stage, "Auto not ticked", False)

    if not auto:
        return BestAudioPlan(
            source=_empty_profile(source_path),
            decisions={stage: _declined(stage) for stage in AUTO_STAGES},
            config=config,
        )

    failures: dict[str, str] = {}
    caveats: list[str] = []

    # 1. Trim first: its slice is the signal every later stage will receive.
    if "trim" in auto:
        try:
            trim_decision, trimmed, silence = _decide_trim(audio, config, True)
        except Exception as exc:  # noqa: BLE001 - a measurement failure disables Auto
            logger.warning("Trim measurement failed: %s", exc, exc_info=True)
            failures["trim"] = str(exc)
            trim_decision, trimmed, silence = (
                _inactive("trim", f"silence measurement failed ({exc})", True),
                None,
                None,
            )
    else:
        trim_decision, trimmed, silence = _declined("trim"), None, None
    working_audio = trimmed if trimmed is not None else audio

    # 2. Everything else, measured on the trimmed segment.
    profile, profile_failures = build_profile(
        audio, source_path, config, auto=auto, working=working_audio, silence=silence
    )
    failures.update(profile_failures)

    decisions: dict[str, StageDecision] = {}

    # 3. Declick and noise report their own measurement failure.
    if "declick" in auto:
        try:
            decisions["declick"] = _decide_declick(working_audio, config, True)
        except Exception as exc:  # noqa: BLE001 - a measurement failure disables Auto
            logger.warning("Click measurement failed: %s", exc, exc_info=True)
            failures["declick"] = str(exc)
            decisions["declick"] = _inactive(
                "declick", f"click measurement failed ({exc})", True
            )
    else:
        decisions["declick"] = _declined("declick")

    decisions["trim"] = trim_decision

    if "reduce_noise" in auto:
        decisions["reduce_noise"] = _decide_reduce_noise(profile, config, True)
    else:
        decisions["reduce_noise"] = _declined("reduce_noise")

    if "eq" in auto:
        decisions["eq"] = _decide_eq(profile, config, True)
    else:
        decisions["eq"] = _declined("eq")

    if "enhance" in auto:
        decisions["enhance"] = _decide_enhance(profile, config, True)
    else:
        decisions["enhance"] = _declined("enhance")

    if "dynamics" in auto:
        decisions["dynamics"] = _decide_dynamics(
            profile, config, True, _added_peak_gain(config, decisions)
        )
    else:
        decisions["dynamics"] = _declined("dynamics")

    # 4. A measurement that raised disables that stage's Auto for this file,
    # with a reason, rather than aborting the run (contract rule A9).
    for stage, reason in failures.items():
        decision = decisions.get(stage)
        if decision is not None and decision.auto:
            decisions[stage] = replace(
                _inactive(
                    stage,
                    f"measurement failed ({reason}) - "
                    "the stage's own settings were used",
                    True,
                ),
                failure=reason,
            )

    # 5. Measured limitations the user should know about, whichever stage ran.
    clicks = profile.clicks
    if clicks is not None and clicks.wider_defects:
        caveats.append(
            f"{profile.file_name}: {clicks.wider_defects} wide defect(s) left "
            f"unrepaired (wider than {config.declick_params.max_width_ms} ms)"
        )
    ceiling = profile.brightness_ceiling_hz
    if "enhance" in auto and ceiling is not None and ceiling < LOSSY_CEILING_HZ:
        caveats.append(
            f"{profile.file_name}: HF limited to {ceiling / 1000.0:.1f} kHz - "
            "the missing top octave is reported, not boosted"
        )
    if "reduce_noise" in auto and config.noise_reduction_params.neural_selected():
        caveats.append(
            f"{profile.file_name}: broadband half left to the neural engine "
            "(the user's choice) - Best Audio measured the hum half only"
        )
    for stage, reason in failures.items():
        caveats.append(
            f"{profile.file_name}: Auto off on {stage} - {reason}; "
            "that stage's own settings were used"
        )

    effective = _apply_params(config, decisions)
    return BestAudioPlan(
        source=profile,
        decisions=decisions,
        config=effective,
        caveats=tuple(caveats),
    )


# ── Reporting ─────────────────────────────────────────────────────────────────


def decision_text(plan: BestAudioPlan) -> str:
    """Return the per-file report line for *plan*.

    Every decision that was supplied or declined is named.  A stage Auto was
    not asked for is omitted, so the line describes what the run asked for.
    """
    if plan.skipped_reason is not None:
        return f"BestAudio: {plan.skipped_reason}"
    parts: list[str] = []
    for stage in AUTO_STAGES:
        decision = plan.decisions.get(stage)
        if decision is None or not decision.auto:
            continue
        if decision.active:
            parts.append(
                f"{stage} auto ({decision.detail})"
                if decision.detail
                else f"{stage} auto"
            )
        else:
            parts.append(f"{stage} inactive: {decision.reason}")
    if not parts:
        return "BestAudio: nothing to decide"
    return "BestAudio: " + "; ".join(parts)


def decision_rows(
    plan: BestAudioPlan, file_name: str, status: str
) -> list[dict[str, str]]:
    """Return the decisions CSV rows for one file, in ``AUTO_STAGES`` order.

    Args:
        plan: The file's plan.
        file_name: The file's display name.
        status: The run's outcome for it (``DONE``, ``SKIPPED``, ``ERROR``).

    Returns:
        One row per Auto stage that was asked for, each naming the primary
        measurement and the parameter it produced.  A stage Auto was not asked
        for contributes nothing, so an untouched run writes no rows.
    """
    rows: list[dict[str, str]] = []
    for stage in AUTO_STAGES:
        decision = plan.decisions.get(stage)
        if decision is None or not decision.auto:
            continue
        primary = decision.evidence[0] if decision.evidence else None
        rows.append(
            {
                "file": file_name,
                "status": status,
                "stage": stage,
                "measurement": primary.name if primary else "decision",
                "value": primary.value if primary else "",
                "threshold": primary.threshold if primary else "",
                "decision": "active" if decision.active else "inactive",
                "parameter": _parameter_text(decision),
            }
        )
    return rows


def _parameter_text(decision: StageDecision) -> str:
    """Return the parameter a decision supplies, or the reason it supplied none."""
    if not decision.params:
        return decision.detail or (
            decision.reason if not decision.active else "confirmed"
        )
    parts: list[str] = []
    for key, value in decision.params.items():
        if isinstance(value, EqBand):
            parts.append(value.describe())
        elif key == "limiter":
            parts.append(f"ceiling={getattr(value, 'ceiling_dbtp', '?')}")
        else:
            parts.append(f"{key}={value}")
    return " ".join(parts)


CSV_HEADER: tuple[str, ...] = (
    "file",
    "status",
    "stage",
    "measurement",
    "value",
    "threshold",
    "decision",
    "parameter",
)


def write_decisions_csv(path: Path, rows: list[dict[str, str]]) -> None:
    """Write the decisions table, replacing any earlier one.

    A write failure is logged and never raised: the audio work has already
    happened by the time this runs, so a report problem must not fail a file.

    Args:
        path: The CSV destination, beside the run's own log.
        rows: Rows from every file in the run, in run order.
    """
    import csv

    try:
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_HEADER)
            writer.writeheader()
            writer.writerows(rows)
    except OSError as exc:
        logger.warning("Could not write the decisions report %s: %s", path, exc)


# ── Post-write verification ───────────────────────────────────────────────────


def verify_written(
    output_path: Path, config: StageConfig, plan: BestAudioPlan
) -> VerificationResult:
    """Measure the file that was just written and check the plan's claims.

    The guardrail asks one question - was the plan wrong? - and answers it
    without guessing: it logs both numbers, records a caveat and returns a line
    for the report.  It never deletes, rewrites or corrects the output and
    never raises.

    Args:
        output_path: The file the run wrote.
        config: The run's configuration (delivery settings, engine choice).
        plan: The plan that produced it.

    Returns:
        The caveats and the report line; both empty when every claim held.
    """
    caveats: list[str] = []
    parts: list[str] = []
    try:
        from audio_suite_shared import audio_probe

        measured = audio_probe.measure_forensics(str(output_path))
    except Exception as exc:  # noqa: BLE001 - verification never fails a run
        logger.warning("Could not verify %s: %s", output_path, exc, exc_info=True)
        return VerificationResult(
            caveats=(
                f"{output_path.name}: written file could not be measured ({exc})",
            ),
            message="",
        )

    ceiling: float | None = None
    if config.normalise:
        ceiling = config.normalise_params.true_peak
    elif config.dynamics and not config.limiter_params.bypass:
        ceiling = config.limiter_params.ceiling_dbtp

    peak = measured.true_peak_dbtp
    if (
        ceiling is not None
        and peak is not None
        and peak > ceiling + VERIFY_PEAK_MARGIN_DB
    ):
        caveats.append(
            f"{output_path.name}: claimed a {ceiling:g} dBTP ceiling, "
            f"measured {peak:.1f} dBTP"
        )
        parts.append(f"claimed {ceiling:g} dBTP, measured {peak:.1f} dBTP")

    n = config.normalise_params
    if (
        config.normalise
        and n.target_mode == "lufs"
        and not n.album_mode
        and measured.integrated_lufs is not None
    ):
        delta = abs(measured.integrated_lufs - n.target_lufs)
        if delta > n.tolerance + VERIFY_LOUDNESS_MARGIN_DB:
            caveats.append(
                f"{output_path.name}: claimed {n.target_lufs:g} LUFS, "
                f"measured {measured.integrated_lufs:.1f} LUFS"
            )
            parts.append(
                f"claimed {n.target_lufs:g} LUFS, measured "
                f"{measured.integrated_lufs:.1f} LUFS"
            )

    # Clipping needs the decoded output, which is one decode more than a file
    # count justifies - so it runs only when the plan measured the source share.
    # It counts samples, so the gain the run applied cannot make it fire falsely.
    clip_before = plan.source.clipped_sample_share
    if clip_before is not None:
        try:
            from pydub import AudioSegment

            written = AudioSegment.from_file(str(output_path))
            share_after = _clipped_share(written)
            if share_after > clip_before + 0.0001:
                caveats.append(
                    f"{output_path.name}: clipped samples rose from "
                    f"{clip_before * 100:.3f}% to {share_after * 100:.3f}%"
                )
                parts.append(
                    f"clipping {clip_before * 100:.2f}% -> {share_after * 100:.2f}%"
                )
        except Exception as exc:  # noqa: BLE001 - a guardrail never fails a run
            logger.warning("Could not re-read %s: %s", output_path, exc, exc_info=True)

    message = ""
    if parts:
        message = f"verify: {'; '.join(parts)} - plan did not achieve its target"
        logger.warning("BestAudio guardrail for %s: %s", output_path.name, message)
    return VerificationResult(caveats=tuple(caveats), message=message)
