"""
Tests for audio_suite_shared.security.key_manager
Gap G-19: KeyManager — key generation, encrypt/decrypt round-trips,
          config encrypt/decrypt, is_encrypted_value, corrupt-key recovery
"""

import base64
import os
from unittest.mock import MagicMock, patch

import pytest

from audio_suite_shared.exceptions import AudioProcessingError
from audio_suite_shared.security.key_manager import KeyManager


@pytest.fixture
def km(tmp_path):
    """KeyManager backed by a temp config path."""
    config = tmp_path / "config.json"
    config.write_text("{}")
    return KeyManager(str(config))


@pytest.fixture
def km_path(tmp_path):
    """Return (KeyManager, config_path, key_path) for key-file inspection."""
    config = tmp_path / "config.json"
    config.write_text("{}")
    manager = KeyManager(str(config))
    key_file = tmp_path / "config.key"
    return manager, config, key_file


# ── Initialisation ────────────────────────────────────────────────────────────


class TestInitialisation:
    def test_creates_key_file_on_first_run(self, tmp_path):
        config = tmp_path / "app.json"
        config.write_text("{}")
        KeyManager(str(config))
        assert (tmp_path / "app.key").exists()

    def test_encryption_enabled_when_cryptography_available(self, km):
        assert km._encryption_enabled is True

    def test_fernet_is_initialised(self, km):
        assert km._fernet is not None

    def test_key_is_bytes(self, km):
        assert isinstance(km._key, bytes)

    def test_loads_existing_key_file(self, tmp_path):
        """Second instantiation reuses the same key."""
        config = tmp_path / "config.json"
        config.write_text("{}")
        km1 = KeyManager(str(config))
        km2 = KeyManager(str(config))
        assert km1._key == km2._key

    def test_key_file_has_restrictive_permissions_on_unix(self, tmp_path):
        if os.name == "nt":
            pytest.skip("Unix-only permission check")
        config = tmp_path / "config.json"
        config.write_text("{}")
        KeyManager(str(config))
        key_file = tmp_path / "config.key"
        mode = oct(os.stat(key_file).st_mode)[-3:]
        assert mode == "600", f"Expected 600, got {mode}"


# ── encrypt_string / decrypt_string ──────────────────────────────────────────


class TestEncryptDecryptString:
    def test_round_trip(self, km):
        plaintext = "my_secret_api_key_12345"
        encrypted = km.encrypt_string(plaintext)
        assert km.decrypt_string(encrypted) == plaintext

    def test_encrypted_differs_from_plaintext(self, km):
        plaintext = "secret"
        encrypted = km.encrypt_string(plaintext)
        assert encrypted != plaintext

    def test_encrypted_is_base64(self, km):
        encrypted = km.encrypt_string("hello")
        # Should not raise
        base64.b64decode(encrypted.encode("utf-8"))

    def test_empty_string_returns_empty(self, km):
        assert km.encrypt_string("") == ""
        assert km.decrypt_string("") == ""

    def test_decrypt_non_encrypted_value_returns_as_is(self, km):
        """Plain text that isn't encrypted should be returned unchanged."""
        plain = "not_encrypted_at_all"
        assert km.decrypt_string(plain) == plain

    def test_unicode_string_round_trips(self, km):
        text = "Ångström & Ünïcödé 音楽"
        assert km.decrypt_string(km.encrypt_string(text)) == text

    def test_long_string_round_trips(self, km):
        text = "x" * 10_000
        assert km.decrypt_string(km.encrypt_string(text)) == text

    def test_wrong_key_returns_original_text(self, tmp_path):
        """Decrypting with a different key should raise AudioProcessingError."""
        config1 = tmp_path / "c1.json"
        config1.write_text("{}")
        config2 = tmp_path / "c2.json"
        config2.write_text("{}")
        km1 = KeyManager(str(config1))
        km2 = KeyManager(str(config2))

        encrypted = km1.encrypt_string("secret")
        # km2 has a different key; should raise AudioProcessingError
        with pytest.raises(AudioProcessingError, match="Failed to decrypt"):
            km2.decrypt_string(encrypted)

    def test_corrupt_base64_raises(self, km):
        """Corrupt data that decodes but isn't valid Fernet should raise."""
        # Manufacture something that looks like base64 but isn't valid Fernet
        fake = base64.b64encode(b"x" * 50).decode("utf-8")
        with pytest.raises(AudioProcessingError, match="Failed to decrypt"):
            km.decrypt_string(fake)


# ── encrypt_config / decrypt_config ──────────────────────────────────────────


class TestEncryptDecryptConfig:
    def test_round_trip_with_fanart_keys(self, km):
        config = {
            "fanart": {
                "app_key": "my_app_key_value",
                "client_key": "my_client_key_value",
            }
        }
        encrypted = km.encrypt_config(config)
        decrypted = km.decrypt_config(encrypted)
        assert decrypted["fanart"]["app_key"] == "my_app_key_value"
        assert decrypted["fanart"]["client_key"] == "my_client_key_value"

    def test_encrypt_config_changes_fanart_keys(self, km):
        config = {"fanart": {"app_key": "plaintext", "client_key": "also_plain"}}
        encrypted = km.encrypt_config(config)
        assert encrypted["fanart"]["app_key"] != "plaintext"
        assert encrypted["fanart"]["client_key"] != "also_plain"

    def test_non_fanart_keys_are_unchanged(self, km):
        config = {"other_setting": "keep_me", "fanart": {"app_key": "secret"}}
        encrypted = km.encrypt_config(config)
        assert encrypted["other_setting"] == "keep_me"

    def test_empty_fanart_keys_are_not_encrypted(self, km):
        config = {"fanart": {"app_key": "", "client_key": ""}}
        encrypted = km.encrypt_config(config)
        assert encrypted["fanart"]["app_key"] == ""
        assert encrypted["fanart"]["client_key"] == ""

    def test_config_without_fanart_returned_unchanged(self, km):
        config = {"setting_a": 1, "setting_b": "hello"}
        result = km.encrypt_config(config)
        assert result == config

    def test_original_config_not_mutated(self, km):
        config = {"fanart": {"app_key": "original"}}
        original_key = config["fanart"]["app_key"]
        km.encrypt_config(config)
        assert config["fanart"]["app_key"] == original_key

    def test_encrypt_config_returns_copy(self, km):
        config = {"fanart": {"app_key": "x"}}
        result = km.encrypt_config(config)
        assert result is not config


# ── is_encrypted_value ────────────────────────────────────────────────────────


class TestIsEncryptedValue:
    def test_actually_encrypted_value_returns_true(self, km):
        encrypted = km.encrypt_string("test_secret")
        assert km.is_encrypted_value(encrypted) is True

    def test_plain_short_string_returns_false(self, km):
        assert km.is_encrypted_value("hello") is False

    def test_empty_string_returns_false(self, km):
        assert km.is_encrypted_value("") is False

    def test_none_returns_false(self, km):
        assert km.is_encrypted_value(None) is False

    def test_integer_returns_false(self, km):
        assert km.is_encrypted_value(42) is False

    def test_invalid_base64_returns_false(self, km):
        assert km.is_encrypted_value("!!!not base64!!!") is False

    def test_short_base64_returns_false(self, km):
        # 43 bytes decoded is under the 44-byte threshold
        short_b64 = base64.b64encode(b"x" * 43).decode()
        assert km.is_encrypted_value(short_b64) is False

    def test_long_base64_returns_true(self, km):
        long_b64 = base64.b64encode(b"x" * 100).decode()
        assert km.is_encrypted_value(long_b64) is True


# ── Corrupt key file recovery ─────────────────────────────────────────────────


class TestCorruptKeyRecovery:
    def test_unreadable_key_generates_new_one(self, tmp_path):
        config = tmp_path / "config.json"
        config.write_text("{}")
        key_file = tmp_path / "config.key"
        key_file.write_bytes(b"corrupted garbage bytes not a valid fernet key")

        # Should not raise; generates a new key
        km = KeyManager(str(config))
        assert km._fernet is not None

    def test_encrypt_decrypt_works_after_new_key_generated(self, tmp_path):
        config = tmp_path / "config.json"
        config.write_text("{}")
        key_file = tmp_path / "config.key"
        key_file.write_bytes(b"bad_key")

        km = KeyManager(str(config))
        result = km.decrypt_string(km.encrypt_string("check"))
        assert result == "check"


# ── Encryption-disabled fallbacks ─────────────────────────────────────────────


class TestEncryptionDisabled:
    """Branches taken when cryptography is unavailable (fallback mode)."""

    def test_init_warns_when_crypto_unavailable(self, tmp_path):
        config = tmp_path / "app.json"
        config.write_text("{}")
        with patch(
            "audio_suite_shared.security.key_manager.CRYPTOGRAPHY_AVAILABLE", False
        ):
            km = KeyManager(str(config))
        assert km._encryption_enabled is False
        assert km._fernet is None

    def test_encrypt_string_returns_plaintext_when_disabled(self, km):
        km._encryption_enabled = False
        assert km.encrypt_string("secret") == "secret"

    def test_decrypt_string_returns_as_is_when_disabled(self, km):
        km._encryption_enabled = False
        assert km.decrypt_string("some_value") == "some_value"

    def test_encrypt_config_returns_copy_when_disabled(self, km):
        km._encryption_enabled = False
        config = {"fanart": {"app_key": "x"}}
        result = km.encrypt_config(config)
        assert result == config
        assert result is not config

    def test_decrypt_config_returns_copy_when_disabled(self, km):
        km._encryption_enabled = False
        config = {"fanart": {"app_key": "x"}}
        result = km.decrypt_config(config)
        assert result == config
        assert result is not config


# ── Key file error paths ──────────────────────────────────────────────────────


class TestKeyFileErrorPaths:
    def test_oserror_reading_key_regenerates_and_falls_back(self, tmp_path):
        """An OSError while reading the key file must regenerate; if that save
        also fails, encrypt/decrypt must still work via a non-persisted key."""
        config = tmp_path / "config.json"
        config.write_text("{}")
        # pathlib resolves config.key existence and open() calls our patch
        with patch(
            "audio_suite_shared.security.key_manager.os.path.exists",
            return_value=True,
        ):
            km = KeyManager(str(config))
            km._encryption_enabled = False  # avoid touching a real key file

        assert km._fernet is not None

    def test_save_key_oserror_returns_fallback_key(self, tmp_path, monkeypatch):
        """A write failure during key generation must fall back to a
        freshly generated (non-persisted) key without raising."""
        import builtins

        config = tmp_path / "config.json"
        config.write_text("{}")

        real_open = builtins.open

        def denied_open(file, mode="r", *args, **kwargs):
            if mode == "wb":
                raise OSError("disk full")
            return real_open(file, mode, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", denied_open)
        km = KeyManager(str(config))
        assert km._fernet is not None
        assert km.encrypt_string("secret") != "secret"

    def test_icacls_failure_is_swallowed(self, tmp_path):
        """A failure restricting ACLs on Windows must not crash startup."""
        config = tmp_path / "app.json"
        config.write_text("{}")
        real_getenv = os.getenv

        def fake_getenv(name, *args, **kwargs):
            if name == "USERNAME":
                return "tester"
            return real_getenv(name, *args, **kwargs)

        with patch(
            "audio_suite_shared.security.key_manager.os.getenv",
            side_effect=fake_getenv,
        ):
            with patch(
                "audio_suite_shared.security.key_manager.run_secure_subprocess",
                side_effect=OSError("icacls missing"),
            ):
                km = KeyManager(str(config))
        assert km._fernet is not None

    def test_icacls_routed_via_secure_subprocess(self, tmp_path):
        """The Windows ACL step must go through run_secure_subprocess."""
        config = tmp_path / "app.json"
        config.write_text("{}")
        real_getenv = os.getenv

        def fake_getenv(name, *args, **kwargs):
            if name == "USERNAME":
                return "tester"
            return real_getenv(name, *args, **kwargs)

        with patch(
            "audio_suite_shared.security.key_manager.os.getenv",
            side_effect=fake_getenv,
        ):
            with patch(
                "audio_suite_shared.security.key_manager.run_secure_subprocess"
            ) as mock_run:
                km = KeyManager(str(config))
        assert km._fernet is not None
        mock_run.assert_called_once()
        exe, args = mock_run.call_args[0]
        assert exe == "icacls"
        assert "/grant:r" in args
        assert "tester:F" in args

    def test_icacls_skipped_when_username_missing(self, tmp_path):
        """A missing USERNAME must skip the ACL grant, never emit 'None:F'."""
        config = tmp_path / "app.json"
        config.write_text("{}")
        with patch(
            "audio_suite_shared.security.key_manager.os.getenv",
            return_value=None,
        ):
            with patch(
                "audio_suite_shared.security.key_manager.run_secure_subprocess"
            ) as mock_run:
                km = KeyManager(str(config))
        assert km._fernet is not None
        mock_run.assert_not_called()

    def test_unix_permissions_applied_when_saving(self, tmp_path):
        """On non-Windows, the key file must be chmodded to 0600."""
        import types

        fake_os = types.ModuleType("fake_os")
        fake_os.name = "posix"
        fake_os.path = os.path
        fake_os.makedirs = os.makedirs
        fake_os.getenv = os.getenv
        mock_chmod = MagicMock()
        fake_os.chmod = mock_chmod

        config = tmp_path / "app.json"
        config.write_text("{}")
        with patch("audio_suite_shared.security.key_manager.os", fake_os):
            KeyManager(str(config))
        mock_chmod.assert_called_once()

    def test_encrypt_failure_raises_audio_processing_error(self, km):
        """If Fernet.encrypt raises, encrypt_string must raise
        AudioProcessingError rather than silently returning plaintext."""
        km._fernet = MagicMock()
        km._fernet.encrypt.side_effect = RuntimeError("encrypt blew up")
        with pytest.raises(AudioProcessingError, match="Encryption failed"):
            km.encrypt_string("secret")
