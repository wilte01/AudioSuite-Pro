"""F-10 — no audio writer may leave the output format to a default.

Every writer in the suite that re-encodes audio is listed in ``WRITER_ROWS``
with the test that covers it. Each test writes a real file from a source whose
rate, channel count and (where the container has one) bit depth are deliberately
*not* the values an encoder would otherwise pick, then **decodes the result**
and compares all three with the source. A writer that silently resamples, mixes
to stereo or narrows the bit depth fails.

Why decoded format: ``audio_normalizer`` handed its output parameters to
FFmpeg's defaults, so every normalised file was resampled to ``loudnorm``'s
192 kHz and 16-bit became 24-bit; the stage's own test measured loudness only
and passed for a release. The shared pydub export did the same in the other
direction: FFmpeg's WAV/AIFF muxers write 16-bit PCM by default, so a 24-bit
source came back as 16-bit. Reading a field the writer just set cannot detect
either defect (``AGENTS.md``, *Defects and failing checks*).

The lock proves it can fail: ``test_the_lock_detects_the_missing_rate_pin``
reverts the normalise pin in-process and asserts the decoded rate really is
192 kHz, so the unchanged-rate assertion above is load-bearing rather than
decorative.

Fixtures are 32 kHz, mono and 24-bit wherever the format stores a depth: none
of those is an encoder default, so a writer cannot pass by agreeing with one.

Changed in 2.1.7: initial version, adopting F-10 from the functional backlog and
finding the shared pydub exporter's 24-bit-to-16-bit loss.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path
from queue import Queue
from typing import Any

import mutagen
import numpy as np
import pytest
from pydub import AudioSegment

pytestmark = pytest.mark.integration

FIXTURE_RATE = 32000
FIXTURE_CHANNELS = 1
FIXTURE_SECONDS = 2.0
FIXTURE_FREQ = 440.0
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"


# ── Writer list (pinned) ──────────────────────────────────────────────────────
#
#: Writer row -> the test that certifies it. Every row of the plan's table is
#: here, and ``test_every_writer_row_has_a_test`` fails if a row is added or
#: removed without its test. A writer whose output legitimately differs states
#: the difference and its reason in the value.
WRITER_ROWS: dict[str, str] = {
    "audio_normalizer.core.normalizer": (
        "TestAudioNormalizerFormat.test_normalise_keeps_rate_channels_and_depth"
    ),
    "audio_enhancer.core.ffmpeg_io.write_audio": (
        "TestAudioEnhancerFormat.test_enhancer_keeps_rate_and_channels"
    ),
    "audio_suite_shared.cue_split.split_cue_file": (
        "TestCueSplitFormat.test_cue_split_keeps_rate"
    ),
    "audio_suite_shared.audio_conversion.numpy_to_segment": (
        "TestAudioConversionFormat.test_conversion_round_trip_keeps_segment_format"
    ),
    "pop_click_remover.core.declicker.declick_audio": (
        "TestPopClickFormat.test_declick_keeps_rate_channels_and_depth"
    ),
    "noise_reduction.core.noise_reducer.reduce_noise": (
        "TestNoiseReductionFormat.test_noise_reduction_keeps_rate_channels_and_depth"
    ),
    "audio_refinery.core.pipeline._write_output": (
        "TestAudioRefineryFormat.test_refinery_export_keeps_rate_channels_and_depth"
    ),
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _write_sine(
    path: Path,
    *,
    codec: str = "pcm_s24le",
    sample_fmt: str | None = None,
    channels: int = FIXTURE_CHANNELS,
    seconds: float = FIXTURE_SECONDS,
) -> Path:
    """Write a real sine-wave fixture through FFmpeg.

    Args:
        path: Destination path; its extension selects the muxer.
        codec: FFmpeg audio codec for the fixture.
        sample_fmt: Optional ``-sample_fmt`` override (FLAC's 24-bit path).
        channels: Channel count for the fixture.
        seconds: Fixture duration.

    Returns:
        The written path.
    """
    args = [
        FFMPEG,
        "-y",
        "-hide_banner",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={FIXTURE_FREQ}:sample_rate={FIXTURE_RATE}:duration={seconds}",
        "-ac",
        str(channels),
        "-c:a",
        codec,
    ]
    if sample_fmt is not None:
        args += ["-sample_fmt", sample_fmt]
    args.append(str(path))
    subprocess.run(args, check=True, capture_output=True)
    return path


def _format_of(path: Path) -> tuple[int, int, int | None]:
    """Decode *path*'s stream format with mutagen.

    Args:
        path: Audio file to inspect.

    Returns:
        ``(sample_rate, channels, bits_per_sample or None)``. Lossy formats do
        not declare a depth, so that element is ``None`` for them.
    """
    audio = mutagen.File(str(path))
    assert audio is not None, f"mutagen could not open {path}"
    info = audio.info
    return (
        int(info.sample_rate),
        int(info.channels),
        getattr(info, "bits_per_sample", None),
    )


def _slot_fixtures() -> tuple[list[Any], Queue[int]]:
    """Return the per-worker slot variables and queue the workflow expects."""
    slots: list[Any] = [type("Slot", (), {"set": staticmethod(lambda _v: None)})()]
    queue: Queue[int] = Queue()
    queue.put(0)
    return slots, queue


def _decoded_segment(path: Path) -> AudioSegment:
    """Decode *path* to a pydub segment (used for click/noise fixture work)."""
    return AudioSegment.from_file(str(path))


# ── The pinned row list ───────────────────────────────────────────────────────


def _resolve_test_name(dotted: str) -> Any:
    """Resolve ``"ClassName.method"`` in this module.

    Args:
        dotted: Class and method name separated by a dot.

    Returns:
        The attribute, or ``None`` when either part is absent.
    """
    class_name, _sep, method_name = dotted.partition(".")
    owner = globals().get(class_name)
    return getattr(owner, method_name, None) if owner is not None else None


class TestWriterRowCoverage:
    def test_every_writer_row_has_a_test(self) -> None:
        """The writer list is pinned and every entry names a real test."""
        assert WRITER_ROWS, "the writer table must not be empty"
        assert len(WRITER_ROWS) == 7
        missing = [
            row
            for row, test_name in WRITER_ROWS.items()
            if not callable(_resolve_test_name(test_name))
        ]
        assert not missing, f"writer rows without a test: {missing}"

    def test_every_writer_test_declares_its_row(self) -> None:
        """Every writer-format test is named by the pinned table."""
        mapped = set(WRITER_ROWS.values())
        declared = {
            f"{cls.__name__}.{name}"
            for cls_name, cls in globals().items()
            if cls_name.startswith("Test")
            and isinstance(cls, type)
            and cls_name != "TestWriterRowCoverage"
            for name in dir(cls)
            if name.startswith("test_") and ("keeps" in name or "round_trip" in name)
        }
        assert declared == mapped, (
            "a writer test is not registered in WRITER_ROWS "
            f"(unregistered: {sorted(declared - mapped)}, "
            f"stale: {sorted(mapped - declared)})"
        )


# ── audio_normalizer ──────────────────────────────────────────────────────────


class TestAudioNormalizerFormat:
    def test_normalise_keeps_rate_channels_and_depth(self, tmp_path: Path) -> None:
        """Normalising a 32 kHz mono 24-bit FLAC must not change its format."""
        from audio_normalizer.core.loudness import measure
        from audio_normalizer.core.normalizer import apply

        source = _write_sine(
            tmp_path / "normalise.flac", codec="flac", sample_fmt="s32"
        )
        assert _format_of(source) == (FIXTURE_RATE, 1, 24)

        loudness = measure(str(source), -16.0)
        assert loudness is not None
        apply(str(source), -16.0, loudness)

        assert _format_of(source) == (FIXTURE_RATE, 1, 24)

        achieved = measure(str(source), -16.0)
        assert achieved is not None
        assert achieved["input_i"] == pytest.approx(-16.0, abs=1.5)

    def test_the_lock_detects_the_missing_rate_pin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With the pin reverted, the decoded rate is 192 kHz.

        This is the harness's own failure check: the assertion in the test
        above would catch a writer that lost the pin, so the lock is not
        vacuously green.
        """
        from audio_normalizer.core import normalizer
        from audio_normalizer.core.loudness import measure

        source = _write_sine(tmp_path / "unpinned.flac", codec="flac", sample_fmt="s32")
        monkeypatch.setattr(normalizer, "_preserve_args", lambda *a, **k: [])

        loudness = measure(str(source), -16.0)
        assert loudness is not None
        normalizer.apply(str(source), -16.0, loudness)

        rate, channels, bits = _format_of(source)
        assert rate == 192000, "the fixture no longer exercises the rate pin"
        assert channels == 1
        assert bits == 24
        assert (rate, channels, bits) != (FIXTURE_RATE, 1, 24)


# ── audio_enhancer ────────────────────────────────────────────────────────────


class TestAudioEnhancerFormat:
    def test_enhancer_keeps_rate_and_channels(self, tmp_path: Path) -> None:
        """The enhancer's AAC writer keeps 32 kHz mono (AAC has no bit depth)."""
        from audio_enhancer.core.ffmpeg_io import write_audio

        frames = int(FIXTURE_RATE * FIXTURE_SECONDS)
        t = np.arange(frames) / FIXTURE_RATE
        audio = (0.4 * np.sin(2 * np.pi * FIXTURE_FREQ * t)).astype(np.float32)
        output = tmp_path / "enhancer.m4a"

        write_audio(audio.reshape(1, -1), FIXTURE_RATE, output)

        rate, channels, bits = _format_of(output)
        assert (rate, channels) == (FIXTURE_RATE, 1)
        # AAC has no source bit depth: 16 is the codec's own, so only rate and
        # channels are comparable with the input here (the plan's "reason the
        # format intentionally differs" for a lossy row).
        assert bits == 16
        decoded = _decoded_segment(output)
        assert decoded.rms > 0


# ── audio_suite_shared.cue_split ──────────────────────────────────────────────


class TestCueSplitFormat:
    def test_cue_split_keeps_rate(self, tmp_path: Path) -> None:
        """``-c copy`` must not resample or remix the image it cuts."""
        from audio_suite_shared.cue_split import split_cue_file

        image = _write_sine(tmp_path / "image.wav")
        assert _format_of(image) == (FIXTURE_RATE, 1, 24)
        cue = tmp_path / "album.cue"
        cue.write_text(
            'FILE "image.wav" WAVE\n'
            "  TRACK 01 AUDIO\n"
            '    TITLE "One"\n'
            "    INDEX 01 00:00:00\n"
            "  TRACK 02 AUDIO\n"
            '    TITLE "Two"\n'
            "    INDEX 01 00:01:00\n",
            encoding="utf-8",
        )
        out_dir = tmp_path / "split"

        written = split_cue_file(cue, out_dir, ffmpeg=FFMPEG)

        assert len(written) == 2
        for path in map(Path, written):
            assert _format_of(path) == (FIXTURE_RATE, 1, 24)


# ── audio_suite_shared.audio_conversion ───────────────────────────────────────


class TestAudioConversionFormat:
    def test_conversion_round_trip_keeps_segment_format(self, tmp_path: Path) -> None:
        """The NumPy round trip carries the segment's rate, channels and width.

        The helper takes ``sample_width`` explicitly and never chooses one, so
        this fixture is 16-bit: the decoded file then tells the same story as
        the segment (``8 * sample_width``) instead of pydub's 4-byte container
        for 24-bit PCM, which would look like a depth change the helper did not
        make.
        """
        from audio_suite_shared.audio_conversion import (
            numpy_to_segment,
            segment_to_numpy,
        )

        source = _write_sine(tmp_path / "source.wav", codec="pcm_s16le")
        assert _format_of(source) == (FIXTURE_RATE, 1, 16)
        segment = _decoded_segment(source)

        frames, rate = segment_to_numpy(segment)
        rebuilt = numpy_to_segment(
            frames, rate, sample_width=segment.sample_width, num_channels=1
        )
        output = tmp_path / "rebuilt.wav"
        rebuilt.export(str(output), format="wav")

        assert _format_of(output) == (
            FIXTURE_RATE,
            1,
            8 * rebuilt.sample_width,
        )


# ── pop_click_remover ─────────────────────────────────────────────────────────


class TestPopClickFormat:
    def test_declick_keeps_rate_channels_and_depth(self, tmp_path: Path) -> None:
        """A live declick write keeps a 32 kHz mono 24-bit WAV's format."""
        from pop_click_remover.core.file_processor import process_single_file

        source = _write_sine(tmp_path / "clicky.wav")
        segment = _decoded_segment(source)
        samples = np.frombuffer(segment.raw_data, dtype=np.int32).copy()
        samples[len(samples) // 2] = 2**30
        segment._spawn(samples.tobytes()).export(
            str(source), format="wav", parameters=["-c:a", "pcm_s24le"]
        )
        assert _format_of(source) == (FIXTURE_RATE, 1, 24)
        temp_dir = tmp_path / "tmp"
        temp_dir.mkdir()
        slots, queue = _slot_fixtures()
        records: list[tuple[str, str, str]] = []

        process_single_file(
            name=source.name,
            dir_path=str(tmp_path),
            is_dry_run=False,
            sensitivity=0.05,
            max_width=2,
            temp_dir=str(temp_dir),
            slot_vars=slots,
            slot_queue=queue,
            lock=threading.Lock(),
            on_progress=lambda **kw: records.append(
                (kw["status"], kw["display_text"], kw["log_text"])
            ),
        )

        assert [status for status, _text, _log in records] == ["FIXED"], records
        assert _format_of(source) == (FIXTURE_RATE, 1, 24)


# ── noise_reduction ───────────────────────────────────────────────────────────


class TestNoiseReductionFormat:
    def test_noise_reduction_keeps_rate_channels_and_depth(
        self, tmp_path: Path
    ) -> None:
        """A live hum removal keeps a 32 kHz mono 24-bit WAV's format."""
        from noise_reduction.core.file_processor import process_single_file
        from noise_reduction.core.models import NoiseReductionParams

        # A 60 Hz-dominated signal guarantees the hum notch changes the audio,
        # so the live write path (not the SKIP branch) is what this locks.
        t = np.arange(int(FIXTURE_RATE * FIXTURE_SECONDS)) / FIXTURE_RATE
        hum = (0.4 * np.sin(2 * np.pi * 60 * t) * (2**23 - 1)).astype(np.int32)
        source = tmp_path / "hum.wav"
        AudioSegment(
            hum.tobytes(), frame_rate=FIXTURE_RATE, sample_width=4, channels=1
        ).export(str(source), format="wav", parameters=["-c:a", "pcm_s24le"])
        assert _format_of(source) == (FIXTURE_RATE, 1, 24)
        temp_dir = tmp_path / "tmp"
        temp_dir.mkdir()
        slots, queue = _slot_fixtures()
        records: list[tuple[str, str, str]] = []

        process_single_file(
            name=source.name,
            dir_path=str(tmp_path),
            params=NoiseReductionParams(
                reduce_hum=True, hum_frequency=60, hum_harmonics=3
            ),
            temp_dir=str(temp_dir),
            slot_vars=slots,
            slot_queue=queue,
            lock=threading.Lock(),
            on_progress=lambda **kw: records.append(
                (kw["status"], kw["display_text"], kw["log_text"])
            ),
        )

        assert [status for status, _text, _log in records] == ["FIXED"], records
        assert _format_of(source) == (FIXTURE_RATE, 1, 24)


# ── audio_refinery ────────────────────────────────────────────────────────────


class TestAudioRefineryFormat:
    def test_refinery_export_keeps_rate_channels_and_depth(
        self, tmp_path: Path
    ) -> None:
        """The Refinery's pydub export keeps a 24-bit source at 24 bits."""
        from audio_refinery.core.pipeline import _write_output

        source = _write_sine(tmp_path / "master.wav")
        assert _format_of(source) == (FIXTURE_RATE, 1, 24)
        audio = _decoded_segment(source)
        output = tmp_path / "rendered.wav"

        _write_output(audio, output, source, ".wav", lambda *_a, **_k: None)

        assert _format_of(output) == (FIXTURE_RATE, 1, 24)
