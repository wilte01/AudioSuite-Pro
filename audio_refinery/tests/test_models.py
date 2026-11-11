"""Locks for the stage toggles' one declaration (F-S1 follow-up)."""

# Changed in 2.7.0: an EQ-only run is a run (F-S1 follow-up).
from __future__ import annotations

import pytest

from audio_refinery.core.models import (
    REFINERY_STAGES,
    StageConfig,
    has_active_stage,
)


@pytest.mark.parametrize("field", [field for field, _name in REFINERY_STAGES])
def test_one_enabled_stage_is_active(field: str) -> None:
    """Every stage the pipeline runs counts on its own."""
    config = StageConfig(**{f: f == field for f, _ in REFINERY_STAGES})

    assert has_active_stage(config) is True


def test_no_enabled_stage_is_inactive() -> None:
    config = StageConfig(**{f: False for f, _ in REFINERY_STAGES})

    assert has_active_stage(config) is False


def test_every_pair_names_a_boolean_field() -> None:
    config = StageConfig()

    for field, name in REFINERY_STAGES:
        assert field == name
        assert isinstance(getattr(config, field), bool)
