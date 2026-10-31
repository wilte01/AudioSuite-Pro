"""Shared fixtures for the duplicate finder suite.

The fixture set is small on purpose, and every file in it exists to test one
decision the tool makes (``PLAN_functional_backlog.md`` F-02):

===============  =========================================================
``song.flac``    lossless flagship of one recording -- the keeper
``song_96/128/320.mp3``
                 the same recording at three bitrates -- must join the FLAC
``take2.mp3``    a different recording of exactly the same length, so the
                 duration guard cannot separate it and only the fingerprint can
``shared_a.mp3`` / ``shared_b.mp3``
                 two different arrangements that begin with the *same* ten
                 seconds, so they share a fingerprint prefix without being the
                 same recording
===============  =========================================================

The recorded distances (``duplicate_finder/tests/test_clustering.py``) are
0.0000-0.0002 inside the group and 0.1580 for the nearest pair that must stay
apart, which is what makes ``DEFAULT_THRESHOLD = 0.10`` a measurement rather
than a guess.

Changed in 2.3.0: new duplicate-detection tool (backlog F-02): fingerprint distance,
clustering, cache and quarantine.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pytest
from pydub import AudioSegment

#: Every generated fixture is 44.1 kHz stereo, the suite's own export default.
SR = 44100

#: The files :func:`build_fixture_library` writes, in the order it writes them.
FIXTURE_FILES = (
    "song.flac",
    "song_96.mp3",
    "song_128.mp3",
    "song_320.mp3",
    "take2.mp3",
    "shared_a.mp3",
    "shared_b.mp3",
)

#: The one recording's four encodings, as the run must group them.
SONG_ENCODINGS = ("song.flac", "song_96.mp3", "song_128.mp3", "song_320.mp3")

A_CHORDS = [[220.0, 277.18, 329.63], [246.94, 311.13, 369.99], [196.0, 246.94, 293.66]]
B_CHORDS = [[261.63, 329.63, 392.0], [293.66, 369.99, 440.0], [349.23, 440.0, 523.25]]
#: The shared introduction both ``shared_*`` fixtures open with.
INTRO_CHORDS = [[174.61, 220.0, 261.63], [196.0, 246.94, 293.66]]


def _note(freq: float, seconds: float, amp: float = 0.5) -> np.ndarray:
    """Return one plucked note at *freq*.

    Args:
        freq: Fundamental frequency in Hz.
        seconds: Note length.
        amp: Peak amplitude.

    Returns:
        The mono waveform.
    """
    t = np.arange(int(SR * seconds)) / SR
    env = np.minimum(1.0, t * 40) * np.exp(-t * 2.2)
    return amp * env * np.sin(2 * np.pi * freq * t)


def _melody(freqs: list[float], note_s: float = 0.25) -> np.ndarray:
    """Return a sequence of notes as one waveform.

    Args:
        freqs: Note frequencies, in order.
        note_s: Length of each note.

    Returns:
        The mono waveform.
    """
    return np.concatenate([_note(f, note_s) for f in freqs])


def _song(seed: int, chords: list[list[float]], repeats: int) -> np.ndarray:
    """Return an arpeggiated chord progression, repeated.

    Args:
        seed: Seeds the small per-repeat gain drift that keeps two repeats from
            being bit-identical.
        chords: Chord tones, one list per chord.
        repeats: How many times the progression repeats.

    Returns:
        The mono waveform.
    """
    rng = np.random.default_rng(seed)
    block = []
    for chord in chords:
        for freq in chord:
            block.append(_melody([freq, freq * 1.5, freq * 2.0], 0.2))
    body = np.concatenate(block)
    return np.concatenate(
        [body * (1.0 + 0.002 * rng.random() * i) for i in range(repeats)]
    )


def _write_wav(path: Path, mono: np.ndarray) -> Path:
    """Write *mono* as a stereo 16-bit WAV at *path*.

    Args:
        path: Destination path.
        mono: The waveform.

    Returns:
        *path*.
    """
    ints = (np.clip(mono, -1.0, 1.0) * 32767).astype(np.int16)
    seg = AudioSegment(
        data=np.column_stack([ints, ints]).flatten().tobytes(),
        sample_width=2,
        frame_rate=SR,
        channels=2,
    )
    seg.export(str(path), format="wav")
    return path


def build_fixture_library(dest: Path) -> Path:
    """Write the declared fixture set into *dest*.

    Args:
        dest: Directory to create the files in; must exist.

    Returns:
        *dest*, for chaining.
    """
    work = dest / "_masters"
    work.mkdir(parents=True, exist_ok=True)
    master_a = _write_wav(work / "a.wav", _song(1, A_CHORDS, 4))
    master_b = _write_wav(work / "b.wav", _song(2, B_CHORDS, 4))

    AudioSegment.from_wav(str(master_a)).export(str(dest / "song.flac"), format="flac")
    for kbps in (96, 128, 320):
        AudioSegment.from_wav(str(master_a)).export(
            str(dest / f"song_{kbps}.mp3"), format="mp3", bitrate=f"{kbps}k"
        )
    AudioSegment.from_wav(str(master_b)).export(
        str(dest / "take2.mp3"), format="mp3", bitrate="192k"
    )

    intro = _song(7, INTRO_CHORDS, 2)
    for name, chords, seed in (
        ("shared_a.mp3", A_CHORDS, 3),
        ("shared_b.mp3", B_CHORDS, 4),
    ):
        master = _write_wav(
            work / f"{name}.wav", np.concatenate([intro, _song(seed, chords, 2)])
        )
        AudioSegment.from_wav(str(master)).export(
            str(dest / name), format="mp3", bitrate="192k"
        )
    shutil.rmtree(work)
    return dest


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the fingerprint cache at *tmp_path*, never the user's home.

    ``default_cache_path()`` honours ``AUDIOSUITE_DUPLICATE_CACHE`` for exactly
    this reason: a test run must not read or write the developer's real cache.
    """
    monkeypatch.setenv("AUDIOSUITE_DUPLICATE_CACHE", str(tmp_path / "cache.db"))


@pytest.fixture(scope="module")
def fixture_library(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Return the declared fixture set, built once for the module.

    Building it exports eight real encodes, so it is done once and copied per
    test rather than rebuilt per test.
    """
    return build_fixture_library(tmp_path_factory.mktemp("duplicate_fixtures"))


@pytest.fixture()
def library(fixture_library: Path, tmp_path: Path) -> Path:
    """Return a private copy of the fixture set that a test may rearrange."""
    destination = tmp_path / "library"
    destination.mkdir()
    for name in FIXTURE_FILES:
        shutil.copy2(fixture_library / name, destination / name)
    return destination
