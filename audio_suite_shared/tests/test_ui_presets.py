"""tests/test_ui_presets.py — the shared per-tool preset store.

``load_tool_preset`` / ``save_tool_preset`` / ``delete_tool_preset`` are what
the analyse-and-tag windows read and write, and the keys they build are the
ones those windows wrote before they moved onto ``SuiteApp``: a renamed key
would orphan every preset a user had saved.  These tests pin the keys and the
name-list behaviour, so the store has a lock of its own rather than riding on
one window's app tests.

Changed in 2.9.0: the store's own lock (C1 stage 2).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from audio_suite_shared import ui_presets


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Back ``suite_config`` with a dict for the duration of one test."""
    values: dict[str, Any] = {}

    def load_value(key: str, default: Any = None) -> Any:
        return values.get(key, default)

    def save_value(key: str, value: Any) -> None:
        values[key] = value

    monkeypatch.setattr("audio_suite_shared.suite_config.load_value", load_value)
    monkeypatch.setattr("audio_suite_shared.suite_config.save_value", save_value)
    return values


class TestLoadToolPreset:
    """A preset's settings come back as a dict, or not at all."""

    def test_returns_the_stored_settings(self, store: dict[str, Any]) -> None:
        store["lyrics_preset_Night Mix"] = json.dumps({"max_workers": 4})

        assert ui_presets.load_tool_preset("lyrics", "Night Mix") == {"max_workers": 4}

    def test_returns_none_when_the_preset_is_absent(
        self, store: dict[str, Any]
    ) -> None:
        assert ui_presets.load_tool_preset("lyrics", "Missing") is None

    def test_returns_none_for_unreadable_json(self, store: dict[str, Any]) -> None:
        store["lyrics_preset_Broken"] = "not json"

        assert ui_presets.load_tool_preset("lyrics", "Broken") is None

    def test_returns_none_when_the_payload_is_not_a_mapping(
        self, store: dict[str, Any]
    ) -> None:
        store["lyrics_preset_List"] = json.dumps(["a", "b"])

        assert ui_presets.load_tool_preset("lyrics", "List") is None


class TestSaveToolPreset:
    """Saving writes the settings and registers the name once."""

    def test_writes_the_settings_under_the_legacy_key(
        self, store: dict[str, Any]
    ) -> None:
        ui_presets.save_tool_preset("lyrics", "Night Mix", {"max_workers": 4})

        assert store["lyrics_preset_Night Mix"] == json.dumps({"max_workers": 4})
        assert store["lyrics_presets_list"] == json.dumps(["Night Mix"])

    def test_an_existing_name_is_not_duplicated(self, store: dict[str, Any]) -> None:
        store["lyrics_presets_list"] = json.dumps(["Night Mix"])

        ui_presets.save_tool_preset("lyrics", "Night Mix", {"max_workers": 2})

        assert store["lyrics_presets_list"] == json.dumps(["Night Mix"])

    def test_a_second_preset_is_appended(self, store: dict[str, Any]) -> None:
        store["lyrics_presets_list"] = json.dumps(["First"])

        ui_presets.save_tool_preset("lyrics", "Second", {"max_workers": 2})

        assert store["lyrics_presets_list"] == json.dumps(["First", "Second"])


class TestDeleteToolPreset:
    """Deleting unlists the preset and leaves its stored values alone."""

    def test_drops_the_name_from_the_list(self, store: dict[str, Any]) -> None:
        store["lyrics_presets_list"] = json.dumps(["A", "B"])
        store["lyrics_preset_A"] = json.dumps({"max_workers": 2})

        ui_presets.delete_tool_preset("lyrics", "A")

        assert store["lyrics_presets_list"] == json.dumps(["B"])
        # The values stay: a re-saved preset of the same name is not half-lost.
        assert store["lyrics_preset_A"] == json.dumps({"max_workers": 2})

    def test_an_unknown_name_leaves_the_list_unchanged(
        self, store: dict[str, Any]
    ) -> None:
        store["lyrics_presets_list"] = json.dumps(["A"])

        ui_presets.delete_tool_preset("lyrics", "Missing")

        assert store["lyrics_presets_list"] == json.dumps(["A"])


class TestTheKeysAreTheLegacyOnes:
    """A window's prefix is all that separates one tool's presets from another."""

    def test_the_bpm_prefix_reproduces_the_bpm_keys(
        self, store: dict[str, Any]
    ) -> None:
        ui_presets.save_tool_preset("bpm", "Fast", {"bpm_min": 120})

        assert store["bpm_preset_Fast"] == json.dumps({"bpm_min": 120})
        assert store["bpm_presets_list"] == json.dumps(["Fast"])
        assert ui_presets.load_tool_preset("bpm", "Fast") == {"bpm_min": 120}
