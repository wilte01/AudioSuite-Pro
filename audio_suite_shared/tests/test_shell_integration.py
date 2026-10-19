"""Tests for audio_suite_shared.shell_integration (Sprint 4 Item 4.1).

The registry is injected everywhere: writing through the real ``winreg`` in a
test would mutate the developer's own Explorer context menu.  Platform
detection is simulated by patching ``sys.platform`` only, never ``os.name``
(AGENTS "Verification Tooling Traps").

Changed in 1.4.0: new suite (PLAN D57/D58/D61).
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from audio_suite_shared import shell_integration as si


class _FakeKey:
    def __init__(self, path: str) -> None:
        self.path = path


class FakeRegistry:
    """A minimal in-memory stand-in for the ``winreg`` module."""

    HKEY_CURRENT_USER = "HKCU"
    KEY_READ = 1
    KEY_WRITE = 2
    REG_SZ = 1

    def __init__(self) -> None:
        self.values: dict[str, dict[str, str]] = {}

    def CreateKeyEx(
        self, root: str, path: str, reserved: int = 0, access: int = 0
    ) -> _FakeKey:
        self.values.setdefault(path, {})
        return _FakeKey(path)

    def SetValueEx(
        self, key: _FakeKey, name: str, reserved: int, kind: int, value: str
    ) -> None:
        self.values[key.path][name] = value

    def CloseKey(self, key: _FakeKey) -> None:
        return None

    def OpenKey(
        self, root: str, path: str, reserved: int = 0, access: int = 0
    ) -> _FakeKey:
        # winreg creates intermediate keys implicitly, so a key exists when it
        # holds values *or* when any stored key lives below it.
        if path not in self.values and not any(
            candidate.startswith(path + "\\") for candidate in self.values
        ):
            raise FileNotFoundError(path)
        return _FakeKey(path)

    def _children(self, path: str) -> list[str]:
        prefix = path + "\\"
        names = {
            candidate[len(prefix) :].split("\\", 1)[0]
            for candidate in self.values
            if candidate.startswith(prefix)
        }
        return sorted(names)

    def EnumKey(self, key: _FakeKey, index: int) -> str:
        children = self._children(key.path)
        if index >= len(children):
            raise OSError("no more keys")
        return children[index]

    def DeleteKey(self, root: str, path: str) -> None:
        if path not in self.values:
            raise FileNotFoundError(path)
        del self.values[path]


@pytest.fixture
def registry() -> FakeRegistry:
    return FakeRegistry()


@pytest.fixture(autouse=True)
def _windows() -> None:
    """Every test runs the Windows arm unless it patches sys.platform itself."""
    with patch.object(sys, "platform", "win32"):
        yield


class TestVerbTable:
    def test_five_verbs_in_declaration_order(self) -> None:
        assert [verb.id for verb in si.VERBS] == [
            "convert_mp3",
            "convert_flac",
            "analyze_bpm",
            "analyze_key",
            "analyze_mood",
        ]

    def test_every_verb_maps_to_a_real_cli_command(self) -> None:
        from audio_suite_shared.cli_app import cli

        ctx = __import__("click").Context(cli, resilient_parsing=True)
        registered = set(cli.list_commands(ctx))
        for verb in si.VERBS:
            assert verb.cli_args[0] in registered, verb.id

    def test_labels_are_unique(self) -> None:
        labels = [verb.label for verb in si.VERBS]
        assert len(labels) == len(set(labels))

    def test_command_names_the_interpreter_and_quotes_the_path(self) -> None:
        command = si.command_for(si.VERBS[0], r"C:\Python\python.exe")
        assert command.startswith('"C:\\Python\\python.exe" -m ')
        assert si.ACTION_MODULE in command
        assert command.endswith('"%1"')

    def test_extensions_are_dot_prefixed_and_non_empty(self) -> None:
        exts = si.supported_extensions()
        assert exts
        assert all(ext.startswith(".") for ext in exts)


class TestInstall:
    def test_writes_one_cascade_per_extension(self, registry: FakeRegistry) -> None:
        written = si.install(registry=registry, executable="python.exe")
        assert written
        mp3_menu = registry.values[si.extension_key(".mp3")]
        assert mp3_menu["MUIVerb"] == si.MENU_LABEL
        assert mp3_menu["SubCommands"] == ""
        for verb in si.VERBS:
            key = si.verb_key(".mp3", verb)
            assert registry.values[key]["MUIVerb"] == verb.label
            command = registry.values[f"{key}\\command"][""]
            assert verb.id in command
            assert command.endswith('"%1"')

    def test_does_not_write_flat_keys_by_default(self, registry: FakeRegistry) -> None:
        si.install(registry=registry)
        flat = si.flat_key(".mp3", si.VERBS[0])
        assert flat not in registry.values

    def test_flat_fallback_writes_sibling_verbs(self, registry: FakeRegistry) -> None:
        si.install(flat=True, registry=registry)
        for verb in si.VERBS:
            key = si.flat_key(".mp3", verb)
            assert registry.values[key]["MUIVerb"].startswith(si.MENU_LABEL)
            assert registry.values[f"{key}\\command"][""].endswith('"%1"')

    def test_install_is_idempotent(self, registry: FakeRegistry) -> None:
        first = si.install(registry=registry)
        before = {path: dict(values) for path, values in registry.values.items()}
        second = si.install(registry=registry)
        assert first == second
        assert registry.values == before

    def test_installed_verbs_reads_the_cascade(self, registry: FakeRegistry) -> None:
        si.install(registry=registry)
        assert si.installed_verbs(".mp3", registry=registry) == tuple(
            verb.id for verb in si.VERBS
        )

    def test_installed_verbs_falls_back_to_flat_keys(
        self, registry: FakeRegistry
    ) -> None:
        si.install(flat=True, registry=registry)
        for verb in si.VERBS:
            registry.DeleteKey("HKCU", si.verb_key(".mp3", verb))
        registry.DeleteKey("HKCU", si.extension_key(".mp3"))
        assert si.installed_verbs(".mp3", registry=registry) == tuple(
            verb.id for verb in si.VERBS
        )

    def test_installed_verbs_empty_when_absent(self, registry: FakeRegistry) -> None:
        assert si.installed_verbs(".mp3", registry=registry) == ()


class TestUninstall:
    def test_removes_the_cascade_and_its_children(self, registry: FakeRegistry) -> None:
        si.install(registry=registry)
        removed = si.uninstall(registry=registry)
        assert removed
        assert si.installed_verbs(".mp3", registry=registry) == ()
        assert si.extension_key(".mp3") not in registry.values

    def test_removes_the_flat_fallback_too(self, registry: FakeRegistry) -> None:
        si.install(flat=True, registry=registry)
        si.uninstall(registry=registry)
        assert not [path for path in registry.values if si.FLAT_PREFIX in path]

    def test_leaves_other_applications_verbs_alone(
        self, registry: FakeRegistry
    ) -> None:
        other = si.SYSTEM_FILE_ASSOCIATIONS + "\\.mp3\\shell\\OtherApp"
        registry.CreateKeyEx("HKCU", other)
        registry.SetValueEx(_FakeKey(other), "MUIVerb", 0, 1, "Other App")
        si.install(registry=registry)
        si.uninstall(registry=registry)
        assert other in registry.values

    def test_uninstall_when_absent_is_a_no_op(self, registry: FakeRegistry) -> None:
        assert si.uninstall(registry=registry) == ()


class TestDryRun:
    def test_dry_run_writes_nothing(self, registry: FakeRegistry) -> None:
        keys = si.install(dry_run=True, registry=registry)
        assert keys == tuple(sorted(si.planned_keys()))
        assert registry.values == {}

    def test_flat_dry_run_lists_the_fallback(self, registry: FakeRegistry) -> None:
        keys = si.install(flat=True, dry_run=True, registry=registry)
        assert si.flat_key(".mp3", si.VERBS[0]) in keys


class TestNonWindows:
    def test_install_refuses_on_a_non_windows_platform(self) -> None:
        with patch.object(sys, "platform", "linux"):
            with pytest.raises(RuntimeError, match="Windows-only"):
                si.install(registry=FakeRegistry())

    def test_uninstall_refuses_on_a_non_windows_platform(self) -> None:
        with patch.object(sys, "platform", "darwin"):
            with pytest.raises(RuntimeError, match="Windows-only"):
                si.uninstall(registry=FakeRegistry())
