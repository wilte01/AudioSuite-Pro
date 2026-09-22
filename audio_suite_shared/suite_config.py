"""
suite_config.py — Shared Audio Suite config persistence.

Reads and writes audio_suite_config.json, which lives in the suite root
(the directory that contains all tool folders and the Master Driver).

Path resolution from this file's location:
    __file__  = .../audio_suite_shared/suite_config.py
    [1] up    = .../audio_suite_shared/   (this package)
    [2] up    = .../SUITE_ROOT/           ← where audio_suite_config.json lives

Each tool's .pyw entry point and all tool folders sit as siblings under
SUITE_ROOT, so the JSON is naturally shared across the whole suite.

Keys currently used:
    last_directory          – last-used music folder path
    <tool_name>_window      – saved window geometry per tool
                             (e.g. 'key_detector_window')
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .constants import DEFAULT_WINDOW_GEOMETRY, MAX_DURATION_HISTORY


@runtime_checkable
class AppState(Protocol):
    """Protocol defining the master-driver state attributes used by suite_config."""

    dir_path: Any  # tk.StringVar
    palette_var: Any  # tk.StringVar
    theme_mode_var: Any  # tk.StringVar
    font_family_var: Any  # tk.StringVar
    font_sizes_vars: dict[str, Any]  # dict[str, tk.IntVar]


_logger = logging.getLogger(__name__)

_SHARED_DIR = Path(__file__).resolve().parent
_SUITE_ROOT = _SHARED_DIR.parent
CONFIG_PATH = _SUITE_ROOT / "audio_suite_config.json"

# In-memory cache — cleared after every save; avoids ~14 redundant file reads
# per tool startup (one per load_* / save_* call).
_config_cache: dict[str, Any] | None = None
_cache_lock = threading.Lock()


def _invalidate_cache() -> None:
    """Clear the in-memory cache so the next read hits disk."""
    global _config_cache
    with _cache_lock:
        _config_cache = None


def _load() -> dict[str, Any]:
    """Load config with minimal safe validation and in-memory caching.

    The result is cached so that subsequent ``load_*`` calls within the
    same process (common at startup) avoid redundant disk I/O.  The cache
    is invalidated by any ``save_*`` call.
    """
    global _config_cache
    with _cache_lock:
        if _config_cache is not None:
            return dict(_config_cache)

    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as f:
                content = f.read()
            data: dict[str, Any]
            data, _ = json.JSONDecoder().raw_decode(content)
        except (json.JSONDecodeError, ValueError) as exc:
            _logger.warning(
                "%s is corrupt and will be ignored: %s",
                CONFIG_PATH.name,
                exc,
                exc_info=True,
            )
            with _cache_lock:
                _config_cache = {}
            return {}
        except OSError as exc:
            _logger.warning(
                "Could not read %s: %s", CONFIG_PATH.name, exc, exc_info=True
            )
            with _cache_lock:
                _config_cache = {}
            return {}

        # Only fix obviously broken values
        if not isinstance(data.get("last_directory"), str):
            data["last_directory"] = ""

        # Fix window geometry if completely broken
        for key in data:
            if key.endswith("_window") and not isinstance(data[key], str):
                data[key] = DEFAULT_WINDOW_GEOMETRY

        # Fix font sizes if obviously broken
        if "font_sizes" in data and not isinstance(data["font_sizes"], dict):
            data["font_sizes"] = {}

        with _cache_lock:
            _config_cache = data
        return data

    with _cache_lock:
        _config_cache = {}
    return {}


def _save(data: dict[str, Any]) -> None:
    """Write config to disk atomically and invalidate the in-memory cache.

    Uses a write-to-tmp-then-rename strategy for crash safety (prevents
    truncation on power loss).  On Windows the rename can fail if anti-virus
    or another process holds a lock, so a direct-write fallback is included.
    The tmp file is scoped to the PID so concurrent processes don't collide.
    """
    tmp = CONFIG_PATH.with_suffix(f".json.tmp.{os.getpid()}")
    # Clean up any stale tmp files left by other crashed processes
    _cleanup_stale_tmps()

    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        try:
            os.replace(str(tmp), str(CONFIG_PATH))
        except OSError:
            # Atomic rename failed (Windows lock) — fall back to direct write
            with CONFIG_PATH.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
    except OSError as exc:
        _logger.error("Could not write %s: %s", CONFIG_PATH.name, exc)
    finally:
        if tmp.exists():
            _try_unlink(tmp)
    _invalidate_cache()


def _get_tmp_pattern() -> str:
    """Return the glob pattern for stale temp files."""
    name = CONFIG_PATH.stem  # "audio_suite_config"
    return f"{name}.json.tmp.*"


def _cleanup_stale_tmps() -> None:
    """Remove stale .json.tmp.* files left by other crashed processes.

    The current process's own temp file is left untouched since it may
    have been created by a prior call within the same process.
    """
    pid = os.getpid()
    for p in CONFIG_PATH.parent.glob(_get_tmp_pattern()):
        try:
            suffix = p.suffixes  # e.g. ['.json', '.tmp', '.1234']
            if len(suffix) >= 3 and suffix[-1].lstrip(".").isdigit():
                file_pid = int(suffix[-1].lstrip("."))
                if file_pid != pid:
                    p.unlink()
        except OSError:
            pass


def _try_unlink(path: Path) -> None:
    """Remove *path* if possible; swallow exceptions (Windows locks, etc.)."""
    try:
        path.unlink()
    except OSError:
        pass


def load_last_directory() -> str:
    """Return the last-used directory, or empty string if not set."""
    return str(_load().get("last_directory", ""))


def save_last_directory(path: str) -> None:
    """Persist the last-used directory, preserving other keys."""
    data = _load()
    data["last_directory"] = path
    _save(data)


def load_palette() -> str:
    """Return the saved palette name, or 'Purple' if not set."""
    return str(_load().get("palette", "Purple"))


def save_palette(name: str) -> None:
    """Persist the chosen palette name, preserving other keys."""
    data = _load()
    data["palette"] = name
    _save(data)


def load_theme_mode() -> str:
    """Return the saved theme mode, or 'Light' if not set."""
    return str(_load().get("theme_mode", "Light"))


def save_theme_mode(mode: str) -> None:
    """Persist the chosen theme mode, preserving other keys."""
    data = _load()
    data["theme_mode"] = mode
    _save(data)


def load_font_family() -> str:
    """Return the saved font family name, or 'Arial' if not set."""
    return str(_load().get("font_family", "Arial"))


def save_font_family(family: str) -> None:
    """Persist the chosen font family name, preserving other keys."""
    data = _load()
    data["font_family"] = family
    _save(data)


def load_font_sizes() -> dict[str, int]:
    """Return the saved font sizes, merging with defaults if missing."""
    default_sizes = {
        "Header": 16,
        "Title_L": 22,
        "Title": 14,
        "Button": 11,
        "Label": 10,
        "Body": 9,
        "Caption": 8,
        "Micro": 7,
        "Mono": 9,
    }
    saved_sizes = _load().get("font_sizes", {})
    for k, v in saved_sizes.items():
        if k in default_sizes:
            default_sizes[k] = v
    return default_sizes


def save_font_sizes(sizes: dict[str, int]) -> None:
    data = _load()
    data["font_sizes"] = sizes
    _save(data)


def load_value(key: str, default: object = None) -> object:
    """Return the value stored under key, or default if not set."""
    return _load().get(key, default)


def save_value(key: str, value: object) -> None:
    """Persist an arbitrary value under key, preserving other keys."""
    data = _load()
    data[key] = value
    _save(data)


# ── Presets ──────────────────────────────────────────────────────────────────
# Config structure:
#   "presets": {
#       "<tool_id>": {
#           "<preset_name>": { <setting_key>: <value>, ... }
#       }
#   }


def save_preset(tool_id: str, name: str, settings: dict[str, Any]) -> None:
    """Save a named preset for a tool, preserving other presets."""
    data = _load()
    presets: dict[str, Any] = data.setdefault("presets", {})
    tool_presets: dict[str, Any] = presets.setdefault(tool_id, {})
    tool_presets[name] = settings
    _save(data)


def load_preset(tool_id: str, name: str) -> dict[str, Any] | None:
    """Return the settings dict for a named preset, or None if not found."""
    data = _load()
    presets: dict[str, Any] = data.get("presets", {})
    tool_presets: dict[str, Any] = presets.get(tool_id, {})
    return tool_presets.get(name)


def list_presets(tool_id: str) -> list[str]:
    """Return a sorted list of preset names for a tool."""
    data = _load()
    presets: dict[str, Any] = data.get("presets", {})
    tool_presets: dict[str, Any] = presets.get(tool_id, {})
    return sorted(tool_presets)


def delete_preset(tool_id: str, name: str) -> None:
    """Delete a named preset for a tool."""
    data = _load()
    presets: dict[str, Any] = data.get("presets", {})
    tool_presets: dict[str, Any] = presets.get(tool_id, {})
    tool_presets.pop(name, None)
    _save(data)


def load_window_geometry(tool_id: str) -> str:
    """Load saved window geometry for a tool, or default."""
    return str(load_value(f"{tool_id}_window", DEFAULT_WINDOW_GEOMETRY))


def save_window_geometry(tool_id: str, geometry: str) -> None:
    """Persist window geometry for a tool, preserving other keys."""
    save_value(f"{tool_id}_window", geometry)


# ── Batch tool duration tracking ──────────────────────────────────────────────
# Config structure:
#   "tool_durations": {
#       "<tool_id>": [12.3, 15.1, 11.8, ...]   # last N run durations in seconds
#   }


def save_tool_duration(tool_id: str, duration_seconds: float) -> None:
    """Append a run duration for a tool, keeping at most 10 entries."""
    data = _load()
    durations: dict[str, Any] = data.setdefault("tool_durations", {})
    history: list[float] = durations.setdefault(tool_id, [])
    history.append(duration_seconds)
    # Keep only the last N runs
    if len(history) > MAX_DURATION_HISTORY:
        history[:] = history[-MAX_DURATION_HISTORY:]
    _save(data)


def load_tool_durations(tool_id: str) -> list[float]:
    """Return the list of recorded run durations for a tool (empty if none)."""
    data = _load()
    durations: dict[str, Any] = data.get("tool_durations", {})
    result: list[float] = durations.get(tool_id, [])
    return result


def load_average_tool_duration(tool_id: str) -> float | None:
    """Return the average run duration for a tool, or None if no history."""
    history = load_tool_durations(tool_id)
    if not history:
        return None
    return sum(history) / len(history)


def save_batch_durations(durations: dict[str, float]) -> None:
    """Save multiple tool durations at once (after a batch run)."""
    for tool_id, secs in durations.items():
        save_tool_duration(tool_id, secs)


def load_app_state(state: AppState) -> None:
    """Populate a master-driver AppState from the shared config.

    Sets dir_path, palette_var, theme_mode_var, font_family_var, and
    font_sizes_vars from the persisted config, falling back to defaults
    when keys are missing.
    """
    data = _load()
    try:
        getattr(state, "dir_path").set(data.get("last_directory", ""))
    except AttributeError as exc:
        _logger.debug("load_app_state: dir_path not available: %s", exc)
    try:
        getattr(state, "palette_var").set(data.get("palette", "Purple"))
    except AttributeError as exc:
        _logger.debug("load_app_state: palette_var not available: %s", exc)
    try:
        getattr(state, "font_family_var").set(data.get("font_family", "Arial"))
    except AttributeError as exc:
        _logger.debug("load_app_state: font_family_var not available: %s", exc)
    try:
        getattr(state, "theme_mode_var").set(data.get("theme_mode", "Light"))
    except AttributeError as exc:
        _logger.debug("load_app_state: theme_mode_var not available: %s", exc)
    try:
        sizes: dict[str, int] = data.get("font_sizes", {})
        for k, var in getattr(state, "font_sizes_vars").items():
            if k in sizes:
                var.set(sizes[k])
    except AttributeError as exc:
        _logger.debug("load_app_state: font_sizes_vars not available: %s", exc)


def save_app_state(state: AppState) -> None:
    """Persist master-driver state keys, preserving all other config keys.

    Saves last_directory, palette, theme_mode, font_family, and font_sizes
    from AppState without dropping keys managed by other tools.
    """
    data = _load()
    try:
        data["last_directory"] = getattr(state, "dir_path").get()
    except AttributeError as exc:
        _logger.debug("save_app_state: dir_path not available: %s", exc)
    try:
        data["palette"] = getattr(state, "palette_var").get()
    except AttributeError as exc:
        _logger.debug("save_app_state: palette_var not available: %s", exc)
    try:
        data["font_family"] = getattr(state, "font_family_var").get()
    except AttributeError as exc:
        _logger.debug("save_app_state: font_family_var not available: %s", exc)
    try:
        data["theme_mode"] = getattr(state, "theme_mode_var").get()
    except AttributeError as exc:
        _logger.debug("save_app_state: theme_mode_var not available: %s", exc)
    try:
        saved_sizes: dict[str, int] = {}
        for k, var in getattr(state, "font_sizes_vars").items():
            saved_sizes[k] = var.get()
        data["font_sizes"] = saved_sizes
    except AttributeError as exc:
        _logger.debug("save_app_state: font_sizes_vars not available: %s", exc)
    _save(data)
