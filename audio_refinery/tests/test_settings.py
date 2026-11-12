# Changed in 2.7.0: the EQ rack, flags and driver emission are locked (F-S1).
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
Changed in 2.5.0: album mode round-trips, and a file written before it existed
still reads as per-file normalisation (F-E1).

Changed in 2.5.0: the exact trim range round-trips, and a file written before
it existed still trims detected silence (F-E3).
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


class TestExactTrim:
    """The exact trim range is a stored stage field, silence when absent."""

    def test_the_range_round_trips(self, tmp_path: Path) -> None:
        live = tmp_path / "live.json"
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(refinery_settings, "_SETTINGS_FILE", live)
            patch.setattr(refinery_settings, "_LEGACY_FILE", tmp_path / "old.json")
            patch.setattr(refinery_settings, "_DEFAULT_FILE", tmp_path / "none.json")
            config = StageConfig()
            config.trim_params.mode = "exact"
            config.trim_params.start_ms = 250
            config.trim_params.end_ms = None
            config.trim_params.duration_ms = 750
            config.trim_params.copy_mode = True

            refinery_settings.save(config)
            loaded = refinery_settings.load()

        assert loaded.trim_params.mode == "exact"
        assert loaded.trim_params.start_ms == 250
        assert loaded.trim_params.end_ms is None
        assert loaded.trim_params.duration_ms == 750
        assert loaded.trim_params.copy_mode is True

    def test_a_file_without_the_keys_keeps_silence_trimming(
        self, tmp_path: Path
    ) -> None:
        live = tmp_path / "live.json"
        live.write_text(
            json.dumps({"trim_params": {"threshold": -40}}), encoding="utf-8"
        )
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(refinery_settings, "_SETTINGS_FILE", live)
            patch.setattr(refinery_settings, "_LEGACY_FILE", tmp_path / "old.json")
            patch.setattr(refinery_settings, "_DEFAULT_FILE", tmp_path / "none.json")

            loaded = refinery_settings.load()

        assert loaded.trim_params.mode == "silence"
        assert loaded.trim_params.start_ms is None
        assert loaded.trim_params.end_ms is None
        assert loaded.trim_params.duration_ms is None
        assert loaded.trim_params.copy_mode is False
        assert loaded.trim_params.threshold == -40

    def test_an_unknown_mode_falls_back_to_silence(self, tmp_path: Path) -> None:
        live = tmp_path / "live.json"
        live.write_text(
            json.dumps({"trim_params": {"mode": "teleport"}}), encoding="utf-8"
        )
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(refinery_settings, "_SETTINGS_FILE", live)
            patch.setattr(refinery_settings, "_LEGACY_FILE", tmp_path / "old.json")
            patch.setattr(refinery_settings, "_DEFAULT_FILE", tmp_path / "none.json")

            assert refinery_settings.load().trim_params.mode == "silence"


class TestAlbumMode:
    """Album mode is a stored stage field, off when the file predates it."""

    def test_album_mode_round_trips(self, tmp_path: Path) -> None:
        live = tmp_path / "live.json"
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(refinery_settings, "_SETTINGS_FILE", live)
            patch.setattr(refinery_settings, "_LEGACY_FILE", tmp_path / "old.json")
            patch.setattr(refinery_settings, "_DEFAULT_FILE", tmp_path / "none.json")
            config = StageConfig()
            config.normalise_params.album_mode = True

            refinery_settings.save(config)

            assert refinery_settings.load().normalise_params.album_mode is True

    def test_a_file_without_the_key_keeps_per_file_behaviour(
        self, tmp_path: Path
    ) -> None:
        live = tmp_path / "live.json"
        live.write_text(
            json.dumps({"normalise_params": {"target_lufs": -18.0}}),
            encoding="utf-8",
        )
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(refinery_settings, "_SETTINGS_FILE", live)
            patch.setattr(refinery_settings, "_LEGACY_FILE", tmp_path / "old.json")
            patch.setattr(refinery_settings, "_DEFAULT_FILE", tmp_path / "none.json")

            loaded = refinery_settings.load()

            assert loaded.normalise_params.album_mode is False
            assert loaded.normalise_params.target_lufs == -18.0


class TestEqRack:
    """The parametric EQ rack round-trips; older files read as stage off (F-S1)."""

    def test_the_rack_round_trips(self, tmp_path: Path) -> None:
        from audio_suite_shared.dsp_eq import EqBand, EqSettings

        live = tmp_path / "live.json"
        config = StageConfig()
        config.eq = True
        config.eq_params = EqSettings(
            bands=(
                EqBand("peaking", 1000.0, 3.0, 1.0),
                EqBand("highpass", 40.0),
            )
        )

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(refinery_settings, "_SETTINGS_FILE", live)
            patch.setattr(refinery_settings, "_LEGACY_FILE", tmp_path / "old.json")
            patch.setattr(refinery_settings, "_DEFAULT_FILE", tmp_path / "none.json")
            refinery_settings.save(config)
            loaded = refinery_settings.load()

        assert loaded.eq is True
        assert loaded.eq_params.bands == (
            EqBand("peaking", 1000.0, 3.0, 1.0),
            EqBand("highpass", 40.0),
        )
        assert loaded.eq_params.bypass is False

    def test_a_file_without_the_keys_keeps_the_stage_off(self, tmp_path: Path) -> None:
        live = tmp_path / "live.json"
        live.write_text(json.dumps({"declick": False}), encoding="utf-8")

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(refinery_settings, "_SETTINGS_FILE", live)
            patch.setattr(refinery_settings, "_LEGACY_FILE", tmp_path / "old.json")
            patch.setattr(refinery_settings, "_DEFAULT_FILE", tmp_path / "none.json")
            loaded = refinery_settings.load()

        assert loaded.eq is False
        assert loaded.eq_params.bands == ()
        assert loaded.eq_params.bypass is False

    def test_an_invalid_stored_band_is_dropped_not_fatal(self, tmp_path: Path) -> None:
        """One bad band must not cost the user the other bands, or the load."""
        live = tmp_path / "live.json"
        live.write_text(
            json.dumps(
                {
                    "eq": True,
                    "eq_params": {
                        "bands": [
                            {
                                "kind": "peaking",
                                "freq_hz": 1000.0,
                                "gain_db": 3.0,
                                "q": 1.0,
                            },
                            {"kind": "peaking", "freq_hz": 99000.0},
                            {"kind": "teleport", "freq_hz": 1000.0},
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(refinery_settings, "_SETTINGS_FILE", live)
            patch.setattr(refinery_settings, "_LEGACY_FILE", tmp_path / "old.json")
            patch.setattr(refinery_settings, "_DEFAULT_FILE", tmp_path / "none.json")
            loaded = refinery_settings.load()

        assert [band.freq_hz for band in loaded.eq_params.bands] == [1000.0]


# Changed in 2.7.0: the dynamics stage and its pair round-trip (F-S2).
class TestDynamicsPersistence:
    def test_the_stage_and_its_pair_round_trip(self, settings_file: Path) -> None:
        from audio_suite_shared.dsp_dynamics import (
            CompressorSettings,
            LimiterSettings,
        )

        config = StageConfig(dynamics=True)
        config.compressor_params = CompressorSettings(
            threshold_db=-30.0, ratio=8.0, makeup_db=2.0
        )
        config.limiter_params = LimiterSettings(
            ceiling_dbtp=-2.0, lookahead_ms=3.0, release_ms=250.0
        )

        refinery_settings.save(config)
        loaded = refinery_settings.load()

        assert loaded.dynamics is True
        assert loaded.compressor_params == config.compressor_params
        assert loaded.limiter_params == config.limiter_params

    def test_a_default_config_leaves_dynamics_off(self, settings_file: Path) -> None:
        from audio_suite_shared.dsp_dynamics import (
            CompressorSettings,
            LimiterSettings,
        )

        refinery_settings.save(StageConfig())

        loaded = refinery_settings.load()

        assert loaded.dynamics is False
        assert loaded.compressor_params == CompressorSettings()
        assert loaded.limiter_params == LimiterSettings()

    def test_an_invalid_stored_compressor_falls_back_to_defaults(
        self, settings_file: Path
    ) -> None:
        from audio_suite_shared.dsp_dynamics import CompressorSettings

        settings_file.write_text(
            '{"dynamics": true, "compressor_params": {"ratio": 0.5}}',
            encoding="utf-8",
        )

        loaded = refinery_settings.load()

        assert loaded.dynamics is True
        assert loaded.compressor_params == CompressorSettings()
