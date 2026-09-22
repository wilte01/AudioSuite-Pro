"""
Tests for audio_suite_shared.suite_config
Gap G-03: load_*/save_* round-trips, defaults, corrupt/missing file recovery

Strategy: monkey-patch CONFIG_PATH so tests write to tmp_path, never the
real suite root. Each test gets an isolated directory.
"""

import json
from pathlib import Path

import pytest

import audio_suite_shared.suite_config as sc


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Redirect CONFIG_PATH to a temp file for every test."""
    config_file = tmp_path / "audio_suite_config.json"
    monkeypatch.setattr(sc, "CONFIG_PATH", config_file)
    sc._invalidate_cache()  # clear stale data from previous CONFIG_PATH
    yield config_file


# ── _load / _save internals ───────────────────────────────────────────────────


class TestLoadSave:
    def test_load_returns_empty_dict_when_file_missing(self, isolated_config):
        assert not isolated_config.exists()
        assert sc._load() == {}

    def test_save_then_load_round_trips(self, isolated_config):
        sc._save({"key": "value", "number": 42})
        data = sc._load()
        assert data["key"] == "value"
        assert data["number"] == 42

    def test_load_returns_empty_dict_on_corrupt_json(self, isolated_config):
        isolated_config.write_text("{ this is not valid json !!!", encoding="utf-8")
        assert sc._load() == {}

    def test_load_returns_empty_dict_on_empty_file(self, isolated_config):
        isolated_config.write_text("", encoding="utf-8")
        assert sc._load() == {}

    def test_save_does_not_raise_on_write_error(self, isolated_config, monkeypatch):
        """_save swallows exceptions silently."""
        monkeypatch.setattr(
            sc, "CONFIG_PATH", Path("/root/cannot_write_here/config.json")
        )
        sc._save({"x": 1})  # must not raise

    def test_load_fixes_non_string_last_directory(self, isolated_config):
        isolated_config.write_text(json.dumps({"last_directory": 99}), encoding="utf-8")
        data = sc._load()
        assert data["last_directory"] == ""

    def test_load_fixes_broken_window_geometry_value(self, isolated_config):
        isolated_config.write_text(
            json.dumps({"key_detector_window": 123}), encoding="utf-8"
        )
        data = sc._load()
        assert isinstance(data["key_detector_window"], str)

    def test_load_fixes_non_dict_font_sizes(self, isolated_config):
        isolated_config.write_text(json.dumps({"font_sizes": "bad"}), encoding="utf-8")
        data = sc._load()
        assert data["font_sizes"] == {}

    def test_load_preserves_valid_window_geometry(self, isolated_config):
        geom = "1200x800+50+50"
        isolated_config.write_text(
            json.dumps({"bpm_analyzer_window": geom}), encoding="utf-8"
        )
        data = sc._load()
        assert data["bpm_analyzer_window"] == geom


# ── last_directory ────────────────────────────────────────────────────────────


class TestLastDirectory:
    def test_default_is_empty_string(self):
        assert sc.load_last_directory() == ""

    def test_round_trip(self, tmp_path):
        path = str(tmp_path)
        sc.save_last_directory(path)
        assert sc.load_last_directory() == path

    def test_overwrite_preserves_other_keys(self, isolated_config):
        sc.save_palette("Ocean")
        sc.save_last_directory("/music")
        assert sc.load_palette() == "Ocean"
        assert sc.load_last_directory() == "/music"

    def test_save_empty_string(self):
        sc.save_last_directory("")
        assert sc.load_last_directory() == ""


# ── palette ───────────────────────────────────────────────────────────────────


class TestPalette:
    def test_default_is_purple(self):
        assert sc.load_palette() == "Purple"

    def test_round_trip(self):
        sc.save_palette("Ocean")
        assert sc.load_palette() == "Ocean"

    def test_multiple_saves_last_wins(self):
        sc.save_palette("Red")
        sc.save_palette("Blue")
        assert sc.load_palette() == "Blue"

    def test_preserves_other_keys(self):
        sc.save_theme_mode("Dark")
        sc.save_palette("Green")
        assert sc.load_theme_mode() == "Dark"


# ── theme_mode ────────────────────────────────────────────────────────────────


class TestThemeMode:
    def test_default_is_light(self):
        assert sc.load_theme_mode() == "Light"

    def test_round_trip(self):
        sc.save_theme_mode("Dark")
        assert sc.load_theme_mode() == "Dark"

    def test_overwrite(self):
        sc.save_theme_mode("Dark")
        sc.save_theme_mode("Light")
        assert sc.load_theme_mode() == "Light"


# ── font_family ───────────────────────────────────────────────────────────────


class TestFontFamily:
    def test_default_is_arial(self):
        assert sc.load_font_family() == "Arial"

    def test_round_trip(self):
        sc.save_font_family("Helvetica")
        assert sc.load_font_family() == "Helvetica"

    def test_preserves_other_keys(self):
        sc.save_palette("Purple")
        sc.save_font_family("Courier")
        assert sc.load_palette() == "Purple"


# ── font_sizes ────────────────────────────────────────────────────────────────


class TestFontSizes:
    def test_default_contains_all_expected_keys(self):
        sizes = sc.load_font_sizes()
        expected = {
            "Header",
            "Title_L",
            "Title",
            "Button",
            "Label",
            "Body",
            "Caption",
            "Micro",
            "Mono",
        }
        assert expected.issubset(set(sizes.keys()))

    def test_defaults_are_integers(self):
        for key, val in sc.load_font_sizes().items():
            assert isinstance(val, int), f"Expected int for {key}, got {type(val)}"

    def test_round_trip_partial_override(self):
        sc.save_font_sizes({"Header": 20, "Body": 12})
        sizes = sc.load_font_sizes()
        assert sizes["Header"] == 20
        assert sizes["Body"] == 12

    def test_saved_sizes_merged_with_defaults(self):
        """Only saved keys override defaults; missing keys revert to defaults."""
        defaults = sc.load_font_sizes()
        sc.save_font_sizes({"Header": 99})
        sizes = sc.load_font_sizes()
        assert sizes["Header"] == 99
        # Other defaults should be intact
        assert sizes["Body"] == defaults["Body"]

    def test_unknown_keys_in_saved_sizes_are_ignored(self):
        sc.save_font_sizes({"Header": 18, "NonExistentKey": 99})
        sizes = sc.load_font_sizes()
        assert "NonExistentKey" not in sizes


# ── load_value / save_value ───────────────────────────────────────────────────


class TestGenericValue:
    def test_missing_key_returns_default(self):
        assert sc.load_value("nonexistent_key") is None

    def test_missing_key_returns_custom_default(self):
        assert sc.load_value("nonexistent_key", default="fallback") == "fallback"

    def test_round_trip_string(self):
        sc.save_value("custom_key", "hello")
        assert sc.load_value("custom_key") == "hello"

    def test_round_trip_integer(self):
        sc.save_value("my_int", 42)
        assert sc.load_value("my_int") == 42

    def test_round_trip_dict(self):
        sc.save_value("my_dict", {"a": 1, "b": [1, 2, 3]})
        assert sc.load_value("my_dict") == {"a": 1, "b": [1, 2, 3]}

    def test_overwrite_value(self):
        sc.save_value("k", "first")
        sc.save_value("k", "second")
        assert sc.load_value("k") == "second"

    def test_save_preserves_existing_keys(self):
        sc.save_value("alpha", "A")
        sc.save_value("beta", "B")
        assert sc.load_value("alpha") == "A"
        assert sc.load_value("beta") == "B"

    def test_returns_none_for_truly_absent_key_after_other_saves(self):
        sc.save_value("present", 1)
        assert sc.load_value("absent") is None


# ── JSON persistence ──────────────────────────────────────────────────────────


class TestPersistenceFormat:
    def test_saved_file_is_valid_json(self, isolated_config):
        sc.save_last_directory("/test")
        sc.save_palette("Red")
        with open(isolated_config, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["last_directory"] == "/test"
        assert data["palette"] == "Red"

    def test_multiple_independent_saves_accumulate(self, isolated_config):
        sc.save_last_directory("/music")
        sc.save_theme_mode("Dark")
        sc.save_font_family("Verdana")
        with open(isolated_config, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["last_directory"] == "/music"
        assert data["theme_mode"] == "Dark"
        assert data["font_family"] == "Verdana"


# ── presets ─────────────────────────────────────────────────────────────────


class TestPresets:
    def test_list_empty_when_none_saved(self, isolated_config):
        assert sc.list_presets("converter") == []

    def test_save_and_list(self, isolated_config):
        sc.save_preset("converter", "Archive FLAC", {"format": "flac", "quality": "8"})
        sc.save_preset("converter", "Streaming MP3", {"format": "mp3", "quality": "2"})
        names = sc.list_presets("converter")
        assert "Archive FLAC" in names
        assert "Streaming MP3" in names
        assert len(names) == 2

    def test_load_preset(self, isolated_config):
        settings = {"format": "flac", "quality": "8", "delete_originals": False}
        sc.save_preset("converter", "Best", settings)
        loaded = sc.load_preset("converter", "Best")
        assert loaded == settings

    def test_load_nonexistent_returns_none(self, isolated_config):
        assert sc.load_preset("converter", "DoesNotExist") is None

    def test_delete_preset(self, isolated_config):
        sc.save_preset("converter", "Temp", {"x": 1})
        sc.save_preset("converter", "Keep", {"y": 2})
        sc.delete_preset("converter", "Temp")
        assert sc.list_presets("converter") == ["Keep"]

    def test_delete_nonexistent_does_not_raise(self, isolated_config):
        sc.delete_preset("converter", "Nothing")  # must not raise

    def test_presets_are_tool_scoped(self, isolated_config):
        sc.save_preset("tool_a", "Preset A", {"v": 1})
        sc.save_preset("tool_b", "Preset B", {"v": 2})
        assert sc.list_presets("tool_a") == ["Preset A"]
        assert sc.list_presets("tool_b") == ["Preset B"]

    def test_overwrite_preset(self, isolated_config):
        sc.save_preset("converter", "Mine", {"format": "mp3"})
        sc.save_preset("converter", "Mine", {"format": "flac", "quality": "8"})
        loaded = sc.load_preset("converter", "Mine")
        assert loaded == {"format": "flac", "quality": "8"}

    def test_presets_persist_across_cache_invalidation(self, isolated_config):
        sc.save_preset("converter", "My Preset", {"format": "wav"})
        sc._invalidate_cache()
        assert sc.load_preset("converter", "My Preset") == {"format": "wav"}

    def test_presets_preserve_existing_config_keys(self, isolated_config):
        sc.save_last_directory("/music")
        sc.save_preset("converter", "Default", {"format": "flac"})
        assert sc.load_last_directory() == "/music"
        assert sc.load_preset("converter", "Default") == {"format": "flac"}


# ── error/fallback internals ─────────────────────────────────────────────────


class TestLoadSaveErrorPaths:
    def test_load_oserror_on_read_returns_empty(self, tmp_path, monkeypatch):
        """A config path that exists but cannot be opened (e.g. a
        directory, or a locked file) yields {} without raising."""
        config_dir = tmp_path / "audio_suite_config.json"
        config_dir.mkdir()
        monkeypatch.setattr(sc, "CONFIG_PATH", config_dir)
        sc._invalidate_cache()
        assert sc._load() == {}

    def test_save_rename_failure_falls_back_to_direct_write(
        self, isolated_config, monkeypatch
    ):
        """Windows anti-virus locks can break the atomic rename; the
        direct-write fallback must still persist the config."""
        import os as os_mod

        def _locked_replace(*args, **kwargs):
            raise OSError("file locked by another process")

        monkeypatch.setattr(os_mod, "replace", _locked_replace)
        sc._save({"key": "value"})
        with open(isolated_config, "r", encoding="utf-8") as f:
            assert json.load(f) == {"key": "value"}


class TestTmpFileHygiene:
    def test_cleanup_removes_only_other_processes_tmps(self, isolated_config, tmp_path):
        import os as os_mod

        other = tmp_path / "audio_suite_config.json.tmp.999999"
        other.write_text("stale", encoding="utf-8")
        mine = tmp_path / f"audio_suite_config.json.tmp.{os_mod.getpid()}"
        mine.write_text("mine", encoding="utf-8")
        nondigit = tmp_path / "audio_suite_config.json.tmp.abc"
        nondigit.write_text("x", encoding="utf-8")

        sc._cleanup_stale_tmps()

        assert not other.exists()
        assert mine.exists()
        assert nondigit.exists()

    def test_cleanup_swallows_unlink_errors(self, isolated_config, tmp_path):
        """A read-only stale tmp (Windows PermissionError) must be
        skipped, not crash the save pipeline."""

        locked = tmp_path / "audio_suite_config.json.tmp.999998"
        locked.write_text("locked", encoding="utf-8")
        locked.chmod(0o444)
        try:
            sc._cleanup_stale_tmps()  # must not raise
        finally:
            locked.chmod(0o666)

    def test_try_unlink_swallows_missing_path(self, isolated_config, tmp_path):
        sc._try_unlink(tmp_path / "definitely_not_here.json")  # must not raise


# ── window geometry ──────────────────────────────────────────────────────────


class TestWindowGeometry:
    def test_default_geometry(self, isolated_config):
        assert sc.load_window_geometry("key_detector") == "800x600+100+100"

    def test_round_trip(self, isolated_config):
        sc.save_window_geometry("key_detector", "1024x768+10+10")
        assert sc.load_window_geometry("key_detector") == "1024x768+10+10"


# ── batch tool duration tracking ─────────────────────────────────────────────


class TestToolDurations:
    def test_default_is_empty_list(self, isolated_config):
        assert sc.load_tool_durations("bpm_analyzer") == []

    def test_average_none_without_history(self, isolated_config):
        assert sc.load_average_tool_duration("bpm_analyzer") is None

    def test_save_and_average(self, isolated_config):
        sc.save_tool_duration("bpm_analyzer", 12.5)
        sc.save_tool_duration("bpm_analyzer", 13.5)
        assert sc.load_tool_durations("bpm_analyzer") == [12.5, 13.5]
        assert sc.load_average_tool_duration("bpm_analyzer") == 13.0

    def test_history_capped_at_last_ten(self, isolated_config):
        for i in range(12):
            sc.save_tool_duration("tool", float(i))
        history = sc.load_tool_durations("tool")
        assert len(history) == 10
        assert history[0] == 2.0
        assert history[-1] == 11.0

    def test_tools_are_tracked_independently(self, isolated_config):
        sc.save_tool_duration("tool_a", 1.0)
        sc.save_tool_duration("tool_b", 2.0)
        assert sc.load_tool_durations("tool_a") == [1.0]
        assert sc.load_tool_durations("tool_b") == [2.0]

    def test_save_batch_durations(self, isolated_config):
        sc.save_batch_durations({"tool_a": 1.5, "tool_b": 2.5})
        assert sc.load_tool_durations("tool_a") == [1.5]
        assert sc.load_tool_durations("tool_b") == [2.5]


# ── master-driver app-state bridges ──────────────────────────────────────────


class TestAppStateBridges:
    def test_load_app_state_with_missing_attrs_does_not_raise(self, isolated_config):
        """A state object lacking any expected attribute is tolerated —
        each miss is logged at debug and skipped."""
        sc.load_app_state(object())  # must not raise

    def test_save_app_state_with_missing_attrs_does_not_raise(self, isolated_config):
        sc.save_app_state(object())  # must not raise

    def test_save_app_state_persists_all_fields(self, isolated_config):
        from types import SimpleNamespace

        state = SimpleNamespace(
            dir_path=SimpleNamespace(get=lambda: "/music"),
            palette_var=SimpleNamespace(get=lambda: "Ocean"),
            font_family_var=SimpleNamespace(get=lambda: "Verdana"),
            theme_mode_var=SimpleNamespace(get=lambda: "Dark"),
            font_sizes_vars={"Header": SimpleNamespace(get=lambda: 18)},
        )
        sc.save_app_state(state)
        assert sc.load_last_directory() == "/music"
        assert sc.load_palette() == "Ocean"
        assert sc.load_font_family() == "Verdana"
        assert sc.load_theme_mode() == "Dark"
        assert sc.load_font_sizes()["Header"] == 18

    def test_load_app_state_populates_state_vars(self, isolated_config):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        sc.save_last_directory("/music")
        sc.save_palette("Ocean")
        sc.save_theme_mode("Dark")
        sc.save_font_family("Verdana")
        sc.save_font_sizes({"Header": 18})

        state = SimpleNamespace(
            dir_path=MagicMock(),
            palette_var=MagicMock(),
            font_family_var=MagicMock(),
            theme_mode_var=MagicMock(),
            font_sizes_vars={"Header": MagicMock()},
        )
        sc.load_app_state(state)
        state.dir_path.set.assert_called_once_with("/music")
        state.palette_var.set.assert_called_once_with("Ocean")
        state.font_family_var.set.assert_called_once_with("Verdana")
        state.theme_mode_var.set.assert_called_once_with("Dark")
        state.font_sizes_vars["Header"].set.assert_called_once_with(18)
