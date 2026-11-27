"""Locks for the render worker's failure isolation (F-M1 order #2).

The reason rendering moved out of process is that a third-party plugin is the
one thing in the suite that can kill its host.  So the locks here are about the
parent surviving: a bundle that refuses to load fails *its* file and names the
plugin, a worker that overruns its wall clock is stopped, a worker that dies
without a status line becomes a crash outcome, and the batch carries on to the
next file.

A stub worker module supplies the paths a real bundle cannot be made to take on
demand (a hang, an abort), which is the plan's "a deliberately crashing stub
worker" clause.  The stub is named through ``render_file``'s documented
``worker=`` seam; the shipped default is the real worker module and no preset
can change it.

Changed in 3.0.0: new file — the crash, timeout and batch-continuation locks.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from pedalboard.io import AudioFile

from audio_suite_shared.plugin_host.chain import PluginChain, PluginSlot
from audio_suite_shared.plugin_host.runner import (
    DEFAULT_TIMEOUT_SECONDS,
    RenderOutcome,
    render_file,
    render_files,
)

SAMPLE_RATE = 48_000

SLOW_WORKER = "tests.slow_worker_stub"
ABORTING_WORKER = "tests.aborting_worker_stub"


def _tone(frames: int = 480) -> np.ndarray:
    """Return a deterministic stereo float32 buffer.

    Parameters
    ----------
    frames : int
        Frames per channel.

    Returns
    -------
    np.ndarray
        Shape ``(2, frames)``.
    """
    ticks = np.arange(frames * 2, dtype=np.float32)
    return ((ticks % 8 - 4) / 4.0).reshape(2, frames).astype(np.float32)


def _write_audio(path: Path, audio: np.ndarray) -> None:
    """Write a 32-bit float WAV fixture.

    Parameters
    ----------
    path : Path
        Destination file.
    audio : np.ndarray
        ``(channels, frames)`` buffer.
    """
    with AudioFile(str(path), "w", SAMPLE_RATE, audio.shape[0], bit_depth=32) as sink:
        sink.write(audio)


def _bundle(root: Path, name: str) -> Path:
    """Create a VST3 bundle directory holding one dummy file.

    Parameters
    ----------
    root : Path
        Folder the bundle lives in.
    name : str
        Bundle name, without the suffix.

    Returns
    -------
    Path
        The bundle path.
    """
    bundle = root / f"{name}.vst3"
    bundle.mkdir()
    (bundle / "Contents").write_bytes(b"stub")
    return bundle


def _active_chain(path: Path) -> PluginChain:
    """Return a chain applying one slot.

    Parameters
    ----------
    path : Path
        The bundle the slot names.

    Returns
    -------
    PluginChain
        A one-slot chain whose slot is not bypassed.
    """
    return PluginChain((PluginSlot(str(path)),))


class TestPluginFailure:
    """A bundle that cannot be loaded is a failed file, not a failed run."""

    def test_a_bundle_that_refuses_to_load_fails_its_file_and_names_the_plugin(
        self, tmp_path: Path
    ) -> None:
        """The child's structured error becomes one outcome naming the plugin."""
        source = tmp_path / "source.wav"
        destination = tmp_path / "rendered.wav"
        _write_audio(source, _tone())
        bundle = _bundle(tmp_path, "Broken")

        outcome = render_file(_active_chain(bundle), source, destination)

        assert not outcome.ok
        assert outcome.status == "failed"
        assert outcome.plugin == "Broken"
        assert "Broken" in outcome.reason
        assert str(bundle) not in outcome.reason
        assert not destination.exists()

    def test_the_batch_continues_after_one_file_fails(self, tmp_path: Path) -> None:
        """One bad file costs one outcome; the rest still render."""
        chain = PluginChain()
        good_one = tmp_path / "one.wav"
        good_two = tmp_path / "two.wav"
        _write_audio(good_one, _tone())
        _write_audio(good_two, _tone())
        jobs = (
            (good_one, tmp_path / "one.out.wav"),
            (tmp_path / "missing.wav", tmp_path / "missing.out.wav"),
            (good_two, tmp_path / "two.out.wav"),
        )

        outcomes = render_files(chain, jobs)

        assert [outcome.status for outcome in outcomes] == [
            "rendered",
            "failed",
            "rendered",
        ]
        assert outcomes[1].ok is False
        assert "missing.wav" in outcomes[1].reason
        assert (tmp_path / "one.out.wav").is_file()
        assert (tmp_path / "two.out.wav").is_file()


class TestStuckWorker:
    """A worker that hangs or dies is contained by the parent."""

    def test_a_worker_that_overruns_its_timeout_is_stopped_and_reported(
        self, tmp_path: Path
    ) -> None:
        """The per-file wall clock turns a hang into a failed file."""
        source = tmp_path / "source.wav"
        _write_audio(source, _tone())

        outcome = render_file(
            PluginChain(),
            source,
            tmp_path / "rendered.wav",
            timeout=1,
            worker=SLOW_WORKER,
        )

        assert not outcome.ok
        assert outcome.status == "failed"
        assert "did not finish within 1 s" in outcome.reason

    def test_a_worker_that_dies_without_a_status_line_is_a_crash(
        self, tmp_path: Path
    ) -> None:
        """An aborting child is an outcome, never an exception in the parent."""
        source = tmp_path / "source.wav"
        _write_audio(source, _tone())

        outcome = render_file(
            PluginChain(),
            source,
            tmp_path / "rendered.wav",
            worker=ABORTING_WORKER,
        )

        assert not outcome.ok
        assert outcome.status == "failed"
        assert "stopped unexpectedly" in outcome.reason
        assert outcome.exit_code not in (0, None)

    def test_a_failed_render_leaves_no_request_file_behind(
        self, tmp_path: Path
    ) -> None:
        """The request is scratch state, removed however the child ends."""
        source = tmp_path / "source.wav"
        _write_audio(source, _tone())

        render_file(
            PluginChain(),
            source,
            tmp_path / "rendered.wav",
            worker=ABORTING_WORKER,
        )

        assert list(tmp_path.glob("*.request.json")) == []

    def test_the_outcome_never_carries_a_plugin_path(self, tmp_path: Path) -> None:
        """An outcome travels into reports, so it names plugins, not folders."""
        source = tmp_path / "source.wav"
        _write_audio(source, _tone())
        bundle = _bundle(tmp_path, "Broken")

        outcome = render_file(_active_chain(bundle), source, tmp_path / "rendered.wav")

        assert isinstance(outcome, RenderOutcome)
        assert str(bundle) not in outcome.reason
        assert "C:" not in outcome.reason and "/" not in outcome.reason
        assert outcome.plugin == "Broken"


class TestHonestOutcome:
    """The runner says what happened, and says nothing it did not observe."""

    def test_the_default_timeout_is_the_plan_value(self) -> None:
        """The per-file wall clock is one declared number."""
        assert DEFAULT_TIMEOUT_SECONDS == 120

    def test_a_successful_render_reports_the_output_path(self, tmp_path: Path) -> None:
        """A rendered file names both sides it wrote and read."""
        source = tmp_path / "source.wav"
        destination = tmp_path / "rendered.wav"
        _write_audio(source, _tone())

        outcome = render_file(PluginChain(), source, destination)

        assert outcome.ok
        assert outcome.status == "rendered"
        assert outcome.output_path == str(destination)
        assert outcome.input_path == str(source)
        assert outcome.reason == ""
