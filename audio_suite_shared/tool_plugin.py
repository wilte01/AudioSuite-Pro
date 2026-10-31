"""
tool_plugin.py — the suite's tool registry, first-party and plugin tools alike.

Defines ToolManifest (declarative tool metadata) and ToolRegistry
(discovery / iteration). Every first-party AudioSuite-Pro tool registers its
manifest in ``_DEFAULT_MANIFESTS``; third-party tools join the same registry
from ``<suite root>/plugins/<name>/MANIFEST.toml`` through
``audio_suite_shared.plugin_system``.

The two populations stay distinguishable on purpose. ``registry.all`` answers
"what can this install run" and is what the Master Driver and the CLI consume,
while ``registry.first_party`` is what the suite's own shipped artifacts (the
README tool index, the platform matrix, the committed JSON schema corpus, the
user guides) are locked against — a third-party plugin must never change what
those documents claim about the distribution.

Usage::

    from audio_suite_shared.tool_plugin import get_registry

    registry = get_registry()
    for m in registry.by_category("enrich"):
        print(m.name)

Changed in 1.3.0: registers the ``spectral_viewer`` manifest (Sprint 3, D42),
the first tool whose manifest is a read-only utility that writes images rather
than tags.
Changed in 1.4.1: the usage block is literal, so the generated API reference
renders it as code rather than a definition list (PLAN D98).
Changed in 2.0.0: registers the ``stem_separator`` manifest, the suite's first
optional-dependency (``ml`` extra) tool (PLAN_feature_expansion.md Item 6.1).
Changed in 2.0.0: registers ``ml_denoiser``, which shares that extra but needs
no torch: RNNoise is a 13 MB C library (Item 6.2).
Changed in 2.1.0: the registry gains the plugin population. Manifests from
``plugins/*/MANIFEST.toml`` are discovered while the registry is built (so the
freeze still means "no late registrations"), a plugin that cannot be registered
is recorded instead of raised, and ``first_party`` / ``plugins`` /
``driver_manifests`` let the shipped-artifact locks and the Master Driver ask
for exactly the population they mean (Sprint 7, Item 7.1).

Changed in 2.3.0: adds the duplicate_finder and restoration manifests (F-02, F-08a).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from audio_suite_shared.exceptions import AudioConfigurationError

logger = logging.getLogger(f"audio_suite.{__name__}")


@dataclass(frozen=True)
class ToolManifest:
    """Declarative metadata for a single AudioSuite-Pro tool.

    Fields
    ------
    id : str
        Unique machine-readable key (e.g. ``"bpm"``).  Used as the
        dict key in ``AppState.module_toggles`` and as the card-module
        name segment (``master_driver.ui.cards.{id}_card``).
    name : str
        Human-readable display name (e.g. ``"BPM Analyzer"``).
    category : str
        One of ``"enrich"``, ``"utility"``, or ``"refinery"``.
        Determines which tab the card appears in and which arg-builder
        path constructs its CLI arguments.
    pyw_filename : str
        Basename of the executable script (e.g. ``"BPM_Analyzer.pyw"``).
        Resolved relative to the suite root at runtime.
    description : str
        One-line description shown in tooltips or help output.
    standalone : bool
        If True the tool opens its own window and is launched via
        ``start_python_script`` (non-blocking).  If False the tool
        is a subprocess that produces log output and is run with
        ``run_python_script`` (blocking).
    default_on : bool
        Initial state of the toggle checkbox.  Most tools default
        to off so the user must opt in.
    cli_command : str | None
        CLI subcommand name (e.g. ``"bpm"``).  None means the tool
        has no CLI equivalent.
    order : int
        Display order within each category (lower = first).
    plugin : bool
        True for a manifest that came from a plugin directory.  The field is
        what keeps the shipped-artifact locks (README index, platform matrix,
        JSON schema corpus, user guides) describing the distribution rather
        than the user's install.
    origin : str
        The plugin directory a plugin manifest came from, or ``""`` for a
        first-party tool.  ``doctor`` and the driver's diagnostics quote it.
    entry_point : str | None
        ``"package.module:callable"`` a plugin's CLI command invokes.  None for
        a first-party tool, whose command is a real Click function.
    ui_entry : str | None
        ``"package.module:build"`` a plugin's Master Driver card builder.
        None means the driver renders the generic plugin card.
    """

    id: str
    name: str
    category: str
    pyw_filename: str
    description: str = ""
    standalone: bool = False
    default_on: bool = False
    cli_command: str | None = None
    order: int = 100
    plugin: bool = False
    origin: str = ""
    entry_point: str | None = None
    ui_entry: str | None = None

    @property
    def is_driver_tool(self) -> bool:
        """Return whether the Master Driver can launch this tool.

        Every first-party tool has a launcher; a plugin may ship only a CLI
        command, in which case the driver has no window to open and must not
        create a toggle whose argument list would be empty.
        """
        return bool(self.pyw_filename)


class ToolRegistry:
    """Registry of all known tool manifests.

    This is a singleton — use ``get_registry()`` instead of
    constructing one directly.
    """

    def __init__(self) -> None:
        self._manifests: dict[str, ToolManifest] = {}
        self._frozen = False
        self._plugin_problems: list[str] = []

    # ── Registration ───────────────────────────────────────────────────────

    def register(self, manifest: ToolManifest) -> None:
        """Add a tool manifest to the registry.

        Raises ``ValueError`` if a manifest with the same ``id`` has
        already been registered, or ``AttributeError`` if the registry
        has been frozen (after bootstrap).
        """
        if self._frozen:
            raise AudioConfigurationError(
                "Cannot register new tool manifests after the registry has been frozen"
            )
        if manifest.id in self._manifests:
            raise AudioConfigurationError(
                f"Tool manifest with id={manifest.id!r} is already registered"
            )
        self._manifests[manifest.id] = manifest

    def register_plugin(self, manifest: ToolManifest) -> bool:
        """Add a plugin's tool manifest, recording a refusal instead of raising.

        A plugin is third-party code with a third-party manifest; the suite has
        to survive one that is wrong.  The refusal is kept in
        :attr:`plugin_problems` so ``audiosuite doctor`` can name it, and the
        other plugins (and every first-party tool) still register.

        Args:
            manifest: The manifest built from a plugin's ``[tool]`` table.

        Returns:
            True when the manifest was registered, False when it was refused.
        """
        if not manifest.plugin:
            raise AudioConfigurationError(
                "register_plugin() only accepts plugin manifests; use register() "
                "for a first-party tool"
            )
        try:
            self.register(manifest)
        except AudioConfigurationError as exc:
            self._plugin_problems.append(f"{manifest.origin or manifest.id}: {exc}")
            logger.warning("Plugin tool refused: %s", exc)
            return False
        return True

    def record_plugin_problem(self, problem: str) -> None:
        """Record a plugin problem discovered before a manifest could be built.

        Args:
            problem: A one-line description naming the plugin and the reason.
        """
        self._plugin_problems.append(problem)

    @property
    def plugin_problems(self) -> list[str]:
        """Refusals recorded while registering plugin manifests."""
        return list(self._plugin_problems)

    @property
    def first_party(self) -> list[ToolManifest]:
        """Every first-party manifest, sorted by (category, order, name).

        This is the population the suite's shipped artifacts describe; a
        plugin must never change what the README index, the platform matrix or
        the committed JSON schema corpus claim.
        """
        return [manifest for manifest in self.all if not manifest.plugin]

    @property
    def plugins(self) -> list[ToolManifest]:
        """Every plugin manifest, sorted by (category, order, name)."""
        return [manifest for manifest in self.all if manifest.plugin]

    @property
    def driver_manifests(self) -> list[ToolManifest]:
        """Manifests the Master Driver can launch (all of them but CLI-only tools)."""
        return [manifest for manifest in self.all if manifest.is_driver_tool]

    def driver_by_category(self, category: str) -> list[ToolManifest]:
        """Launcher-bearing manifests in *category*, sorted by order.

        Args:
            category: One of ``"enrich"``, ``"utility"`` or ``"refinery"``.

        Returns:
            The driver-visible manifests of that category.
        """
        return [
            manifest
            for manifest in self.by_category(category)
            if manifest.is_driver_tool
        ]

    # ── Lookup ─────────────────────────────────────────────────────────────

    def get(self, tool_id: str) -> ToolManifest | None:
        """Return the manifest for *tool_id*, or None."""
        return self._manifests.get(tool_id)

    def __contains__(self, tool_id: str) -> bool:
        return tool_id in self._manifests

    def __len__(self) -> int:
        return len(self._manifests)

    # ── Iteration ──────────────────────────────────────────────────────────

    @property
    def all(self) -> list[ToolManifest]:
        """All registered manifests, first-party tools then plugins.

        Plugins sort after the first-party population so a third-party tool
        never displaces a shipped tool's documented position (the Utilities
        tab's order, the CLI help sections and the README index all derive from
        this order).  Within each population the sort is (category, order,
        name).
        """
        return sorted(
            self._manifests.values(),
            key=lambda m: (m.plugin, m.category, m.order, m.name),
        )

    def by_category(self, category: str) -> list[ToolManifest]:
        """Manifests in *category*, first-party tools then plugins, by order."""
        return sorted(
            (m for m in self._manifests.values() if m.category == category),
            key=lambda m: (m.plugin, m.order, m.name),
        )

    def by_cli(self) -> list[ToolManifest]:
        """Manifests that have a ``cli_command``, sorted by command name."""
        return sorted(
            (m for m in self._manifests.values() if m.cli_command),
            key=lambda m: m.cli_command or "",
        )

    # ── Singleton support ──────────────────────────────────────────────────

    def _freeze(self) -> None:
        """Prevent further registrations (called after bootstrap)."""
        self._frozen = True


# ---------------------------------------------------------------------------
# Singleton holder
# ---------------------------------------------------------------------------

_REGISTRY: ToolRegistry | None = None


# ── First-party manifest table ────────────────────────────────────────────────
#
# Declarative source of truth for every first-party tool.  Each ``id`` is the
# key every other registration point must agree with: the card module filename
# (``master_driver.ui.cards.{id}_card``), the CLI command, the arg-builder
# entry, the batch-orchestrator dependency graph, the AppState toggle key and
# the user-guide registry.  Listing order is driven by the sorted
# ``(category, order, name)`` key at :meth:`ToolRegistry.get_manifests`.

_DEFAULT_MANIFESTS: tuple[ToolManifest, ...] = (
    # ── Enrich tools (tag / metadata) ────────────────────────────────────
    ToolManifest(
        id="scrubber",
        name="Metadata Scrubber",
        category="enrich",
        pyw_filename="Metadata_Scrubber.pyw",
        description="Scrub metadata from MP3 files",
        cli_command="scrub",
        order=10,
    ),
    ToolManifest(
        id="fingerprinter",
        name="Audio Fingerprinter",
        category="enrich",
        pyw_filename="Audio_Fingerprinter.pyw",
        description="Fingerprint audio and identify tracks via AcoustID",
        cli_command="fingerprint",
        standalone=True,
        order=15,
    ),
    ToolManifest(
        id="replaygain",
        name="ReplayGain Analyzer",
        category="enrich",
        pyw_filename="ReplayGain_Analyzer.pyw",
        description="Measure and write ReplayGain tags",
        cli_command="replaygain",
        order=20,
    ),
    ToolManifest(
        id="album_genre",
        name="Album Genre Tagger",
        category="enrich",
        pyw_filename="AlbumGenre_Tagger.pyw",
        description="Tag genre from album-level metadata",
        cli_command="album-genre",
        standalone=False,
        order=30,
    ),
    ToolManifest(
        id="genre_sync",
        name="Genre Sync",
        category="enrich",
        pyw_filename="Genre_Sync.pyw",
        description="Sync genre tags from custom field hierarchy",
        cli_command="genre-sync",
        order=40,
    ),
    ToolManifest(
        id="bpm",
        name="BPM Analyzer",
        category="enrich",
        pyw_filename="BPM_Analyzer.pyw",
        description="Detect and tag BPM for audio files",
        cli_command="bpm",
        order=50,
    ),
    ToolManifest(
        id="tempo",
        name="Tempo Analyzer",
        category="enrich",
        pyw_filename="Tempo_Analyzer.pyw",
        description="Derive tempo markings from existing BPM tags",
        cli_command="tempo",
        order=60,
    ),
    ToolManifest(
        id="key",
        name="Key Detector",
        category="enrich",
        pyw_filename="Key_Detector.pyw",
        description="Detect and tag musical key",
        cli_command="key",
        order=70,
    ),
    ToolManifest(
        id="mood_analyzer",
        name="Mood Analyzer",
        category="enrich",
        pyw_filename="Mood_Analyzer.pyw",
        description="Signal-based mood tagging (valence-arousal)",
        cli_command="mood-analyzer",
        order=85,
    ),
    ToolManifest(
        id="art",
        name="Album Art Sync",
        category="enrich",
        pyw_filename="Album_Art_Synch.pyw",
        description="Embed and synchronise album art",
        cli_command="album-art",
        standalone=False,
        order=90,
    ),
    # ── Utility tools ────────────────────────────────────────────────────
    ToolManifest(
        id="converter",
        name="Music Format Converter",
        category="utility",
        pyw_filename="Music_Format_Converter.pyw",
        description="Convert audio files between formats",
        cli_command="convert",
        order=10,
    ),
    ToolManifest(
        id="asx_extractor",
        name="ASX Playlist Extractor",
        category="utility",
        pyw_filename="ASX_Playlist_Extractor.pyw",
        description="Extract playlists from ASX files",
        cli_command="asx-extract",
        standalone=False,
        order=20,
    ),
    ToolManifest(
        id="album_art_normalizer",
        name="Album Art Normalizer",
        category="utility",
        pyw_filename="Album_Art_Normalizer.pyw",
        description="Resize and normalize embedded album artwork",
        standalone=False,
        cli_command="artnormalize",
        order=25,
    ),
    ToolManifest(
        id="cd_ripper",
        name="CD Ripper",
        category="utility",
        pyw_filename="CD_Ripper.pyw",
        description="Rip audio CDs",
        cli_command="cd-rip",
        standalone=True,
        order=30,
    ),
    ToolManifest(
        id="mood_analysis_batch",
        name="Mood Analysis Batch Tagger",
        category="utility",
        pyw_filename="Mood_Analysis_Batch_Tagger.pyw",
        description="Recursive signal-based batch mood analysis and tagging",
        cli_command="mood-analysis-batch",
        standalone=True,
        order=41,
    ),
    ToolManifest(
        id="library_stats",
        name="Library Statistics Dashboard",
        category="utility",
        pyw_filename="Library_Stats.pyw",
        description="Read-only tag statistics dashboard",
        cli_command="stats",
        standalone=True,
        order=50,
    ),
    ToolManifest(
        id="spectral_viewer",
        name="Spectral Viewer",
        category="utility",
        pyw_filename="Spectral_Viewer.pyw",
        description="Render and export FFT spectrograms",
        cli_command="spectrogram",
        standalone=True,
        order=52,
    ),
    ToolManifest(
        id="file_reorganizer",
        name="Tag-Based File Reorganizer",
        category="utility",
        pyw_filename="File_Reorganizer.pyw",
        description="Move/copy files into a tag-based folder hierarchy",
        cli_command="reorganize",
        standalone=True,
        order=55,
    ),
    ToolManifest(
        id="tag_field_updater",
        name="Tag Field Updater",
        category="utility",
        pyw_filename="Tag_Field_Updater.pyw",
        description="Scan and update tag fields",
        cli_command="tag-update",
        standalone=True,
        order=45,
    ),
    ToolManifest(
        id="noise_reduction",
        name="Noise Reduction",
        category="utility",
        pyw_filename="Noise_Reduction.pyw",
        description="Remove hum and broadband noise from audio files",
        cli_command="reduce",
        standalone=True,
        order=42,
    ),
    ToolManifest(
        id="audio_enhancer",
        name="Audio Enhancer",
        category="utility",
        pyw_filename="Audio_Enhancer.pyw",
        description="Improve dynamic range and clarity of audio files",
        cli_command="enhance",
        standalone=True,
        order=43,
    ),
    ToolManifest(
        id="audio_normalizer",
        name="Audio Normalizer",
        category="utility",
        pyw_filename="Audio_Normalizer.pyw",
        description="Normalise audio loudness to a target LUFS level",
        cli_command="normalise",
        standalone=True,
        order=44,
    ),
    ToolManifest(
        id="pop_click_remover",
        name="Pop & Click Remover",
        category="utility",
        pyw_filename="Pop_Click_Remover.pyw",
        description="Remove clicks and pops from audio files",
        cli_command="declick",
        standalone=True,
        order=45,
    ),
    ToolManifest(
        id="silence_trimmer",
        name="Silence Trimmer",
        category="utility",
        pyw_filename="Silence_Trimmer.pyw",
        description="Trim silence and optionally apply fades",
        cli_command="silence-trim",
        standalone=True,
        order=46,
    ),
    ToolManifest(
        id="stem_separator",
        name="Stem Separator",
        category="utility",
        pyw_filename="Stem_Separator.pyw",
        description="Separate tracks into vocals, drums, bass and other stems",
        cli_command="stems",
        standalone=True,
        order=48,
    ),
    ToolManifest(
        id="ml_denoiser",
        name="ML Denoiser",
        category="utility",
        pyw_filename="ML_Denoiser.pyw",
        description="Neural noise reduction with RNNoise (speech-trained)",
        cli_command="denoise",
        standalone=True,
        order=53,
    ),
    ToolManifest(
        id="duplicate_finder",
        name="Duplicate Finder",
        category="utility",
        pyw_filename="Duplicate_Finder.pyw",
        description="Find duplicate recordings by fingerprint and quarantine extras",
        cli_command="duplicates",
        standalone=True,
        order=54,
    ),
    ToolManifest(
        id="restoration",
        name="Restoration (Declip)",
        category="utility",
        pyw_filename="Restoration.pyw",
        description="Reconstruct flat-topped peaks lost to clipping",
        cli_command="declip",
        standalone=True,
        order=56,
    ),
    ToolManifest(
        id="tag_editor",
        name="Tag Editor",
        category="utility",
        pyw_filename="Tag_Editor.pyw",
        description="Edit common tags in an interactive grid",
        cli_command="tag-edit",
        standalone=True,
        order=47,
    ),
    ToolManifest(
        id="lyrics_manager",
        name="Lyrics Manager",
        category="enrich",
        pyw_filename="Lyrics_Manager.pyw",
        description="Fetch and embed synced & plain lyrics from online sources",
        cli_command="lyrics",
        order=95,
    ),
    ToolManifest(
        id="undo_tag_edits",
        name="Undo Tag Edits",
        category="utility",
        pyw_filename="Undo_Tag_Edits.pyw",
        description="Restore file tags to the way they were before a batch run",
        standalone=True,
        order=60,
    ),
    # ── Refinery (single pipeline) ───────────────────────────────────────
    ToolManifest(
        id="audio_refinery",
        name="Audio Refinery",
        category="refinery",
        pyw_filename="Audio_Refinery.pyw",
        description="DSP pipeline: declick, trim, enhance, normalise",
        # Plan G2: audio_refinery.cli registers a `refine` subcommand, but the
        # manifest declared cli_command=None — so the discoverability contract
        # could not check this tool, and the CLI help had an orphan command no
        # manifest pointed at. Declared here so the command and the tool agree.
        cli_command="refine",
        standalone=True,
        order=10,
    ),
)

#: The shipped tool table, under a name the plugin loader can consult without
#: reaching into a private constant. The ids are the reserved ids a plugin may
#: not reuse.
FIRST_PARTY_MANIFESTS: tuple[ToolManifest, ...] = _DEFAULT_MANIFESTS


def _build_default_registry() -> ToolRegistry:
    """Create and populate the registry with first-party and plugin tools.

    Assembles the first-party population from the declarative
    ``_DEFAULT_MANIFESTS`` table, then lets ``plugin_system`` add the enabled
    plugins' tool contributions.  Discovery happens here rather than after the
    freeze on purpose: a frozen registry is what makes the tool listing stable
    for the life of a process, and a plugin is only ever registered once.

    A plugin failure never propagates: discovery records a rejected manifest,
    and ``register_plugin`` records a refused one, so a broken third-party
    plugin cannot stop the CLI or the Master Driver from starting.

    The table's ids, field values and declaration order are the contract the
    expected-set test (``test_tool_plugin.py``) and the Master Driver's tool
    listing depend on — edit the table, never this function, to add a tool.
    """
    r = ToolRegistry()
    for manifest in _DEFAULT_MANIFESTS:
        r.register(manifest)
    _register_plugin_tools(r)
    r._freeze()
    return r


def _register_plugin_tools(registry: ToolRegistry) -> None:
    """Register the enabled plugins' tool contributions on *registry*.

    Args:
        registry: The registry being built, before it is frozen.
    """
    from audio_suite_shared.plugin_system import get_plugins

    try:
        plugins = get_plugins()
    except Exception as exc:  # pragma: no cover - discovery is total by design
        registry.record_plugin_problem(
            f"plugin discovery failed: {type(exc).__name__}: {exc}"
        )
        logger.warning("Plugin discovery failed: %s", exc)
        return
    for problem in plugins.problems:
        registry.record_plugin_problem(f"{problem.directory.name}: {problem.reason}")
    for plugin_manifest in plugins.tool_manifests():
        contribution = plugin_manifest.tool
        if contribution is None:  # pragma: no cover - tool_manifests() filters
            continue
        registry.register_plugin(
            ToolManifest(
                id=contribution.id,
                name=contribution.name,
                category=contribution.category,
                # A plugin's launcher is resolved against the suite root, the
                # same way a first-party launcher is; the loader has already
                # checked that the file exists inside the plugin directory.
                pyw_filename=contribution.launcher or "",
                description=contribution.description,
                standalone=contribution.standalone,
                cli_command=contribution.cli_command,
                order=contribution.order,
                plugin=True,
                origin=str(plugin_manifest.directory),
                entry_point=contribution.entry_point,
                ui_entry=contribution.ui_entry,
            )
        )


def get_registry() -> ToolRegistry:
    """Return the global ToolRegistry singleton (lazy-initialised)."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_default_registry()
    return _REGISTRY
