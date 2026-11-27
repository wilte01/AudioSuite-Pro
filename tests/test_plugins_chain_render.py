"""Locks for the render layer and the worker's success path (F-M1 order #2).

Order #1 proved a chain excludes bypassed slots from the render list; this file
proves what that buys.  Two properties are measured, not asserted by reading
internal state back:

* **Bypass is bit-transparent.**  A fully bypassed chain hands the caller the
  very array it was given — same object, no copy, no sample touched — and
  through the worker the decoded output equals the decoded input exactly, not
  "within a tolerance".  A tolerance would pass a chain that silently gained a
  sample or dropped one.
* **The render is deterministic.**  Two separate worker processes write
  byte-identical files, so a preset renders the same next week as today.

No real VST3/AU binary is bundled, downloaded or required: the render layer is
driven with fake slot effects, and the worker is driven with chains that load no
plugin at all.  A real bundle's determinism needs a bundle the project may ship,
which it does not have (F-M1 order #2 decision).

Changed in 3.0.0: new file — the render layer and worker success-path locks.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import numpy as np
import pytest
from pedalboard.io import AudioFile

from audio_suite_shared.plugin_host.chain import PluginChain, PluginSlot
from audio_suite_shared.plugin_host.render import (
    PluginRenderError,
    SlotEffect,
    render_buffer,
)
from audio_suite_shared.plugin_host.runner import render_file
from audio_suite_shared.plugin_host.worker import (
    EXIT_OK,
    EXIT_USAGE,
    WorkerRequestError,
    main,
    read_request,
)

SAMPLE_RATE = 48_000


def _tone(frames: int = 600, channels: int = 2) -> np.ndarray:
    """Return a deterministic float32 buffer with exactly representable values.

    Parameters
    ----------
    frames : int
        Frames per channel.
    channels : int
        Channel count.

    Returns
    -------
    np.ndarray
        Shape ``(channels, frames)``, values on an eighth-note grid so a decode
        can only match exactly or fail loudly.
    """
    ticks = np.arange(frames * channels, dtype=np.float32)
    values = (ticks % 16 - 8) / 8.0
    return values.reshape(channels, frames).astype(np.float32)


def _write_audio(path: Path, audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    """Write *audio* as a 32-bit float WAV, the worker's lossless intermediate.

    Parameters
    ----------
    path : Path
        Destination file.
    audio : np.ndarray
        ``(channels, frames)`` float32 buffer.
    sample_rate : int
        Sample rate to write.
    """
    with AudioFile(str(path), "w", sample_rate, audio.shape[0], bit_depth=32) as sink:
        sink.write(audio)


def _read_audio(path: Path) -> np.ndarray:
    """Return a file's decoded float32 buffer.

    Parameters
    ----------
    path : Path
        The file to decode.

    Returns
    -------
    np.ndarray
        ``(channels, frames)`` samples.
    """
    with AudioFile(str(path), "r") as source:
        return source.read(source.frames)


def _bundle(root: Path, name: str) -> Path:
    """Create a VST3 bundle directory holding one dummy binary.

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
    (bundle / "Contents" / "x86_64-win").mkdir(parents=True)
    (bundle / "Contents" / "x86_64-win" / f"{name}.vst3").write_bytes(b"stub")
    return bundle


def _bypassed_chain(*paths: Path) -> PluginChain:
    """Return a chain whose every slot is bypassed.

    Parameters
    ----------
    paths : Path
        Bundle paths the slots name.

    Returns
    -------
    PluginChain
        The chain, ready to render the input unchanged.
    """
    return PluginChain(tuple(PluginSlot(str(path), bypass=True) for path in paths))


def _effect(marker: list[str], name: str, factor: float = 0.5) -> SlotEffect:
    """Return a fake slot effect that records its turn and scales the buffer.

    Parameters
    ----------
    marker : list[str]
        Receives this effect's name when it runs.
    name : str
        This effect's name.
    factor : float
        Gain to apply.

    Returns
    -------
    SlotEffect
        A ``(audio, sample_rate) -> audio`` effect.
    """

    def apply(audio: np.ndarray, sample_rate: float) -> np.ndarray:
        marker.append(name)
        return audio * np.float32(factor)

    return cast(SlotEffect, apply)


class TestRenderBuffer:
    """The pure layer: order, bypass short-circuit and failure naming."""

    def test_an_empty_chain_returns_the_input_array_itself(self) -> None:
        """No slot means no work: the caller's own buffer comes back."""
        audio = _tone()

        def loader(slot: PluginSlot) -> SlotEffect:
            raise AssertionError("an empty chain must load nothing")

        assert render_buffer(PluginChain(), audio, SAMPLE_RATE, loader) is audio

    def test_a_fully_bypassed_chain_returns_the_input_array_itself(self) -> None:
        """Bypass is bit-transparent because it never copies or loads."""
        audio = _tone()
        chain = _bypassed_chain(Path("C:/plugins/Alpha.vst3"))
        loaded: list[str] = []

        def loader(slot: PluginSlot) -> SlotEffect:
            loaded.append(slot.plugin_name)
            raise AssertionError("a bypassed slot must not be loaded")

        assert render_buffer(chain, audio, SAMPLE_RATE, loader) is audio
        assert loaded == []

    def test_active_slots_run_in_order_and_bypassed_ones_are_skipped(self) -> None:
        """The render follows slot order and skips exactly the bypassed slots."""
        audio = _tone()
        chain = PluginChain(
            (
                PluginSlot("C:/plugins/First.vst3"),
                PluginSlot("C:/plugins/Second.vst3", bypass=True),
                PluginSlot("C:/plugins/Third.vst3"),
            )
        )
        marker: list[str] = []
        effects = {
            "First": _effect(marker, "first", 0.5),
            "Third": _effect(marker, "third", 0.25),
        }

        def loader(slot: PluginSlot) -> SlotEffect:
            return effects[slot.plugin_name]

        rendered = render_buffer(chain, audio, SAMPLE_RATE, loader)

        assert marker == ["first", "third"]
        assert rendered.dtype == np.float32
        np.testing.assert_array_equal(
            rendered, audio * np.float32(0.5) * np.float32(0.25)
        )

    def test_the_input_buffer_is_never_modified(self) -> None:
        """A render works on the caller's buffer without editing it."""
        audio = _tone()
        before = audio.copy()
        chain = PluginChain((PluginSlot("C:/plugins/First.vst3"),))

        def loader(slot: PluginSlot) -> SlotEffect:
            return _effect([], "first", 0.5)

        render_buffer(chain, audio, SAMPLE_RATE, loader)

        np.testing.assert_array_equal(audio, before)

    def test_two_renders_of_one_buffer_agree_exactly(self) -> None:
        """Nothing in the layer varies between two identical passes."""
        audio = _tone()
        chain = PluginChain(
            (
                PluginSlot("C:/plugins/First.vst3"),
                PluginSlot("C:/plugins/Second.vst3"),
            )
        )

        def loader(slot: PluginSlot) -> SlotEffect:
            factor = 0.5 if slot.plugin_name == "First" else 0.25
            return _effect([], slot.plugin_name, factor)

        first = render_buffer(chain, audio, SAMPLE_RATE, loader)
        second = render_buffer(chain, audio, SAMPLE_RATE, loader)

        np.testing.assert_array_equal(first, second)

    def test_a_failing_slot_is_named_without_its_path(self) -> None:
        """A loader failure becomes one error naming the slot and plugin only."""
        chain = PluginChain(
            (
                PluginSlot("C:/plugins/First.vst3"),
                PluginSlot("C:/plugins/Broken.vst3"),
            )
        )

        def loader(slot: PluginSlot) -> SlotEffect:
            if slot.plugin_name == "Broken":
                raise RuntimeError(f"cannot load {slot.plugin_path}")
            return _effect([], "first")

        with pytest.raises(PluginRenderError) as caught:
            render_buffer(chain, _tone(), SAMPLE_RATE, loader)

        message = str(caught.value)
        assert caught.value.slot_index == 1
        assert caught.value.plugin == "Broken"
        assert "Broken" in message
        assert "C:/plugins" not in message
        assert "RuntimeError" in message


class TestWorkerSuccessPath:
    """The worker writes the samples it was given, and writes them the same twice."""

    def test_a_bypassed_chain_through_the_worker_is_bit_transparent(
        self, tmp_path: Path
    ) -> None:
        """The decoded output equals the decoded input exactly, not closely."""
        source = tmp_path / "source.wav"
        destination = tmp_path / "rendered.wav"
        audio = _tone()
        _write_audio(source, audio)

        outcome = render_file(
            _bypassed_chain(_bundle(tmp_path, "Alpha")),
            source,
            destination,
        )

        assert outcome.ok, outcome.reason
        rendered = _read_audio(destination)
        assert rendered.dtype == np.float32
        assert np.array_equal(rendered, audio)
        assert rendered.shape == audio.shape

    def test_two_worker_processes_write_identical_files(self, tmp_path: Path) -> None:
        """Determinism spans processes, which is what a batch run needs."""
        source = tmp_path / "source.wav"
        _write_audio(source, _tone())
        chain = _bypassed_chain(_bundle(tmp_path, "Alpha"), _bundle(tmp_path, "Beta"))
        digests: list[str] = []

        for index in range(2):
            destination = tmp_path / f"rendered_{index}.wav"
            outcome = render_file(chain, source, destination)
            assert outcome.ok, outcome.reason
            digests.append(hashlib.sha256(destination.read_bytes()).hexdigest())

        assert digests[0] == digests[1]

    def test_a_saved_preset_renders_the_same_in_a_fresh_process(
        self, tmp_path: Path
    ) -> None:
        """A preset's chain survives JSON and a new worker unchanged.

        The slot is bypassed, so this proves the preset and state plumbing that
        the worker consumes — not that a plugin *applied* a saved state, which
        needs a real bundle (F-M1 order #2 decision).
        """
        source = tmp_path / "source.wav"
        _write_audio(source, _tone())
        chain = _bypassed_chain(_bundle(tmp_path, "Alpha"))
        preset_path = tmp_path / "chain.json"
        preset_path.write_text(json.dumps(chain.to_preset()), encoding="utf-8")

        reloaded = PluginChain.from_preset(
            json.loads(preset_path.read_text(encoding="utf-8"))
        )
        first = tmp_path / "in_memory.wav"
        second = tmp_path / "reloaded.wav"

        assert render_file(chain, source, first).ok
        assert render_file(reloaded, source, second).ok
        assert first.read_bytes() == second.read_bytes()
        assert reloaded.to_preset() == chain.to_preset()

    def test_the_request_round_trips_the_chain_preset(self, tmp_path: Path) -> None:
        """The worker reads the same chain the caller wrote."""
        source = tmp_path / "source.wav"
        destination = tmp_path / "rendered.wav"
        chain = _bypassed_chain(_bundle(tmp_path, "Alpha"))
        request_path = tmp_path / "request.json"
        request_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "input": str(source),
                    "output": str(destination),
                    "chain": chain.to_preset(),
                }
            ),
            encoding="utf-8",
        )

        request = read_request(request_path)

        assert request.input_path == source
        assert request.output_path == destination
        assert request.chain.to_preset() == chain.to_preset()

    def test_a_request_without_a_wav_output_is_refused(self, tmp_path: Path) -> None:
        """The float WAV intermediate is the contract, so a preset cannot change it."""
        request_path = tmp_path / "request.json"
        request_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "input": str(tmp_path / "source.wav"),
                    "output": str(tmp_path / "rendered.flac"),
                    "chain": PluginChain().to_preset(),
                }
            ),
            encoding="utf-8",
        )

        with pytest.raises(WorkerRequestError, match="32-bit float WAV"):
            read_request(request_path)

    def test_the_worker_reports_a_usage_error_as_one_json_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A malformed request exits non-zero with a machine-readable status."""
        request_path = tmp_path / "request.json"
        request_path.write_text("{not json", encoding="utf-8")

        exit_code = main([str(request_path)])

        assert exit_code == EXIT_USAGE
        document = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert document["status"] == "usage"
        assert "C:" not in document["reason"]

    def test_a_valid_request_exits_zero(self, tmp_path: Path) -> None:
        """The success status line is the exit-0 contract the runner reads."""
        source = tmp_path / "source.wav"
        destination = tmp_path / "rendered.wav"
        _write_audio(source, _tone())
        request_path = tmp_path / "request.json"
        request_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "input": str(source),
                    "output": str(destination),
                    "chain": PluginChain().to_preset(),
                }
            ),
            encoding="utf-8",
        )

        assert main([str(request_path)]) == EXIT_OK
        assert destination.is_file()
