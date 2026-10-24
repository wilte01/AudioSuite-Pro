"""loader.py — discovery and validation of ``plugins/*/MANIFEST.toml``.

The loader is deliberately boring and total: it walks the plugin directory one
level deep, parses each manifest with :mod:`tomllib`, validates every field it
read, and returns a :class:`Discovery` that holds a state for *every* candidate
directory.  It imports no plugin code, so discovery can run at import time of
``audio_suite_shared.cli_app`` without executing third-party Python.

Two consequences matter to the rest of the suite:

* a malformed plugin is a
  :class:`~audio_suite_shared.plugin_system.models.PluginProblem` and never an
  exception, so one bad manifest cannot stop the other plugins, the CLI or the
  Master Driver from starting;
* enablement is resolved here but changes nothing about parsing — a disabled
  plugin is still fully described, which is what ``audiosuite plugins list``
  needs to tell a user what they have installed.

The trust rule is one sentence: **parsing a manifest is safe; importing a
plugin's modules is not, and only happens for enabled plugins when a host
resolves one of their entry points.**

Changed in 2.1.0: new module — MANIFEST.toml discovery, validation and
enablement resolution (Sprint 7, Item 7.1).
"""

from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

import tomllib

from audio_suite_shared.plugin_system.models import (
    PLUGIN_API_VERSION,
    PLUGIN_CATEGORIES,
    ContributionSpec,
    PluginManifest,
    PluginProblem,
    PluginState,
    ToolContribution,
)

logger = logging.getLogger(f"audio_suite.{__name__}")

#: File every plugin directory must hold.
MANIFEST_FILENAME = "MANIFEST.toml"

#: Environment override for the plugin root.  It mirrors ``AUDIOSUITE_LOG_DIR``:
#: the tests and a parallel checkout point discovery at a tree of their own
#: instead of the installed suite's ``plugins/`` directory.
PLUGIN_DIR_ENV = "AUDIOSUITE_PLUGIN_DIR"

#: Configuration key holding the per-plugin enablement map.
ENABLED_CONFIG_KEY = "plugins_enabled"

#: Plugins this suite ships and enables itself.  The list lives in first-party
#: code on purpose: a manifest cannot opt itself in, so a third-party plugin is
#: always an explicit decision by the user.
BUNDLED_DEFAULT_ENABLED = frozenset({"example_plugin"})

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PLUGIN_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_CLI_COMMAND = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_ENTRY_POINT = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*):([A-Za-z_][A-Za-z0-9_]*)$"
)
_VERSION = re.compile(r"^\d+(?:\.\d+){0,3}(?:[.\-+][A-Za-z0-9.]+)?$")

_ALLOWED_TOP_LEVEL = frozenset({"plugin", "tool", "tag_processor", "analysis"})
_ALLOWED_PLUGIN_KEYS = frozenset(
    {"id", "name", "version", "author", "description", "api_version"}
)
_ALLOWED_TOOL_KEYS = frozenset(
    {
        "id",
        "name",
        "category",
        "description",
        "entry_point",
        "cli_command",
        "launcher",
        "standalone",
        "order",
    }
)
_ALLOWED_UI_KEYS = frozenset({"entry"})
_ALLOWED_CONTRIBUTION_KEYS = frozenset({"id", "name", "entry_point"})


class PluginManifestError(ValueError):
    """A plugin manifest is unreadable or violates the manifest contract."""


@dataclass(frozen=True)
class Discovery:
    """The result of one discovery pass.

    Attributes
    ----------
    states : tuple[PluginState, ...]
        One state per candidate plugin directory, sorted by plugin id (or
        directory name for a refused manifest).
    problems : tuple[PluginProblem, ...]
        The refused manifests, sorted like ``states``.
    """

    states: tuple[PluginState, ...]
    problems: tuple[PluginProblem, ...]

    @property
    def manifests(self) -> tuple[PluginManifest, ...]:
        """Return the manifests of every plugin that parsed, enabled or not."""
        return tuple(
            state.manifest for state in self.states if state.manifest is not None
        )

    @property
    def enabled(self) -> tuple[PluginManifest, ...]:
        """Return the manifests of the enabled plugins that parsed."""
        return tuple(
            state.manifest
            for state in self.states
            if state.manifest is not None and state.enabled
        )

    def state_for(self, plugin_id: str) -> PluginState | None:
        """Return the state recorded for *plugin_id*, or None.

        Args:
            plugin_id: The manifest-declared plugin id.

        Returns:
            The matching state, or None when no directory declared that id.
        """
        for state in self.states:
            if state.plugin_id == plugin_id:
                return state
        return None


def default_plugin_root() -> Path:
    """Return the plugin directory discovery should use.

    ``AUDIOSUITE_PLUGIN_DIR`` overrides the location entirely; without it the
    answer is ``<suite root>/plugins``, derived from this file's location and
    never from the current working directory.

    Returns:
        The plugin directory path (it may not exist).
    """
    override = os.environ.get(PLUGIN_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _suite_root() / "plugins"


def _suite_root() -> Path:
    """Return the suite root that owns this installation.

    File location: ``<root>/audio_suite_shared/plugin_system/loader.py``.

    Returns:
        The resolved suite root directory.
    """
    return Path(__file__).resolve().parents[2]


def suite_package_names() -> frozenset[str]:
    """Return the importable top-level package names the suite ships.

    A plugin directory with one of these names would import into a first-party
    module namespace instead of its own, so discovery refuses it.  The set is
    derived from the tree rather than hard-coded, so a new tool package is
    protected automatically.

    Returns:
        Package names, empty when the suite root cannot be read.
    """
    root = _suite_root()
    try:
        return frozenset(
            entry.name
            for entry in root.iterdir()
            if entry.is_dir() and (entry / "__init__.py").is_file()
        )
    except OSError:  # pragma: no cover - unreadable root
        return frozenset()


def load_enabled_map() -> dict[str, bool]:
    """Return the user's per-plugin enablement map from the shared config.

    The config is read through :mod:`audio_suite_shared.suite_config`, so the
    plugin switch lives where every other suite preference lives.  An
    unreadable config yields an empty map rather than an error: discovery must
    never be the reason a tool cannot start.

    Returns:
        ``{plugin_id: enabled}`` for every boolean entry recorded.
    """
    from audio_suite_shared import suite_config

    try:
        stored = suite_config.load_value(ENABLED_CONFIG_KEY, {})
    except Exception as exc:  # pragma: no cover - defensive, config is atomic
        logger.warning("Could not read %s: %s", ENABLED_CONFIG_KEY, exc)
        return {}
    if not isinstance(stored, dict):
        return {}
    enabled: dict[str, bool] = {}
    for key, value in stored.items():
        if isinstance(key, str) and isinstance(value, bool):
            enabled[key] = value
    return enabled


def save_enabled_map(enabled: Mapping[str, bool]) -> None:
    """Persist the per-plugin enablement map to the shared config.

    Args:
        enabled: ``{plugin_id: enabled}`` to store.  A plugin absent from the
            map falls back to :data:`BUNDLED_DEFAULT_ENABLED`.
    """
    from audio_suite_shared import suite_config

    suite_config.save_value(ENABLED_CONFIG_KEY, dict(enabled))


def is_enabled(plugin_id: str, enabled: Mapping[str, bool]) -> bool:
    """Return whether *plugin_id* is enabled by *enabled* or by the suite.

    Args:
        plugin_id: The manifest-declared plugin id.
        enabled: The user's stored map.

    Returns:
        The stored value when the user has one, else whether this suite ships
        the plugin enabled by default.
    """
    return enabled.get(plugin_id, plugin_id in BUNDLED_DEFAULT_ENABLED)


def discover(
    root: Path | None = None,
    *,
    enabled: Mapping[str, bool] | None = None,
    reserved_ids: frozenset[str] = frozenset(),
    reserved_commands: frozenset[str] = frozenset(),
) -> Discovery:
    """Discover and validate every plugin directory under *root*.

    Args:
        root: Plugin directory to scan; ``None`` uses :func:`default_plugin_root`.
        enabled: Per-plugin enablement overrides; ``None`` reads the shared
            config.
        reserved_ids: Manifest ids already taken by first-party tools.  A
            plugin declaring one is refused rather than silently shadowing it.
        reserved_commands: CLI subcommand names the suite already registers.  A
            plugin declaring one is refused, so ``audiosuite doctor`` cannot
            be replaced by a plugin.

    Returns:
        The discovery result.  A missing plugin directory yields an empty
        result; no failure in this function is raised to the caller.
    """
    directory_root = (root if root is not None else default_plugin_root()).resolve()
    enabled_map = load_enabled_map() if enabled is None else dict(enabled)
    reserved = set(reserved_ids) | suite_package_names()
    commands = set(reserved_commands)

    states: list[PluginState] = []
    problems: list[PluginProblem] = []
    seen_ids: dict[str, Path] = {}
    seen_tools: dict[str, Path] = {}
    seen_commands: dict[str, Path] = {}

    for candidate in _candidate_directories(directory_root):
        try:
            manifest = _parse_manifest(
                candidate,
                reserved_ids=reserved,
                reserved_commands=commands,
                seen_plugin_ids=seen_ids,
                seen_tool_ids=seen_tools,
                seen_commands=seen_commands,
            )
        except PluginManifestError as exc:
            problems.append(
                PluginProblem(
                    directory=candidate,
                    plugin_id=_declared_id(candidate),
                    reason=str(exc),
                )
            )
            logger.warning("Plugin rejected (%s): %s", candidate.name, exc)
            continue

        seen_ids[manifest.plugin_id] = candidate
        if manifest.tool is not None:
            seen_tools[manifest.tool.id] = candidate
            if manifest.tool.cli_command is not None:
                seen_commands[manifest.tool.cli_command] = candidate
        states.append(
            PluginState(
                plugin_id=manifest.plugin_id,
                name=manifest.name,
                version=manifest.version,
                directory=candidate,
                enabled=is_enabled(manifest.plugin_id, enabled_map),
                manifest=manifest,
            )
        )

    for problem in problems:
        states.append(
            PluginState(
                plugin_id=problem.plugin_id or problem.directory.name,
                name=problem.plugin_id or problem.directory.name,
                version="",
                directory=problem.directory,
                enabled=False,
                manifest=None,
                problem=problem.reason,
            )
        )

    states.sort(key=lambda state: (state.plugin_id, str(state.directory)))
    problems.sort(key=lambda problem: str(problem.directory))
    return Discovery(states=tuple(states), problems=tuple(problems))


def _candidate_directories(root: Path) -> list[Path]:
    """Return the plugin directories under *root*, sorted by name.

    A directory is a candidate only when it holds a ``MANIFEST.toml``; a stray
    folder (a README, a cache) is not an error.  Symlinked directories are
    followed once, which is how a developer keeps a plugin outside the tree.

    Args:
        root: Plugin directory to scan.

    Returns:
        Sorted candidate directory paths.
    """
    try:
        entries = sorted(root.iterdir(), key=lambda path: path.name)
    except OSError:
        return []
    return [
        entry
        for entry in entries
        if entry.is_dir() and (entry / MANIFEST_FILENAME).is_file()
    ]


def _declared_id(directory: Path) -> str:
    """Return whatever id a refused manifest declared, for the report.

    Args:
        directory: The plugin directory.

    Returns:
        The plugin id when it could be read as a string, else ``""``.
    """
    try:
        with (directory / MANIFEST_FILENAME).open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return ""
    plugin = raw.get("plugin")
    if isinstance(plugin, dict):
        declared = plugin.get("id")
        if isinstance(declared, str):
            return declared
    return ""


def _parse_manifest(
    directory: Path,
    *,
    reserved_ids: set[str],
    reserved_commands: set[str],
    seen_plugin_ids: Mapping[str, Path],
    seen_tool_ids: Mapping[str, Path],
    seen_commands: Mapping[str, Path],
) -> PluginManifest:
    """Parse and validate one ``MANIFEST.toml``.

    Args:
        directory: The plugin directory.
        reserved_ids: First-party ids and package names a plugin may not take.
        reserved_commands: CLI subcommand names the suite already registers.
        seen_plugin_ids: Plugin ids already claimed in this pass.
        seen_tool_ids: Tool ids already claimed in this pass.
        seen_commands: CLI command names already claimed in this pass.

    Returns:
        The validated manifest.

    Raises:
        PluginManifestError: The manifest is unreadable or violates the contract.
    """
    manifest_path = directory / MANIFEST_FILENAME
    try:
        with manifest_path.open("rb") as handle:
            raw = tomllib.load(handle)
    except OSError as exc:
        raise PluginManifestError(f"{MANIFEST_FILENAME} cannot be read: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise PluginManifestError(
            f"{MANIFEST_FILENAME} is not valid TOML: {exc}"
        ) from exc

    unknown = sorted(set(raw) - _ALLOWED_TOP_LEVEL)
    if unknown:
        raise PluginManifestError(
            f"{MANIFEST_FILENAME} declares unknown section(s) {unknown}; "
            f"allowed: {sorted(_ALLOWED_TOP_LEVEL)}"
        )

    plugin_table = _require_table(raw, "plugin", manifest_path)
    _reject_unknown(plugin_table, _ALLOWED_PLUGIN_KEYS, "[plugin]", manifest_path)

    plugin_id = _require_str(plugin_table, "id", "[plugin]", manifest_path)
    if not _PLUGIN_ID.match(plugin_id):
        raise PluginManifestError(
            f"[plugin].id {plugin_id!r} must match {_PLUGIN_ID.pattern}"
        )
    name = _require_str(plugin_table, "name", "[plugin]", manifest_path)
    version = _require_str(plugin_table, "version", "[plugin]", manifest_path)
    if not _VERSION.match(version):
        raise PluginManifestError(
            f"[plugin].version {version!r} is not a dotted version string"
        )
    author = _require_str(plugin_table, "author", "[plugin]", manifest_path)
    description = _require_str(plugin_table, "description", "[plugin]", manifest_path)
    api_version = _require_int(plugin_table, "api_version", "[plugin]", manifest_path)
    if api_version != PLUGIN_API_VERSION:
        raise PluginManifestError(
            f"manifest api_version {api_version} is not supported; "
            f"this suite understands api_version {PLUGIN_API_VERSION}"
        )

    package = directory.name
    if package in reserved_ids:
        raise PluginManifestError(
            f"directory name {package!r} is a first-party package name; "
            "rename the plugin directory"
        )
    if not _IDENTIFIER.match(package):
        raise PluginManifestError(
            f"directory name {package!r} is not a valid Python identifier, so the "
            "plugin's modules could not be imported"
        )
    if plugin_id in reserved_ids:
        raise PluginManifestError(
            f"plugin id {plugin_id!r} is already used by a first-party tool"
        )
    if plugin_id in seen_plugin_ids:
        raise PluginManifestError(
            f"plugin id {plugin_id!r} is already declared by "
            f"{seen_plugin_ids[plugin_id].name}"
        )
    if plugin_id == package:
        # Not a hard requirement, but the manifest example and the guide use
        # the directory name as the package, so the mismatch is worth naming.
        logger.debug("plugin %s uses package %s", plugin_id, package)

    tool = _parse_tool(
        raw.get("tool"),
        plugin_id=plugin_id,
        directory=directory,
        package=package,
        manifest_path=manifest_path,
        reserved_ids=reserved_ids,
        reserved_commands=reserved_commands,
        seen_tool_ids=seen_tool_ids,
        seen_commands=seen_commands,
    )
    tag_processors = _parse_contributions(
        raw.get("tag_processor"),
        kind="tag_processor",
        plugin_id=plugin_id,
        directory=directory,
        package=package,
        manifest_path=manifest_path,
    )
    analysis = _parse_contributions(
        raw.get("analysis"),
        kind="analysis",
        plugin_id=plugin_id,
        directory=directory,
        package=package,
        manifest_path=manifest_path,
    )

    return PluginManifest(
        directory=directory.resolve(),
        plugin_id=plugin_id,
        name=name,
        version=version,
        author=author,
        description=description,
        api_version=api_version,
        tool=tool,
        tag_processors=tag_processors,
        analysis=analysis,
    )


def _parse_tool(
    raw: object,
    *,
    plugin_id: str,
    directory: Path,
    package: str,
    manifest_path: Path,
    reserved_ids: set[str],
    reserved_commands: set[str],
    seen_tool_ids: Mapping[str, Path],
    seen_commands: Mapping[str, Path],
) -> ToolContribution | None:
    """Parse the optional ``[tool]`` table.

    Args:
        raw: The raw TOML value, or None when the table is absent.
        plugin_id: The owning plugin's id, used to derive a CLI command name.
        directory: The plugin directory (for launcher containment checks).
        package: The plugin's importable package name.
        manifest_path: The manifest path, used in messages.
        reserved_ids: First-party ids and package names.
        reserved_commands: CLI subcommand names the suite already registers.
        seen_tool_ids: Tool ids already claimed in this pass.
        seen_commands: CLI command names already claimed in this pass.

    Returns:
        The tool contribution, or None when the manifest declares no tool.

    Raises:
        PluginManifestError: The table is malformed or names a dead surface.
    """
    if raw is None:
        return None
    tool_table = _require_table({"tool": raw}, "tool", manifest_path)
    ui_entry: str | None = None
    unknown = sorted(set(tool_table) - _ALLOWED_TOOL_KEYS - {"ui"})
    if unknown:
        raise PluginManifestError(
            f"[tool] declares unknown key(s) {unknown}; "
            f"allowed: {sorted(_ALLOWED_TOOL_KEYS | {'ui'})}"
        )
    ui_table = tool_table.get("ui")
    if ui_table is not None:
        table = _require_table({"ui": ui_table}, "ui", manifest_path)
        _reject_unknown(table, _ALLOWED_UI_KEYS, "[tool.ui]", manifest_path)
        ui_entry = _optional_str(table, "entry", "[tool.ui]", manifest_path)
        if ui_entry is None:
            raise PluginManifestError("[tool.ui] is present but declares no entry")
        _validate_entry_point(ui_entry, package, "[tool.ui].entry")

    tool_id = _require_str(tool_table, "id", "[tool]", manifest_path)
    if not _PLUGIN_ID.match(tool_id):
        raise PluginManifestError(
            f"[tool].id {tool_id!r} must match {_PLUGIN_ID.pattern}"
        )
    if tool_id in reserved_ids:
        raise PluginManifestError(
            f"tool id {tool_id!r} is already used by a first-party tool"
        )
    if tool_id in seen_tool_ids:
        raise PluginManifestError(
            f"tool id {tool_id!r} is already declared by {seen_tool_ids[tool_id].name}"
        )
    name = _require_str(tool_table, "name", "[tool]", manifest_path)
    category = _require_str(tool_table, "category", "[tool]", manifest_path)
    if category not in PLUGIN_CATEGORIES:
        raise PluginManifestError(
            f"[tool].category {category!r} is not one of {sorted(PLUGIN_CATEGORIES)}"
        )
    description = (
        _optional_str(tool_table, "description", "[tool]", manifest_path) or ""
    )

    entry_point = _optional_str(tool_table, "entry_point", "[tool]", manifest_path)
    if entry_point is not None:
        _validate_entry_point(entry_point, package, "[tool].entry_point")
    cli_command = _optional_str(tool_table, "cli_command", "[tool]", manifest_path)
    if cli_command is not None:
        if not _CLI_COMMAND.match(cli_command):
            raise PluginManifestError(
                f"[tool].cli_command {cli_command!r} must match {_CLI_COMMAND.pattern}"
            )
        if cli_command in reserved_commands:
            raise PluginManifestError(
                f"[tool].cli_command {cli_command!r} is already registered by the suite"
            )
        if cli_command in seen_commands:
            raise PluginManifestError(
                f"[tool].cli_command {cli_command!r} is already declared by "
                f"{seen_commands[cli_command].name}"
            )
    elif entry_point is not None:
        fallback = f"plugin-{plugin_id}"
        if fallback in reserved_commands or fallback in seen_commands:
            raise PluginManifestError(
                f"derived CLI command {fallback!r} is already taken; declare "
                "[tool].cli_command"
            )
        cli_command = fallback
    launcher = _optional_str(tool_table, "launcher", "[tool]", manifest_path)
    if launcher is not None:
        launcher = _validate_launcher(launcher, directory)
    if entry_point is None and launcher is None:
        raise PluginManifestError(
            "[tool] declares neither entry_point nor launcher, so the tool has "
            "no surface a user could reach"
        )

    standalone = _optional_bool(tool_table, "standalone", "[tool]", manifest_path)
    order = _optional_int(tool_table, "order", "[tool]", manifest_path)
    return ToolContribution(
        id=tool_id,
        name=name,
        category=category,
        description=description,
        entry_point=entry_point,
        cli_command=cli_command if entry_point is not None else None,
        launcher=launcher,
        ui_entry=ui_entry,
        standalone=True if standalone is None else standalone,
        order=100 if order is None else order,
    )


def _parse_contributions(
    raw: object,
    *,
    kind: str,
    plugin_id: str,
    directory: Path,
    package: str,
    manifest_path: Path,
) -> tuple[ContributionSpec, ...]:
    """Parse a ``[[tag_processor]]`` or ``[[analysis]]`` array of tables.

    Args:
        raw: The raw TOML value, or None when the array is absent.
        kind: The contribution kind being parsed.
        plugin_id: The owning plugin id.
        directory: The plugin directory (recorded for diagnostics).
        package: The plugin's importable package name.
        manifest_path: The manifest path, used in messages.

    Returns:
        The validated contributions in manifest order.

    Raises:
        PluginManifestError: An entry is malformed or repeats an id.
    """
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise PluginManifestError(
            f"[[{kind}]] must be an array of tables in {manifest_path}"
        )
    seen: set[str] = set()
    specs: list[ContributionSpec] = []
    for index, entry in enumerate(raw):
        label = f"[[{kind}]][{index}]"
        table = _require_table({label: entry}, label, manifest_path)
        _reject_unknown(table, _ALLOWED_CONTRIBUTION_KEYS, label, manifest_path)
        contribution_id = _require_str(table, "id", label, manifest_path)
        if not _PLUGIN_ID.match(contribution_id):
            raise PluginManifestError(
                f"{label}.id {contribution_id!r} must match {_PLUGIN_ID.pattern}"
            )
        if contribution_id in seen:
            raise PluginManifestError(
                f"{label}.id {contribution_id!r} is declared twice by {directory.name}"
            )
        seen.add(contribution_id)
        name = _require_str(table, "name", label, manifest_path)
        entry_point = _require_str(table, "entry_point", label, manifest_path)
        _validate_entry_point(entry_point, package, f"{label}.entry_point")
        specs.append(
            ContributionSpec(
                plugin_id=plugin_id,
                kind=kind,
                id=contribution_id,
                name=name,
                entry_point=entry_point,
            )
        )
    return tuple(specs)


def _validate_entry_point(entry_point: str, package: str, label: str) -> None:
    """Validate an ``module:callable`` reference and its containment.

    Args:
        entry_point: The declared reference.
        package: The plugin's importable package name; the module must live
            inside it, so a manifest cannot point at ``os:system``.
        label: The manifest key being validated, for the message.

    Raises:
        PluginManifestError: The reference is malformed or escapes the plugin.
    """
    match = _ENTRY_POINT.match(entry_point)
    if match is None:
        raise PluginManifestError(f"{label} {entry_point!r} is not 'module:callable'")
    module = match.group(1)
    if module != package and not module.startswith(f"{package}."):
        raise PluginManifestError(
            f"{label} {entry_point!r} must name a module inside the plugin "
            f"package {package!r}"
        )
    for part in module.split("."):
        if part in sys.stdlib_module_names:
            raise PluginManifestError(
                f"{label} {entry_point!r} would import the standard-library "
                f"module {part!r} instead of the plugin"
            )


def _validate_launcher(launcher: str, directory: Path) -> str:
    """Validate a declared launcher and return its suite-relative form.

    Args:
        launcher: The declared path, relative to the plugin directory.
        directory: The plugin directory.

    Returns:
        The suite-root-relative POSIX path the Master Driver resolves.

    Raises:
        PluginManifestError: The path escapes the plugin, is not a ``.pyw``, or
            does not exist.
    """
    candidate = Path(launcher)
    if candidate.is_absolute():
        raise PluginManifestError(
            f"[tool].launcher {launcher!r} must be relative to the plugin directory"
        )
    resolved = (directory / candidate).resolve()
    plugin_root = directory.resolve()
    try:
        resolved.relative_to(plugin_root)
    except ValueError as exc:
        raise PluginManifestError(
            f"[tool].launcher {launcher!r} leaves the plugin directory"
        ) from exc
    if resolved.suffix.lower() != ".pyw":
        raise PluginManifestError(f"[tool].launcher {launcher!r} must be a .pyw file")
    if not resolved.is_file():
        raise PluginManifestError(f"[tool].launcher {launcher!r} does not exist")
    suite_relative = (
        resolved.relative_to(_suite_root()) if _is_under_suite(resolved) else resolved
    )
    return suite_relative.as_posix()


def _is_under_suite(path: Path) -> bool:
    """Return whether *path* lives under the suite root.

    Args:
        path: Resolved path to test.

    Returns:
        True when the path can be expressed relative to the suite root.
    """
    try:
        path.relative_to(_suite_root())
    except ValueError:
        return False
    return True


def _require_table(
    raw: Mapping[str, object], key: str, manifest_path: Path
) -> dict[str, object]:
    """Return ``raw[key]`` as a table.

    Args:
        raw: The table to look in.
        key: The table name.
        manifest_path: The manifest path, used in messages.

    Returns:
        The table.

    Raises:
        PluginManifestError: The key is missing or not a table.
    """
    value = raw.get(key)
    if not isinstance(value, dict):
        raise PluginManifestError(f"{manifest_path.name} is missing the [{key}] table")
    return {str(name): item for name, item in value.items()}


def _reject_unknown(
    table: Mapping[str, object],
    allowed: frozenset[str],
    label: str,
    manifest_path: Path,
) -> None:
    """Refuse keys a table does not define, so a typo is an error.

    Args:
        table: The parsed table.
        allowed: Keys the table defines.
        label: The table name for the message.
        manifest_path: The manifest path, used in messages.

    Raises:
        PluginManifestError: The table holds an unknown key.
    """
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise PluginManifestError(
            f"{label} in {manifest_path.name} declares unknown key(s) {unknown}"
        )


def _require_str(
    table: Mapping[str, object], key: str, label: str, manifest_path: Path
) -> str:
    """Return a required non-empty string field.

    Args:
        table: The table holding the field.
        key: The field name.
        label: The table name for the message.
        manifest_path: The manifest path, used in messages.

    Returns:
        The field value.

    Raises:
        PluginManifestError: The field is missing, not a string, or empty.
    """
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PluginManifestError(
            f"{label}.{key} is required and must be a non-empty string "
            f"({manifest_path.name})"
        )
    return value.strip()


def _optional_str(
    table: Mapping[str, object], key: str, label: str, manifest_path: Path
) -> str | None:
    """Return an optional string field, refusing a wrong type.

    Args:
        table: The table holding the field.
        key: The field name.
        label: The table name for the message.
        manifest_path: The manifest path, used in messages.

    Returns:
        The stripped value, or None when absent.

    Raises:
        PluginManifestError: The field is present but not a string.
    """
    if key not in table:
        return None
    value = table[key]
    if not isinstance(value, str) or not value.strip():
        raise PluginManifestError(
            f"{label}.{key} must be a non-empty string when present "
            f"({manifest_path.name})"
        )
    return value.strip()


def _require_int(
    table: Mapping[str, object], key: str, label: str, manifest_path: Path
) -> int:
    """Return a required integer field (a bool is not an integer here).

    Args:
        table: The table holding the field.
        key: The field name.
        label: The table name for the message.
        manifest_path: The manifest path, used in messages.

    Returns:
        The field value.

    Raises:
        PluginManifestError: The field is missing or not an integer.
    """
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise PluginManifestError(
            f"{label}.{key} is required and must be an integer ({manifest_path.name})"
        )
    return value


def _optional_int(
    table: Mapping[str, object], key: str, label: str, manifest_path: Path
) -> int | None:
    """Return an optional integer field.

    Args:
        table: The table holding the field.
        key: The field name.
        label: The table name for the message.
        manifest_path: The manifest path, used in messages.

    Returns:
        The value, or None when absent.

    Raises:
        PluginManifestError: The field is present but not an integer.
    """
    if key not in table:
        return None
    return _require_int(table, key, label, manifest_path)


def _optional_bool(
    table: Mapping[str, object], key: str, label: str, manifest_path: Path
) -> bool | None:
    """Return an optional boolean field.

    Args:
        table: The table holding the field.
        key: The field name.
        label: The table name for the message.
        manifest_path: The manifest path, used in messages.

    Returns:
        The value, or None when absent.

    Raises:
        PluginManifestError: The field is present but not a boolean.
    """
    if key not in table:
        return None
    value = table[key]
    if not isinstance(value, bool):
        raise PluginManifestError(
            f"{label}.{key} must be a boolean ({manifest_path.name})"
        )
    return value


def manifest_as_dict(manifest: PluginManifest) -> dict[str, object]:
    """Return a JSON-friendly view of *manifest* for ``doctor --json``.

    Args:
        manifest: The manifest to render.

    Returns:
        A flat mapping; the tool and contribution entries are plain dicts.
    """
    payload: dict[str, object] = {
        "plugin": manifest.plugin_id,
        "name": manifest.name,
        "version": manifest.version,
        "author": manifest.author,
        "description": manifest.description,
        "api_version": manifest.api_version,
        "directory": str(manifest.directory),
        "tool": None if manifest.tool is None else asdict(manifest.tool),
        "contributions": [
            {"kind": spec.kind, "id": spec.id, "name": spec.name}
            for spec in manifest.contributions()
        ],
    }
    return payload
