"""spectrogram.py — FFT spectrogram computation and figure rendering.

The single place where a spectrogram's numbers come from. Decoding reuses the
shared analysis loader, so the Sprint 1 containers (WavPack, Monkey's Audio,
Musepack, Speex, DSF) decode through its FFmpeg fallback exactly as the BPM and
key analyzers do.

Everything here is deliberately GUI-free: :func:`compute_spectrogram` returns
plain arrays, :func:`build_figure` builds a matplotlib ``Figure`` without
touching ``pyplot`` (no global figure manager, so a canvas can be embedded in
Tk and a figure can be exported in a headless CLI run), and
:func:`export_image` writes one PNG. The GUI and the CLI are both thin shells
over these three functions.

Changed in 1.3.0: initial version (PLAN_feature_expansion.md Item 3.1 / D42).
Changed in 1.4.0: the shared loader now supplies the plain-language decode
error, so this module re-raises it instead of rewrapping it with a full path.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from audio_suite_shared.analysis_loader import (
    decode_error,
    librosa_load_with_fallback,
)
from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.exceptions import AudioAnalysisError, AudioCodecError

logger = logging.getLogger(f"audio_suite.{__name__}")

#: FFT window size in samples. 2048 resolves ~10 Hz bins at 44.1 kHz, which
#: shows harmonics and codec cut-offs without smearing transients.
DEFAULT_N_FFT = 2048

#: Samples between successive FFT frames (75 % overlap at the default window).
DEFAULT_HOP_LENGTH = 512

#: Display floor relative to the loudest bin, in dB.
DEFAULT_DB_RANGE = 80.0

#: Sequential colour map; bright means loud.
DEFAULT_CMAP = "magma"

#: Longest window decoded for one spectrogram, in seconds. The viewer is an
#: inspection tool, not an analysis engine: a cap keeps a stray multi-hour file
#: from spending minutes and gigabytes on one image.
MAX_ANALYSIS_SECONDS = 600

#: Suffix appended to the source stem for every exported image.
OUTPUT_SUFFIX = "_spectrogram.png"

#: Smallest window that can be transformed at all.
MIN_WINDOW_SECONDS = 0.1

#: Floor used when a window carries no energy at all (digital silence).
_SILENCE_PEAK_DB = -240.0


@dataclass(frozen=True)
class SpectrogramData:
    """One computed spectrogram, ready to render or assert on.

    Attributes:
        db: Magnitude in dB relative to the loudest bin, shaped
            ``(frequencies, frames)``. The loudest bin is 0 dB and the display
            floor is ``-DEFAULT_DB_RANGE``.
        frequencies: Bin centre frequencies in Hz, ascending.
        times: Frame times in seconds, relative to the start of the file (the
            selected window's offset is added).
        sample_rate: Native sample rate of the decoded audio.
        duration_secs: Length of the analysed window in seconds.
        n_fft: FFT window size used.
        hop_length: Samples between frames.
        peak_db: Absolute peak sample level in dBFS (``-240`` for silence), so
            a quiet master and a hot one are distinguishable even though both
            are normalised to 0 dB for display. This is a time-domain level,
            not the FFT magnitude: an STFT bin's magnitude scales with the
            window length and would report +48 dBFS for a half-scale tone.
    """

    db: npt.NDArray[np.floating[Any]]
    frequencies: npt.NDArray[np.floating[Any]]
    times: npt.NDArray[np.floating[Any]]
    sample_rate: int
    duration_secs: float
    n_fft: int
    hop_length: int
    peak_db: float

    @property
    def shape(self) -> tuple[int, int]:
        """Return ``(frequency_bins, time_frames)``."""
        return (int(self.db.shape[0]), int(self.db.shape[1]))


def _load_window(
    file_path: str, start: float, end: float
) -> tuple[npt.NDArray[np.float32], int]:
    """Decode the selected window of *file_path*.

    The shared loader caps by duration from the file's beginning, so the window
    is decoded from ``0`` to ``end`` (or the global cap) and then sliced in
    memory. That keeps the FFmpeg fallback for the Sprint 1 formats, which a
    byte-offset decode would bypass.

    Args:
        file_path: Path to an audio file.
        start: Window start in seconds (``0`` for the beginning).
        end: Window end in seconds; ``0`` means "to the end" (capped).

    Returns:
        Two-tuple ``(samples, sample_rate)`` for the requested window.

    Raises:
        ValueError: If ``end`` is not greater than ``start``.
        AudioCodecError: If the file cannot be decoded.
        AudioAnalysisError: If the window is shorter than the minimum.
    """
    if end > 0 and end <= start:
        raise ValueError(f"End ({end:.3f}s) must be later than start ({start:.3f}s).")

    duration = int(math.ceil(end)) if end > 0 else MAX_ANALYSIS_SECONDS
    try:
        samples, sample_rate = librosa_load_with_fallback(
            file_path, duration=duration, mono=True, sr=None
        )
    except AudioCodecError:
        # The shared loader already produced the user-facing reason (the
        # decoder's own wording is misleading); re-raise it unchanged so the
        # CLI and GUI keep one exception type without losing that message.
        raise
    except Exception as exc:
        # Any other failure still gets the same declared type, so one
        # unreadable file cannot abort a whole folder.
        raise decode_error(file_path, original=exc) from exc
    sr = int(sample_rate)
    if sr <= 0:
        raise AudioAnalysisError(
            f"Audio has no sample rate and cannot be analysed: {file_path}"
        )

    window: npt.NDArray[np.float32] = samples
    start_index = int(round(start * sr))
    if start_index:
        window = window[start_index:]
    if end > 0:
        window = window[: int(round((end - start) * sr))]

    if len(window) / sr < MIN_WINDOW_SECONDS:
        raise AudioAnalysisError(
            f"Selected window is too short to analyse ({len(window) / sr:.2f}s)."
        )
    return window, sr


def compute_spectrogram(
    file_path: str,
    *,
    start: float = 0.0,
    end: float = 0.0,
    n_fft: int = DEFAULT_N_FFT,
    hop_length: int = DEFAULT_HOP_LENGTH,
    max_freq: float = 0.0,
) -> SpectrogramData:
    """Compute the FFT spectrogram of a file or of one window of it.

    Args:
        file_path: Path to an audio file.
        start: Window start in seconds (``0`` for the beginning).
        end: Window end in seconds; ``0`` means "to the end" (capped).
        n_fft: FFT window size in samples.
        hop_length: Samples between frames.
        max_freq: Highest frequency to keep in Hz; ``0`` keeps the Nyquist
            range. Bins above it are dropped, which is what makes a 20 kHz
            codec cut-off visible without squashing the bass into one row.

    Returns:
        A populated :class:`SpectrogramData`.

    Raises:
        ValueError: If the window or the FFT parameters are nonsense.
        AudioAnalysisError: If the window is too short for ``n_fft``.
    """
    if n_fft <= 0 or hop_length <= 0:
        raise ValueError("FFT size and hop length must be positive.")
    if hop_length > n_fft:
        raise ValueError("Hop length cannot exceed the FFT window size.")

    import librosa

    samples, sr = _load_window(file_path, start, end)
    if len(samples) < n_fft:
        raise AudioAnalysisError(
            f"Window is shorter than the FFT size ({len(samples)} < {n_fft} samples)."
        )

    spectrum: npt.NDArray[np.complexfloating[Any, Any]] = librosa.stft(
        samples, n_fft=n_fft, hop_length=hop_length
    )
    magnitude: npt.NDArray[np.floating[Any]] = np.abs(spectrum)
    peak = float(magnitude.max()) if magnitude.size else 0.0
    peak_amplitude = float(np.max(np.abs(samples))) if len(samples) else 0.0
    peak_db = (
        _SILENCE_PEAK_DB if peak_amplitude <= 0.0 else 20.0 * math.log10(peak_amplitude)
    )

    # Relative to the loudest bin, clipped to a fixed floor, so the colour map
    # means the same thing on a quiet and a hot master. Digital silence has no
    # peak to normalise against, and ``20*log10(0)`` is -inf, which an image
    # cannot show: it fills the frame with the display floor instead.
    if peak > 0.0:
        relative: npt.NDArray[np.floating[Any]] = librosa.amplitude_to_db(
            magnitude, ref=float(peak)
        )
    else:
        relative = np.full(magnitude.shape, -float(DEFAULT_DB_RANGE), dtype=np.float32)
    frequencies: npt.NDArray[np.floating[Any]] = librosa.fft_frequencies(
        sr=sr, n_fft=n_fft
    )
    times: npt.NDArray[np.floating[Any]] = (
        librosa.times_like(relative, sr=sr, hop_length=hop_length) + start
    )

    if max_freq > 0:
        keep = frequencies <= max_freq
        relative = relative[keep]
        frequencies = frequencies[keep]

    return SpectrogramData(
        db=relative,
        frequencies=frequencies,
        times=times,
        sample_rate=sr,
        duration_secs=len(samples) / sr,
        n_fft=n_fft,
        hop_length=hop_length,
        peak_db=peak_db,
    )


def build_figure(
    data: SpectrogramData,
    *,
    title: str = "",
    dynamic_range_db: float = DEFAULT_DB_RANGE,
    cmap: str = DEFAULT_CMAP,
    dpi: int = 100,
) -> Any:
    """Render *data* as a matplotlib figure (no ``pyplot``, no window).

    Args:
        data: A computed spectrogram.
        title: Plot title; typically the file name.
        dynamic_range_db: Colour floor relative to the peak, in dB.
        cmap: Matplotlib colour map name.
        dpi: Figure resolution.

    Returns:
        A ``matplotlib.figure.Figure`` the caller owns (embed it in a Tk canvas
        or hand it to :func:`export_image`).

    Raises:
        ValueError: If ``dynamic_range_db`` is not positive.
    """
    if dynamic_range_db <= 0:
        raise ValueError("Dynamic range must be positive.")

    from matplotlib.figure import Figure

    figure = Figure(figsize=(10.0, 4.8), dpi=dpi, facecolor="#ffffff")
    axes = figure.add_subplot(111)

    frequencies = data.frequencies
    times = data.times
    if len(frequencies) and len(times):
        extent = (
            float(times[0]),
            float(times[-1]),
            float(frequencies[0]),
            float(frequencies[-1]),
        )
    else:  # pragma: no cover - compute_spectrogram never returns an empty axis
        extent = (0.0, 0.0, 0.0, 0.0)

    image = axes.imshow(
        data.db,
        origin="lower",
        aspect="auto",
        cmap=cmap,
        vmin=-float(dynamic_range_db),
        vmax=0.0,
        extent=extent,
        interpolation="nearest",
    )
    axes.set_xlabel("Time (s)", fontsize=9)
    axes.set_ylabel("Frequency (Hz)", fontsize=9)
    axes.tick_params(labelsize=8)
    axes.set_title(title or "Spectrogram", fontsize=10, fontweight="bold")

    colorbar = figure.colorbar(image, ax=axes, pad=0.01)
    colorbar.set_label("dB re peak", fontsize=9)
    colorbar.ax.tick_params(labelsize=8)
    figure.tight_layout()
    return figure


def export_image(figure: Any, output_path: str | os.PathLike[str]) -> str:
    """Write *figure* to *output_path* as a PNG.

    Args:
        figure: A figure returned by :func:`build_figure`.
        output_path: Destination file path.

    Returns:
        The destination path as a string.

    Raises:
        OSError: If the destination directory cannot be created or the file
            cannot be written.
    """
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, format="png", dpi=figure.dpi, bbox_inches="tight")
    return str(destination)


def output_path_for(
    source: str | os.PathLike[str], output_dir: str | os.PathLike[str] | None = None
) -> Path:
    """Return the PNG path for *source*: ``<stem>_spectrogram.png``.

    Args:
        source: The audio file the image describes.
        output_dir: Destination directory; defaults to the source's own folder.

    Returns:
        The destination path (not created).
    """
    source_path = Path(source)
    target_dir = Path(output_dir) if output_dir else source_path.parent
    return target_dir / f"{source_path.stem}{OUTPUT_SUFFIX}"


def iter_audio_files(path: str | os.PathLike[str]) -> list[str]:
    """Return the audio files to render for *path*.

    A file path yields itself when its extension is supported. A directory is
    walked recursively and its files are returned sorted, so a batch and its
    log are deterministic.

    Args:
        path: An audio file or a directory to scan.

    Returns:
        Sorted list of audio file paths (empty when a directory holds none).

    Raises:
        FileNotFoundError: If *path* does not exist.
    """
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    if target.is_file():
        return [str(target)] if target.suffix.lower() in SUPPORTED_EXTENSIONS else []

    found: list[str] = []
    for root, _dirs, files in os.walk(target):
        for name in files:
            if name.lower().endswith(SUPPORTED_EXTENSIONS):
                found.append(os.path.join(root, name))
    return sorted(found)


def render_spectrogram(
    source: str,
    output_path: str | os.PathLike[str],
    *,
    start: float = 0.0,
    end: float = 0.0,
    n_fft: int = DEFAULT_N_FFT,
    hop_length: int = DEFAULT_HOP_LENGTH,
    max_freq: float = 0.0,
    dynamic_range_db: float = DEFAULT_DB_RANGE,
    cmap: str = DEFAULT_CMAP,
) -> str:
    """Compute, render and write one spectrogram PNG.

    Args:
        source: Audio file to analyse.
        output_path: Destination PNG path.
        start: Window start in seconds.
        end: Window end in seconds (``0`` = to the end, capped).
        n_fft: FFT window size in samples.
        hop_length: Samples between frames.
        max_freq: Highest frequency to keep in Hz (``0`` = Nyquist).
        dynamic_range_db: Colour floor relative to the peak, in dB.
        cmap: Matplotlib colour map name.

    Returns:
        The written path.
    """
    data = compute_spectrogram(
        source,
        start=start,
        end=end,
        n_fft=n_fft,
        hop_length=hop_length,
        max_freq=max_freq,
    )
    figure = build_figure(
        data,
        title=Path(source).name,
        dynamic_range_db=dynamic_range_db,
        cmap=cmap,
    )
    return export_image(figure, output_path)
