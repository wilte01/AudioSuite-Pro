"""
Tests for metadata_scrubber.utils.tag_prefs
Gap: no tests existed for tag_prefs persistence layer.
"""

import json
import os

from metadata_scrubber.utils.tag_prefs import (
    _prefs_path,
    load_kept_tags,
    save_kept_tags,
)


class TestPrefsPath:
    def test_returns_path_with_filename(self, tmp_path):
        result = _prefs_path(str(tmp_path))
        assert result == os.path.join(str(tmp_path), "tag_prefs.json")

    def test_returns_absolute_path(self, tmp_path):
        result = _prefs_path(str(tmp_path))
        assert os.path.isabs(result)


class TestLoadKeptTags:
    def test_returns_set_when_file_exists(self, tmp_path):
        data = {"kept_tags": ["TAG1", "TAG2"]}
        path = os.path.join(str(tmp_path), "tag_prefs.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        result = load_kept_tags(str(tmp_path))
        assert result == {"TAG1", "TAG2"}

    def test_returns_empty_set_when_file_missing(self, tmp_path):
        result = load_kept_tags(str(tmp_path))
        assert result == set()

    def test_returns_empty_set_when_malformed_json(self, tmp_path):
        path = os.path.join(str(tmp_path), "tag_prefs.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("not valid json")
        result = load_kept_tags(str(tmp_path))
        assert result == set()

    def test_returns_empty_set_when_empty_tags_list(self, tmp_path):
        data = {"kept_tags": []}
        path = os.path.join(str(tmp_path), "tag_prefs.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        result = load_kept_tags(str(tmp_path))
        assert result == set()

    def test_returns_empty_set_when_key_missing(self, tmp_path):
        data = {"other_key": ["val"]}
        path = os.path.join(str(tmp_path), "tag_prefs.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        result = load_kept_tags(str(tmp_path))
        assert result == set()

    def test_handles_non_list_kept_tags(self, tmp_path):
        data = {"kept_tags": "not_a_list"}
        path = os.path.join(str(tmp_path), "tag_prefs.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        result = load_kept_tags(str(tmp_path))
        assert result == set()

    def test_handles_directory_collision_gracefully(self, tmp_path):
        path = os.path.join(str(tmp_path), "tag_prefs.json")
        os.mkdir(path)
        result = load_kept_tags(str(tmp_path))
        assert result == set()


class TestSaveKeptTags:
    def test_saves_and_can_reload(self, tmp_path):
        save_kept_tags(str(tmp_path), ["TAG1", "TAG2"])
        result = load_kept_tags(str(tmp_path))
        assert result == {"TAG1", "TAG2"}

    def test_saves_sorted(self, tmp_path):
        save_kept_tags(str(tmp_path), ["TAG_B", "TAG_A"])
        path = os.path.join(str(tmp_path), "tag_prefs.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["kept_tags"] == sorted(["TAG_B", "TAG_A"])

    def test_overwrites_existing_file(self, tmp_path):
        save_kept_tags(str(tmp_path), ["OLD"])
        save_kept_tags(str(tmp_path), ["NEW"])
        result = load_kept_tags(str(tmp_path))
        assert result == {"NEW"}

    def test_empty_list_saves_and_reloads(self, tmp_path):
        save_kept_tags(str(tmp_path), [])
        result = load_kept_tags(str(tmp_path))
        assert result == set()

    def test_oserror_not_raised(self, tmp_path):
        save_kept_tags(str(tmp_path / "no_such_dir"), ["TAG"])
