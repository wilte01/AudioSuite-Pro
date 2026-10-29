"""
audio_playback.py — Shared A/B audition playback for Audio Suite DSP tools.

Provides a thin portable playback utility built on ``sounddevice`` that lets
the DSP GUIs let the user audition the original and processed versions of a
file before/after processing.  ``sounddevice`` is BSD/MIT-licensed and
portable across Windows/macOS/Linux with no redistribution restriction, and
was approved as the A/B playback dependency for the suite (see
``PLAN_gap_analysis.md`` Phase 2.1).

Design notes
------------
* Playback is **non-blocking best-effort** from the GUI's perspective: it runs
  on a short-lived daemon thread so the Tk main loop is never stalled.  Each
  call stops any previously playing sample first, so clicking a different
  "Play" button cleanly interrupts the prior one.
* Decoding to a temp WAV is delegated to ``pydub`` (already a suite dependency),
  so we never hand a compressed file directly to the sound device.
* All failures are handled via ``@handle_audio_errors(reraise=False)`` so a
  missing device, file, or codec is logged and reported through the standard
  suite error plumbing without crashing the GUI thread.
"""
# Changed in 2.1.7: ASCII-only status output (R-14) - typography stays in
# comments and docs; a cp1252 console cannot encode these glyphs.

from __future__ import annotations

import logging
import shutil
import tempfile
import threading
import wave
from pathlib import Path

import numpy as np
import numpy.typing as npt

from .exceptions import AudioSuiteError, handle_audio_errors, map_to_audio_error

logger = logging.getLogger(f"audio_suite.{__name__}")

# Lazy import so tests that never touch the device don't require sounddevice
# to be importable.  The dependency is declared in pyproject.toml; this guard
# is purely defensive for environments that import the module without it.
try:  # pragma: no cover - exercised indirectly when the device is present
    import sounddevice as _sd

    _HAS_BACKEND = True
except (ImportError, OSError) as _exc:  # pragma: no cover
    logger.debug("Audio playback backend unavailable: %s", _exc)
    _HAS_BACKEND = False
    _sd = None

# A daemon thread keeps the pydub/sounddevice work off the Tk main thread.
_play_lock = threading.Lock()
_play_thread: threading.Thread | None = None
_stop_event = threading.Event()

# How long a new play / stop call waits for an in-flight audition to observe
# the stop flag.  The stream loop checks per 0.05 s block, so this is generous.
_PLAY_STOP_TIMEOUT = 1.0


class AudioPlaybackError(AudioSuiteError):
    """Raised when an audio file cannot be prepared or played."""


class AuditionItem:
    """A single before/after audition source — an original or processed file.

    Encapsulates the path plus an optional display label so each DSP tool can
    present the pair cleanly (e.g. "Original", "Result") without coupling the
    playback layer to any particular tool's result model.
    """

    __slots__ = ("path", "label")

    def __init__(self, path: str | Path, label: str = "") -> None:
        self.path = Path(path)
        self.label = label

    def exists(self) -> bool:
        """True if the audio file is present on disk."""
        return self.path.is_file()


def _ensure_wav(source: Path) -> Path:
    """Decode an arbitrary audio file to a temporary WAV readable by the device.

    Raises:
        AudioPlaybackError: If the source is missing or undecodable.
    """
    from pydub import AudioSegment

    if not source.is_file():
        raise AudioPlaybackError(
            f"File not found for playback: {source.name}", context={"path": str(source)}
        )

    try:
        segment = AudioSegment.from_file(str(source))
    except Exception as exc:
        raise AudioPlaybackError(
            f"Could not decode {source.name} for playback.", original=exc
        ) from exc

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        segment.export(str(tmp_path), format="wav")
    except Exception as exc:
        _cleanup(tmp_path)
        raise AudioPlaybackError(
            f"Could not prepare {source.name} for playback.", original=exc
        ) from exc
    return tmp_path


def _cleanup(path: Path | None) -> None:
    """Best-effort removal of a temp WAV file."""
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError as _exc:  # pragma: no cover - non-fatal teardown
        logger.debug("Could not remove temp file %s: %s", path, _exc)


_current_wav: Path | None = None


def _join_play_thread() -> None:
    """Wait briefly for the playback worker to finish (best-effort)."""
    thread = _play_thread
    if thread is None or thread is threading.current_thread():
        return
    if thread.is_alive():
        thread.join(timeout=_PLAY_STOP_TIMEOUT)


def stop_playback() -> None:
    """Stop any in-flight audition and drop the temp WAV.

    Safe to call from any thread; never raises.  Waits briefly for the
    worker to observe the stop flag so audio never outlives the click or
    window that stopped it.
    """
    global _current_wav  # noqa: PLW0603
    _stop_event.set()
    _join_play_thread()
    with _play_lock:
        _cleanup(_current_wav)
        _current_wav = None


@handle_audio_errors(reraise=False, context="audio_playback")
def play_audio(
    source: str | Path,
    device: str | None = None,
    block: bool = False,
) -> bool:
    """Play an audio file (any pydub-supported format) through the default
    sound device.

    Args:
        source: Path to the audio file to play.
        device: Optional sounddevice device name/id to play on.  When omitted
            the default output device is used.
        block:  When True (and ``_HAS_BACKEND``), playback runs synchronously
            on the calling thread instead of spawning a worker.  Purely
            intended for tests; GUI callers should leave it False.

    Returns:
        True if playback was (or will be) attempted; False when the backend is
        unavailable or the file/device raises.
    """
    path = Path(source)
    if not _HAS_BACKEND:
        logger.warning("Audio playback unavailable - sounddevice not installed.")
        return False

    # Interrupt any in-flight audition first: a second Play click must
    # replace the audio, never stack a second stream on top of it.
    global _stop_event, _play_thread  # noqa: PLW0603
    _stop_event.set()
    _join_play_thread()
    _stop_event = threading.Event()

    def _run() -> None:
        global _current_wav  # noqa: PLW0603
        wav_path: Path | None = None
        try:
            wav_path = _ensure_wav(path)
            with _play_lock:
                _cleanup(_current_wav)
                _current_wav = wav_path
            _play_wav(wav_path, device, _stop_event)
        except Exception as exc:
            # A daemon thread's stderr is lost under pythonw, so any failure
            # here would otherwise vanish without a trace.
            mapped = map_to_audio_error(exc)
            logger.error("Audition playback failed: %s", mapped, exc_info=True)
        finally:
            with _play_lock:
                # Only drop our own temp WAV — a previous worker that timed
                # out of the join must not delete the new run's file.
                if wav_path is not None and _current_wav is wav_path:
                    _cleanup(_current_wav)
                    _current_wav = None

    if block:
        _run()
    else:
        _play_thread = threading.Thread(target=_run, daemon=True)
        _play_thread.start()
    return True


def _read_wav(wav_path: Path) -> tuple[npt.NDArray[np.float32], int]:
    """Read a PCM WAV into float32 samples scaled to [-1, 1], always 2-D.

    ``sounddevice`` has no file-reading API (that lives in ``soundfile``),
    so the temp WAV produced by ``_ensure_wav`` is decoded here with the
    stdlib ``wave`` module plus ``numpy``.

    Normalization convention matches ``audio_suite_shared.audio_conversion``
    (canonical float32 [-1, 1] format).  This function reads directly via
    the ``wave`` module for efficiency rather than going through pydub, but
    the resulting scale is identical.

    Args:
        wav_path: Path to a PCM WAV file.

    Returns:
        (samples, sample_rate) where samples has shape (frames, channels).

    Raises:
        AudioPlaybackError: If the WAV uses a sample width we cannot convert
            (only 8/16/32-bit PCM is handled).
    """
    with wave.open(str(wav_path), "rb") as wav:
        channels = wav.getnchannels()
        sample_rate = wav.getframerate()
        width = wav.getsampwidth()
        frames = wav.readframes(wav.getnframes())

    if width == 2:
        data = np.frombuffer(frames, dtype="<i2").astype(np.float32)
        data /= 32768.0
    elif width == 4:
        data = np.frombuffer(frames, dtype="<i4").astype(np.float32)
        data /= 2147483648.0
    elif width == 1:
        data = np.frombuffer(frames, dtype=np.uint8).astype(np.float32)
        data -= 128.0
        data /= 128.0
    else:
        raise AudioPlaybackError(
            f"Cannot play {wav_path.name}: {width * 8}-bit WAV is unsupported.",
            context={"path": str(wav_path), "sample_width": width},
        )
    return data.reshape(-1, channels), sample_rate


def _play_wav(wav_path: Path, device: str | None, stop: threading.Event) -> None:
    """Actually stream a WAV to the sound device, honouring stop."""
    if _sd is None:
        logger.warning("Audio playback unavailable - sounddevice not installed.")
        return

    data, sample_rate = _read_wav(wav_path)
    if data.size == 0:
        return

    # 0.05s block for responsive stopping.
    samples_per_block = int(sample_rate * 0.05)
    with _sd.OutputStream(
        samplerate=sample_rate,
        channels=data.shape[1],
        dtype="float32",
        device=device,
    ) as out:
        for start in range(0, data.shape[0], samples_per_block):
            if stop.is_set():
                break
            out.write(data[start : start + samples_per_block])


def can_audition(source: str | Path) -> bool:
    """Return True if the given file could be played.

    Intended so GUI buttons can expose a stable disabled/enabled state; does
    not attempt to actually decode the file.
    """
    return _HAS_BACKEND and Path(source).is_file()


def playback_status() -> str:
    """Short human-readable status of the playback backend for UI display."""
    if _HAS_BACKEND:
        return "available"
    return "unavailable"


def describe_failure(source: str | Path) -> str:
    """Return a user-facing message describing why playback of *source* failed."""
    path = Path(source)
    if not path.is_file():
        return f"File not found: {path.name}"
    if not _HAS_BACKEND:
        return (
            "Audio playback is not available on this system "
            "(sounddevice could not be initialised)."
        )
    return "This file could not be decoded for playback."


# ── Original snapshots for in-place audition ───────────────────────────────────
# In-place tools (Refinery, Normalizer, Pop & Click, Silence Trimmer) overwrite
# their source files, so the "before" half of an A/B comparison must be captured
# before processing begins.  These helpers byte-copy the candidate file into a
# per-run session folder that is cleared when a new run starts or the app closes.

_snapshot_dir: Path | None = None


def audition_snapshot_dir() -> Path:
    """Return the session-wide snapshot folder, creating it on first use."""
    global _snapshot_dir  # noqa: PLW0603
    if _snapshot_dir is None or not _snapshot_dir.is_dir():
        _snapshot_dir = Path(tempfile.mkdtemp(prefix="audiosuite_audition_"))
    return _snapshot_dir


def clear_snapshots() -> None:
    """Remove the audition snapshot folder (called on run start / app close)."""
    global _snapshot_dir  # noqa: PLW0603
    if _snapshot_dir is not None and _snapshot_dir.is_dir():
        shutil.rmtree(_snapshot_dir, ignore_errors=True)
    _snapshot_dir = None


def create_original_snapshot(
    source: str | Path, extensions: tuple[str, ...]
) -> Path | None:
    """Byte-copy a single audio file as the "before" half of an audition.

    Unlike ``snapshot_first_audio`` this targets an explicit file rather than
    the first match in a directory.  Returns None (and logs) if the file is
    missing, unsupported, or the copy fails.

    Args:
        source:     The audio file to snapshot.
        extensions: Tuple of supported extensions.

    Returns:
        Path to the snapshot, or None.
    """
    path = Path(source)
    if not path.is_file() or path.suffix.lower() not in extensions:
        return None
    try:
        dest = audition_snapshot_dir() / f"{path.stem}_orig{path.suffix}"
        shutil.copy2(path, dest)
        return dest
    except OSError as _exc:  # pragma: no cover - defensive
        logger.debug("Could not snapshot original for audition: %s", _exc)
        return None


def snapshot_first_audio(
    source: str | Path, extensions: tuple[str, ...]
) -> Path | None:
    """Byte-copy the first supported audio file under *source* for audition.

    *source* may be a single audio file or a directory tree.  The copy lands
    in the session snapshot folder and keeps the original extension so the
    playback layer can decode it later.

    Args:
        source:     An audio file or a directory to scan.
        extensions: Tuple of supported extensions (e.g. ``SUPPORTED_EXTENSIONS``).

    Returns:
        Path to the snapshot if one was taken, else None (no audio found or
        the copy failed).
    """
    path = Path(source)
    if path.is_file():
        return create_original_snapshot(path, extensions)
    try:
        target = _pick_source(path, extensions)
        if target is None:
            return None
        dest = audition_snapshot_dir() / f"{target.stem}_orig{target.suffix}"
        shutil.copy2(target, dest)
        return dest
    except OSError as _exc:  # pragma: no cover - defensive
        logger.debug("Could not snapshot original for audition: %s", _exc)
        return None


def _pick_source(source: Path, extensions: tuple[str, ...]) -> Path | None:
    """Resolve a single playable file from *source* (file or directory)."""
    if source.is_file():
        return source if source.suffix.lower() in extensions else None
    if source.is_dir():
        for file_path in sorted(source.iterdir()):
            if file_path.is_file() and file_path.suffix.lower() in extensions:
                return file_path
    return None


def peek_first_audio(source: str | Path, extensions: tuple[str, ...]) -> Path | None:
    """Return the first supported audio file under *source*, without copying.

    This is the path ``snapshot_first_audio`` snapshots; callers that need to
    pair a snapshot with its on-disk original use this to learn the original.

    Args:
        source:     An audio file or a directory tree.
        extensions: Tuple of supported extensions (e.g. ``SUPPORTED_EXTENSIONS``).

    Returns:
        The first matching file path, or None if none is found.
    """
    return _pick_source(Path(source), extensions)


__all__ = [
    "AuditionItem",
    "AudioPlaybackError",
    "audition_snapshot_dir",
    "can_audition",
    "clear_snapshots",
    "create_original_snapshot",
    "describe_failure",
    "peek_first_audio",
    "play_audio",
    "playback_status",
    "snapshot_first_audio",
    "stop_playback",
]
