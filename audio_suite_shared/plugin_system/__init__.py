"""plugin_system — third-party extensions for AudioSuite-Pro.

A plugin is a directory under ``<suite root>/plugins/`` holding a
``MANIFEST.toml``.  This package discovers and validates those manifests, keeps
them in one process-wide registry, and resolves a contribution's entry point
only when a host actually runs it.

The public surface is deliberately small:

.. code-block:: python

    from audio_suite_shared.plugin_system import get_plugins

    registry = get_plugins()
    for state in registry.states:
        print(state.plugin_id, state.status)

Hosts that consume contributions use
:mod:`audio_suite_shared.plugin_system.extension_points`; a plugin author needs
neither module, because a contribution is a plain ``module:callable`` reference
validated by the loader.

Changed in 2.1.0: new package — the plugin system's public surface (Sprint 7,
Item 7.1).
"""

from __future__ import annotations

from audio_suite_shared.plugin_system.extension_points import (
    PluginContext,
    TagProcessorOutcome,
    context_for,
    normalise_outcome,
    resolved_contributions,
    run_analysis,
    run_tag_processor,
    run_tool_entry,
)
from audio_suite_shared.plugin_system.loader import (
    BUNDLED_DEFAULT_ENABLED,
    MANIFEST_FILENAME,
    PLUGIN_DIR_ENV,
    Discovery,
    PluginManifestError,
    default_plugin_root,
    discover,
    is_enabled,
    load_enabled_map,
    manifest_as_dict,
    save_enabled_map,
)
from audio_suite_shared.plugin_system.models import (
    PLUGIN_API_VERSION,
    PLUGIN_CATEGORIES,
    ContributionSpec,
    PluginError,
    PluginManifest,
    PluginProblem,
    PluginState,
    ToolContribution,
)
from audio_suite_shared.plugin_system.registry import (
    PluginRegistry,
    get_plugins,
    reset_plugins_for_tests,
)

__all__ = [
    "BUNDLED_DEFAULT_ENABLED",
    "MANIFEST_FILENAME",
    "PLUGIN_API_VERSION",
    "PLUGIN_CATEGORIES",
    "PLUGIN_DIR_ENV",
    "ContributionSpec",
    "Discovery",
    "PluginContext",
    "PluginError",
    "PluginManifest",
    "PluginManifestError",
    "PluginProblem",
    "PluginRegistry",
    "PluginState",
    "TagProcessorOutcome",
    "ToolContribution",
    "context_for",
    "default_plugin_root",
    "discover",
    "get_plugins",
    "is_enabled",
    "load_enabled_map",
    "manifest_as_dict",
    "normalise_outcome",
    "reset_plugins_for_tests",
    "resolved_contributions",
    "run_analysis",
    "run_tag_processor",
    "run_tool_entry",
    "save_enabled_map",
]
