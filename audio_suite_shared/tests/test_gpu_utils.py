"""Tests for ``audio_suite_shared.gpu_utils`` — honest device reporting.

The rule this module exists for: the device a run gets is a property of the
installed torch build, not of the machine.  A CPU-only wheel on a machine with
a GPU must report CPU *and* say why, because the PyPI Windows wheel in the
``ml`` extra is exactly that build (PLAN_feature_expansion.md D116).

Changed in 2.0.0: initial version, with Sprint 6's ML tools.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from audio_suite_shared import gpu_utils


def _fake_torch(
    *, available: bool, cuda_version: str | None = None, name: str = "Fake GPU"
) -> Any:
    """Return an object shaped like the parts of torch this module reads."""

    def _props(_index: int) -> SimpleNamespace:
        return SimpleNamespace(total_memory=8 * 1024**3)

    return SimpleNamespace(
        version=SimpleNamespace(cuda=cuda_version),
        cuda=SimpleNamespace(
            is_available=lambda: available,
            get_device_name=lambda _index: name,
            get_device_properties=_props,
        ),
    )


class TestDetectDevice:
    """What torch measured decides the answer, and the reason says why."""

    def test_missing_torch_falls_back_to_cpu_and_names_the_extra(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(gpu_utils, "_import_torch", lambda: None)

        info = gpu_utils.detect_device()

        assert info.device == gpu_utils.CPU
        assert info.is_gpu is False
        assert "torch is not installed" in info.reason
        assert "ml" in info.reason

    def test_cpu_only_wheel_is_reported_as_the_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CUDA-compiled torch with no driver is a different answer."""
        monkeypatch.setattr(
            gpu_utils,
            "_import_torch",
            lambda: _fake_torch(available=False, cuda_version=None),
        )

        info = gpu_utils.detect_device()

        assert info.device == gpu_utils.CPU
        assert "CPU-only build" in info.reason

    def test_missing_driver_is_distinguished_from_a_cpu_wheel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            gpu_utils,
            "_import_torch",
            lambda: _fake_torch(available=False, cuda_version="12.1"),
        )

        info = gpu_utils.detect_device()

        assert info.device == gpu_utils.CPU
        assert "no usable GPU" in info.reason
        assert "CPU-only build" not in info.reason

    def test_usable_cuda_reports_the_card_and_version(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            gpu_utils,
            "_import_torch",
            lambda: _fake_torch(
                available=True, cuda_version="12.1", name="NVIDIA RTX 3060"
            ),
        )

        info = gpu_utils.detect_device()

        assert info.device == gpu_utils.CUDA
        assert info.is_gpu is True
        assert info.name == "NVIDIA RTX 3060"
        assert "CUDA 12.1" in info.reason
        assert info.label() == "CUDA (NVIDIA RTX 3060)"

    def test_gpu_can_be_turned_off_without_probing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``--device cpu`` must not import torch at all."""

        def _boom() -> Any:  # pragma: no cover - must not run
            raise AssertionError("torch was probed for an explicit CPU run")

        monkeypatch.setattr(gpu_utils, "_import_torch", _boom)

        info = gpu_utils.detect_device(prefer_gpu=False)

        assert info.device == gpu_utils.CPU
        assert "turned off" in info.reason


class TestResolveDevice:
    """The option value maps to one device, and a bad value fails loudly."""

    def test_auto_uses_the_probe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            gpu_utils,
            "_import_torch",
            lambda: _fake_torch(available=True, cuda_version="12.1"),
        )

        assert gpu_utils.resolve_device("auto").device == gpu_utils.CUDA

    def test_explicit_cpu_skips_the_probe(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            gpu_utils,
            "_import_torch",
            lambda: _fake_torch(available=True, cuda_version="12.1"),
        )

        assert gpu_utils.resolve_device("cpu").device == gpu_utils.CPU

    def test_explicit_cuda_without_a_gpu_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            gpu_utils,
            "_import_torch",
            lambda: _fake_torch(available=False, cuda_version=None),
        )

        with pytest.raises(ValueError) as caught:
            gpu_utils.resolve_device("cuda")
        assert "CUDA was requested" in str(caught.value)

    def test_unknown_device_raises(self) -> None:
        with pytest.raises(ValueError) as caught:
            gpu_utils.resolve_device("tpu")
        assert "unknown device" in str(caught.value)

    def test_blank_means_auto(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(gpu_utils, "_import_torch", lambda: None)

        assert gpu_utils.resolve_device("").device == gpu_utils.CPU
        assert gpu_utils.describe(gpu_utils.resolve_device("")) == "CPU"
