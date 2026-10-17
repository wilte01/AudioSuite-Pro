"""Tests for audio_fingerprinter.utils.musicbrainz_token.

The token is the credential that turns a run into a public MusicBrainz edit, so
the tests pin the resolution order (environment wins over the encrypted store),
the encrypted round trip, and that a broken/missing value never becomes a
usable token.

Changed in 1.2.0: new suite for the Sprint 2 Item 2.3 submission credential.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from audio_fingerprinter.utils.musicbrainz_token import (
    CONFIG_KEY,
    ENV_VAR,
    build_auth,
    clear_token,
    describe_source,
    get_key_manager,
    has_token,
    load_token,
    save_token,
)


class TestGetKeyManager:
    @patch("audio_fingerprinter.utils.musicbrainz_token.KeyManager")
    def test_returns_key_manager(self, mock_cls):
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        assert get_key_manager() is mock_instance

    @patch("audio_fingerprinter.utils.musicbrainz_token.KeyManager")
    def test_construction_exception_raises(self, mock_cls):
        mock_cls.side_effect = OSError("config missing")
        with pytest.raises(OSError):
            get_key_manager()


class TestLoadToken:
    @patch("audio_fingerprinter.utils.musicbrainz_token.os.environ", {})
    @patch("audio_fingerprinter.utils.musicbrainz_token.load_value", return_value="")
    def test_no_token_returns_empty(self, _mock_load):
        assert load_token() == ""

    @patch("audio_fingerprinter.utils.musicbrainz_token.os.environ", {ENV_VAR: "env"})
    def test_env_var_takes_priority(self):
        # A one-off run must not need the store touched at all.
        assert load_token() == "env"

    @patch(
        "audio_fingerprinter.utils.musicbrainz_token.os.environ",
        {ENV_VAR: "  env-token  "},
    )
    def test_env_var_is_stripped(self):
        assert load_token() == "env-token"

    @patch("audio_fingerprinter.utils.musicbrainz_token.os.environ", {})
    @patch(
        "audio_fingerprinter.utils.musicbrainz_token.load_value",
        return_value="encrypted_val",
    )
    @patch("audio_fingerprinter.utils.musicbrainz_token.get_key_manager")
    def test_stored_token_is_decrypted(self, mock_km, _mock_load):
        mock_km.return_value.decrypt_string.return_value = "stored-token"
        assert load_token() == "stored-token"

    @patch("audio_fingerprinter.utils.musicbrainz_token.os.environ", {})
    @patch(
        "audio_fingerprinter.utils.musicbrainz_token.load_value",
        return_value="encrypted_val",
    )
    @patch("audio_fingerprinter.utils.musicbrainz_token.get_key_manager")
    def test_decrypt_failure_yields_no_token(self, mock_km, _mock_load):
        from audio_suite_shared.exceptions import AudioProcessingError

        mock_km.return_value.decrypt_string.side_effect = AudioProcessingError("bad")
        # A corrupt stored value must never be sent to MusicBrainz.
        assert load_token() == ""

    @patch("audio_fingerprinter.utils.musicbrainz_token.os.environ", {})
    @patch("audio_fingerprinter.utils.musicbrainz_token.load_value", return_value=1234)
    def test_non_string_config_value_is_ignored(self, _mock_load):
        assert load_token() == ""


class TestSaveToken:
    @patch("audio_fingerprinter.utils.musicbrainz_token.save_value")
    @patch("audio_fingerprinter.utils.musicbrainz_token.get_key_manager")
    def test_encrypts_and_saves(self, mock_km, mock_save):
        mock_km.return_value.encrypt_string.return_value = "encrypted"
        save_token("my-token")
        mock_km.return_value.encrypt_string.assert_called_once_with("my-token")
        mock_save.assert_called_once_with(CONFIG_KEY, "encrypted")

    @patch("audio_fingerprinter.utils.musicbrainz_token.save_value")
    @patch("audio_fingerprinter.utils.musicbrainz_token.get_key_manager")
    def test_empty_token_clears(self, mock_km, mock_save):
        save_token("")
        mock_save.assert_called_once_with(CONFIG_KEY, "")

    @patch("audio_fingerprinter.utils.musicbrainz_token.save_value")
    @patch("audio_fingerprinter.utils.musicbrainz_token.get_key_manager")
    def test_whitespace_is_stripped(self, mock_km, _mock_save):
        mock_km.return_value.encrypt_string.return_value = "enc"
        save_token("  token  ")
        mock_km.return_value.encrypt_string.assert_called_once_with("token")


class TestClearToken:
    @patch("audio_fingerprinter.utils.musicbrainz_token.save_value")
    def test_clears(self, mock_save):
        clear_token()
        mock_save.assert_called_once_with(CONFIG_KEY, "")


class TestHasToken:
    @patch("audio_fingerprinter.utils.musicbrainz_token.load_token", return_value="")
    def test_no_token(self, _mock_load):
        assert has_token() is False

    @patch("audio_fingerprinter.utils.musicbrainz_token.load_token", return_value="t")
    def test_has_token(self, _mock_load):
        assert has_token() is True


class TestBuildAuth:
    @patch("audio_fingerprinter.utils.musicbrainz_token.load_token", return_value="t")
    def test_oauth_is_default(self, _mock_load):
        auth = build_auth()
        assert auth.token == "t"
        assert auth.method == "oauth"
        assert auth.problem == ""

    @patch("audio_fingerprinter.utils.musicbrainz_token.load_token", return_value="t")
    def test_app_token_carries_the_username(self, _mock_load):
        auth = build_auth("app-token", "  alice ")
        assert auth.method == "app-token"
        assert auth.username == "alice"
        assert auth.problem == ""

    @patch("audio_fingerprinter.utils.musicbrainz_token.load_token", return_value="")
    def test_missing_token_reports_its_problem(self, _mock_load):
        # build_auth never raises: the caller decides whether to fail fast.
        assert build_auth().problem


class TestDescribeSource:
    @patch("audio_fingerprinter.utils.musicbrainz_token.os.environ", {ENV_VAR: "env"})
    def test_env_source(self):
        assert ENV_VAR in describe_source()

    @patch("audio_fingerprinter.utils.musicbrainz_token.os.environ", {})
    @patch("audio_fingerprinter.utils.musicbrainz_token.load_token", return_value="t")
    def test_stored_source(self, _mock_load):
        assert "stored" in describe_source()

    @patch("audio_fingerprinter.utils.musicbrainz_token.os.environ", {})
    @patch("audio_fingerprinter.utils.musicbrainz_token.load_token", return_value="")
    def test_missing_source_explains_the_preview(self, _mock_load):
        assert "previews the payload" in describe_source()
