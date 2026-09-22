"""
tests/test_config.py
Unit tests for file_reorganizer.utils.config.

``suite_config.load_value`` / ``suite_config.save_value`` are mocked so that
tests never touch the real ``audio_suite_config.json`` on disk.  The one-time
legacy-migration path is exercised against real temp files.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from audio_suite_shared import suite_config
from file_reorganizer.core.defaults import DEFAULT_SPECIFIC, DEFAULT_VARIOUS
from file_reorganizer.utils.config import load_settings, save_settings

_DEST = "file_reorganizer_dest_dir"
_ACTION = "file_reorganizer_action"
_SPECIFIC = "file_reorganizer_specific_pattern"
_VARIOUS = "file_reorganizer_various_pattern"


class FakeStore:
    """In-memory stand-in for suite_config load/save."""

    def __init__(self) -> None:
        self.data: dict[str, object] = {}

    def load(self, key: str, default: object = None) -> object:
        return self.data.get(key, default)

    def save(self, key: str, value: object) -> None:
        self.data[key] = value


# ---------------------------------------------------------------------------
# load_settings / save_settings
# ---------------------------------------------------------------------------


class TestLoadSettings:
    def test_returns_saved_values(self) -> None:
        store = FakeStore()
        store.data = {
            _DEST: "/music/out",
            _ACTION: "move",
            _SPECIFIC: "sp",
            _VARIOUS: "va",
        }
        with (
            patch.object(suite_config, "load_value", side_effect=store.load),
            patch.object(suite_config, "save_value", side_effect=store.save),
        ):
            result = load_settings()
        assert result == {
            "dest_dir": "/music/out",
            "action": "move",
            "specific_pattern": "sp",
            "various_pattern": "va",
        }

    def test_defaults_when_nothing_saved(self) -> None:
        store = FakeStore()
        with (
            patch.object(suite_config, "load_value", side_effect=store.load),
            patch.object(suite_config, "save_value", side_effect=store.save),
        ):
            result = load_settings()
        assert result == {
            "dest_dir": "",
            "action": "copy",
            "specific_pattern": DEFAULT_SPECIFIC,
            "various_pattern": DEFAULT_VARIOUS,
        }

    def test_non_string_values_fall_back_to_defaults(self) -> None:
        store = FakeStore()
        store.data = {
            _DEST: 123,
            _ACTION: None,
            _SPECIFIC: ["not", "a", "string"],
            _VARIOUS: b"bytes",
        }
        with (
            patch.object(suite_config, "load_value", side_effect=store.load),
            patch.object(suite_config, "save_value", side_effect=store.save),
        ):
            result = load_settings()
        assert result == {
            "dest_dir": "",
            "action": "copy",
            "specific_pattern": DEFAULT_SPECIFIC,
            "various_pattern": DEFAULT_VARIOUS,
        }


class TestSaveSettings:
    def test_writes_all_keys(self) -> None:
        store = FakeStore()
        with (
            patch.object(suite_config, "load_value", side_effect=store.load),
            patch.object(suite_config, "save_value", side_effect=store.save),
        ):
            save_settings(
                dest_dir="/out",
                action="move",
                specific_pattern="sp",
                various_pattern="va",
            )
        assert store.data[_DEST] == "/out"
        assert store.data[_ACTION] == "move"
        assert store.data[_SPECIFIC] == "sp"
        assert store.data[_VARIOUS] == "va"

    def test_does_not_persist_source_dir(self) -> None:
        store = FakeStore()
        with (
            patch.object(suite_config, "load_value", side_effect=store.load),
            patch.object(suite_config, "save_value", side_effect=store.save),
        ):
            save_settings(dest_dir="/out", action="copy")
        assert set(store.data) == {_DEST, _ACTION, _SPECIFIC, _VARIOUS}
        assert "source_dir" not in store.data


# ---------------------------------------------------------------------------
# Legacy migration
# ---------------------------------------------------------------------------


def _write_legacy(tmp_path: Path, payload: dict | None = None) -> Path:
    legacy = tmp_path / "reorganizer_config.json"
    legacy.write_text(json.dumps(payload or {}), encoding="utf-8")
    return legacy


class TestMigrateLegacy:
    def test_no_legacy_file_is_noop(self, tmp_path: Path) -> None:
        store = FakeStore()
        with (
            patch.object(suite_config, "load_value", side_effect=store.load),
            patch.object(suite_config, "save_value", side_effect=store.save),
        ):
            result = load_settings(str(tmp_path / "missing_config.json"))
        assert store.data == {}
        assert result["action"] == "copy"

    def test_legacy_values_migrated_into_shared(self, tmp_path: Path) -> None:
        legacy = _write_legacy(
            tmp_path,
            {
                "dest_dir": "/legacy/out",
                "action": "move",
                "specific_pattern": "legacy_sp",
                "various_pattern": "legacy_va",
            },
        )
        store = FakeStore()
        with (
            patch.object(suite_config, "load_value", side_effect=store.load),
            patch.object(suite_config, "save_value", side_effect=store.save),
        ):
            result = load_settings(str(legacy))
        assert store.data == {
            _DEST: "/legacy/out",
            _ACTION: "move",
            _SPECIFIC: "legacy_sp",
            _VARIOUS: "legacy_va",
        }
        assert not legacy.exists()
        assert result["dest_dir"] == "/legacy/out"

    def test_existing_shared_value_wins_over_legacy(self, tmp_path: Path) -> None:
        legacy = _write_legacy(tmp_path, {"action": "move"})
        store = FakeStore()
        store.data[_ACTION] = "copy"  # already persisted in shared config
        with (
            patch.object(suite_config, "load_value", side_effect=store.load),
            patch.object(suite_config, "save_value", side_effect=store.save),
        ):
            result = load_settings(str(legacy))
        assert store.data[_ACTION] == "copy"
        assert result["action"] == "copy"

    def test_corrupt_legacy_file_left_untouched(self, tmp_path: Path) -> None:
        legacy = tmp_path / "reorganizer_config.json"
        legacy.write_text("{ not valid json ", encoding="utf-8")
        store = FakeStore()
        with (
            patch.object(suite_config, "load_value", side_effect=store.load),
            patch.object(suite_config, "save_value", side_effect=store.save),
        ):
            result = load_settings(str(legacy))
        assert store.data == {}
        assert legacy.exists()
        assert result["action"] == "copy"

    def test_non_object_legacy_file_ignored(self, tmp_path: Path) -> None:
        legacy = _write_legacy(tmp_path)
        legacy.write_text(json.dumps(["not", "a", "mapping"]), encoding="utf-8")
        store = FakeStore()
        with (
            patch.object(suite_config, "load_value", side_effect=store.load),
            patch.object(suite_config, "save_value", side_effect=store.save),
        ):
            result = load_settings(str(legacy))
        assert store.data == {}
        assert legacy.exists()
        assert result["action"] == "copy"
