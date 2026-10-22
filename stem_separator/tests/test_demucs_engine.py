"""Tests for ``stem_separator.core.demucs_engine``.

Demucs and torch are not installed in the suite's environment (the ``ml``
extra is opt-in), so every test here supplies the modules the adapter imports
and asserts what the adapter does with them.  The audio assertions decode the
files the writer produced: a stem file check that read back the array the code
just wrote would not notice a wrong sample width, channel count or scale.

The one exception is :class:`TestRealModel`, which is marked ``real_ml`` and so
deselected from the default run (PLAN D115).  It is the only test that proves
the adapter's call into the real API is shaped the way the installed Demucs
expects; run it with ``pytest -m real_ml`` on a machine with the extra.

Changed in 2.0.0: initial version (Sprint 6, Item 6.1).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydub import AudioSegment
from pydub.generators import Sine

from audio_suite_shared.exceptions import AudioMissingDependencyError
from stem_separator.core import demucs_engine
from stem_separator.core.demucs_engine import (
    clear_separator_cache,
    missing_dependency_reason,
    mix_stems,
    require_demucs,
    separate,
    write_stem,
)
from stem_separator.core.models import MODEL_SAMPLE_RATE, STEM_NAMES

SR = 44100


@pytest.fixture(autouse=True)
def _clean_cache() -> Any:
    """Each test starts with no loaded model."""
    clear_separator_cache()
    yield
    clear_separator_cache()


def _wav(path: Path, *, seconds: float = 0.25, channels: int = 2) -> Path:
    """Write a short stereo tone the adapter can decode."""
    tone = Sine(440).to_audio_segment(duration=int(seconds * 1000))
    if channels == 2:
        tone = AudioSegment.from_mono_audiosegments(tone, tone)
    tone.export(str(path), format="wav")
    return path


def _install_fake_torch(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Register a fake torch and return the list of tensors it was handed."""
    seen: list[Any] = []
    module = types.ModuleType("torch")

    def _from_numpy(array: Any) -> Any:
        seen.append(array)
        return array

    module.from_numpy = _from_numpy  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", module)
    return seen


def _install_fake_demucs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``import demucs.api`` succeed without the real package."""
    package = types.ModuleType("demucs")
    api = types.ModuleType("demucs.api")
    package.api = api  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "demucs", package)
    monkeypatch.setitem(sys.modules, "demucs.api", api)


class _FakeSeparator:
    """Returns one constant array per stem, at the length it was given."""

    def __init__(self, *, missing: str | None = None) -> None:
        self.missing = missing
        self.calls: list[tuple[int, int]] = []

    def separate_tensor(
        self, tensor: Any, sample_rate: int
    ) -> tuple[Any, dict[str, Any]]:
        samples = int(np.asarray(tensor).shape[-1])
        self.calls.append((sample_rate, samples))
        stems = {
            name: np.full((2, samples), 0.1 * (index + 1), dtype=np.float32)
            for index, name in enumerate(STEM_NAMES)
            if name != self.missing
        }
        return np.zeros((2, samples), dtype=np.float32), stems


class TestAvailability:
    """A missing extra is a named dependency error, not an ImportError."""

    def test_missing_demucs_reason_names_the_extra(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "demucs", None)

        reason = missing_dependency_reason()

        assert reason is not None
        assert "Demucs is not installed" in reason
        assert "ml" in reason

    def test_require_demucs_raises_the_dependency_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "demucs", None)

        with pytest.raises(AudioMissingDependencyError) as caught:
            require_demucs()
        assert "demucs" in str(caught.value).lower() or "Demucs" in str(caught.value)

    def test_installed_demucs_reports_no_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_demucs(monkeypatch)

        assert missing_dependency_reason() is None
        require_demucs()


class TestSeparate:
    """The adapter decodes once, separates at the model's rate and keeps floats."""

    def test_stems_come_back_at_the_model_rate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_demucs(monkeypatch)
        tensors = _install_fake_torch(monkeypatch)
        separator = _FakeSeparator()
        monkeypatch.setattr(demucs_engine, "_separator", lambda *_a: separator)
        source = _wav(tmp_path / "song.wav")

        track = separate(str(source), device="cpu")

        expected_samples = int(0.25 * MODEL_SAMPLE_RATE)
        assert separator.calls == [(MODEL_SAMPLE_RATE, expected_samples)]
        assert set(track.stems) == set(STEM_NAMES)
        for array in track.stems.values():
            assert array.dtype == np.float32
            assert array.shape == (2, expected_samples)
        # One decode, handed to the model — not decoded again inside it.
        assert len(tensors) == 1
        assert tensors[0].shape == (2, expected_samples)

    def test_only_the_requested_stems_are_kept(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_demucs(monkeypatch)
        _install_fake_torch(monkeypatch)
        monkeypatch.setattr(demucs_engine, "_separator", lambda *_a: _FakeSeparator())

        track = separate(
            str(_wav(tmp_path / "song.wav")), device="cpu", stems=["bass", "vocals"]
        )

        assert list(track.stems) == ["vocals", "bass"]

    def test_a_stem_the_model_omitted_is_an_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_demucs(monkeypatch)
        _install_fake_torch(monkeypatch)
        monkeypatch.setattr(
            demucs_engine, "_separator", lambda *_a: _FakeSeparator(missing="drums")
        )

        with pytest.raises(ValueError) as caught:
            separate(str(_wav(tmp_path / "song.wav")), device="cpu")
        assert "drums" in str(caught.value)

    def test_unknown_model_is_refused_before_loading(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_demucs(monkeypatch)

        with pytest.raises(ValueError) as caught:
            separate(str(_wav(tmp_path / "song.wav")), model="nope")
        assert "nope" in str(caught.value)


class TestMixStems:
    """The mix is a sum, clipped; it never wraps around."""

    def test_mix_sums_named_stems(self) -> None:
        stems = {
            "vocals": np.full((2, 10), 0.25, dtype=np.float32),
            "drums": np.full((2, 10), 0.5, dtype=np.float32),
        }

        mixed = mix_stems(stems)

        assert np.allclose(mixed, 0.75)

    def test_mix_clips_instead_of_wrapping(self) -> None:
        stems = {
            "vocals": np.full((2, 10), 0.8, dtype=np.float32),
            "drums": np.full((2, 10), 0.8, dtype=np.float32),
        }

        mixed = mix_stems(stems)

        assert float(mixed.max()) == 1.0

    def test_mix_can_choose_a_subset(self) -> None:
        stems = {
            "vocals": np.full((2, 4), 0.1, dtype=np.float32),
            "bass": np.full((2, 4), 0.2, dtype=np.float32),
        }

        mixed = mix_stems(stems, ["bass"])

        assert np.allclose(mixed, 0.2)

    def test_shape_mismatch_is_refused(self) -> None:
        stems = {
            "vocals": np.zeros((2, 10), dtype=np.float32),
            "bass": np.zeros((2, 9), dtype=np.float32),
        }

        with pytest.raises(ValueError):
            mix_stems(stems)

    def test_empty_selection_is_refused(self) -> None:
        with pytest.raises(ValueError):
            mix_stems({})


class TestWriteStem:
    """The written file is 16-bit PCM at the right length, rate and level."""

    def test_a_constant_half_scale_stem_round_trips(self, tmp_path: Path) -> None:
        audio = np.full((2, SR // 2), 0.5, dtype=np.float32)
        target = tmp_path / "out" / "vocals.wav"

        write_stem(audio, SR, target)

        decoded = AudioSegment.from_wav(str(target))
        assert decoded.frame_rate == SR
        assert decoded.channels == 2
        assert decoded.sample_width == 2
        assert len(decoded) == pytest.approx(500, abs=2)
        assert decoded.rms == pytest.approx(0.5 * 32767, rel=0.001)

    def test_hot_samples_are_clipped_not_wrapped(self, tmp_path: Path) -> None:
        audio = np.full((2, 100), 1.5, dtype=np.float32)
        target = tmp_path / "loud.wav"

        write_stem(audio, SR, target)

        decoded = AudioSegment.from_wav(str(target))
        assert max(decoded.get_array_of_samples()) == 32767
        assert min(decoded.get_array_of_samples()) == 32767

    def test_a_mono_array_is_written_as_stereo(self, tmp_path: Path) -> None:
        audio = np.full((SR // 4,), 0.25, dtype=np.float32)
        target = tmp_path / "mono.wav"

        write_stem(audio, SR, target)

        decoded = AudioSegment.from_wav(str(target))
        assert decoded.channels == 2
        assert len(decoded) == pytest.approx(250, abs=2)


@pytest.mark.real_ml
class TestRealModel:
    """The real Demucs path: ``pytest -m real_ml`` with the ``ml`` extra.

    Deselected from the default run because it needs the extra and downloads
    ~80 MB of weights on first use.  The assertions are audio outcomes, not
    the adapter's own state: the stems are the model's, at the model's rate,
    and the file written from one decodes to that level.
    """

    def test_a_real_separation_writes_the_models_own_stem(self, tmp_path: Path) -> None:
        pytest.importorskip(
            "demucs", reason="the 'ml' extra is not installed (uv sync --extra ml)"
        )
        source = _wav(tmp_path / "song.wav", seconds=2.0)

        track = separate(str(source), device="cpu", stems=("vocals",))

        stem = track.stems["vocals"]
        assert track.sample_rate == MODEL_SAMPLE_RATE
        assert stem.shape == (2, 2 * MODEL_SAMPLE_RATE)
        assert stem.dtype == np.float32
        assert np.isfinite(stem).all()

        target = tmp_path / "vocals.wav"
        write_stem(stem, track.sample_rate, target)

        decoded = AudioSegment.from_wav(str(target))
        assert decoded.frame_rate == MODEL_SAMPLE_RATE
        assert decoded.channels == 2
        assert len(decoded) == pytest.approx(2000, abs=5)
        # A 440 Hz tone is not a vocal, so the model silences most of it.  The
        # assertion is that the written PCM carries the model's level, in both
        # directions: a lost stem would read as silence, and the source's own
        # level would mean the model never ran.
        expected_rms = float(np.sqrt(np.mean(np.square(stem, dtype=np.float64))))
        assert decoded.rms == pytest.approx(expected_rms * 32767, rel=0.02)
        source_rms = float(
            np.sqrt(
                np.mean(
                    np.square(
                        np.asarray(
                            AudioSegment.from_wav(str(source)).get_array_of_samples(),
                            dtype=np.float64,
                        )
                        / 32768.0
                    )
                )
            )
        )
        assert expected_rms < source_rms
