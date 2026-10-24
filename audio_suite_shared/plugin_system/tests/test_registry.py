"""Tests for :mod:`audio_suite_shared.plugin_system.registry`.

Two properties are load-bearing and are proved here rather than assumed:

* resolution is **lazy** — importing the suite's CLI must not import a plugin,
  which the marker-file case asserts by checking the filesystem before and
  after ``resolve``;
* a plugin that cannot be imported is a named ``PluginError``, so a host can
  report it against the plugin instead of failing the run.

Changed in 2.1.0: new file — the plugin registry's contract (Sprint 7).
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from audio_suite_shared.plugin_system import registry as plugin_registry
from audio_suite_shared.plugin_system.loader import MANIFEST_FILENAME, discover
from audio_suite_shared.plugin_system.models import PluginError

_PLUGIN_TABLE = """
[plugin]
id = "{plugin_id}"
name = "{name}"
version = "1.0.0"
author = "Tester"
description = "Registry test plugin"
api_version = 1
"""

_TOOL = """
[tool]
id = "{tool_id}"
name = "Registry Tool"
category = "utility"
description = "A tool"
entry_point = "{package}.tool:main"
cli_command = "{command}"
"""

_TAG_PROCESSOR = """
[[tag_processor]]
id = "tp"
name = "TP"
entry_point = "{package}.hooks:apply"
"""

_ANALYSIS = """
[[analysis]]
id = "an"
name = "AN"
entry_point = "{package}.hooks:analyse"
"""


@pytest.fixture(autouse=True)
def restore_process_state() -> Iterator[None]:
    """Undo the imports and sys.path entries a test's resolution performs."""
    modules_before = set(sys.modules)
    path_before = list(sys.path)
    yield
    plugin_registry.reset_plugins_for_tests()
    for name in set(sys.modules) - modules_before:
        del sys.modules[name]
    sys.path[:] = path_before


def _make_plugin(
    root: Path,
    package: str,
    *,
    plugin_id: str | None = None,
    with_tool: bool = False,
    with_contributions: bool = False,
    module_body: str = (
        "def apply(path, dry_run):\n"
        "    return True\n"
        "\n\n"
        "def analyse(path, tags):\n"
        "    return {'n': 1}\n"
    ),
) -> Path:
    """Create a plugin package with a manifest and one module.

    Args:
        root: Directory to create the plugin under.
        package: The package (directory) name.
        plugin_id: The declared plugin id; defaults to *package*.
        with_tool: Whether to declare a ``[tool]`` table.
        with_contributions: Whether to declare both contribution kinds.
        module_body: Source of the package's ``hooks`` module.

    Returns:
        The plugin directory.
    """
    directory = root / package
    directory.mkdir(parents=True)
    body = _PLUGIN_TABLE.format(plugin_id=plugin_id or package, name=package)
    if with_tool:
        body += _TOOL.format(
            tool_id=f"{package}_tool", package=package, command=f"{package}-tool"
        )
    if with_contributions:
        body += _TAG_PROCESSOR.format(package=package) + _ANALYSIS.format(
            package=package
        )
    (directory / MANIFEST_FILENAME).write_text(body, encoding="utf-8")
    (directory / "__init__.py").write_text("", encoding="utf-8")
    (directory / "hooks.py").write_text(module_body, encoding="utf-8")
    (directory / "tool.py").write_text(
        "def main(directory, dry_run=False):\n    return None\n", encoding="utf-8"
    )
    return directory


def _registry(
    root: Path, *, enabled: dict[str, bool]
) -> plugin_registry.PluginRegistry:
    """Discover *root* and wrap it in a registry.

    Args:
        root: The plugin root to scan.
        enabled: The enablement map to apply.

    Returns:
        A registry over the discovered plugins.
    """
    discovery = discover(root, enabled=enabled)
    assert discovery.problems == (), [problem.reason for problem in discovery.problems]
    return plugin_registry.PluginRegistry(discovery, root.resolve())


class TestViews:
    def test_only_enabled_plugins_are_active(self, tmp_path: Path) -> None:
        _make_plugin(tmp_path, "regalpha", with_tool=True, with_contributions=True)
        _make_plugin(tmp_path, "regbeta", with_contributions=True)

        registry = _registry(tmp_path, enabled={"regalpha": True})

        assert [manifest.plugin_id for manifest in registry.manifests] == [
            "regalpha",
            "regbeta",
        ]
        assert [manifest.plugin_id for manifest in registry.enabled] == ["regalpha"]
        assert [state.status for state in registry.states] == ["loaded", "disabled"]

    def test_tool_manifests_require_an_enabled_tool(self, tmp_path: Path) -> None:
        _make_plugin(tmp_path, "regalpha", with_tool=True)
        _make_plugin(tmp_path, "regbeta")

        registry = _registry(tmp_path, enabled={"regalpha": True, "regbeta": True})

        assert [manifest.plugin_id for manifest in registry.tool_manifests()] == [
            "regalpha"
        ]

    def test_contributions_are_sorted_and_enabled_only(self, tmp_path: Path) -> None:
        _make_plugin(tmp_path, "regbeta", with_contributions=True)
        _make_plugin(tmp_path, "regalpha", with_contributions=True)
        _make_plugin(tmp_path, "regdisabled", with_contributions=True)

        registry = _registry(
            tmp_path, enabled={"regalpha": True, "regbeta": True, "regdisabled": False}
        )

        assert [spec.plugin_id for spec in registry.tag_processors()] == [
            "regalpha",
            "regbeta",
        ]
        assert [spec.plugin_id for spec in registry.analysis_contributions()] == [
            "regalpha",
            "regbeta",
        ]

    def test_manifest_for_finds_disabled_plugins(self, tmp_path: Path) -> None:
        _make_plugin(tmp_path, "regalpha")

        registry = _registry(tmp_path, enabled={})

        assert registry.manifest_for("regalpha") is not None
        assert registry.manifest_for("absent") is None
        assert registry.plugin_root == tmp_path.resolve()


class TestResolution:
    def test_resolution_is_lazy(self, tmp_path: Path) -> None:
        marker = tmp_path / "imported.marker"
        _make_plugin(
            tmp_path,
            "regalpha",
            with_contributions=True,
            module_body=(
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('x', encoding='utf-8')\n"
                "\n\ndef apply(path, dry_run):\n    return True\n"
            ),
        )
        registry = _registry(tmp_path, enabled={"regalpha": True})

        assert not marker.exists(), "discovery must not import plugin code"

        spec = registry.tag_processors()[0]
        hook = registry.resolve_spec(spec)

        assert marker.exists()
        assert callable(hook)

    def test_resolution_is_cached(self, tmp_path: Path) -> None:
        _make_plugin(tmp_path, "regalpha", with_contributions=True)
        registry = _registry(tmp_path, enabled={"regalpha": True})

        spec = registry.tag_processors()[0]

        assert registry.resolve_spec(spec) is registry.resolve_spec(spec)

    def test_missing_module_is_a_plugin_error(self, tmp_path: Path) -> None:
        _make_plugin(tmp_path, "regalpha", with_contributions=True)
        registry = _registry(tmp_path, enabled={"regalpha": True})

        with pytest.raises(PluginError, match="cannot import 'regalpha.absent'"):
            registry.resolve("regalpha.absent:apply")

    def test_missing_attribute_is_a_plugin_error(self, tmp_path: Path) -> None:
        _make_plugin(tmp_path, "regalpha", with_contributions=True)
        registry = _registry(tmp_path, enabled={"regalpha": True})

        with pytest.raises(PluginError, match="has no attribute 'nope'"):
            registry.resolve("regalpha.hooks:nope")

    def test_non_callable_entry_point_is_a_plugin_error(self, tmp_path: Path) -> None:
        _make_plugin(
            tmp_path,
            "regalpha",
            with_contributions=True,
            module_body="VALUE = 3\n",
        )
        registry = _registry(tmp_path, enabled={"regalpha": True})

        with pytest.raises(PluginError, match="not callable"):
            registry.resolve("regalpha.hooks:VALUE")

    def test_resolve_spec_names_the_plugin_and_contribution(
        self, tmp_path: Path
    ) -> None:
        _make_plugin(tmp_path, "regalpha", with_contributions=True, module_body="")
        registry = _registry(tmp_path, enabled={"regalpha": True})

        spec = registry.tag_processors()[0]

        with pytest.raises(PluginError) as excinfo:
            registry.resolve_spec(spec)

        message = str(excinfo.value)
        assert "regalpha" in message
        assert "tag_processor:tp" in message

    def test_module_import_error_is_wrapped(self, tmp_path: Path) -> None:
        _make_plugin(
            tmp_path,
            "regalpha",
            with_contributions=True,
            module_body="raise RuntimeError('boom')\n",
        )
        registry = _registry(tmp_path, enabled={"regalpha": True})

        with pytest.raises(PluginError, match="RuntimeError: boom"):
            registry.resolve("regalpha.hooks:apply")


class TestSingleton:
    def test_get_plugins_is_a_singleton(self, tmp_path: Path) -> None:
        _make_plugin(tmp_path, "regalpha")

        first = plugin_registry.get_plugins(root=tmp_path, enabled={"regalpha": True})
        second = plugin_registry.get_plugins()

        assert first is second
        assert [manifest.plugin_id for manifest in first.enabled] == ["regalpha"]

    def test_reset_allows_a_second_discovery(self, tmp_path: Path) -> None:
        first = plugin_registry.get_plugins(root=tmp_path, enabled={})
        plugin_registry.reset_plugins_for_tests()
        second = plugin_registry.get_plugins(root=tmp_path, enabled={})

        assert first is not second
