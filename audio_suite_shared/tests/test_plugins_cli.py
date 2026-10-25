"""Tests for :mod:`audio_suite_shared.plugins_cli`.

``plugins list`` publishes every discovered plugin and counts a rejected
manifest in the payload's ``errors``.  Audit R-06 (plan D9) is that the shell
status has to agree with the count a run reports, so this module pins both
halves: a rejected manifest exits 1 with the reason still printed, and a tree
whose plugins are all sound exits 0.

Changed in 2.1.4: new file — the ``plugins list`` exit contract (plan C1, D23).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from audio_suite_shared.cli_app import cli
from audio_suite_shared.plugin_system import loader, reset_plugins_for_tests
from audio_suite_shared.plugin_system.models import PLUGIN_API_VERSION

_MANIFEST = """
[plugin]
id = "{plugin_id}"
name = "Fixture Plugin"
version = "1.0.0"
author = "Tester"
description = "A plugin for the plugins-list tests"
api_version = {api_version}
"""


def _write_plugin(root: Path, plugin_id: str, *, api_version: int) -> Path:
    """Create a plugin directory whose manifest declares *api_version*."""
    plugin_dir = root / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / loader.MANIFEST_FILENAME).write_text(
        _MANIFEST.format(plugin_id=plugin_id, api_version=api_version),
        encoding="utf-8",
    )
    return plugin_dir


@pytest.fixture
def plugin_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point discovery at a throwaway plugin tree and reset the singleton."""
    root = tmp_path / "plugins"
    root.mkdir()
    monkeypatch.setenv("AUDIOSUITE_PLUGIN_DIR", str(root))
    monkeypatch.delenv("AUDIOSUITE_PLUGIN_DISABLED", raising=False)
    reset_plugins_for_tests()
    yield root
    reset_plugins_for_tests()


def _list(*args: str):
    """Invoke ``plugins list`` with the given extra arguments."""
    return CliRunner().invoke(cli, ["plugins", "list", *args])


class TestPluginsListExitContract:
    def test_a_rejected_manifest_exits_1_and_is_reported(
        self, plugin_root: Path
    ) -> None:
        """A manifest the suite refused is an error, not a footnote."""
        _write_plugin(plugin_root, "good_plugin", api_version=PLUGIN_API_VERSION)
        _write_plugin(plugin_root, "future_plugin", api_version=PLUGIN_API_VERSION + 99)

        result = _list("--json")

        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["errors"] == 1
        rejected = [p for p in payload["plugins"] if p["status"] == "rejected"]
        assert [p["id"] for p in rejected] == ["future_plugin"]
        assert rejected[0]["problem"]

    def test_the_text_report_names_the_rejected_plugin(self, plugin_root: Path) -> None:
        _write_plugin(plugin_root, "future_plugin", api_version=PLUGIN_API_VERSION + 99)

        result = _list()

        assert result.exit_code == 1
        assert "1 rejected" in result.output
        assert "future_plugin" in result.output

    def test_an_all_sound_tree_exits_0(self, plugin_root: Path) -> None:
        _write_plugin(plugin_root, "good_plugin", api_version=PLUGIN_API_VERSION)

        result = _list("--json")

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["errors"] == 0
        # A third-party plugin is disabled until the user enables it (enablement
        # is a suite preference, never a manifest field) but it is not rejected.
        assert [p["status"] for p in payload["plugins"]] == ["disabled"]
        assert payload["plugins"][0]["problem"] is None

    def test_an_empty_tree_exits_0(self, plugin_root: Path) -> None:
        result = _list()

        assert result.exit_code == 0, result.output
        assert "No plugins found" in result.output


class TestPluginsToggleExitContract:
    """``enable`` / ``disable`` already own their status; pin it while here."""

    def test_enabling_an_unknown_plugin_is_a_usage_error(
        self, plugin_root: Path
    ) -> None:
        result = CliRunner().invoke(cli, ["plugins", "enable", "nope"])

        assert result.exit_code == 2
        assert "no plugin with id" in result.output

    def test_enabling_a_rejected_plugin_exits_1(self, plugin_root: Path) -> None:
        _write_plugin(plugin_root, "future_plugin", api_version=PLUGIN_API_VERSION + 99)

        result = CliRunner().invoke(cli, ["plugins", "enable", "future_plugin"])

        assert result.exit_code == 1
        assert "rejected" in result.output
