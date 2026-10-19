"""
settings.py — Configuration constants and JSON config file handling.

Changed in 1.4.0: drops the unused fixed ``CONCURRENT_WORKERS`` entry; worker
counts resolve from ``audio_suite_shared.constants`` (D67).
"""

import json
import logging
import os
from typing import Any

# Import security modules
from audio_suite_shared.security.key_manager import KeyManager

logger = logging.getLogger(__name__)

# Runtime tuning constants
CONFIG = {
    "REQUEST_TIMEOUT": 10,
    "MAX_API_RESULTS": 5,
    "FOLDER_IMAGE_SIZE": 1000,
    "PROGRESS_BATCH_SIZE": 10,
}

# Universal guardrails (applied in all run modes)
MIN_ART_DIMENSION: int = 500  # px; smaller candidates are rejected
ALBUM_MATCH_THRESHOLD: float = 0.85  # 0.0–1.0; below this → rejected


def load_config(script_file: str = __file__) -> dict[str, Any]:
    """
    Load API keys from album_art_config.json next to script.
    Creates a template file with empty keys if not found.
    Uses KeyManager for encryption of sensitive data.
    """
    config_file = os.path.join(
        os.path.dirname(os.path.abspath(script_file)), "album_art_config.json"
    )
    default = {"fanart": {"app_key": "", "client_key": ""}}

    if not os.path.exists(config_file):
        key_manager = KeyManager(config_file)
        encrypted_default = key_manager.encrypt_config(default)
        with open(config_file, "w", encoding="utf-8-sig") as f:
            json.dump(encrypted_default, f, indent=2)
        return default

    try:
        with open(config_file, "r", encoding="utf-8-sig") as f:
            encrypted_config = json.load(f)
            key_manager = KeyManager(config_file)
            return key_manager.decrypt_config(encrypted_config)
    except (json.JSONDecodeError, OSError, ValueError) as e:
        logger.warning("Failed to load config from %s: %s", config_file, e)
        return default


def save_config(config: dict[str, Any], script_file: str = __file__) -> None:
    """
    Save API keys to album_art_config.json with encryption.

    Args:
        config: Configuration dictionary with API keys
        script_file: Script file path (used to derive config file path)
    """
    config_file = os.path.join(
        os.path.dirname(os.path.abspath(script_file)), "album_art_config.json"
    )
    try:
        key_manager = KeyManager(config_file)
        encrypted_config = key_manager.encrypt_config(config)
        tmp_path = config_file + ".tmp"
        with open(tmp_path, "w", encoding="utf-8-sig") as f:
            json.dump(encrypted_config, f, indent=2)
        os.replace(tmp_path, config_file)
    except (OSError, TypeError) as e:
        logger.warning("Failed to save config to %s: %s", config_file, e)
