"""Tests for audio_suite_shared.constants.

Covers presence, value, and type of every named constant and verifies that
the consumer-facing magic-number constants are actually referenced by their
consuming modules (import-level assertion).
"""

from __future__ import annotations

import pytest

import audio_suite_shared.constants as constants
from audio_suite_shared.constants import (
    CPU_WORKER_TIMEOUT_SECS,
    DEFAULT_MAX_WORKERS,
    DEFAULT_WINDOW_GEOMETRY,
    JPEG_QUALITY,
    MAX_DURATION_HISTORY,
    VARIOUS_ARTISTS_ALIASES,
    WORKER_TIMEOUT_SECS,
)


def _parse_x11_geometry(value: str) -> tuple[int, int, int, int]:
    """Parse an X11 geometry string ``WxH+X+Y`` into (width, height, x, y)."""
    dims, pos = value.split("+", 1)
    width, height = dims.split("x", 1)
    x, y = pos.split("+", 1)
    return int(width), int(height), int(x), int(y)


class TestPresenceAndValues:
    """Every named constant exists with its documented value."""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("DEFAULT_MAX_WORKERS", 4),
            ("WORKER_TIMEOUT_SECS", 300),
            ("CPU_WORKER_TIMEOUT_SECS", 600),
            ("JPEG_QUALITY", 92),
            ("MAX_DURATION_HISTORY", 10),
            ("DEFAULT_WINDOW_GEOMETRY", "800x600+100+100"),
            ("VARIOUS_ARTISTS_ALIASES", frozenset({"various artists", "various"})),
        ],
    )
    def test_named_constant_present_with_value(
        self, name: str, expected: object
    ) -> None:
        assert getattr(constants, name) == expected


class TestTypes:
    """Type correctness of the named constants."""

    def test_integer_constants(self) -> None:
        for constant in (DEFAULT_MAX_WORKERS, JPEG_QUALITY, MAX_DURATION_HISTORY):
            assert isinstance(constant, int)
            assert not isinstance(constant, bool)

    def test_float_declared_constants(self) -> None:
        for constant in (WORKER_TIMEOUT_SECS, CPU_WORKER_TIMEOUT_SECS):
            assert isinstance(constant, (int, float))
            assert not isinstance(constant, bool)

    def test_window_geometry_is_string(self) -> None:
        assert isinstance(DEFAULT_WINDOW_GEOMETRY, str)

    def test_various_artists_aliases_is_frozenset_of_strings(self) -> None:
        assert isinstance(VARIOUS_ARTISTS_ALIASES, frozenset)
        assert all(isinstance(alias, str) for alias in VARIOUS_ARTISTS_ALIASES)


class TestWindowGeometry:
    def test_parses_to_x11_geometry_tuple(self) -> None:
        assert _parse_x11_geometry(DEFAULT_WINDOW_GEOMETRY) == (800, 600, 100, 100)


class TestConsumerReferences:
    """Magic-number constants are consumed by their owning modules."""

    def test_jpeg_quality_is_consumed_by_art_processor(self) -> None:
        import album_art_normalizer.core.art_processor as consumer

        assert consumer.JPEG_QUALITY == constants.JPEG_QUALITY

    def test_max_duration_history_is_consumed_by_suite_config(self) -> None:
        import audio_suite_shared.suite_config as consumer

        assert consumer.MAX_DURATION_HISTORY == constants.MAX_DURATION_HISTORY

    def test_default_max_workers_is_consumed_by_audio_fingerprinter(
        self,
    ) -> None:
        import audio_fingerprinter.core.file_processor as consumer

        assert consumer.DEFAULT_MAX_WORKERS == constants.DEFAULT_MAX_WORKERS

    def test_default_max_workers_is_consumed_by_audio_enhancer(self) -> None:
        import audio_enhancer.core.file_processor as consumer

        assert consumer.DEFAULT_MAX_WORKERS == constants.DEFAULT_MAX_WORKERS

    def test_default_max_workers_is_consumed_by_noise_reduction(self) -> None:
        import noise_reduction.core.file_processor as consumer

        assert consumer.DEFAULT_MAX_WORKERS == constants.DEFAULT_MAX_WORKERS

    def test_default_max_workers_is_consumed_by_pop_click_remover(self) -> None:
        import pop_click_remover.core.file_processor as consumer

        assert consumer.DEFAULT_MAX_WORKERS == constants.DEFAULT_MAX_WORKERS
