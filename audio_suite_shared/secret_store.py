"""secret_store.py — one encrypted credential store for the suite's API keys.

A credential the suite stores itself follows one resolution order:

    ``<ENV VAR>``  >  decrypted config value  >  ``""``

The Fingerprinter had it twice — once for the AcoustID API key and once for the
MusicBrainz submission token — as five near-identical functions each.  The two
credentials differ only in *which* config key, *which* environment variable and
*which* label the warning names, so those three are the whole of a
:class:`SecretStore` and the resolution order lives here once.

The config accessors are passed in rather than imported, because the caller's
module is where a test (and a future alternative store) substitutes them; the
shared part is the order and the encryption, not the config file.  Nothing here
logs or returns a credential value: a decrypt failure warns and yields ``""``,
which every caller already treats as "not configured".
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .exceptions import AudioProcessingError
from .security.key_manager import KeyManager

logger = logging.getLogger(f"audio_suite.{__name__}")

#: Reads one key from the shared config, returning a default when it is absent.
ConfigReader = Callable[[str, str], Any]
#: Writes one key to the shared config.
ConfigWriter = Callable[[str, Any], None]

__all__ = ["ConfigReader", "ConfigWriter", "SecretStore"]


@dataclass(frozen=True)
class SecretStore:
    """The resolution order for one encrypted credential.

    Attributes:
        config_key: The key in the shared ``audio_suite_config.json``.
        env_var: The environment variable that overrides it for one run.
        label: How the credential is named to the user in a warning, e.g.
            ``"AcoustID API key"``.
    """

    config_key: str
    env_var: str
    label: str

    def load(self, key_manager: KeyManager, config_reader: ConfigReader) -> str:
        """Return the credential, if any is configured.

        Args:
            key_manager: Decrypts the stored value.
            config_reader: Reads the stored (encrypted) value, as
                ``config_reader(key, default)``.

        Returns:
            The credential, or ``""`` when the environment variable is unset
            and the config holds nothing or something undecryptable.
        """
        from_env = os.environ.get(self.env_var, "").strip()
        if from_env:
            return from_env

        stored = config_reader(self.config_key, "")
        if not isinstance(stored, str) or not stored:
            return ""

        try:
            return key_manager.decrypt_string(stored)
        except AudioProcessingError:
            logger.warning(
                "Stored %s could not be decrypted.", self.label, exc_info=True
            )
            return ""

    def save(
        self,
        value: str,
        key_manager: KeyManager,
        config_writer: ConfigWriter,
    ) -> None:
        """Encrypt and persist the credential.

        Args:
            value: The credential to store.  An empty string clears the stored
                value, which is how the Setup tab's Clear button works.
            key_manager: Encrypts the value.
            config_writer: Writes the stored value, as
                ``config_writer(key, value)``.

        Raises:
            AudioProcessingError: If encryption fails.
        """
        encrypted = ""
        if value:
            encrypted = key_manager.encrypt_string(value.strip())
        config_writer(self.config_key, encrypted)

    def clear(self, config_writer: ConfigWriter) -> None:
        """Remove the stored credential from the config.

        Args:
            config_writer: Writes the stored value, as
                ``config_writer(key, value)``.
        """
        config_writer(self.config_key, "")
