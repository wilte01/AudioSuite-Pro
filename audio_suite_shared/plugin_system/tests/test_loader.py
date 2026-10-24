"""Tests for :mod:`audio_suite_shared.plugin_system.loader`.

The loader is the security boundary: it is the only code that reads a
third-party manifest before any plugin module is imported.  Every rejection
reason therefore has its own case here, and the discovery tests assert both
halves of the contract — a bad plugin is refused *and* the good one beside it
still loads.

Changed in 2.1.0: new file — the manifest loader's contract (Sprint 7).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from audio_suite_shared.plugin_system import loader
from audio_suite_shared.plugin_system.models import PLUGIN_API_VERSION

_PLUGIN_TABLE = """
[plugin]
id = "{plugin_id}"
name = "Test Plugin"
version = "1.0.0"
author = "Tester"
description = "A plugin for the loader tests"
api_version = {api_version}
"""


def _write_plugin(
    root: Path,
    directory: str,
    plugin_id: str,
    *,
    extra: str = "",
    api_version: int = PLUGIN_API_VERSION,
    manifest: str | None = None,
) -> Path:
    """Create a plugin directory holding a manifest.

    Args:
        root: Directory to create the plugin under.
        directory: The plugin directory name (also its package name).
        plugin_id: The plugin id to declare.
        extra: TOML appended after the ``[plugin]`` table.
        api_version: The manifest API generation to declare.
        manifest: Full manifest text, used instead of the generated one.

    Returns:
        The created plugin directory.
    """
    plugin_dir = root / directory
    plugin_dir.mkdir(parents=True)
    body = (
        manifest
        if manifest is not None
        else (
            _PLUGIN_TABLE.format(plugin_id=plugin_id, api_version=api_version) + extra
        )
    )
    (plugin_dir / loader.MANIFEST_FILENAME).write_text(body, encoding="utf-8")
    return plugin_dir


def _tool_table(plugin_dir_name: str, **overrides: str) -> str:
    """Return a valid ``[tool]`` table, with keys overridable.

    Args:
        plugin_dir_name: The plugin's package name, used in the entry point.
        **overrides: Field values to replace the defaults with.

    Returns:
        The TOML text of the table.
    """
    fields = {
        "id": "test_tool",
        "name": "Test Tool",
        "category": "utility",
        "description": "A tool for the loader tests",
        "entry_point": f"{plugin_dir_name}.tool:main",
        "cli_command": "test-plugin",
    }
    fields.update(overrides)
    lines = ["", "[tool]"]
    for key, value in fields.items():
        if value == "":
            continue
        lines.append(f'{key} = "{value}"')
    return "\n".join(lines) + "\n"


class TestValidManifests:
    def test_minimal_manifest_parses(self, tmp_path: Path) -> None:
        _write_plugin(tmp_path, "alpha_plugin", "alpha_plugin")

        discovery = loader.discover(tmp_path, enabled={})

        assert len(discovery.states) == 1
        state = discovery.states[0]
        assert state.plugin_id == "alpha_plugin"
        assert state.status == "disabled"
        assert state.manifest is not None
        assert state.manifest.tool is None
        assert discovery.problems == ()

    def test_tool_and_contributions_parse(self, tmp_path: Path) -> None:
        plugin_dir = _write_plugin(
            tmp_path,
            "alpha_plugin",
            "alpha_plugin",
            extra=(
                _tool_table("alpha_plugin")
                + '\n[tool.ui]\nentry = "alpha_plugin.ui:build"\n'
                + '\n[[tag_processor]]\nid = "tp"\nname = "TP"\n'
                'entry_point = "alpha_plugin.tags:apply"\n'
                + '\n[[analysis]]\nid = "an"\nname = "AN"\n'
                'entry_point = "alpha_plugin.stats:analyse"\n'
            ),
        )
        (plugin_dir / "Example.pyw").write_text("", encoding="utf-8")

        discovery = loader.discover(tmp_path, enabled={"alpha_plugin": True})

        manifest = discovery.enabled[0]
        assert manifest.tool is not None
        assert manifest.tool.id == "test_tool"
        assert manifest.tool.cli_command == "test-plugin"
        assert manifest.tool.ui_entry == "alpha_plugin.ui:build"
        assert [spec.id for spec in manifest.tag_processors] == ["tp"]
        assert [spec.id for spec in manifest.analysis] == ["an"]
        assert [spec.kind for spec in manifest.contributions()] == [
            "tag_processor",
            "analysis",
        ]

    def test_entry_point_without_cli_command_derives_a_name(
        self, tmp_path: Path
    ) -> None:
        _write_plugin(
            tmp_path,
            "alpha_plugin",
            "alpha_plugin",
            extra=_tool_table("alpha_plugin", cli_command=""),
        )

        discovery = loader.discover(tmp_path, enabled={"alpha_plugin": True})

        assert discovery.enabled[0].tool is not None
        assert discovery.enabled[0].tool.cli_command == "plugin-alpha_plugin"

    def test_launcher_is_returned_suite_relative(self, tmp_path: Path) -> None:
        plugin_dir = _write_plugin(
            tmp_path,
            "alpha_plugin",
            "alpha_plugin",
            extra=_tool_table("alpha_plugin", launcher="Alpha.pyw"),
        )
        (plugin_dir / "Alpha.pyw").write_text("", encoding="utf-8")

        discovery = loader.discover(tmp_path, enabled={"alpha_plugin": True})

        launcher = discovery.enabled[0].tool
        assert launcher is not None
        # The temp tree is not under the suite root, so the path stays absolute
        # and the driver's os.path.join(suite_root, ...) keeps it intact.
        assert Path(launcher.launcher or "").is_absolute()

    def test_manifest_as_dict_is_json_friendly(self, tmp_path: Path) -> None:
        import json

        _write_plugin(
            tmp_path,
            "alpha_plugin",
            "alpha_plugin",
            extra=_tool_table("alpha_plugin"),
        )

        discovery = loader.discover(tmp_path, enabled={"alpha_plugin": True})
        payload = loader.manifest_as_dict(discovery.enabled[0])

        assert payload["plugin"] == "alpha_plugin"
        assert json.dumps(payload)  # no Path objects leak into the payload


class TestManifestRejections:
    """One case per refusal: a plugin that cannot be honoured must say why."""

    @pytest.mark.parametrize(
        ("case", "manifest", "expected"),
        [
            (
                "not_toml",
                "[plugin\nid = 'x'",
                "not valid TOML",
            ),
            (
                "missing_plugin_table",
                "[tool]\nid = 'x'\n",
                "missing the [plugin] table",
            ),
            (
                "bad_id",
                _PLUGIN_TABLE.format(plugin_id="Not An Id", api_version=1),
                "must match",
            ),
            (
                "bad_version",
                _PLUGIN_TABLE.format(plugin_id="alpha", api_version=1).replace(
                    'version = "1.0.0"', 'version = "one"'
                ),
                "not a dotted version string",
            ),
            (
                "api_version",
                _PLUGIN_TABLE.format(plugin_id="alpha", api_version=99),
                "api_version 99 is not supported",
            ),
            (
                "unknown_section",
                _PLUGIN_TABLE.format(plugin_id="alpha", api_version=1)
                + "\n[extra]\nx = 1\n",
                "unknown section",
            ),
        ],
    )
    def test_manifest_is_refused(
        self, tmp_path: Path, case: str, manifest: str, expected: str
    ) -> None:
        _write_plugin(tmp_path, "alpha_plugin", "alpha_plugin", manifest=manifest)

        discovery = loader.discover(tmp_path, enabled={})

        assert discovery.enabled == ()
        assert discovery.problems, case
        assert expected in discovery.problems[0].reason

    def test_api_version_names_both_numbers(self, tmp_path: Path) -> None:
        _write_plugin(
            tmp_path,
            "alpha_plugin",
            "alpha_plugin",
            api_version=PLUGIN_API_VERSION + 1,
        )

        discovery = loader.discover(tmp_path, enabled={})

        reason = discovery.problems[0].reason
        assert str(PLUGIN_API_VERSION + 1) in reason
        assert str(PLUGIN_API_VERSION) in reason

    def test_unknown_tool_key_is_refused(self, tmp_path: Path) -> None:
        _write_plugin(
            tmp_path,
            "alpha_plugin",
            "alpha_plugin",
            extra=_tool_table("alpha_plugin") + 'typo = "x"\n',
        )

        discovery = loader.discover(tmp_path, enabled={})

        assert "typo" in discovery.problems[0].reason

    def test_tool_without_a_surface_is_refused(self, tmp_path: Path) -> None:
        _write_plugin(
            tmp_path,
            "alpha_plugin",
            "alpha_plugin",
            extra=_tool_table("alpha_plugin", entry_point=""),
        )

        discovery = loader.discover(tmp_path, enabled={})

        assert "neither entry_point nor launcher" in discovery.problems[0].reason

    def test_tool_id_collision_with_a_first_party_tool(self, tmp_path: Path) -> None:
        _write_plugin(
            tmp_path,
            "alpha_plugin",
            "alpha_plugin",
            extra=_tool_table("alpha_plugin", id="bpm"),
        )

        discovery = loader.discover(
            tmp_path, enabled={}, reserved_ids=frozenset({"bpm"})
        )

        assert "already used by a first-party tool" in discovery.problems[0].reason

    def test_plugin_id_collision_with_a_first_party_id(self, tmp_path: Path) -> None:
        _write_plugin(tmp_path, "alpha_plugin", "bpm")

        discovery = loader.discover(
            tmp_path, enabled={}, reserved_ids=frozenset({"bpm"})
        )

        assert "already used by a first-party tool" in discovery.problems[0].reason

    def test_entry_point_outside_the_package_is_refused(self, tmp_path: Path) -> None:
        _write_plugin(
            tmp_path,
            "alpha_plugin",
            "alpha_plugin",
            extra=_tool_table("alpha_plugin", entry_point="elsewhere.module:main"),
        )

        discovery = loader.discover(tmp_path, enabled={})

        assert "inside the plugin package" in discovery.problems[0].reason

    def test_entry_point_naming_a_stdlib_module_is_refused(
        self, tmp_path: Path
    ) -> None:
        _write_plugin(
            tmp_path,
            "alpha_plugin",
            "alpha_plugin",
            extra=_tool_table("alpha_plugin", entry_point="alpha_plugin.os:system"),
        )

        discovery = loader.discover(tmp_path, enabled={})

        assert "standard-library module" in discovery.problems[0].reason

    def test_entry_point_without_a_callable_is_refused(self, tmp_path: Path) -> None:
        _write_plugin(
            tmp_path,
            "alpha_plugin",
            "alpha_plugin",
            extra=_tool_table("alpha_plugin", entry_point="alpha_plugin.tool"),
        )

        discovery = loader.discover(tmp_path, enabled={})

        assert "module:callable" in discovery.problems[0].reason

    def test_reserved_cli_command_is_refused(self, tmp_path: Path) -> None:
        _write_plugin(
            tmp_path,
            "alpha_plugin",
            "alpha_plugin",
            extra=_tool_table("alpha_plugin", cli_command="doctor"),
        )

        discovery = loader.discover(
            tmp_path, enabled={}, reserved_commands=frozenset({"doctor"})
        )

        assert "already registered by the suite" in discovery.problems[0].reason

    def test_two_plugins_may_not_share_a_command(self, tmp_path: Path) -> None:
        _write_plugin(
            tmp_path, "alpha_plugin", "alpha_plugin", extra=_tool_table("alpha_plugin")
        )
        _write_plugin(
            tmp_path,
            "beta_plugin",
            "beta_plugin",
            extra=_tool_table(
                "beta_plugin", id="beta_tool", entry_point="beta_plugin.tool:main"
            ),
        )

        discovery = loader.discover(tmp_path, enabled={})

        assert [manifest.plugin_id for manifest in discovery.manifests] == [
            "alpha_plugin"
        ]
        assert "already declared by alpha_plugin" in discovery.problems[0].reason

    def test_two_plugins_may_not_share_a_plugin_id(self, tmp_path: Path) -> None:
        _write_plugin(tmp_path, "alpha_plugin", "same_id")
        _write_plugin(tmp_path, "beta_plugin", "same_id")

        discovery = loader.discover(tmp_path, enabled={})

        assert len(discovery.enabled) == 0
        assert "already declared by" in discovery.problems[0].reason

    def test_launcher_escaping_the_plugin_is_refused(self, tmp_path: Path) -> None:
        _write_plugin(
            tmp_path,
            "alpha_plugin",
            "alpha_plugin",
            extra=_tool_table("alpha_plugin", launcher="../Outside.pyw"),
        )

        discovery = loader.discover(tmp_path, enabled={})

        assert "leaves the plugin directory" in discovery.problems[0].reason

    def test_launcher_must_be_a_pyw(self, tmp_path: Path) -> None:
        plugin_dir = _write_plugin(
            tmp_path,
            "alpha_plugin",
            "alpha_plugin",
            extra=_tool_table("alpha_plugin", launcher="Alpha.py"),
        )
        (plugin_dir / "Alpha.py").write_text("", encoding="utf-8")

        discovery = loader.discover(tmp_path, enabled={})

        assert "must be a .pyw file" in discovery.problems[0].reason

    def test_missing_launcher_is_refused(self, tmp_path: Path) -> None:
        _write_plugin(
            tmp_path,
            "alpha_plugin",
            "alpha_plugin",
            extra=_tool_table("alpha_plugin", launcher="Missing.pyw"),
        )

        discovery = loader.discover(tmp_path, enabled={})

        assert "does not exist" in discovery.problems[0].reason

    def test_non_identifier_directory_is_refused(self, tmp_path: Path) -> None:
        _write_plugin(tmp_path, "alpha-plugin", "alpha_plugin")

        discovery = loader.discover(tmp_path, enabled={})

        assert "not a valid Python identifier" in discovery.problems[0].reason

    def test_first_party_package_name_is_refused(self, tmp_path: Path) -> None:
        _write_plugin(tmp_path, "audio_suite_shared", "alpha_plugin")

        discovery = loader.discover(tmp_path, enabled={})

        assert "first-party package name" in discovery.problems[0].reason

    def test_contribution_without_entry_point_is_refused(self, tmp_path: Path) -> None:
        _write_plugin(
            tmp_path,
            "alpha_plugin",
            "alpha_plugin",
            extra='\n[[tag_processor]]\nid = "tp"\nname = "TP"\n',
        )

        discovery = loader.discover(tmp_path, enabled={})

        assert "entry_point is required" in discovery.problems[0].reason

    def test_duplicate_contribution_id_is_refused(self, tmp_path: Path) -> None:
        _write_plugin(
            tmp_path,
            "alpha_plugin",
            "alpha_plugin",
            extra=(
                '\n[[analysis]]\nid = "an"\nname = "AN"\n'
                'entry_point = "alpha_plugin.stats:a"\n'
                '\n[[analysis]]\nid = "an"\nname = "AN2"\n'
                'entry_point = "alpha_plugin.stats:b"\n'
            ),
        )

        discovery = loader.discover(tmp_path, enabled={})

        assert "declared twice" in discovery.problems[0].reason


class TestDiscovery:
    def test_a_missing_directory_is_empty_not_an_error(self, tmp_path: Path) -> None:
        discovery = loader.discover(tmp_path / "absent", enabled={})

        assert discovery.states == ()
        assert discovery.problems == ()

    def test_a_directory_without_a_manifest_is_not_a_plugin(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "not_a_plugin").mkdir()

        assert loader.discover(tmp_path, enabled={}).states == ()

    def test_one_bad_plugin_does_not_stop_the_others(self, tmp_path: Path) -> None:
        _write_plugin(tmp_path, "alpha_plugin", "alpha_plugin")
        _write_plugin(
            tmp_path,
            "broken_plugin",
            "broken_plugin",
            manifest="[plugin\n",
        )

        discovery = loader.discover(tmp_path, enabled={"alpha_plugin": True})

        assert [state.plugin_id for state in discovery.enabled] == ["alpha_plugin"]
        assert [problem.directory.name for problem in discovery.problems] == [
            "broken_plugin"
        ]
        assert discovery.states[-1].status == "rejected"

    def test_enablement_defaults_to_disabled_for_a_third_party_plugin(
        self, tmp_path: Path
    ) -> None:
        _write_plugin(tmp_path, "alpha_plugin", "alpha_plugin")

        discovery = loader.discover(tmp_path, enabled={})

        assert discovery.enabled == ()
        assert discovery.manifests, "a disabled manifest is still described"
        assert discovery.states[0].status == "disabled"

    def test_enablement_map_turns_a_plugin_on(self, tmp_path: Path) -> None:
        _write_plugin(tmp_path, "alpha_plugin", "alpha_plugin")

        discovery = loader.discover(tmp_path, enabled={"alpha_plugin": True})

        assert [state.status for state in discovery.states] == ["loaded"]
        assert len(discovery.enabled) == 1

    def test_store_map_turns_a_bundled_plugin_off(self, tmp_path: Path) -> None:
        bundled = sorted(loader.BUNDLED_DEFAULT_ENABLED)[0]
        _write_plugin(tmp_path, bundled, bundled)

        discovery = loader.discover(tmp_path, enabled={bundled: False})

        assert discovery.states[0].status == "disabled"

    def test_state_for_finds_a_plugin(self, tmp_path: Path) -> None:
        _write_plugin(tmp_path, "alpha_plugin", "alpha_plugin")

        discovery = loader.discover(tmp_path, enabled={})

        assert discovery.state_for("alpha_plugin") is not None
        assert discovery.state_for("absent") is None

    def test_default_root_honours_the_environment_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(loader.PLUGIN_DIR_ENV, str(tmp_path))

        assert loader.default_plugin_root() == tmp_path.resolve()

    def test_default_root_is_the_suite_plugins_directory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(loader.PLUGIN_DIR_ENV, raising=False)

        root = loader.default_plugin_root()

        assert root.name == "plugins"
        assert (root / "example_plugin" / loader.MANIFEST_FILENAME).is_file()


class TestShippedExamplePlugin:
    """The committed example plugin is what proves discovery is not vacuous."""

    def test_the_shipped_plugins_directory_loads_the_example(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(loader.PLUGIN_DIR_ENV, raising=False)

        discovery = loader.discover(enabled={})

        assert discovery.problems == ()
        ids = [manifest.plugin_id for manifest in discovery.manifests]
        assert ids, "the shipped plugins/ directory discovered no plugin"
        assert "example_plugin" in ids

    def test_the_example_is_enabled_by_the_suite_itself(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(loader.PLUGIN_DIR_ENV, raising=False)

        discovery = loader.discover(enabled={})

        enabled = [manifest.plugin_id for manifest in discovery.enabled]
        assert enabled == ["example_plugin"]

    def test_the_example_declares_every_extension_point(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(loader.PLUGIN_DIR_ENV, raising=False)

        discovery = loader.discover(enabled={})
        manifest = next(
            item for item in discovery.manifests if item.plugin_id == "example_plugin"
        )

        assert manifest.tool is not None
        assert manifest.tool.ui_entry is not None
        assert manifest.tag_processors
        assert manifest.analysis
