"""registry.py — the process-wide view of discovered plugins and their hooks.

The registry owns three jobs:

* it holds the :class:`~audio_suite_shared.plugin_system.loader.Discovery` for
  this process, so the plugin directory is scanned once;
* it answers the hosts' questions (which tag processors are active, which
  analysis contributions to run, which tools joined the tool registry);
* it resolves an ``module:callable`` entry point **lazily**, so importing
  ``audio_suite_shared.cli_app`` never executes third-party Python — only the
  moment a host actually runs a contribution does the plugin's module load.

Resolution failures become :class:`~audio_suite_shared.plugin_system.models.PluginError`
naming the plugin and the entry point, which every host reports against the
plugin rather than aborting its run.

Changed in 2.1.0: new module — the plugin registry and lazy entry-point
resolution (Sprint 7, Item 7.1).
"""

from __future__ import annotations

import importlib
import logging
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

from audio_suite_shared.plugin_system.loader import Discovery, discover
from audio_suite_shared.plugin_system.models import (
    ContributionSpec,
    PluginError,
    PluginManifest,
    PluginProblem,
    PluginState,
)

logger = logging.getLogger(f"audio_suite.{__name__}")

CallableAny = Callable[..., Any]

#: Plugin roots already appended to ``sys.path`` this process.
_IMPORTED_ROOTS: set[str] = set()


class PluginRegistry:
    """The discovered plugins of this process, and their lazy entry points.

    Args:
        discovery: The result of one discovery pass.
        plugin_root: The directory the pass scanned; it is added to
            ``sys.path`` when an entry point is resolved.
    """

    def __init__(self, discovery: Discovery, plugin_root: Path) -> None:
        self._discovery = discovery
        self._plugin_root = plugin_root
        self._resolved: dict[str, CallableAny] = {}

    # ── Discovery views ────────────────────────────────────────────────────

    @property
    def states(self) -> tuple[PluginState, ...]:
        """Every discovered plugin, enabled, disabled or rejected."""
        return self._discovery.states

    @property
    def problems(self) -> tuple[PluginProblem, ...]:
        """The refused manifests, with their reasons."""
        return self._discovery.problems

    @property
    def manifests(self) -> tuple[PluginManifest, ...]:
        """The parsed manifests of every plugin, enabled or not."""
        return self._discovery.manifests

    @property
    def enabled(self) -> tuple[PluginManifest, ...]:
        """The parsed manifests of the enabled plugins."""
        return self._discovery.enabled

    @property
    def plugin_root(self) -> Path:
        """The directory discovery scanned."""
        return self._plugin_root

    def manifest_for(self, plugin_id: str) -> PluginManifest | None:
        """Return the parsed manifest for *plugin_id*, or None.

        Args:
            plugin_id: The manifest-declared plugin id.

        Returns:
            The manifest, including for a disabled plugin.
        """
        for manifest in self.manifests:
            if manifest.plugin_id == plugin_id:
                return manifest
        return None

    # ── Contribution views ─────────────────────────────────────────────────

    def tool_manifests(self) -> tuple[PluginManifest, ...]:
        """Return enabled plugins that declare a tool, in discovery order."""
        return tuple(manifest for manifest in self.enabled if manifest.tool is not None)

    def tag_processors(self) -> tuple[ContributionSpec, ...]:
        """Return every active tag processor, ordered by plugin then id."""
        return _sorted_specs(
            spec for manifest in self.enabled for spec in manifest.tag_processors
        )

    def analysis_contributions(self) -> tuple[ContributionSpec, ...]:
        """Return every active analysis contribution, ordered by plugin then id."""
        return _sorted_specs(
            spec for manifest in self.enabled for spec in manifest.analysis
        )

    # ── Resolution ─────────────────────────────────────────────────────────

    def resolve(self, entry_point: str) -> CallableAny:
        """Import and return the callable an entry point names.

        Args:
            entry_point: ``"module:callable"`` as validated by the loader.

        Returns:
            The callable, resolved once and cached for the process.

        Raises:
            PluginError: The module cannot be imported, the attribute is
                missing, or it is not callable.
        """
        cached = self._resolved.get(entry_point)
        if cached is not None:
            return cached
        module_name, _, attribute = entry_point.partition(":")
        _ensure_import_path(self._plugin_root)
        try:
            module: ModuleType = importlib.import_module(module_name)
        except Exception as exc:
            raise PluginError(
                f"cannot import {module_name!r} for entry point {entry_point!r}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        target = getattr(module, attribute, None)
        if target is None:
            raise PluginError(
                f"{module_name!r} has no attribute {attribute!r} "
                f"for entry point {entry_point!r}"
            )
        if not callable(target):
            raise PluginError(
                f"entry point {entry_point!r} resolves to "
                f"{type(target).__name__}, which is not callable"
            )
        resolved: CallableAny = target
        self._resolved[entry_point] = resolved
        return resolved

    def resolve_spec(self, spec: ContributionSpec) -> CallableAny:
        """Resolve a contribution's entry point, naming its plugin on failure.

        Args:
            spec: The contribution to resolve.

        Returns:
            The contribution callable.

        Raises:
            PluginError: The entry point does not resolve.
        """
        try:
            return self.resolve(spec.entry_point)
        except PluginError as exc:
            raise PluginError(
                f"plugin {spec.plugin_id!r} contribution {spec.kind}:{spec.id}: {exc}"
            ) from exc


def _sorted_specs(specs: Any) -> tuple[ContributionSpec, ...]:
    """Return contribution specs sorted by ``(plugin_id, id)``.

    Args:
        specs: An iterable of specs.

    Returns:
        The sorted tuple.
    """
    return tuple(sorted(specs, key=lambda spec: (spec.plugin_id, spec.id)))


def _ensure_import_path(plugin_root: Path) -> None:
    """Append *plugin_root* to ``sys.path`` once per process.

    Appending rather than inserting keeps the suite's own packages ahead of a
    plugin that reuses one of their names; the loader already refuses such a
    directory, so the append is the belt to that braces.

    Args:
        plugin_root: The directory holding the plugin packages.
    """
    entry = str(plugin_root)
    if entry in _IMPORTED_ROOTS:
        return
    if entry not in sys.path:
        sys.path.append(entry)
    _IMPORTED_ROOTS.add(entry)


def _reserved_ids() -> frozenset[str]:
    """Return the manifest ids first-party tools have already claimed.

    Imported lazily: ``tool_plugin`` builds the plugin registry, so a
    module-level import here would be a cycle.

    Returns:
        The ids of every first-party manifest.
    """
    from audio_suite_shared import tool_plugin

    return frozenset(manifest.id for manifest in tool_plugin.FIRST_PARTY_MANIFESTS)


def _reserved_commands() -> frozenset[str]:
    """Return the CLI subcommand names a plugin may not take.

    A plugin command is a real top-level command, so a name collision would
    either shadow a first-party tool or make ``audiosuite --help`` ambiguous.
    The suite's own non-manifest commands (``doctor``, the ``cue`` group and
    the ``plugins`` group itself) are reserved alongside the tool commands.

    Returns:
        The reserved command names.
    """
    from audio_suite_shared import tool_plugin

    names = {
        manifest.cli_command
        for manifest in tool_plugin.FIRST_PARTY_MANIFESTS
        if manifest.cli_command
    }
    names |= {"doctor", "cue", "plugins"}
    return frozenset(names)


# ---------------------------------------------------------------------------
# Process singleton
# ---------------------------------------------------------------------------

_REGISTRY: PluginRegistry | None = None


def get_plugins(
    *,
    root: Path | None = None,
    enabled: Mapping[str, bool] | None = None,
) -> PluginRegistry:
    """Return the process-wide plugin registry, discovering on first use.

    Args:
        root: Plugin directory override; ignored once the registry exists.
        enabled: Enablement override for this discovery; ignored once the
            registry exists.

    Returns:
        The registry for this process.
    """
    global _REGISTRY
    if _REGISTRY is None:
        from audio_suite_shared.plugin_system.loader import default_plugin_root

        plugin_root = (root if root is not None else default_plugin_root()).resolve()
        _REGISTRY = PluginRegistry(
            discover(
                plugin_root,
                enabled=enabled,
                reserved_ids=_reserved_ids(),
                reserved_commands=_reserved_commands(),
            ),
            plugin_root,
        )
    return _REGISTRY


def reset_plugins_for_tests() -> None:
    """Drop the cached registry and the import path entries it added.

    The registry is a per-process singleton, so a test that needs a different
    plugin directory (or a different enablement map) resets it here.  This is
    the only supported way to re-discover within one process.

    The roots *are* removed from ``sys.path``: leaving them behind made a
    later discovery import a module from the previous test's plugin directory,
    because that earlier entry came first and Python caches by module name.
    """
    global _REGISTRY
    _REGISTRY = None
    for entry in tuple(_IMPORTED_ROOTS):
        while entry in sys.path:
            sys.path.remove(entry)
    _IMPORTED_ROOTS.clear()
