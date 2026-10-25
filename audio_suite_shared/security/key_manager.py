"""
key_manager.py — Secure key management for API keys and sensitive configuration.

Provides encryption/decryption services for sensitive data
stored in configuration files.
Uses Fernet symmetric encryption for secure key storage.

Changed in 2.1.3: the key-file hardening moved out of ``_generate_and_save_key``
into the public ``harden_key_file()``, so a caller that copies an existing key
into its canonical directory can re-apply it. ``shutil.copyfile`` does not carry
permissions, so a migrated 0600 key was landing as ``0666 & ~umask`` — readable
by every local user on POSIX (audit R-04, plan B1).
"""

import base64
import binascii
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from audio_suite_shared.exceptions import AudioProcessingError
from audio_suite_shared.secure_subprocess import run_secure_subprocess

logger = logging.getLogger(f"audio_suite.{__name__}")

# Try to import cryptography, provide fallback if not available
try:
    from cryptography.fernet import Fernet, InvalidToken

    CRYPTOGRAPHY_AVAILABLE = True
    # cryptography is a declared hard dependency (pyproject); this fallback
    # exists to keep the module importable in an incomplete env, so it cannot
    # run in a correctly installed suite. The disabled-encryption behaviour
    # itself is exercised by TestEncryptionDisabled patching the flag
    # (tests/test_key_manager.py) — only the import-time guard is excluded.
except ImportError:  # pragma: no cover
    CRYPTOGRAPHY_AVAILABLE = False
    Fernet = None  # type: ignore[assignment, misc]
    InvalidToken = None  # type: ignore[assignment, misc]


class KeyManager:
    """Manages encryption keys and provides secure config encryption/decryption."""

    def __init__(self, config_path: str):
        """
        Initialize KeyManager with configuration file path.

        Args:
            config_path: Path to configuration file (used to derive key file path)
        """
        self.config_path = config_path
        self._encryption_enabled = CRYPTOGRAPHY_AVAILABLE
        self._key: bytes | None = None
        self._fernet: Any = None
        # Set when an existing key file was unusable and had to be replaced.
        # decrypt_string uses it to explain why older values are now
        # unreadable instead of reporting a bare decryption failure.
        self._key_regenerated: bool = False

        if CRYPTOGRAPHY_AVAILABLE:
            self._key = self._load_or_generate_key()
            self._fernet = Fernet(self._key)
        else:
            logger.warning(
                "cryptography module not available."
                " Configuration will not be encrypted."
            )

    def _load_or_generate_key(self) -> bytes:
        """
        Load existing encryption key or generate a new one.

        Returns:
            bytes: Encryption key for Fernet
        """
        key_file = self.key_file_path()

        if os.path.exists(key_file):
            try:
                with open(key_file, "rb") as f:
                    key = f.read()
                # Validate the key is usable before returning it
                Fernet(key)
                return key
            except (IOError, OSError) as e:
                logger.warning("Could not read key file, generating new key: %s", e)
                # The bytes on disk may still be a perfectly good key that
                # merely could not be read, so the copy is worth restoring.
                recoverable = True
            except Exception as e:
                logger.warning("Key file invalid, generating new key: %s", e)
                # The stored key was already unusable; copying it preserves
                # evidence, not the ability to decrypt anything.
                recoverable = False

            # An existing key is about to be overwritten. It is the only
            # thing that can decrypt values already encrypted under it, so
            # keep a copy before it goes, and record that the replacement
            # makes those values unreadable.
            self._key_regenerated = True
            logger.warning(
                "Replacing the encryption key at %s: a key file already existed "
                "but could not be used. Values encrypted under the previous key "
                "(for example the Fanart app_key/client_key) can no longer be "
                "decrypted and will need to be re-entered.",
                key_file,
            )
            self._backup_existing_key(key_file, recoverable=recoverable)
            return self._generate_and_save_key(key_file)
        return self._generate_and_save_key(key_file)

    def _backup_existing_key(self, key_file: str, *, recoverable: bool) -> None:
        """
        Copy an existing key file to ``<key_file>.bak`` before it is replaced.

        The key being replaced is the only thing that can decrypt values
        already encrypted under it, so this copy is what makes those values
        recoverable. An existing ``.bak`` is never clobbered, because it holds
        the *original* key, which is the more valuable of the two.

        Args:
            key_file: Path of the key file that is about to be overwritten.
            recoverable: True when the stored bytes may still be a usable key
                (it merely could not be read), so restoring the copy would
                recover values. False when the stored key was already invalid,
                making the copy diagnostic evidence only.
        """
        backup = f"{key_file}.bak"
        if os.path.exists(backup):
            logger.info(
                "Keeping the existing key backup at %s rather than overwriting it",
                backup,
            )
            return
        try:
            shutil.copy2(key_file, backup)
        except OSError:
            logger.warning(
                "Could not back up the previous key to %s: values encrypted "
                "under it are now unrecoverable",
                backup,
                exc_info=True,
            )
            return
        if recoverable:
            logger.warning(
                "Backed up the previous encryption key to %s before replacing it. "
                "Restore that file (and delete the new key file) to recover values "
                "encrypted under the old key.",
                backup,
            )
        else:
            logger.warning(
                "Kept a copy of the unusable key file at %s before replacing it. "
                "The stored key was already invalid, so this copy is for diagnosis "
                "only and cannot recover values encrypted under it.",
                backup,
            )

    def key_file_path(self) -> str:
        """Return the key file this manager uses: ``<config path>.key``."""
        return str(Path(self.config_path).with_suffix(".key"))

    def harden_key_file(self) -> None:
        """Restrict the key file to the current user.

        ``icacls`` on Windows (routed through the secure wrapper), ``0600``
        elsewhere. Applied when a key is generated, and by callers that copy an
        existing key file into its canonical directory: a copy is a new file and
        inherits that directory's permissions rather than the original's.
        """
        key_file = self.key_file_path()
        if os.name == "nt":
            # On Windows, restrict to current user via icacls.
            # Route through the secured wrapper so the ACL command is
            # allowlisted, argument-validated, and startupinfo-hardened.
            username = os.getenv("USERNAME")
            if not username:
                logger.warning(
                    "USERNAME is not set; skipping Windows ACL hardening "
                    "on key file: %s",
                    key_file,
                )
                return
            try:
                run_secure_subprocess(
                    "icacls",
                    [
                        key_file,
                        "/inheritance:r",
                        "/grant:r",
                        f"{username}:F",
                    ],
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
            except Exception:
                logger.warning(
                    "Could not set Windows ACL on key file: %s "
                    "(key file written without ACL hardening)",
                    key_file,
                    exc_info=True,
                )
        else:
            os.chmod(key_file, 0o600)

    def _generate_and_save_key(self, key_file: str) -> bytes:
        """
        Generate a new encryption key and save it to file.

        Args:
            key_file: Path where to save the key

        Returns:
            bytes: Generated encryption key
        """
        try:
            key = Fernet.generate_key()
            # Ensure directory exists
            key_dir = os.path.dirname(key_file) or "."
            os.makedirs(key_dir, exist_ok=True)

            with open(key_file, "wb") as f:
                f.write(key)

            # Set restrictive permissions on key file
            self.harden_key_file()

            return key
        except (IOError, OSError) as e:
            logger.error(
                "Could not save key file: %s. The key returned for this session "
                "exists only in memory: every value encrypted with it will be "
                "undecryptable after a restart, and the next launch will "
                "generate a different key.",
                e,
                exc_info=True,
            )
            # Fallback to a generated key (won't persist)
            return Fernet.generate_key()

    def encrypt_string(self, plaintext: str) -> str:
        """
        Encrypt a string value.

        Args:
            plaintext: String to encrypt

        Returns:
            str: Base64-encoded encrypted string or plaintext
            if encryption not available
        """
        if not plaintext:
            return ""

        if not self._encryption_enabled:
            # Return plaintext as-is if encryption is not available
            return plaintext

        try:
            encrypted_bytes = self._fernet.encrypt(plaintext.encode("utf-8"))
            return base64.b64encode(encrypted_bytes).decode("utf-8")
        except Exception as e:
            logger.error("Error encrypting data: %s", e, exc_info=True)
            raise AudioProcessingError(
                "Encryption failed — not returning plaintext"
            ) from e

    def decrypt_string(self, encrypted_text: str) -> str:
        """
        Decrypt a string value.

        Args:
            encrypted_text: Base64-encoded encrypted string

        Returns:
            str: Decrypted plaintext string or original text if encryption not available
        """
        if not encrypted_text:
            return ""

        if not self._encryption_enabled:
            # Return text as-is if encryption is not available
            return encrypted_text

        # Check if this looks like encrypted data before trying to decrypt
        if not self.is_encrypted_value(encrypted_text):
            return encrypted_text

        try:
            encrypted_bytes = base64.b64decode(encrypted_text.encode("utf-8"))
            decrypted_bytes: bytes = self._fernet.decrypt(encrypted_bytes)
            return decrypted_bytes.decode("utf-8")
        except (InvalidToken, ValueError, binascii.Error) as e:
            logger.error("Error decrypting data: %s", e, exc_info=True)
            message = "Failed to decrypt configuration value"
            if self._key_regenerated:
                message += (
                    ": the encryption key was regenerated because the previous "
                    "key file was unusable, so values encrypted under it (for "
                    "example the Fanart app_key/client_key) must be re-entered"
                )
            raise AudioProcessingError(message, original=e) from e

    def encrypt_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """
        Encrypt sensitive fields in a configuration dictionary.

        Args:
            config: Configuration dictionary with potentially sensitive data

        Returns:
            Dict: Configuration with sensitive fields encrypted (or unchanged
                if encryption not available)
        """
        if not self._encryption_enabled:
            # Return config as-is if encryption is not available
            return config.copy()

        encrypted_config = config.copy()

        # Encrypt API keys in fanart configuration
        if "fanart" in encrypted_config and isinstance(
            encrypted_config["fanart"], dict
        ):
            fanart = encrypted_config["fanart"].copy()

            if "app_key" in fanart and fanart["app_key"]:
                fanart["app_key"] = self.encrypt_string(fanart["app_key"])

            if "client_key" in fanart and fanart["client_key"]:
                fanart["client_key"] = self.encrypt_string(fanart["client_key"])

            encrypted_config["fanart"] = fanart

        return encrypted_config

    def decrypt_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """
        Decrypt sensitive fields in a configuration dictionary.

        Args:
            config: Configuration dictionary with encrypted sensitive data

        Returns:
            Dict: Configuration with sensitive fields decrypted (or unchanged
                if encryption not available)
        """
        if not self._encryption_enabled:
            # Return config as-is if encryption is not available
            return config.copy()

        decrypted_config = config.copy()

        # Decrypt API keys in fanart configuration
        if "fanart" in decrypted_config and isinstance(
            decrypted_config["fanart"], dict
        ):
            fanart = decrypted_config["fanart"].copy()

            if "app_key" in fanart and fanart["app_key"]:
                fanart["app_key"] = self.decrypt_string(fanart["app_key"])

            if "client_key" in fanart and fanart["client_key"]:
                fanart["client_key"] = self.decrypt_string(fanart["client_key"])

            decrypted_config["fanart"] = fanart

        return decrypted_config

    def is_encrypted_value(self, value: Any) -> bool:
        """
        Check if a value appears to be a Fernet-encrypted token.

        ``encrypt_string`` stores ``base64(fernet_token)`` where the Fernet
        token itself is URL-safe base64 starting with ``'g'`` (the base64
        encoding of version byte 0x80).  A plain base64 string (e.g. a raw
        API key) will fail this check even if it is ≥44 bytes, preventing
        the false positive that previously caused ``decrypt_string`` to
        attempt decryption of plaintext and raise.

        Args:
            value: Value to check

        Returns:
            bool: True if value appears to be a Fernet-encrypted token
        """
        if not isinstance(value, str) or not value:
            return False

        try:
            decoded = base64.b64decode(value.encode("utf-8"))
            # The outer base64 decode yields the Fernet token bytes, which
            # are themselves URL-safe base64 starting with 'g' (version
            # byte 0x80).  Verify both the prefix and a minimum length
            # (1 version + 8 timestamp + 16 IV + 16 min ciphertext +
            # 32 HMAC = 73 raw bytes, base64 to ≥96 chars).
            if len(decoded) < 96 or decoded[0:1] != b"g":
                return False
            # Confirm the inner base64 decodes to a valid Fernet structure.
            inner = base64.urlsafe_b64decode(decoded)
            return len(inner) >= 73 and inner[0] == 0x80
        except (binascii.Error, ValueError):
            return False
