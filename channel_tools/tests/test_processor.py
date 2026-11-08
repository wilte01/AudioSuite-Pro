"""The channel batch, measured on the files it writes.

Every assertion reads the audio back from disk (or the source's own bytes): a
dry run must leave the file untouched, a live run must decode to the layout the
rule promises, and a rule that changes nothing must not rewrite the file.

Changed in 2.5.0: new file (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E6).
"""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydub import AudioSegment
from pydub.generators import Sine

from audio_suite_shared import channel_ops
from audio_suite_shared.audio_conversion import (
    measure_rms_db,
    pack_24bit,
    segment_to_numpy,
)
from audio_suite_shared.audio_formats import source_bit_depth
from channel_tools.core.models import ChannelSettings
from channel_tools.core.processor import REPORT_NAMES, run_channels

MS = 200


def _stereo_wav(path: Path, *, sample_width: int = 2) -> Path:
    """Write a 440 Hz left / 220 Hz right WAV at the given sample width."""
    left = Sine(440).to_audio_segment(duration=MS, volume=-10)
    right = Sine(220).to_audio_segment(duration=MS, volume=-10)
    segment = AudioSegment.from_mono_audiosegments(left, right)
    if segment.sample_width != sample_width:
        segment = segment.set_sample_width(sample_width)
    segment.export(str(path), format="wav")
    return path


def _wav24(path: Path) -> Path:
    """Write a real 24-bit stereo WAV, the depth-preservation case.

    pydub's own export path promotes a 3-byte segment, so the file is written
    with the stdlib writer and the shared 24-bit packer instead.
    """
    frames = 4_410
    t = np.arange(frames) / 8_000
    left = np.round(0.4 * np.sin(2.0 * np.pi * 440.0 * t) * (2**23 - 1)).astype(
        np.int32
    )
    right = np.round(0.4 * np.sin(2.0 * np.pi * 220.0 * t) * (2**23 - 1)).astype(
        np.int32
    )
    interleaved = np.empty(frames * 2, dtype=np.int32)
    interleaved[0::2] = left
    interleaved[1::2] = right
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(3)
        handle.setframerate(8_000)
        handle.writeframes(pack_24bit(interleaved))
    return path


def _mono_wav(path: Path) -> Path:
    """Write a mono WAV, the case a mono rule has nothing to change."""
    Sine(440).to_audio_segment(duration=MS, volume=-10).set_channels(1).export(
        str(path), format="wav"
    )
    return path


def _run(
    folder: Path,
    settings: ChannelSettings,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    """Run the batch and return the completion payload it published."""
    payload: dict[str, Any] = {}

    def complete(**kwargs: Any) -> None:
        payload.update(kwargs)

    run_channels(
        str(folder),
        settings=settings,
        dry_run=dry_run,
        on_complete=complete,
    )
    return payload


class TestDryRun:
    """A dry run reports the rule and writes no audio."""

    def test_the_source_bytes_are_untouched(self, tmp_path: Path) -> None:
        source = _stereo_wav(tmp_path / "song.wav")
        before = source.read_bytes()
        payload = _run(
            tmp_path, ChannelSettings(operation=channel_ops.MONO_MEAN), dry_run=True
        )
        assert source.read_bytes() == before
        assert payload["succeeded"] == 1
        assert payload["skipped"] == 0

    def test_the_dry_report_is_written_and_names_the_rule(self, tmp_path: Path) -> None:
        _stereo_wav(tmp_path / "song.wav")
        payload = _run(
            tmp_path, ChannelSettings(operation=channel_ops.MONO_MEAN), dry_run=True
        )
        report = tmp_path / REPORT_NAMES[True]
        text = report.read_text(encoding="utf-8")
        assert text.startswith("CHANNEL TOOLS REPORT")
        assert "Mode: DRY RUN" in text
        assert "Mono, arithmetic mean (0.5 x (L + R))" in text
        assert "SUMMARY:" in text
        assert payload["report"] == str(report)


class TestLiveRun:
    """A live run writes the layout its rule promised."""

    def test_mono_downmix_decodes_as_one_channel_at_the_mean_level(
        self, tmp_path: Path
    ) -> None:
        source = _stereo_wav(tmp_path / "song.wav")
        original, _ = segment_to_numpy(AudioSegment.from_file(str(source)))
        expected = measure_rms_db(0.5 * (original[0] + original[1]))
        payload = _run(
            tmp_path, ChannelSettings(operation=channel_ops.MONO_MEAN), dry_run=False
        )
        written = AudioSegment.from_file(str(source))
        assert written.channels == 1
        decoded, _ = segment_to_numpy(written)
        assert decoded.shape[0] == 1
        assert measure_rms_db(decoded) == pytest.approx(expected, abs=0.05)
        assert payload["succeeded"] == 1
        assert "LIVE UPDATE" in (tmp_path / REPORT_NAMES[False]).read_text(
            encoding="utf-8"
        )

    def test_a_24_bit_source_keeps_its_depth(self, tmp_path: Path) -> None:
        # pydub decodes 24-bit PCM into a 4-byte container, so the depth is
        # measured on the file itself (the probe the workflow pins exports
        # with), not on the decoder's sample_width.
        source = _wav24(tmp_path / "hires.wav")
        assert source_bit_depth(str(source)) == 24
        _run(
            tmp_path,
            ChannelSettings(operation=channel_ops.INVERT_PHASE, invert_target="both"),
            dry_run=False,
        )
        assert source_bit_depth(str(source)) == 24

    def test_a_rule_that_changes_nothing_does_not_rewrite_the_file(
        self, tmp_path: Path
    ) -> None:
        source = _mono_wav(tmp_path / "mono.wav")
        before = source.read_bytes()
        payload = _run(
            tmp_path, ChannelSettings(operation=channel_ops.MONO_MEAN), dry_run=False
        )
        assert source.read_bytes() == before
        assert payload["succeeded"] == 0
        assert payload["skipped"] == 1

    def test_unity_width_leaves_a_stereo_file_alone(self, tmp_path: Path) -> None:
        source = _stereo_wav(tmp_path / "song.wav")
        before = source.read_bytes()
        payload = _run(
            tmp_path,
            ChannelSettings(operation=channel_ops.STEREO_WIDTH, width_percent=100.0),
            dry_run=False,
        )
        assert source.read_bytes() == before
        assert payload["skipped"] == 1
