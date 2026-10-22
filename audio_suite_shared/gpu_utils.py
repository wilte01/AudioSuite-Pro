"""gpu_utils.py — detect and describe the compute device an ML tool will use.

The ML tools (Stem Separator, and the denoiser added by Sprint 6 item 6.2) run
on CPU or CUDA, and which one they get is a property of the *installed* torch
wheel rather than of the machine: the PyPI Windows wheel in the ``ml`` extra is
a CPU build (``2.14.1+cpu``), so ``torch.cuda.is_available()`` is ``False``
even on a machine with a discrete GPU.  Reporting "GPU: available" from the
presence of a card would therefore be a lie, so this module only ever reports
what torch itself measured, and says why when the answer is CPU.

Nothing here imports torch at module import time: torch is an optional
dependency, the GUI and the CLI must keep working without it, and importing it
costs seconds.  Call :func:`detect_device` when a run starts (or when the tool
opens, to label the device) and :func:`describe` for a one-line caption.

Changed in 2.0.0: initial version, extracted for Sprint 6's ML tools
(PLAN_feature_expansion.md Item 6.1/6.3).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(f"audio_suite.{__name__}")

#: The two device strings torch and demucs accept.
CPU: str = "cpu"
CUDA: str = "cuda"

#: The value a tool's ``--device`` option uses when it has no preference.
AUTO: str = "auto"

#: Where the ``ml`` extra is documented; repeated in the CPU fallback reason so
#: a user who sees "CPU" knows how to change it.
ML_EXTRA_HINT: str = "install the 'ml' extra (uv sync --extra ml)"


@dataclass(frozen=True)
class DeviceInfo:
    """The device a run will use, and the evidence for that answer.

    Attributes:
        device: ``"cuda"`` or ``"cpu"`` — the string torch and demucs take.
        name: Human-readable device name (the CUDA card, or ``"CPU"``).
        reason: Why this device was chosen, in one sentence.  A CPU answer
            always names the cause (no torch, a CPU-only wheel, no driver).
    """

    device: str
    name: str
    reason: str

    @property
    def is_gpu(self) -> bool:
        """Return True when the run will use CUDA."""
        return self.device == CUDA

    def label(self) -> str:
        """Return ``"CUDA (<card>)"`` or ``"CPU"`` for a status line."""
        if self.is_gpu:
            return f"CUDA ({self.name})"
        return "CPU"


def _import_torch() -> Any | None:
    """Return the torch module, or None when it is not installed.

    A failure other than ``ImportError`` (a broken install raising ``OSError``
    for a missing DLL, for instance) is a CPU fallback too, but it is logged
    rather than silently treated as "not installed".
    """
    try:
        import torch
    except ImportError:
        return None
    except Exception as exc:  # pragma: no cover - broken installs only
        logger.warning("torch is installed but failed to import: %s", exc)
        return None
    return torch


def _cpu_torch_build(torch: Any) -> bool:
    """Return True when the torch wheel has no CUDA support compiled in.

    ``torch.version.cuda`` is ``None`` for a CPU-only build, which is a
    different answer from "CUDA is compiled in but no driver answered".
    """
    return getattr(torch.version, "cuda", None) is None


def detect_device(prefer_gpu: bool = True) -> DeviceInfo:
    """Return the device a run should use, with the reason it was chosen.

    Args:
        prefer_gpu: When False, report CPU without probing CUDA at all.  This
            is what an explicit ``--device cpu`` resolves to.

    Returns:
        A :class:`DeviceInfo` whose ``reason`` names the evidence: the CUDA
        version and card, or the exact reason CUDA was not used.
    """
    if not prefer_gpu:
        return DeviceInfo(
            device=CPU,
            name="CPU",
            reason="GPU use was turned off for this run.",
        )

    torch = _import_torch()
    if torch is None:
        return DeviceInfo(
            device=CPU,
            name="CPU",
            reason=f"torch is not installed; {ML_EXTRA_HINT} to enable CUDA.",
        )

    try:
        available = bool(torch.cuda.is_available())
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("torch.cuda.is_available() failed: %s", exc)
        return DeviceInfo(
            device=CPU,
            name="CPU",
            reason=f"CUDA could not be queried ({exc}); using the CPU.",
        )

    if not available:
        if _cpu_torch_build(torch):
            return DeviceInfo(
                device=CPU,
                name="CPU",
                reason=(
                    "the installed torch is a CPU-only build; install a CUDA "
                    "build of torch to run on the GPU."
                ),
            )
        return DeviceInfo(
            device=CPU,
            name="CPU",
            reason="torch has CUDA support but no usable GPU was found.",
        )

    version = getattr(torch.version, "cuda", None) or "unknown"
    try:
        name = str(torch.cuda.get_device_name(0))
        total = float(torch.cuda.get_device_properties(0).total_memory)
        memory = f"{total / (1024**3):.1f} GB"
    except Exception:  # pragma: no cover - driver hiccups
        name, memory = "CUDA device", "unknown memory"
    return DeviceInfo(
        device=CUDA,
        name=name,
        reason=f"CUDA {version} on {name} ({memory}).",
    )


def resolve_device(requested: str = AUTO) -> DeviceInfo:
    """Resolve a tool's ``--device`` value to a :class:`DeviceInfo`.

    Args:
        requested: ``"auto"`` (the default), ``"cpu"`` or ``"cuda"``.
            Anything else raises ``ValueError`` so a bad value fails at the
            option boundary rather than silently falling back to CPU.

    Returns:
        The resolved device.

    Raises:
        ValueError: *requested* is not one of the three accepted values.
    """
    normalised = (requested or AUTO).strip().lower()
    if normalised == AUTO:
        return detect_device()
    if normalised == CPU:
        return detect_device(prefer_gpu=False)
    if normalised == CUDA:
        detected = detect_device()
        if not detected.is_gpu:
            raise ValueError(f"CUDA was requested but is not usable: {detected.reason}")
        return detected
    raise ValueError(
        f"unknown device {requested!r}; use one of {AUTO!r}, {CPU!r}, {CUDA!r}"
    )


def describe(info: DeviceInfo) -> str:
    """Return the one-line caption a tool shows for a device.

    Args:
        info: The resolved device.

    Returns:
        ``"CUDA (NVIDIA RTX 3060)"`` or ``"CPU"``; the reason is kept separate
        (:attr:`DeviceInfo.reason`) so a status line stays short.
    """
    return info.label()
