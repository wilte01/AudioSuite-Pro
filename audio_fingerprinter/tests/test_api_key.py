"""Tests for audio_fingerprinter.utils.api_key."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from audio_fingerprinter.utils.api_key import (
    CONFIG_KEY,
    ENV_VAR,
    clear_api_key,
    get_key_manager,
    has_api_key,
    load_api_key,
    save_api_key,
)


class TestGetKeyManager:
    @patch("audio_fingerprinter.utils.api_key.KeyManager")
    def test_returns_key_manager(self, mock_cls):
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        result = get_key_manager()
        assert result is mock_instance
        mock_cls.assert_called_once()

    @patch("audio_fingerprinter.utils.api_key.KeyManager")
    def test_construction_exception_raises(self, mock_cls):
        mock_cls.side_effect = OSError("config missing")
        with pytest.raises(OSError):
            get_key_manager()


class TestLoadApiKey:
    @patch("audio_fingerprinter.utils.api_key.os.environ", {})
    @patch("audio_fingerprinter.utils.api_key.load_value", return_value="")
    def test_no_key_returns_empty(self, mock_load):
        result = load_api_key()
        assert result == ""

    @patch("audio_fingerprinter.utils.api_key.os.environ", {ENV_VAR: "env_key"})
    def test_env_var_takes_priority(self):
        result = load_api_key()
        assert result == "env_key"

    @patch("audio_fingerprinter.utils.api_key.os.environ", {})
    @patch("audio_fingerprinter.utils.api_key.load_value", return_value="encrypted_val")
    @patch("audio_fingerprinter.utils.api_key.get_key_manager")
    def test_stored_key_decrypted(self, mock_km, mock_load):
        mock_km.return_value.decrypt_string.return_value = "decrypted_key"
        result = load_api_key()
        assert result == "decrypted_key"

    @patch("audio_fingerprinter.utils.api_key.os.environ", {})
    @patch("audio_fingerprinter.utils.api_key.load_value", return_value="encrypted_val")
    @patch("audio_fingerprinter.utils.api_key.get_key_manager")
    def test_decrypt_failure_returns_empty(self, mock_km, mock_load):
        from audio_suite_shared.exceptions import AudioProcessingError

        mock_km.return_value.decrypt_string.side_effect = AudioProcessingError("bad")
        result = load_api_key()
        assert result == ""

    @patch("audio_fingerprinter.utils.api_key.os.environ", {ENV_VAR: "  env_key  "})
    def test_env_var_stripped(self):
        result = load_api_key()
        assert result == "env_key"


class TestSaveApiKey:
    @patch("audio_fingerprinter.utils.api_key.save_value")
    @patch("audio_fingerprinter.utils.api_key.get_key_manager")
    def test_encrypts_and_saves(self, mock_km, mock_save):
        mock_km.return_value.encrypt_string.return_value = "encrypted"
        save_api_key("my_key")
        mock_km.return_value.encrypt_string.assert_called_once_with("my_key")
        mock_save.assert_called_once_with(CONFIG_KEY, "encrypted")

    @patch("audio_fingerprinter.utils.api_key.save_value")
    @patch("audio_fingerprinter.utils.api_key.get_key_manager")
    def test_empty_key_clears(self, mock_km, mock_save):
        save_api_key("")
        mock_save.assert_called_once_with(CONFIG_KEY, "")

    @patch("audio_fingerprinter.utils.api_key.save_value")
    @patch("audio_fingerprinter.utils.api_key.get_key_manager")
    def test_stripped_whitespace(self, mock_km, mock_save):
        mock_km.return_value.encrypt_string.return_value = "enc"
        save_api_key("  key  ")
        mock_km.return_value.encrypt_string.assert_called_once_with("key")


class TestClearApiKey:
    @patch("audio_fingerprinter.utils.api_key.save_value")
    def test_clears(self, mock_save):
        clear_api_key()
        mock_save.assert_called_once_with(CONFIG_KEY, "")


class TestHasApiKey:
    @patch("audio_fingerprinter.utils.api_key.load_api_key", return_value="")
    def test_no_key(self, mock_load):
        assert has_api_key() is False

    @patch("audio_fingerprinter.utils.api_key.load_api_key", return_value="key")
    def test_has_key(self, mock_load):
        assert has_api_key() is True
