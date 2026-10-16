"""
audio_refinery/tests/test_settings.py
Tests for audio_refinery.utils.settings load()/save() persistence.

Changed in 1.1.0: added regression coverage for persisting the six
Sprint 1 effect fields (reverse, karaoke, karaoke_strength, phaser,
flanger, chorus) so GUI effect toggles survive a restart.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import audio_refinery.utils.settings as refinery_settings
from audio_refinery.core.models import EnhanceParams, StageConfig


@pytest.fixture()
def settings_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the module's settings path at a per-test temp file."""
    target = tmp_path / "refinery_settings.json"
    monkeypatch.setattr(refinery_settings, "_SETTINGS_FILE", target)
    return target


class TestEffectPersistence:
    def test_effect_fields_round_trip(self, settings_file: Path) -> None:
        config = StageConfig()
        config.enhance_params = EnhanceParams(
            reverse=True,
            karaoke=True,
            karaoke_strength=0.7,
            phaser=True,
            flanger=True,
            chorus=True,
        )

        refinery_settings.save(config)
        loaded = refinery_settings.load()

        assert loaded.enhance_params.reverse is True
        assert loaded.enhance_params.karaoke is True
        assert loaded.enhance_params.karaoke_strength == 0.7
        assert loaded.enhance_params.phaser is True
        assert loaded.enhance_params.flanger is True
        assert loaded.enhance_params.chorus is True

    def test_saved_json_contains_effect_keys(self, settings_file: Path) -> None:
        refinery_settings.save(StageConfig())

        data = json.loads(settings_file.read_text(encoding="utf-8"))
        enhance = data["enhance_params"]
        for key in (
            "reverse",
            "karaoke",
            "karaoke_strength",
            "phaser",
            "flanger",
            "chorus",
        ):
            assert key in enhance

    def test_effect_defaults_when_absent(self, settings_file: Path) -> None:
        settings_file.write_text(
            json.dumps({"enhance_params": {"preset": "Moderate"}}),
            encoding="utf-8",
        )

        params = refinery_settings.load().enhance_params

        assert params.reverse is False
        assert params.karaoke is False
        assert params.karaoke_strength == 1.0
        assert params.phaser is False
        assert params.flanger is False
        assert params.chorus is False
