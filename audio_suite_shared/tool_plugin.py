"""
tool_plugin.py — Plugin System for Tool Registration.

Defines ToolManifest (declarative tool metadata) and ToolRegistry
(discovery / iteration). All first-party AudioSuite-Pro tools register
their manifests here. Third-party tools can add manifests via the
register() method or by dropping a plugin package with a
tool_manifest() function into a configured plugin directory.

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
"""

from __future__ import annotations

from dataclasses import dataclass

from audio_suite_shared.exceptions import AudioConfigurationError


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


class ToolRegistry:
    """Registry of all known tool manifests.

    This is a singleton — use ``get_registry()`` instead of
    constructing one directly.
    """

    def __init__(self) -> None:
        self._manifests: dict[str, ToolManifest] = {}
        self._frozen = False

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
        """All registered manifests sorted by (category, order)."""
        return sorted(
            self._manifests.values(),
            key=lambda m: (m.category, m.order, m.name),
        )

    def by_category(self, category: str) -> list[ToolManifest]:
        """Manifests in *category* sorted by order."""
        return sorted(
            (m for m in self._manifests.values() if m.category == category),
            key=lambda m: (m.order, m.name),
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


def _build_default_registry() -> ToolRegistry:
    """Create and populate the registry with all first-party tools.

    Assembles the registry from the declarative ``_DEFAULT_MANIFESTS`` table.
    The table's ids, field values and declaration order are the contract the
    expected-set test (``test_tool_plugin.py``) and the Master Driver's tool
    listing depend on — edit the table, never this function, to add a tool.
    """
    r = ToolRegistry()
    for manifest in _DEFAULT_MANIFESTS:
        r.register(manifest)
    r._freeze()
    return r


def get_registry() -> ToolRegistry:
    """Return the global ToolRegistry singleton (lazy-initialised)."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_default_registry()
    return _REGISTRY
