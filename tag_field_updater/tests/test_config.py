"""Tests for the action-group config (F-01) — one key in the shared config.

The groups live in ``audio_suite_config.json`` through
``audio_suite_shared.suite_config`` (no tool-local file), so every test here
redirects ``CONFIG_PATH`` and never touches the shipped config.

Reading is deliberately tolerant and writing is exact: a hand-edited or older
entry must not stop the tool from starting, and a group that cannot be
understood is skipped rather than guessed at — a half-read pattern list would
tag files nobody described.

Changed in 2.2.0: new — F-01.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from audio_suite_shared import suite_config
from tag_field_updater.utils import config


@pytest.fixture(autouse=True)
def isolated_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[Path, None, None]:
    """Point the shared suite config at ``tmp_path`` for every test here."""
    path = tmp_path / "audio_suite_config.json"
    monkeypatch.setattr(suite_config, "CONFIG_PATH", path)
    monkeypatch.setattr(suite_config, "_LOCK_PATH", path.with_suffix(".json.lock"))
    suite_config._invalidate_cache()
    yield path
    suite_config._invalidate_cache()


class TestRoundTrip:
    def test_saved_group_reads_back_verbatim(self) -> None:
        config.save_action_group(
            "Bandcamp", ("%track% %artist% - %title%", "%artist% - %title%")
        )

        group = config.get_action_group("Bandcamp")
        assert group is not None
        assert group.patterns == ("%track% %artist% - %title%", "%artist% - %title%")
        assert group.only_fill_blanks is True

    def test_the_write_mode_is_stored_with_the_patterns(self) -> None:
        config.save_action_group(
            "Loud", ("%artist% - %title%",), only_fill_blanks=False
        )
        group = config.get_action_group("Loud")
        assert group is not None
        assert group.only_fill_blanks is False

    def test_saving_a_second_group_keeps_the_first(self) -> None:
        config.save_action_group("One", ("%artist% - %title%",))
        config.save_action_group("Two", ("%track%. %title%",))

        assert set(config.load_action_groups()) == {"One", "Two"}

    def test_a_group_is_replaceable_by_name(self) -> None:
        config.save_action_group("One", ("%artist% - %title%",))
        config.save_action_group("One", ("%track% - %artist% - %title%",))

        groups = config.load_action_groups()
        assert groups["One"].patterns == ("%track% - %artist% - %title%",)

    def test_names_and_patterns_are_trimmed(self) -> None:
        config.save_action_group("  Spaced  ", ("  %artist% - %title%  ", "   "))
        group = config.get_action_group("Spaced")
        assert group is not None
        assert group.patterns == ("%artist% - %title%",)

    def test_deleting_removes_only_that_group(self) -> None:
        config.save_action_group("One", ("%artist% - %title%",))
        config.save_action_group("Two", ("%track%. %title%",))

        assert config.delete_action_group("One") is True
        assert set(config.load_action_groups()) == {"Two"}

    def test_deleting_an_unknown_group_reports_it(self) -> None:
        assert config.delete_action_group("Nope") is False


class TestValidation:
    def test_a_blank_name_is_refused(self) -> None:
        with pytest.raises(ValueError, match="needs a name"):
            config.save_action_group("   ", ("%artist% - %title%",))

    def test_an_empty_pattern_list_is_refused(self) -> None:
        with pytest.raises(ValueError, match="at least one filename pattern"):
            config.save_action_group("Empty", ())

    def test_a_blank_pattern_list_is_refused(self) -> None:
        with pytest.raises(ValueError, match="at least one filename pattern"):
            config.save_action_group("Blank", ("  ", ""))


class TestMalformedConfig:
    def test_a_non_object_value_reads_as_no_groups(self) -> None:
        suite_config.save_value(config.ACTION_GROUPS_KEY, ["not", "an", "object"])
        assert config.load_action_groups() == {}

    @pytest.mark.parametrize(
        "entry",
        [
            {"patterns": []},
            {"patterns": "not-a-list"},
            {"patterns": ["  "]},
            {"patterns": [1, 2]},
            "strings-are-not-groups",
        ],
    )
    def test_an_unusable_entry_is_skipped_not_guessed(self, entry: object) -> None:
        suite_config.save_value(
            config.ACTION_GROUPS_KEY,
            {"Good": {"patterns": ["%artist% - %title%"]}, "Bad": entry},
        )

        groups = config.load_action_groups()
        assert set(groups) == {"Good"}

    def test_a_missing_key_reads_as_no_groups(self) -> None:
        assert config.load_action_groups() == {}

    def test_a_non_boolean_mode_falls_back_to_filling_blanks(self) -> None:
        suite_config.save_value(
            config.ACTION_GROUPS_KEY,
            {"Odd": {"patterns": ["%artist% - %title%"], "only_fill_blanks": "yes"}},
        )

        group = config.get_action_group("Odd")
        assert group is not None
        assert group.only_fill_blanks is True
