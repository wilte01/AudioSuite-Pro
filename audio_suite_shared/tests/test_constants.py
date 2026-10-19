"""Tests for audio_suite_shared.constants.

Covers presence, value, and type of every named constant and verifies that
the consumer-facing magic-number constants are actually referenced by their
consuming modules (import-level assertion).
Changed in 1.4.0: adds the default_max_workers() ceiling/fallback tests.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import audio_suite_shared.constants as constants
from audio_suite_shared.constants import (
    CPU_WORKER_TIMEOUT_SECS,
    DEFAULT_MAX_WORKERS,
    DEFAULT_WINDOW_GEOMETRY,
    JPEG_QUALITY,
    MAX_DURATION_HISTORY,
    MAX_WORKERS_CEILING,
    VARIOUS_ARTISTS_ALIASES,
    WORKER_TIMEOUT_SECS,
    cap_workers_to_slot_grid,
    default_max_workers,
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
            ("DEFAULT_MAX_WORKERS", default_max_workers()),
            ("MAX_WORKERS_CEILING", 8),
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


class TestDefaultMaxWorkers:
    """The worker default follows the host, capped by the ceiling (D56)."""

    def test_uses_logical_cpu_count(self) -> None:
        with patch("audio_suite_shared.constants.os.cpu_count", return_value=6):
            assert default_max_workers() == 6

    def test_caps_at_the_ceiling(self) -> None:
        with patch("audio_suite_shared.constants.os.cpu_count", return_value=64):
            assert default_max_workers() == MAX_WORKERS_CEILING == 8

    def test_falls_back_when_cpu_count_is_unknown(self) -> None:
        with patch("audio_suite_shared.constants.os.cpu_count", return_value=None):
            assert default_max_workers() == 4

    def test_constant_is_an_import_time_snapshot_of_the_function(self) -> None:
        assert DEFAULT_MAX_WORKERS == default_max_workers()


class TestCapWorkersToSlotGrid:
    """A requested pool size never exceeds the GUI's slot grid (D66)."""

    def test_caps_at_the_grid(self) -> None:
        assert cap_workers_to_slot_grid(12, [object()] * 8) == 8

    def test_leaves_a_fitting_count_alone(self) -> None:
        assert cap_workers_to_slot_grid(4, [object()] * 8) == 4
        assert cap_workers_to_slot_grid(8, [object()] * 8) == 8

    def test_no_grid_returns_the_request(self) -> None:
        assert cap_workers_to_slot_grid(12, None) == 12
        assert cap_workers_to_slot_grid(12, object()) == 12

    def test_an_empty_grid_is_not_a_cap_of_zero(self) -> None:
        assert cap_workers_to_slot_grid(3, []) == 3

    def test_a_non_positive_count_is_left_for_caller_validation(self) -> None:
        assert cap_workers_to_slot_grid(0, [object()] * 8) == 0
        assert cap_workers_to_slot_grid(-2, [object()] * 8) == -2


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
