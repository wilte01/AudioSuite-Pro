"""
Tests for cd_ripper.core.cd_ripper_config

Coverage strategy
-----------------
- load/save/get_output_dir/set_output_dir round-trip through the shared
  ``audio_suite_shared.suite_config`` (real functions, CONFIG_PATH redirected
  to tmp_path so the real ``audio_suite_config.json`` is never touched).
- migrate_legacy reads a legacy ``cd_ripper_prefs.json`` into the shared
  config (guarded: fresh shared value wins), then deletes the legacy file.
- get_log_path returns the package-local ``cd_ripper.log`` path.

All tests use tmp_path via the ``isolated_config`` fixture.
"""

import json
from pathlib import Path

import pytest

import audio_suite_shared.suite_config as sc
from cd_ripper.core import cd_ripper_config

_KEY_OUTPUT_DIR = "cd_ripper_output_dir"


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Redirect suite_config.CONFIG_PATH to a temp file for every test."""
    config_file = tmp_path / "audio_suite_config.json"
    monkeypatch.setattr(sc, "CONFIG_PATH", config_file)
    sc._invalidate_cache()
    monkeypatch.setattr(
        cd_ripper_config,
        "_legacy_config_path",
        lambda legacy_path="": tmp_path / "no_legacy_here.json",
    )
    yield config_file


# ===========================================================================
# load
# ===========================================================================


class TestLoad:
    def test_returns_empty_dict_when_nothing_saved(self) -> None:
        assert cd_ripper_config.load() == {}

    def test_returns_saved_output_dir(self) -> None:
        cd_ripper_config.set_output_dir("/music")
        assert cd_ripper_config.load() == {"output_dir": "/music"}

    def test_returns_empty_dict_when_saved_value_not_a_string(self) -> None:
        sc.save_value(_KEY_OUTPUT_DIR, 12345)
        assert cd_ripper_config.load() == {}


# ===========================================================================
# save
# ===========================================================================


class TestSave:
    def test_writes_output_dir(self) -> None:
        cd_ripper_config.save({"output_dir": "/some/path"})
        assert cd_ripper_config.get_output_dir() == "/some/path"

    def test_empty_dict_is_no_op(self) -> None:
        cd_ripper_config.save({})
        assert cd_ripper_config.load() == {}

    def test_non_string_output_dir_ignored(self) -> None:
        cd_ripper_config.save({"output_dir": 42})
        assert cd_ripper_config.load() == {}


# ===========================================================================
# get_output_dir
# ===========================================================================


class TestGetOutputDir:
    def test_returns_stored_output_dir(self) -> None:
        cd_ripper_config.set_output_dir("/music/rips")
        assert cd_ripper_config.get_output_dir() == "/music/rips"

    def test_returns_empty_string_when_no_prefs(self) -> None:
        assert cd_ripper_config.get_output_dir() == ""

    def test_returns_empty_string_when_key_absent(self) -> None:
        sc.save_value("other_key", "value")
        assert cd_ripper_config.get_output_dir() == ""


# ===========================================================================
# set_output_dir
# ===========================================================================


class TestSetOutputDir:
    def test_persists_path_retrievable_by_get(self) -> None:
        cd_ripper_config.set_output_dir("/my/music")
        assert cd_ripper_config.get_output_dir() == "/my/music"

    def test_overwrites_previous_path(self) -> None:
        cd_ripper_config.set_output_dir("/first")
        cd_ripper_config.set_output_dir("/second")
        assert cd_ripper_config.get_output_dir() == "/second"

    def test_returns_none(self) -> None:
        result = cd_ripper_config.set_output_dir("/path")
        assert result is None


# ===========================================================================
# migrate_legacy
# ===========================================================================


@pytest.fixture
def real_legacy(tmp_path, monkeypatch):
    """Write a legacy file to tmp_path and point _legacy_config_path at it."""

    def _make(content: object) -> Path:
        legacy = tmp_path / "cd_ripper_prefs.json"
        if isinstance(content, str):
            legacy.write_text(content, encoding="utf-8")
        else:
            legacy.write_text(json.dumps(content), encoding="utf-8")
        monkeypatch.setattr(
            cd_ripper_config,
            "_legacy_config_path",
            lambda legacy_path="": legacy,
        )
        return legacy

    return _make


class TestMigrateLegacy:
    def test_no_legacy_file_is_noop(self) -> None:
        cd_ripper_config.migrate_legacy(str(Path("/missing/cd_ripper_prefs.json")))
        assert cd_ripper_config.load() == {}

    def test_legacy_output_dir_migrated_and_file_deleted(self, real_legacy) -> None:
        legacy = real_legacy({"output_dir": "/legacy/ripped"})
        cd_ripper_config.migrate_legacy(str(legacy))
        assert cd_ripper_config.get_output_dir() == "/legacy/ripped"
        assert not legacy.exists()

    def test_existing_shared_value_wins_over_legacy(self, real_legacy) -> None:
        cd_ripper_config.set_output_dir("/already/saved")
        legacy = real_legacy({"output_dir": "/legacy/ripped"})
        cd_ripper_config.migrate_legacy(str(legacy))
        assert cd_ripper_config.get_output_dir() == "/already/saved"
        assert not legacy.exists()

    def test_corrupt_legacy_file_left_untouched(self, real_legacy) -> None:
        legacy = real_legacy("{not valid json")
        cd_ripper_config.migrate_legacy(str(legacy))
        assert legacy.exists()


# ===========================================================================
# get_log_path
# ===========================================================================


class TestGetLogPath:
    def test_returns_log_in_cd_ripper_package_folder(self) -> None:
        result = Path(cd_ripper_config.get_log_path())
        expected_dir = Path(__file__).resolve().parent.parent
        assert result.parent == expected_dir
        assert result.name == "cd_ripper.log"

    def test_real_module_level_log_path_sits_in_package_folder(self) -> None:
        module_dir = Path(cd_ripper_config.__file__).resolve().parent.parent
        assert Path(cd_ripper_config._LOG_PATH).parent == module_dir
        assert Path(cd_ripper_config._LOG_PATH).name == "cd_ripper.log"
