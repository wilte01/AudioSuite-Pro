"""Noise Reduction -- hum, hiss, and broadband noise removal."""

from __future__ import annotations

__all__ = ["NoiseReductionApp"]


def __getattr__(name: str) -> object:
    if name == "NoiseReductionApp":
        from .app import NoiseReductionApp

        return NoiseReductionApp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
