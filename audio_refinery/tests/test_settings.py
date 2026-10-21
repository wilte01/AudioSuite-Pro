"""
audio_refinery/tests/test_settings.py
Tests for audio_refinery.utils.settings load()/save() persistence.

Changed in 1.1.0: added regression coverage for persisting the six
Sprint 1 effect fields (reverse, karaoke, karaoke_strength, phaser,
flanger, chorus) so GUI effect toggles survive a restart.
Changed in 1.4.1: the live file moved out of the checkout (PLAN D101), so the
fixture isolates the live, legacy and shipped-default paths together - a test
that patched only the live path would silently read this checkout's legacy
file and pass for the wrong reason.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import audio_refinery.utils.settings as refinery_settings
from audio_refinery.core.models import EnhanceParams, StageConfig

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def settings_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every settings source at temp paths, leaving the live one writable."""
    target = tmp_path / "refinery_settings.json"
    monkeypatch.setattr(refinery_settings, "_SETTINGS_FILE", target)
    monkeypatch.setattr(refinery_settings, "_LEGACY_FILE", tmp_path / "legacy.json")
    monkeypatch.setattr(refinery_settings, "_DEFAULT_FILE", tmp_path / "default.json")
    monkeypatch.setattr(refinery_settings, "_legacy_notice_emitted", False)
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


class TestLiveFileLocation:
    """A pipeline run must never write inside the checkout (PLAN D101)."""

    def test_the_live_file_is_outside_the_checkout(self) -> None:
        """The path a save writes is under the user's home, not the repo."""
        live = refinery_settings._SETTINGS_FILE
        assert not live.is_relative_to(REPO_ROOT), (
            f"live settings resolve inside the checkout: {live} - a session "
            "would dirty a tracked path"
        )
        assert live == Path.home() / ".audiosuite" / "refinery_settings.json"

    def test_the_legacy_file_is_the_old_in_checkout_path(self) -> None:
        """The adoption fallback points at the path older versions wrote."""
        legacy = refinery_settings._LEGACY_FILE
        assert legacy == REPO_ROOT / "audio_refinery" / "refinery_settings.json"

    def test_a_save_never_modifies_a_tracked_path(self, tmp_path: Path) -> None:
        """Saving changes the live file only - the legacy copy is read-only."""
        live = tmp_path / "live" / "refinery_settings.json"
        legacy = tmp_path / "legacy.json"
        legacy.write_text('{"enhance": false}', encoding="utf-8")
        legacy_before = legacy.read_bytes()

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(refinery_settings, "_SETTINGS_FILE", live)
            patch.setattr(refinery_settings, "_LEGACY_FILE", legacy)
            patch.setattr(refinery_settings, "_legacy_notice_emitted", False)
            config = refinery_settings.load()
            assert config.enhance is False, "the legacy file was not adopted"
            refinery_settings.save(config)

        assert live.exists(), "save did not write the live file"
        assert legacy.read_bytes() == legacy_before, (
            "save rewrote the legacy checkout copy - it must be read-only"
        )

    def test_the_live_file_wins_over_the_legacy_one(self, tmp_path: Path) -> None:
        """Once the live file exists, the old checkout copy is ignored."""
        live = tmp_path / "refinery_settings.json"
        legacy = tmp_path / "legacy.json"
        live.write_text(json.dumps({"declick": False}), encoding="utf-8")
        legacy.write_text(json.dumps({"declick": True}), encoding="utf-8")

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(refinery_settings, "_SETTINGS_FILE", live)
            patch.setattr(refinery_settings, "_LEGACY_FILE", legacy)
            patch.setattr(refinery_settings, "_DEFAULT_FILE", tmp_path / "none.json")
            assert refinery_settings.load().declick is False

    def test_a_corrupt_live_file_falls_through_to_the_next_source(
        self, tmp_path: Path
    ) -> None:
        """A broken live file must not poison the chain."""
        live = tmp_path / "refinery_settings.json"
        legacy = tmp_path / "legacy.json"
        live.write_text("this is not json", encoding="utf-8")
        legacy.write_text(json.dumps({"trim": False}), encoding="utf-8")

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(refinery_settings, "_SETTINGS_FILE", live)
            patch.setattr(refinery_settings, "_LEGACY_FILE", legacy)
            patch.setattr(refinery_settings, "_DEFAULT_FILE", tmp_path / "none.json")
            assert refinery_settings.load().trim is False


class TestShippedDefault:
    """The committed default is generated, not hand-maintained."""

    def test_the_committed_default_equals_stage_config(self) -> None:
        """Byte equality with the writer's own output for a default config."""
        committed = (
            REPO_ROOT / "audio_refinery" / "refinery_settings.default.json"
        ).read_text(encoding="utf-8")
        assert committed == refinery_settings.settings_text(StageConfig()), (
            "audio_refinery/refinery_settings.default.json is stale - regenerate "
            "it with settings_text(StageConfig())"
        )

    def test_the_shipped_default_survives_a_missing_live_file(
        self, tmp_path: Path
    ) -> None:
        """First run reads the committed default when no live file exists."""
        shipped = tmp_path / "refinery_settings.default.json"
        shipped.write_text(json.dumps({"enhance": False}), encoding="utf-8")

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(refinery_settings, "_SETTINGS_FILE", tmp_path / "none.json")
            patch.setattr(refinery_settings, "_LEGACY_FILE", tmp_path / "old.json")
            patch.setattr(refinery_settings, "_DEFAULT_FILE", shipped)
            assert refinery_settings.load().enhance is False
