"""
shell_integration.py — Windows Explorer right-click verbs for AudioSuite-Pro.

Installs a per-user context-menu entry for every supported audio extension:
a cascading ``AudioSuite-Pro`` submenu (``MUIVerb`` + ``SubCommands``) with one
verb per action, plus an optional flat-verb fallback (``install(flat=True)``)
for Explorer versions that do not render the cascade.

Everything is written under
``HKEY_CURRENT_USER\\Software\\Classes\\SystemFileAssociations\\<ext>\\shell``,
which is per-user and therefore needs **no elevation**.  The plan's original
``HKEY_CLASSES_ROOT`` keys require administrator rights on every install and
return ``[WinError 5]`` unelevated (PLAN D57).

The module never imports ``winreg`` at import time: ``_registry()`` loads it
lazily, so the suite stays importable on non-Windows hosts and tests can
inject a fake registry without touching the developer's real context menu.

Changed in 1.4.0: new module (Sprint 4 Item 4.1, PLAN D57/D58/D60).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

from .audio_formats import SUPPORTED_EXTENSIONS

#: The per-user class root; writing here needs no elevation (PLAN D57).
CLASSES_ROOT = "Software\\Classes"
SYSTEM_FILE_ASSOCIATIONS = f"{CLASSES_ROOT}\\SystemFileAssociations"

#: Menu identity, used for the cascade key and the flat-key prefix.
MENU_LABEL = "AudioSuite-Pro"
MENU_KEY = "AudioSuitePro"
FLAT_PREFIX = f"{MENU_KEY}."

#: Module invoked by every verb: ``python -m audio_suite_shared.shell_action``.
ACTION_MODULE = "audio_suite_shared.shell_action"


@dataclass(frozen=True)
class ShellVerb:
    """One right-click action.

    Attributes:
        id: Registry key name and ``shell_action`` verb id.
        label: Human-readable menu text.
        cli_args: The CLI command the verb maps onto, for documentation and
            the lock test that keeps the menu and the CLI in step.
    """

    id: str
    label: str
    cli_args: tuple[str, ...]


#: The five verbs the user chose (PLAN D57): two conversions, three analyses.
VERBS: tuple[ShellVerb, ...] = (
    ShellVerb("convert_mp3", "Convert to MP3", ("convert", "--format", "mp3")),
    ShellVerb("convert_flac", "Convert to FLAC", ("convert", "--format", "flac")),
    ShellVerb("analyze_bpm", "Analyze BPM", ("bpm",)),
    ShellVerb("analyze_key", "Analyze Key", ("key",)),
    ShellVerb("analyze_mood", "Analyze Mood", ("mood-analyzer",)),
)

VERB_BY_ID: dict[str, ShellVerb] = {verb.id: verb for verb in VERBS}


def supported_extensions() -> tuple[str, ...]:
    """Return the lowercase, dot-prefixed extensions that get a menu."""
    return tuple(ext for ext in SUPPORTED_EXTENSIONS if ext.startswith("."))


def extension_key(ext: str) -> str:
    """Return the cascade key path for one extension (no root)."""
    return f"{SYSTEM_FILE_ASSOCIATIONS}\\{ext}\\shell\\{MENU_KEY}"


def verb_key(ext: str, verb: ShellVerb) -> str:
    """Return the cascading submenu key for one verb."""
    return f"{extension_key(ext)}\\shell\\{verb.id}"


def flat_key(ext: str, verb: ShellVerb) -> str:
    """Return the flat-fallback key for one verb."""
    return f"{SYSTEM_FILE_ASSOCIATIONS}\\{ext}\\shell\\{FLAT_PREFIX}{verb.id}"


def command_for(verb: ShellVerb, executable: str | None = None) -> str:
    """Return the Explorer command line for *verb*.

    The interpreter is named explicitly instead of relying on PATH: on a live
    install PATH can resolve ``audiosuite`` to a different interpreter than
    the one the user installed (PLAN D60).  ``%1`` is quoted because Explorer
    substitutes the path raw and any folder with a space would otherwise split
    the argument.
    """
    exe = executable or sys.executable
    return f'"{exe}" -m {ACTION_MODULE} {verb.id} "%1"'


def _is_windows() -> bool:
    """Return True on Windows; the only platform this integration supports."""
    return sys.platform == "win32"


def _registry() -> Any:
    """Return the ``winreg`` module.

    Tests replace this accessor so registry writes never reach the real
    context menu; production imports it lazily so non-Windows hosts (and CI)
    can import this module.
    """
    import winreg

    return winreg


def _require_windows() -> None:
    if not _is_windows():
        raise RuntimeError(
            "Windows Explorer integration is Windows-only; "
            "run it from the installed Windows environment."
        )


def _ensure_key(reg: Any, path: str) -> Any:
    """Create (or open) *path* under HKCU and return the open key handle."""
    return reg.CreateKeyEx(reg.HKEY_CURRENT_USER, path, 0, reg.KEY_WRITE)


def _set_string(reg: Any, path: str, name: str, value: str) -> None:
    """Write one REG_SZ value, creating the key if needed."""
    key = _ensure_key(reg, path)
    try:
        reg.SetValueEx(key, name, 0, reg.REG_SZ, value)
    finally:
        reg.CloseKey(key)


def _enum_subkeys(reg: Any, path: str) -> tuple[str, ...]:
    """Return the direct child key names of *path* (empty when absent)."""
    try:
        key = reg.OpenKey(reg.HKEY_CURRENT_USER, path, 0, reg.KEY_READ)
    except FileNotFoundError:
        return ()
    names: list[str] = []
    try:
        index = 0
        while True:
            try:
                names.append(reg.EnumKey(key, index))
            except OSError:
                break
            index += 1
    finally:
        reg.CloseKey(key)
    return tuple(names)


def _delete_tree(reg: Any, path: str) -> bool:
    """Delete *path* and every descendant; True when something was removed."""
    children = _enum_subkeys(reg, path)
    if not children:
        try:
            reg.DeleteKey(reg.HKEY_CURRENT_USER, path)
        except FileNotFoundError:
            return False
        return True
    for child in children:
        _delete_tree(reg, f"{path}\\{child}")
    try:
        reg.DeleteKey(reg.HKEY_CURRENT_USER, path)
    except FileNotFoundError:
        return False
    return True


def planned_keys(*, flat: bool = False) -> tuple[str, ...]:
    """Return every key ``install`` writes (or would write under ``--dry``)."""
    keys: list[str] = []
    for ext in supported_extensions():
        keys.append(extension_key(ext))
        keys.extend(verb_key(ext, verb) for verb in VERBS)
        if flat:
            keys.extend(flat_key(ext, verb) for verb in VERBS)
    return tuple(keys)


def install(
    *,
    flat: bool = False,
    dry_run: bool = False,
    registry: Any | None = None,
    executable: str | None = None,
) -> tuple[str, ...]:
    """Register the per-user context-menu entries.

    Args:
        flat: Also write the flat-verb fallback keys (PLAN D58).  The default
            cascading submenu is always written.
        dry_run: When True, write nothing and return the keys that would be
            written (the suite's trace-mode discipline).
        registry: Injectable registry module; defaults to ``winreg``.
        executable: Interpreter to embed in the command; defaults to
            ``sys.executable``.

    Returns:
        The sorted key paths that were written (or would be, under *dry_run*).

    Raises:
        RuntimeError: On a non-Windows platform.
    """
    _require_windows()
    if dry_run:
        return tuple(sorted(planned_keys(flat=flat)))

    reg = registry if registry is not None else _registry()
    written: list[str] = []

    for ext in supported_extensions():
        menu = extension_key(ext)
        _set_string(reg, menu, "MUIVerb", MENU_LABEL)
        # An empty SubCommands value turns the entry into a cascade whose
        # children are the ``shell\<verb>`` keys below.
        _set_string(reg, menu, "SubCommands", "")
        for verb in VERBS:
            key = verb_key(ext, verb)
            _set_string(reg, key, "MUIVerb", verb.label)
            _set_string(reg, f"{key}\\command", "", command_for(verb, executable))
            written.extend((key, f"{key}\\command"))
        written.append(menu)

        if flat:
            for verb in VERBS:
                key = flat_key(ext, verb)
                _set_string(reg, key, "MUIVerb", f"{MENU_LABEL}: {verb.label}")
                _set_string(reg, f"{key}\\command", "", command_for(verb, executable))
                written.extend((key, f"{key}\\command"))

    return tuple(sorted(set(written)))


def uninstall(*, registry: Any | None = None) -> tuple[str, ...]:
    """Remove the menu entries this module installed.

    Removes both the cascade and the flat fallback, and never touches sibling
    verbs another application may have registered under the same extension.

    Args:
        registry: Injectable registry module; defaults to ``winreg``.

    Returns:
        The key paths that were removed (empty when nothing was installed).

    Raises:
        RuntimeError: On a non-Windows platform.
    """
    _require_windows()
    reg = registry if registry is not None else _registry()
    removed: list[str] = []

    for ext in supported_extensions():
        for path in (extension_key(ext),) + tuple(
            flat_key(ext, verb) for verb in VERBS
        ):
            if _delete_tree(reg, path):
                removed.append(path)

    return tuple(sorted(removed))


def installed_verbs(ext: str, *, registry: Any | None = None) -> tuple[str, ...]:
    """Return the verb ids registered for *ext* (cascade first, then flat).

    Args:
        ext: Dot-prefixed extension, e.g. ``".mp3"``.
        registry: Injectable registry module; defaults to ``winreg``.

    Returns:
        Installed verb ids in declaration order; empty when nothing is
        installed for that extension.
    """
    _require_windows()
    reg = registry if registry is not None else _registry()
    cascade = f"{extension_key(ext)}\\shell"
    present = set(_enum_subkeys(reg, cascade))
    found = [verb.id for verb in VERBS if verb.id in present]
    if found:
        return tuple(found)

    flat_parent = f"{SYSTEM_FILE_ASSOCIATIONS}\\{ext}\\shell"
    present = set(_enum_subkeys(reg, flat_parent))
    return tuple(verb.id for verb in VERBS if f"{FLAT_PREFIX}{verb.id}" in present)
