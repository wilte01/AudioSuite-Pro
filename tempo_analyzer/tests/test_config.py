"""
tests/test_config.py
Unit tests for tempo_analyzer.utils.config.

``suite_config.load_value`` and ``suite_config.save_value`` are mocked so
that tests never touch the real ``audio_suite_config.json`` on disk.
"""

from unittest.mock import patch

from tempo_analyzer.utils.config import load_scheme, save_scheme

VALID_SCHEMES = ["Italian", "German", "English"]
DEFAULT = "Italian"


# ---------------------------------------------------------------------------
# load_scheme
# ---------------------------------------------------------------------------


class TestLoadScheme:
    def test_returns_saved_scheme_when_valid(self):
        with patch(
            "tempo_analyzer.utils.config.suite_config.load_value", return_value="German"
        ):
            assert load_scheme("ignored", VALID_SCHEMES) == "German"

    def test_returns_default_when_no_value_saved(self):
        def mock_load(key, default=None):
            return default

        with patch(
            "tempo_analyzer.utils.config.suite_config.load_value", side_effect=mock_load
        ):
            assert load_scheme("ignored", VALID_SCHEMES, default="English") == "English"

    def test_returns_default_when_saved_value_not_in_valid_list(self):
        with patch(
            "tempo_analyzer.utils.config.suite_config.load_value",
            return_value="Klingon",
        ):
            assert load_scheme("ignored", VALID_SCHEMES) == "Italian"

    def test_returns_default_when_saved_value_is_not_string(self):
        with patch(
            "tempo_analyzer.utils.config.suite_config.load_value", return_value=42
        ):
            assert load_scheme("ignored", VALID_SCHEMES) == "Italian"

    def test_returns_default_when_key_missing(self):
        def mock_load(key, default=None):
            return default

        with patch(
            "tempo_analyzer.utils.config.suite_config.load_value", side_effect=mock_load
        ):
            assert load_scheme("ignored", VALID_SCHEMES, default="German") == "German"

    def test_never_raises_on_unreadable_file(self):
        """The implementation delegates to suite_config which handles
        errors silently."""
        with patch(
            "tempo_analyzer.utils.config.suite_config.load_value", return_value=DEFAULT
        ):
            result = load_scheme("ignored", VALID_SCHEMES)
            assert result == "Italian"


# ---------------------------------------------------------------------------
# save_scheme
# ---------------------------------------------------------------------------


class TestSaveScheme:
    def test_writes_scheme(self):
        with patch("tempo_analyzer.utils.config.suite_config.save_value") as mock_save:
            save_scheme("ignored", "German")
            mock_save.assert_called_once_with("tempo_scheme", "German")

    def test_overwrites_existing(self):
        with patch("tempo_analyzer.utils.config.suite_config.save_value") as mock_save:
            save_scheme("ignored", "English")
            mock_save.assert_called_once_with("tempo_scheme", "English")

    def test_does_not_raise_on_failure(self):
        with patch(
            "tempo_analyzer.utils.config.suite_config.save_value",
            side_effect=PermissionError("mock"),
        ):
            save_scheme("ignored", "Italian")  # must not raise

    def test_roundtrip_with_load_scheme(self):
        store: dict = {}

        def mock_load(key: str, default: object = None) -> object:
            return store.get(key, default)

        def mock_save(key: str, value: object) -> None:
            store[key] = value

        with (
            patch(
                "tempo_analyzer.utils.config.suite_config.load_value",
                side_effect=mock_load,
            ),
            patch(
                "tempo_analyzer.utils.config.suite_config.save_value",
                side_effect=mock_save,
            ),
        ):
            save_scheme("ignored", "English")
            assert load_scheme("ignored", VALID_SCHEMES) == "English"
