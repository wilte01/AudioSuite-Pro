"""
Tests for metadata_scrubber.utils.tag_prefs.

Changed in 2.5.0: the selection lives in the shared suite config, so these
tests redirect ``suite_config.CONFIG_PATH`` at a temporary file and assert the
stored value, and point ``LEGACY_PREFS_PATH`` at the temp directory instead of
the package folder.
"""

import json

import pytest

import audio_suite_shared.suite_config as suite_config
from metadata_scrubber.utils import tag_prefs
from metadata_scrubber.utils.tag_prefs import load_kept_tags, save_kept_tags

_KEY = "metadata_scrubber_kept_tags"


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Keep every test away from the real suite config and package folder."""
    config_file = tmp_path / "audio_suite_config.json"
    monkeypatch.setattr(suite_config, "CONFIG_PATH", config_file)
    monkeypatch.setattr(
        tag_prefs, "LEGACY_PREFS_PATH", tmp_path / "legacy" / "tag_prefs.json"
    )
    suite_config._invalidate_cache()
    yield config_file
    suite_config._invalidate_cache()


class TestLoadKeptTags:
    def test_returns_empty_set_when_nothing_is_stored(self):
        assert load_kept_tags() == set()

    def test_returns_the_stored_set(self):
        suite_config.save_value(_KEY, ["TAG1", "TAG2"])
        assert load_kept_tags() == {"TAG1", "TAG2"}

    def test_stored_empty_list_loads_empty(self):
        suite_config.save_value(_KEY, [])
        assert load_kept_tags() == set()

    def test_a_non_list_value_loads_empty(self):
        suite_config.save_value(_KEY, "not_a_list")
        assert load_kept_tags() == set()

    def test_non_string_entries_are_dropped(self):
        suite_config.save_value(_KEY, ["TAG1", 3, None])
        assert load_kept_tags() == {"TAG1"}


class TestSaveKeptTags:
    def test_saves_sorted(self, isolated_config):
        save_kept_tags(["TAG_B", "TAG_A"])
        assert suite_config.load_value(_KEY) == ["TAG_A", "TAG_B"]

    def test_round_trips(self):
        save_kept_tags(["TAG1", "TAG2"])
        assert load_kept_tags() == {"TAG1", "TAG2"}

    def test_overwrites_the_previous_selection(self):
        save_kept_tags(["OLD"])
        save_kept_tags(["NEW"])
        assert load_kept_tags() == {"NEW"}

    def test_writes_no_file_into_the_package_folder(self, tmp_path):
        package = tmp_path / "package"
        package.mkdir()
        tag_prefs.LEGACY_PREFS_PATH = package / "tag_prefs.json"

        save_kept_tags(["TAG"])

        assert list(package.iterdir()) == []


class TestLegacyMigration:
    def _write_legacy(self, path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        return path

    def test_imports_and_deletes_the_old_file(self):
        legacy = self._write_legacy(
            tag_prefs.LEGACY_PREFS_PATH,
            json.dumps({"kept_tags": ["TAG_B", "TAG_A"]}),
        )

        assert load_kept_tags() == {"TAG_A", "TAG_B"}
        assert not legacy.exists()

    def test_saving_also_migrates_first(self):
        legacy = self._write_legacy(
            tag_prefs.LEGACY_PREFS_PATH, json.dumps({"kept_tags": ["OLD"]})
        )

        save_kept_tags(["NEW"])

        assert not legacy.exists()
        assert load_kept_tags() == {"NEW"}

    def test_a_stored_selection_wins_over_the_legacy_file(self):
        suite_config.save_value(_KEY, ["FRESH"])
        legacy = self._write_legacy(
            tag_prefs.LEGACY_PREFS_PATH, json.dumps({"kept_tags": ["STALE"]})
        )

        assert load_kept_tags() == {"FRESH"}
        assert legacy.exists()

    def test_a_malformed_legacy_file_is_left_in_place(self):
        legacy = self._write_legacy(tag_prefs.LEGACY_PREFS_PATH, "not valid json")

        assert load_kept_tags() == set()
        assert legacy.exists()

    def test_a_directory_in_place_of_the_file_is_ignored(self):
        tag_prefs.LEGACY_PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tag_prefs.LEGACY_PREFS_PATH.mkdir()

        assert load_kept_tags() == set()
