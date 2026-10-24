"""models.py — typed records for the AudioSuite-Pro plugin system.

A plugin is a directory under the suite root's ``plugins/`` folder holding a
``MANIFEST.toml``.  The manifest is parsed into :class:`PluginManifest`, which
carries at most one tool contribution and any number of tag-processor and
analysis contributions.  Everything in this module is inert data: no import,
no I/O beyond the ``Path`` values recorded for diagnostics.

The records are frozen so a host cannot mutate a loaded manifest, and
:class:`PluginProblem` is a value rather than an exception so discovery can
report every bad plugin instead of stopping at the first one.

Changed in 2.1.0: new module — the records shared by the plugin loader, the
registry and the first-party hosts (Sprint 7, Item 7.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: The manifest API generation this suite understands.  A manifest declaring
#: any other value is refused with both numbers named, so a plugin written for
#: a future layout cannot be half-parsed.
PLUGIN_API_VERSION = 1

#: Tool categories the Master Driver and the CLI understand.  A plugin tool
#: must live in one of them; the value decides its tab and help section.
PLUGIN_CATEGORIES = frozenset({"enrich", "utility", "refinery"})

#: Contribution kinds a manifest may declare, in reporting order.
CONTRIBUTION_KINDS: tuple[str, ...] = ("tag_processor", "analysis")


#: A resolution or invocation failure of plugin code.  Raised by the registry
#: when an enabled plugin's entry point cannot be imported or is not callable;
#: hosts catch it, record it against the plugin and keep going.
class PluginError(RuntimeError):
    """An enabled plugin's code could not be resolved or run."""


@dataclass(frozen=True)
class ToolContribution:
    """A tool a plugin adds to the suite's tool surfaces.

    Attributes
    ----------
    id : str
        Unique machine-readable key, used exactly like a first-party
        manifest id (driver toggle, card lookup, argument builder, CLI command).
    name : str
        Human-readable display name.
    category : str
        One of ``enrich``, ``utility`` or ``refinery``.
    description : str
        One-line description for cards and help text.
    entry_point : str | None
        ``"package.module:callable"`` for the CLI command, or None when the
        plugin ships no headless entry point.
    cli_command : str | None
        The subcommand name the entry point is registered under, or None to
        derive ``plugin-<plugin_id>``.  The loader refuses a name a first-party
        command already uses, so a plugin cannot shadow ``bpm`` or ``doctor``.
    launcher : str | None
        Suite-root-relative ``.pyw`` the Master Driver starts, or None when
        the plugin ships no window.
    ui_entry : str | None
        ``"package.module:build"`` for the plugin's own Master Driver card, or
        None to render the generic plugin card.
    standalone : bool
        True (the default) when the launcher opens its own window.  Plugin
        tools are always windows from the driver's point of view, so False is
        only meaningful for an enrich-style blocking run.
    order : int
        Display order within the category.
    """

    id: str
    name: str
    category: str
    description: str = ""
    entry_point: str | None = None
    cli_command: str | None = None
    launcher: str | None = None
    ui_entry: str | None = None
    standalone: bool = True
    order: int = 100


@dataclass(frozen=True)
class ContributionSpec:
    """A tag-processor or analysis contribution declared by a manifest.

    Attributes
    ----------
    plugin_id : str
        The owning plugin, so a host can report which plugin a contribution
        came from and disable it as a unit.
    kind : str
        One of :data:`CONTRIBUTION_KINDS`.
    id : str
        Contribution id, unique within its plugin and kind.
    name : str
        Human-readable name, used in host output.
    entry_point : str
        ``"package.module:callable"`` resolved when the contribution runs.
    """

    plugin_id: str
    kind: str
    id: str
    name: str
    entry_point: str


@dataclass(frozen=True)
class PluginManifest:
    """One parsed ``plugins/<dir>/MANIFEST.toml``.

    Attributes
    ----------
    directory : Path
        The plugin's own directory, resolved and verified to contain the
        manifest that produced this record.
    plugin_id : str
        Manifest-declared plugin id, unique across the suite.
    name : str
        Human-readable plugin name.
    version : str
        The plugin's own version string (``"1.0.0"``).
    author : str
        Plugin author, shown by ``audiosuite plugins list``.
    description : str
        One-line plugin description.
    api_version : int
        The manifest generation this plugin was written for.
    tool : ToolContribution | None
        The tool contribution, when the manifest declares one.
    tag_processors : tuple[ContributionSpec, ...]
        Tag processors, in manifest order.
    analysis : tuple[ContributionSpec, ...]
        Analysis contributions, in manifest order.
    """

    directory: Path
    plugin_id: str
    name: str
    version: str
    author: str
    description: str
    api_version: int
    tool: ToolContribution | None = None
    tag_processors: tuple[ContributionSpec, ...] = ()
    analysis: tuple[ContributionSpec, ...] = ()

    @property
    def package_name(self) -> str:
        """Return the importable package name the plugin directory provides."""
        return self.directory.name

    def contributions(self) -> tuple[ContributionSpec, ...]:
        """Return every non-tool contribution, in declaration order."""
        return self.tag_processors + self.analysis


@dataclass(frozen=True)
class PluginProblem:
    """A plugin directory that was found and refused, with the reason.

    Attributes
    ----------
    directory : Path
        The plugin directory that failed.
    plugin_id : str
        The declared id when it could be read, else ``""``.
    reason : str
        One sentence naming what is wrong, suitable for ``doctor`` output.
    """

    directory: Path
    plugin_id: str
    reason: str


@dataclass(frozen=True)
class PluginState:
    """The discovery state of one plugin directory, for ``plugins list``.

    Attributes
    ----------
    plugin_id : str
        The declared id, or the directory name when the manifest was refused
        before the id could be read.
    name : str
        The declared name, or the directory name for a refused manifest.
    version : str
        The declared version, or ``""``.
    directory : Path
        The plugin directory.
    enabled : bool
        Whether the user's configuration includes this plugin's code.  A
        refused plugin is never enabled.
    manifest : PluginManifest | None
        The parsed manifest, present for every plugin that parsed.
    problem : str | None
        The refusal reason for a rejected plugin, else None.
    """

    plugin_id: str
    name: str
    version: str
    directory: Path
    enabled: bool
    manifest: PluginManifest | None = None
    problem: str | None = None

    @property
    def status(self) -> str:
        """Return ``loaded``, ``disabled`` or ``rejected`` for reporting."""
        if self.problem is not None:
            return "rejected"
        return "loaded" if self.enabled else "disabled"
