"""test_config.py — config (shared suite_config delegation) tests."""

from unittest.mock import patch

from mood_analysis_batch_tagger.utils.config import load_run_mode, save_run_mode

CONFIG_MODULE = "mood_analysis_batch_tagger.utils.config.suite_config"


class TestLoadRunMode:
    def test_returns_saved_value(self) -> None:
        with patch(
            f"{CONFIG_MODULE}.load_value", return_value="Live Update"
        ) as mock_load:
            assert load_run_mode() == "Live Update"
        mock_load.assert_called_once_with("mood_analysis_batch_run_mode", "Dry Run")

    def test_default_when_nothing_saved(self) -> None:
        with patch(f"{CONFIG_MODULE}.load_value", return_value=None):
            assert load_run_mode() == "Dry Run"

    def test_rejects_invalid_value(self) -> None:
        with patch(f"{CONFIG_MODULE}.load_value", return_value="Turbo"):
            assert load_run_mode() == "Dry Run"

    def test_returns_default_on_exception(self) -> None:
        with patch(f"{CONFIG_MODULE}.load_value", side_effect=OSError("denied")):
            assert load_run_mode(default="Live Update") == "Live Update"

    def test_custom_default(self) -> None:
        with patch(f"{CONFIG_MODULE}.load_value", return_value=None) as mock_load:
            assert load_run_mode() == "Dry Run"
        mock_load.assert_called_once_with("mood_analysis_batch_run_mode", "Dry Run")


class TestSaveRunMode:
    def test_saves_value(self) -> None:
        with patch(f"{CONFIG_MODULE}.save_value") as mock_save:
            save_run_mode("", "Live Update")
        mock_save.assert_called_once_with("mood_analysis_batch_run_mode", "Live Update")

    def test_swallows_save_error(self) -> None:
        with patch(
            f"{CONFIG_MODULE}.save_value", side_effect=OSError("disk full")
        ) as mock_save:
            save_run_mode("", "Dry Run")
        mock_save.assert_called_once_with("mood_analysis_batch_run_mode", "Dry Run")
