"""
settings.py — Configuration constants and JSON config file handling.

Changed in 1.4.0: drops the unused fixed ``CONCURRENT_WORKERS`` entry; worker
counts resolve from ``audio_suite_shared.constants`` (D67).

Changed in 2.1.3: the config file is resolved from this package's own location,
never from the calling module (audit R-04,
``PLAN_audit_2026-10-24_remediation.md`` B1). The GUI called ``load_config(
__file__)`` from ``app.py`` and the CLI/batch path called it from
``core/pipeline.py``, so the two read *different* files
(``album_art_sync/album_art_config.json`` and
``album_art_sync/core/album_art_config.json``) and one source of keys could be
silently empty. ``load_config``/``save_config`` now take no arguments and use
``config_path()``; a legacy pair found at either old location is copied — JSON
*and* its sibling ``.key`` — into the canonical directory on first load, with
the legacy files left untouched for manual recovery.
"""

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

# Import security modules
from audio_suite_shared.security.key_manager import KeyManager

logger = logging.getLogger(__name__)

#: Runtime tuning constants
CONFIG = {
    "REQUEST_TIMEOUT": 10,
    "MAX_API_RESULTS": 5,
    "FOLDER_IMAGE_SIZE": 1000,
    "PROGRESS_BATCH_SIZE": 10,
}

# Universal guardrails (applied in all run modes)
MIN_ART_DIMENSION: int = 500  # px; smaller candidates are rejected
ALBUM_MATCH_THRESHOLD: float = 0.85  # 0.0–1.0; below this → rejected

#: The config file name; the encryption key sits beside it as ``.key``.
CONFIG_FILENAME = "album_art_config.json"

#: The one directory every caller reads and writes. Module-level so tests can
#: monkeypatch it instead of passing a fake "script" path.
CONFIG_DIR: Path = Path(__file__).resolve().parent


def config_path() -> Path:
    """Return the canonical config file every caller must use."""
    return CONFIG_DIR / CONFIG_FILENAME


def legacy_config_paths() -> list[Path]:
    """Return the pre-2.1.3 config locations, in migration order.

    Before 2.1.3 each entry point derived the path from its own ``__file__``, so
    ``app.py`` wrote beside the package and ``core/pipeline.py`` wrote inside
    ``core/``. Both are searched; the package-root file wins because that is the
    one the GUI (the only writer) used.
    """
    package_root = Path(__file__).resolve().parents[1]
    return [package_root / CONFIG_FILENAME, package_root / "core" / CONFIG_FILENAME]


def _migrate_legacy_config() -> Path | None:
    """Copy a legacy JSON (and its key) to the canonical path.

    Never deletes or overwrites a legacy file, and never overwrites an existing
    canonical key: a JSON copied without the key its values were encrypted with
    would be unreadable, so the key travels with it.

    Returns:
        The canonical path when a migration happened, otherwise ``None``.
    """
    target = config_path()
    for legacy in legacy_config_paths():
        if not legacy.is_file():
            continue

        legacy_key = legacy.with_suffix(".key")
        target_key = target.with_suffix(".key")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(legacy, target)
            if legacy_key.is_file() and not target_key.exists():
                shutil.copyfile(legacy_key, target_key)
                # ``copyfile`` carries content, not permissions: the copy is a
                # new file that inherits this directory's mode rather than the
                # legacy key's 0600, so re-apply the suite's key hardening.
                KeyManager(str(target)).harden_key_file()
            elif not legacy_key.is_file():
                logger.warning(
                    "Migrated album-art config %s without its key file; values "
                    "encrypted with that key are unreadable until they are "
                    "re-entered.",
                    legacy,
                )
        except OSError as exc:
            logger.warning("Failed to migrate config %s: %s", legacy, exc)
            return None

        logger.info("Migrated album-art config %s -> %s", legacy, target)
        return target
    return None


def load_config() -> dict[str, Any]:
    """Load API keys from the canonical album-art config file.

    Creates a template file with empty keys when neither the canonical file nor
    a legacy one exists, and migrates a legacy file on first load. Uses
    ``KeyManager`` for encryption of sensitive data.

    Returns:
        The decrypted configuration, or the empty template when the file cannot
        be read or decrypted.
    """
    config_file = config_path()
    default = {"fanart": {"app_key": "", "client_key": ""}}

    if not config_file.exists():
        _migrate_legacy_config()

    if not config_file.exists():
        # Constructing the manager here makes it harden the key file's ACLs in
        # the canonical directory rather than inheriting a legacy directory's.
        config_file.parent.mkdir(parents=True, exist_ok=True)
        key_manager = KeyManager(str(config_file))
        encrypted_default = key_manager.encrypt_config(default)
        with open(config_file, "w", encoding="utf-8-sig") as f:
            json.dump(encrypted_default, f, indent=2)
        return default

    try:
        with open(config_file, "r", encoding="utf-8-sig") as f:
            encrypted_config = json.load(f)
            key_manager = KeyManager(str(config_file))
            return key_manager.decrypt_config(encrypted_config)
    except (json.JSONDecodeError, OSError, ValueError) as e:
        logger.warning("Failed to load config from %s: %s", config_file, e)
        return default


def save_config(config: dict[str, Any]) -> None:
    """Save API keys to the canonical album-art config file with encryption.

    Args:
        config: Configuration dictionary with API keys.
    """
    config_file = config_path()
    try:
        config_file.parent.mkdir(parents=True, exist_ok=True)
        key_manager = KeyManager(str(config_file))
        encrypted_config = key_manager.encrypt_config(config)
        tmp_path = str(config_file) + ".tmp"
        with open(tmp_path, "w", encoding="utf-8-sig") as f:
            json.dump(encrypted_config, f, indent=2)
        os.replace(tmp_path, config_file)
    except (OSError, TypeError) as e:
        logger.warning("Failed to save config to %s: %s", config_file, e)
