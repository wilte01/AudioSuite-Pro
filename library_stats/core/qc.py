"""The QC / forensics pass: what a file's audio actually measures.

Changed in 2.7.0: new module - the per-file QC metrics behind ``--qc``
(PLAN_2026-11-03_2.7.0_feature_wave_3.md F-S7).

Two kinds of figure live here.  Loudness, true peak, sample peak, crest factor
and per-channel DC offset are FFmpeg's, read from the shared probe so this module
runs no process of its own.  Clipped samples, dropouts and phase correlation are
not something FFmpeg reports, so they are counted from the decoded samples.

Those samples come from ``soundfile`` when libsndfile reads the container,
and otherwise from the shared :func:`audio_suite_shared.audio_probe.
decode_samples`, which decodes through FFmpeg at the file's own rate and
channel count.  A ``.m4a`` or WavPack file therefore keeps its clipping,
silence-run and phase figures, where it used to lose three columns while
its loudness and peak still measured.

"DR" is deliberately not a column: the crest factor is what this module measures,
and a user comparing it with a TT-DR meter would be comparing two different
things.  The guide says so where the column is explained.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

from audio_suite_shared.audio_probe import (
    ForensicMetrics,
    StreamInfo,
    decode_samples,
    measure_forensics,
    probe_stream,
)
from audio_suite_shared.exceptions import AudioFormatError, AudioSuiteError

#: A sample this close to full scale is a clipped sample.  A float WAV built with
#: ``1.0`` survives the round trip exactly, and a PCM one decodes to
#: ``32767/32768``, so the tolerance has to admit both.
CLIP_FLOOR = 0.999

#: The pass runs FFmpeg subprocesses, so past a point extra threads only queue:
#: on a 20-core host 51 files went 4.9x faster at eight workers and 5.7x at
#: sixteen, and the per-file floor is the subprocess latency, not the CPU.  Half
#: the cores keeps a big machine responsive while still using its parallelism.
QC_MAX_WORKERS = 8


#: A loudness range needs gated short-term windows, and EBU Tech 3342 measures
#: them over 3 s.  FFmpeg prints ``LRA: 0.0`` for a stream it cannot gate, which
#: is indistinguishable by value alone from a genuinely flat one, so the
#: duration is what separates them here.
LRA_MIN_SECONDS = 3.0

#: A run of digital silence this long is a dropout rather than a zero crossing.
DROPOUT_SECONDS = 0.005

#: Frames quieter than this count as silence.  Digital silence is exactly zero,
#: so the tolerance only has to absorb float round-trip error.
SILENCE_AMPLITUDE = 1e-6

#: Why a phase figure can be absent.  A missing number never means ``0.0``.
PHASE_MONO = "mono file: phase correlation needs two channels"
PHASE_UNAVAILABLE = "the samples could not be decoded"
LRA_TOO_SHORT = "shorter than 3.0 s: no gated window, so no loudness range"


@dataclass(frozen=True)
class QcMetrics:
    """One file's QC figures, with the reason when one is missing.

    Attributes:
        file: The measured file's name.
        integrated_lufs: Gated integrated loudness, or ``None`` on refusal.
        lra_lu: Loudness range in LU.  ``None`` when the file is too short to
            gate a range or FFmpeg printed none - never ``0.0`` for "not
            measured", though ``0.0`` is reported for a long file that really
            has no range.
        lra_note: Why ``lra_lu`` is absent; empty when it is there.
        true_peak_dbtp: Oversampled peak, or ``None``.
        sample_peak_dbfs: Loudest decoded sample in dBFS, or ``None``.
        crest_factor_db: Sample peak minus RMS, or ``None``.
        dc_offset: One DC offset per channel, or ``()``.
        phase_correlation: Channel correlation in ``[-1, 1]``, or ``None`` for a
            mono file or one whose samples could not be read.
        phase_note: Why ``phase_correlation`` is absent; empty when it is there.
        clipped_samples: Samples at or above :data:`CLIP_FLOOR`, or ``None``.
        dropouts: Runs of at least :data:`DROPOUT_SECONDS` of digital silence.
        stream: The stream the probe reported, or ``None`` on refusal.
        qc_error: Why the file could not be measured; empty when it was.
    """

    file: str
    integrated_lufs: float | None = None
    lra_lu: float | None = None
    lra_note: str = ""
    true_peak_dbtp: float | None = None
    sample_peak_dbfs: float | None = None
    crest_factor_db: float | None = None
    dc_offset: tuple[float, ...] = field(default_factory=tuple)
    phase_correlation: float | None = None
    phase_note: str = ""
    clipped_samples: int | None = None
    dropouts: int | None = None
    stream: StreamInfo | None = None
    qc_error: str = ""

    @property
    def measured(self) -> bool:
        """Whether the file produced a usable measurement."""
        return not self.qc_error

    def as_dict(self) -> dict[str, object]:
        """Return the metrics as JSON-friendly values.

        ``None`` stays ``None`` rather than becoming ``0``: a report consumer
        must be able to tell "not measured" from "measured as zero".
        """
        payload: dict[str, object] = {
            "file": self.file,
            "integrated_lufs": self.integrated_lufs,
            "lra_lu": self.lra_lu,
            "lra_note": self.lra_note,
            "true_peak_dbtp": self.true_peak_dbtp,
            "sample_peak_dbfs": self.sample_peak_dbfs,
            "crest_factor_db": self.crest_factor_db,
            "dc_offset": list(self.dc_offset),
            "phase_correlation": self.phase_correlation,
            "phase_note": self.phase_note,
            "clipped_samples": self.clipped_samples,
            "dropouts": self.dropouts,
            "qc_error": self.qc_error,
        }
        if self.stream is not None:
            payload["stream"] = {
                "container": self.stream.container,
                "codec": self.stream.codec,
                "sample_rate": self.stream.sample_rate,
                "channels": self.stream.channels,
                "bit_depth": self.stream.bit_depth,
                "duration_sec": self.stream.duration_sec,
                "bitrate_kbps": self.stream.bitrate_kbps,
            }
        return payload


@dataclass(frozen=True)
class QcSummary:
    """The library-level QC picture the three reports all render.

    The CLI, the JSON payload and the HTML section paint the same facts - how
    many files were measured, how many carry damage, which ones are worst - so
    they read them from one value rather than each counting the same list.  A
    report that says "3 clipped" next to a worst-offender table of two files is
    exactly the contradiction this type exists to prevent.

    Attributes:
        total: Files offered to the pass, measured or not.
        measured: Files that produced figures.
        unmeasured: Files refused, with a reason in their ``qc_error``.
        clipped: Measured files with at least one clipped sample.
        with_dropouts: Measured files with at least one dropout run.
        offenders: The worst files, worst first (see :func:`worst_offenders`).
    """

    total: int = 0
    measured: int = 0
    unmeasured: int = 0
    clipped: int = 0
    with_dropouts: int = 0
    offenders: tuple[QcMetrics, ...] = ()

    @property
    def clean(self) -> bool:
        """Whether every file was measurable and none showed damage."""
        return self.unmeasured == 0 and self.clipped == 0 and self.with_dropouts == 0

    def as_dict(self) -> dict[str, object]:
        """Return the summary as JSON-friendly values.

        ``worst_offenders`` names the files only: the per-file figures are in
        the ``files`` list beside it, so repeating them here would double the
        payload for a ranking the reader can look up by name.
        """
        return {
            "total": self.total,
            "measured": self.measured,
            "unmeasured": self.unmeasured,
            "clipped": self.clipped,
            "with_dropouts": self.with_dropouts,
            "worst_offenders": [item.file for item in self.offenders],
        }


def qc_summary(metrics: Sequence[QcMetrics], *, limit: int = 5) -> QcSummary:
    """Count the pass and rank it, so every report tells one story.

    Args:
        metrics: Every file offered to the pass, refusals included.
        limit: How many offenders to name.

    Returns:
        The counts, split into measured and refused, and the ranked offenders.
    """
    measured = [item for item in metrics if item.measured]
    return QcSummary(
        total=len(metrics),
        measured=len(measured),
        unmeasured=len(metrics) - len(measured),
        clipped=sum(1 for item in measured if (item.clipped_samples or 0) > 0),
        with_dropouts=sum(1 for item in measured if (item.dropouts or 0) > 0),
        offenders=worst_offenders(measured, limit=limit),
    )


def default_qc_workers() -> int:
    """Return the worker count a QC pass uses when the caller names none.

    Half the cores, at least one, never more than :data:`QC_MAX_WORKERS`.  A
    fixed one -- the previous default -- made every run serial on every
    machine, and a fixed eight oversubscribes a small one.

    Returns:
        A worker count suitable for ``ThreadPoolExecutor``.
    """
    cores = os.cpu_count() or 1
    return max(1, min(QC_MAX_WORKERS, cores // 2))


def worst_offenders(
    metrics: Sequence[QcMetrics], *, limit: int = 5
) -> tuple[QcMetrics, ...]:
    """Return the files a QC report should name first.

    One ranking, shared by the CSV, the JSON payload and the HTML section: three
    consumers each deciding what "worst" means is how a report contradicts
    itself.  Clipping leads because it is damage rather than a characteristic;
    dropouts follow, then inverted phase (the most negative correlation first),
    then crest factor, where a very low figure means a squashed master.  A file
    with nothing wrong is not an offender, and the order is stable by name.

    Args:
        metrics: Measured files.  Refusals are ignored: they are reported
            separately, as a file that could not be measured.
        limit: How many to return.

    Returns:
        The worst files, worst first.
    """
    measured = [item for item in metrics if item.measured]

    def severity(item: QcMetrics) -> tuple[float, float, float, float, str]:
        return (
            -float(item.clipped_samples or 0),
            -float(item.dropouts or 0),
            min(0.0, item.phase_correlation or 0.0),
            item.crest_factor_db if item.crest_factor_db is not None else 99.0,
            item.file,
        )

    ranked = sorted(measured, key=severity)
    return tuple(ranked[:limit])


def _read_samples(
    path: str, *, stream: StreamInfo | None = None
) -> tuple[np.ndarray, int]:
    """Decode *path* to a ``(frames, channels)`` float array and its rate.

    ``soundfile`` is tried first: it reads the containers libsndfile supports
    without starting a process, and it is the decoder the rest of this module
    is calibrated against.  A container it cannot open - ``.m4a``, ``.wma``,
    WavPack - is decoded by the shared probe instead, so a container the
    library cannot read no longer costs three of the nine QC columns.

    Args:
        path: The audio file.
        stream: The file's probe result, when the caller has one; the FFmpeg
            decode needs the channel count and rate it reports.

    Returns:
        The samples and the sample rate.

    Raises:
        AudioSuiteError: Neither decoder could read the file.  ``soundfile``'s
            own exception is not part of this module's contract, so it is
            wrapped, and the FFmpeg failure is kept as the cause.
    """
    try:
        data, samplerate = sf.read(path, always_2d=True, dtype="float32")
    except (RuntimeError, ValueError, OSError) as exc:
        try:
            return decode_samples(path, stream=stream)
        except AudioSuiteError as fallback:
            raise AudioFormatError(
                f"'{path}' could not be decoded for sample-level QC: "
                f"soundfile could not read it ({exc}) and the FFmpeg decode "
                f"failed too ({fallback})",
                context={"file": path},
            ) from fallback
    return data, int(samplerate)


def _clipped_samples(samples: np.ndarray) -> int:
    """Return how many frames hold at least one sample at full scale."""
    return int(np.count_nonzero(np.any(np.abs(samples) >= CLIP_FLOOR, axis=1)))


def _dropouts(samples: np.ndarray, samplerate: int) -> int:
    """Return how many runs of digital silence the file holds.

    A dropout is a run, not a sample: a zero crossing is one sample of near-zero
    audio on one channel, and a file cut off to silence is one gap however long
    it lasts.
    """
    minimum = max(1, int(round(DROPOUT_SECONDS * samplerate)))
    silent = np.all(np.abs(samples) <= SILENCE_AMPLITUDE, axis=1)
    count = 0
    run = 0
    for is_silent in silent:
        if is_silent:
            run += 1
            continue
        if run >= minimum:
            count += 1
        run = 0
    if run >= minimum:
        count += 1
    return count


def _phase_correlation(samples: np.ndarray) -> float | None:
    """Return the two channels' correlation, or ``None`` when it is undefined."""
    if samples.shape[1] < 2:
        return None
    left = samples[:, 0].astype(np.float64)
    right = samples[:, 1].astype(np.float64)
    if left.std() == 0.0 or right.std() == 0.0:
        return None
    return float(np.corrcoef(left, right)[0, 1])


def _loudness_range(
    forensic: ForensicMetrics, duration_sec: float | None
) -> tuple[float | None, str]:
    """Return the loudness range to report, and why it is absent.

    FFmpeg prints ``LRA: 0.0`` both for a file too short to gate and for one
    that is genuinely flat, so the value alone cannot decide which is meant.
    A file shorter than one 3 s window has no measurement to report, and a
    reported ``0.0`` there would read as a perfectly flat dynamic range; a
    longer file keeps whatever FFmpeg measured, ``0.0`` included.

    Args:
        forensic: The probe's figures for the file.
        duration_sec: The stream's length, or ``None`` when unknown.

    Returns:
        The range and the note explaining its absence (empty when present).
    """
    if duration_sec is not None and duration_sec < LRA_MIN_SECONDS:
        return None, LRA_TOO_SHORT
    if forensic.loudness_range_lu is None:
        return None, "FFmpeg printed no loudness range"
    return forensic.loudness_range_lu, ""


def _from_probe(
    path: str,
    forensic: ForensicMetrics,
    *,
    stream: StreamInfo | None = None,
    duration_sec: float | None = None,
    clipped_samples: int | None = None,
    dropouts: int | None = None,
    phase_correlation: float | None = None,
    phase_note: str = "",
) -> QcMetrics:
    """Build the metrics from the probe's figures and the sample-domain ones."""
    lra_lu, lra_note = _loudness_range(forensic, duration_sec)
    return QcMetrics(
        file=_name(path),
        integrated_lufs=forensic.integrated_lufs,
        lra_lu=lra_lu,
        lra_note=lra_note,
        true_peak_dbtp=forensic.true_peak_dbtp,
        sample_peak_dbfs=forensic.sample_peak_dbfs,
        crest_factor_db=forensic.crest_factor_db,
        dc_offset=forensic.dc_offset,
        phase_correlation=phase_correlation,
        phase_note=phase_note,
        clipped_samples=clipped_samples,
        dropouts=dropouts,
        stream=stream,
    )


def _name(path: str) -> str:
    """Return the file's display name."""
    return Path(path).name or path


def measure_file(path: str) -> QcMetrics:
    """Measure one file's QC figures without writing anything.

    A file that cannot be measured is reported in ``qc_error`` rather than
    raised: a QC pass over a library must not stop the scan it accompanies.

    Args:
        path: The audio file to measure.

    Returns:
        The measured figures, or the reason they could not be taken.
    """
    try:
        stream = probe_stream(path)
        forensic = measure_forensics(path)
    except AudioSuiteError as exc:
        return QcMetrics(file=_name(path), qc_error=str(exc))

    duration = stream.duration_sec
    try:
        samples, samplerate = _read_samples(path, stream=stream)
    except AudioSuiteError:
        return _from_probe(
            path,
            forensic,
            stream=stream,
            duration_sec=duration,
            phase_note=PHASE_UNAVAILABLE,
        )

    correlation = _phase_correlation(samples)
    if correlation is None:
        note = PHASE_MONO if samples.shape[1] < 2 else PHASE_UNAVAILABLE
    else:
        note = ""
    return _from_probe(
        path,
        forensic,
        stream=stream,
        duration_sec=duration,
        clipped_samples=_clipped_samples(samples),
        dropouts=_dropouts(samples, samplerate),
        phase_correlation=correlation,
        phase_note=note,
    )
