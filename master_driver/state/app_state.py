# Changed in 2.4.0: duplicate dispositions and ASX stubs.
"""
app_state.py — Single container for all Master Driver tk variables.

Passing this object as a dependency instead of 'self' makes each UI card
and runner function explicit about what state it touches.

Changed in 1.0.1: removes the unused ``library_stats_completeness``/``_detail`` toggle
keys.

Changed in 1.2.0: adds the fingerprinter MusicBrainz / ISRC toggles.
Changed in 1.3.0: adds the Spectral Viewer option variables (PLAN D42).
Changed in 1.4.0: the five worker-count variables default to
``default_max_workers()`` instead of a literal "4" (PLAN D56).
Changed in 1.4.1: the five utility-toggle property aliases say which
``module_toggles`` entry they return (PLAN D98).
Changed in 2.0.0: adds the Stem Separator's destination, model, device, mix
and per-stem selection variables (Sprint 6, Item 6.1).
Changed in 2.0.0: adds the ML Denoiser's amount percentage (Item 6.2).  The
module toggle itself comes from the registry, so a new tool needs no toggle line
here (and ``test_app_state.py`` freezes the expected set).
Changed in 2.1.0: toggles are generated for ``registry.driver_manifests`` rather
than ``registry.all``, so a plugin tool that ships only a CLI entry point gets no
toggle (Sprint 7, Item 7.1).

Changed in 2.6.0: carries the Duplicate Finder's exact-matching choice (F-E9).
Changed in 2.6.0: carries the Artwork Extractor's sidecar options (F-E10
follow-up).  Its module toggle comes from the registry like every tool's.

Changed in 2.3.0: carries the duplicate_finder and restoration module toggles (F-02,
F-08a).

Changed in 2.3.1 (U-03, released in 2.6.0): the five DSP tools' option variables
(``declick_*``, ``trimmer_*``, ``nr_*``, ``enhancer_*``, ``normalizer_*``) go with
their cards; the toggles follow ``driver_manifests``, so they go too.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from audio_suite_shared.constants import default_max_workers
from audio_suite_shared.tool_plugin import get_registry
from music_format_converter.core.formats import (
    LOSSLESS_FORMATS as CONVERTER_LOSSLESS_FORMATS,
)
from music_format_converter.core.formats import (
    LOSSY_FORMATS as CONVERTER_LOSSY_FORMATS,
)


class AppState:
    """All tkinter variables for the Master Driver, grouped logically.

    Args:
        master: Optional widget/root to bind tk variables to.  ``None``
            uses tkinter's default root (normal in a single-root app).  Pass
            it when several Tk roots coexist (e.g. in UI tests) so the mode
            variables live in the same interpreter as the widgets that
            display them.
    """

    def __init__(self, master: tk.Misc | None = None) -> None:
        registry = get_registry()

        # ── Core controls ─────────────────────────────────────────────────────
        self.dir_path = tk.StringVar(master)
        self.global_mode = tk.StringVar(master, value="Dry Run")
        self.auto_start = tk.BooleanVar(master, value=False)
        self.auto_end = tk.BooleanVar(master, value=False)
        self.select_all_var = tk.BooleanVar(master, value=False)
        self.clear_logs_var = tk.BooleanVar(master, value=False)
        self.parallel_var = tk.BooleanVar(master, value=False)

        # ── Settings ──────────────────────────────────────────────────────────
        self.palette_var = tk.StringVar(master, value="Purple")
        self.theme_mode_var = tk.StringVar(master, value="Light")
        self.font_family_var = tk.StringVar(master, value="Arial")
        self.font_sizes_vars: dict[str, tk.IntVar] = {
            "Header": tk.IntVar(master, value=16),
            "Title_L": tk.IntVar(value=22),
            "Title": tk.IntVar(value=14),
            "Button": tk.IntVar(value=11),
            "Label": tk.IntVar(value=10),
            "Body": tk.IntVar(value=9),
            "Caption": tk.IntVar(master, value=8),
            "Micro": tk.IntVar(master, value=7),
            "Mono": tk.IntVar(master, value=9),
        }

        # ── Module activation toggles (auto-generated from registry) ─────────
        # ``driver_manifests`` excludes a plugin that ships only a CLI entry
        # point: the driver has no window to open for it, and a toggle whose
        # argument list is empty is exactly what the launch gate blocks (D128).
        self.module_toggles: dict[str, tk.BooleanVar] = {}
        for manifest in registry.driver_manifests:
            self.module_toggles[manifest.id] = tk.BooleanVar(
                master, value=manifest.default_on
            )

        # ── Per-module options ────────────────────────────────────────────────
        self._init_tool_option_vars(master)

        self.scrubber_preserve_lyrics = tk.BooleanVar(master, value=True)
        self.scrubber_preserve_album_artist = tk.BooleanVar(master, value=True)
        self.scrubber_preserve_embedded_art = tk.BooleanVar(master, value=True)

        self.album_genre_coverage = tk.StringVar(master, value="50")

        self.rg_lufs = tk.StringVar(master, value="-16.0")

        self.bpm_range_min = tk.StringVar(master, value="75")
        self.bpm_range_max = tk.StringVar(master, value="175")
        self.bpm_duration = tk.StringVar(master, value="90")

        self.lyrics_provider = tk.StringVar(master, value="lrclib")
        self.lyrics_request_timeout = tk.StringVar(master, value="10.0")
        self.lyrics_skip_existing = tk.BooleanVar(master, value=True)
        self.lyrics_plain_fallback = tk.BooleanVar(master, value=True)

        self.tempo_scheme = tk.StringVar(master, value="Italian")

        self.key_duration = tk.StringVar(master, value="90")

        self.bpm_parallel = tk.BooleanVar(master, value=False)
        default_workers = str(default_max_workers())
        self.bpm_workers = tk.StringVar(master, value=default_workers)

        self.lyrics_parallel = tk.BooleanVar(master, value=False)
        self.lyrics_workers = tk.StringVar(master, value=default_workers)

        self.key_parallel = tk.BooleanVar(master, value=False)
        self.key_workers = tk.StringVar(master, value=default_workers)

        self.mood_duration = tk.StringVar(master, value="90")
        self.mood_parallel = tk.BooleanVar(master, value=False)
        self.mood_workers = tk.StringVar(master, value=default_workers)

        self.mood_analysis_batch_duration = tk.StringVar(master, value="90")
        self.mood_analysis_batch_parallel = tk.BooleanVar(master, value=False)
        self.mood_analysis_batch_workers = tk.StringVar(master, value=default_workers)

        self.art_res = tk.StringVar(master, value="800")
        self.art_purge = tk.BooleanVar(master, value=True)
        self.art_min_dim = tk.StringVar(master, value="500")
        self.art_match_threshold = tk.StringVar(master, value="0.85")

        # ── Utilities window controls ─────────────────────────────────────────
        self.converter_output_format = tk.StringVar(master, value="mp3")
        self.converter_quality = tk.StringVar(master, value="highest")
        self.converter_delete_originals = tk.BooleanVar(master, value=False)
        self.converter_output_dir = tk.StringVar(master, value="")
        # Widget references created later by the converter card; readers use
        # getattr(...) with a None default until the utilities window is built.
        self._converter_detected_label: tk.Label | None = None
        self._converter_format_menu: ttk.Combobox | None = None

        self.util_global_mode = tk.StringVar(master, value="Dry Run")
        self.util_auto_start = tk.BooleanVar(master, value=False)
        self.util_auto_end = tk.BooleanVar(master, value=False)
        self.util_select_all_var = tk.BooleanVar(master, value=False)
        self.util_clear_logs_var = tk.BooleanVar(master, value=False)

        # ── Format converter internal lists ───────────────────────────────────
        # Imported from music_format_converter rather than hardcoded so the
        # Master Driver dropdowns track the tool's own set (mp4/aiff/aif
        # included) and cannot drift again.
        self.converter_lossy_formats: list[str] = list(CONVERTER_LOSSY_FORMATS)
        self.converter_lossless_formats: list[str] = list(CONVERTER_LOSSLESS_FORMATS)
        self.converter_all_formats: list[str] = (
            self.converter_lossy_formats + self.converter_lossless_formats
        )
        self.converter_available_formats: list[str] = list(self.converter_all_formats)

        # ── Audio Refinery controls ───────────────────────────────────────────
        self.refinery_source = tk.StringVar(master, value="")
        self.refinery_output = tk.StringVar(master, value="")
        self.refinery_auto_start = tk.BooleanVar(master, value=False)
        self.refinery_auto_end = tk.BooleanVar(master, value=False)
        self.refinery_select_all_var = tk.BooleanVar(master, value=False)

        # ── Fingerprinter controls ─────────────────────────────────────────────
        self.fingerprinter_lookup = tk.BooleanVar(master, value=True)
        self.fingerprinter_write_tags = tk.BooleanVar(master, value=False)
        self.fingerprinter_write_mbids = tk.BooleanVar(master, value=False)
        self.fingerprinter_mbid_region = tk.StringVar(master, value="")
        self.fingerprinter_musicbrainz = tk.BooleanVar(master, value=False)
        self.fingerprinter_write_isrc = tk.BooleanVar(master, value=False)
        self.fingerprinter_threshold = tk.StringVar(master, value="0.5")
        self.fingerprinter_max_length = tk.StringVar(master, value="120")
        self.fingerprinter_fpcalc = tk.StringVar(master, value="")
        self.fingerprinter_api_key = tk.StringVar(master, value="")

        # ── Converter extra controls ──────────────────────────────────────────
        self.converter_sample_rate = tk.StringVar(master, value="source")
        self.converter_bit_depth = tk.StringVar(master, value="auto")
        self.converter_normalize_mp3 = tk.BooleanVar(master, value=False)
        self.converter_target_lufs = tk.StringVar(master, value="-16.0")

        # ── Album Art Normalizer controls ─────────────────────────────────────
        self.art_normalizer_size = tk.StringVar(master, value="800")

        # ── Library Stats controls ────────────────────────────────────────────
        self.library_stats_incremental = tk.StringVar(master, value="full")
        self.library_stats_refresh = tk.BooleanVar(master, value=False)
        self.library_stats_export_csv = tk.StringVar(master, value="")
        self.library_stats_export_json = tk.StringVar(master, value="")

        # ── Spectral Viewer controls ──────────────────────────────────────────
        self.spectral_output_dir = tk.StringVar(master, value="")
        self.spectral_n_fft = tk.StringVar(master, value="2048")
        self.spectral_db_range = tk.StringVar(master, value="80")

        # ── File Reorganizer controls ─────────────────────────────────────────
        self.file_reorg_output_dir = tk.StringVar(master, value="")
        self.file_reorg_action = tk.StringVar(master, value="copy")
        self.file_reorg_specific_pattern = tk.StringVar(master, value="")
        self.file_reorg_various_pattern = tk.StringVar(master, value="")

        # ── CD Ripper controls ────────────────────────────────────────────────
        self.cd_ripper_output_dir = tk.StringVar(master, value="")
        self.cd_ripper_format = tk.StringVar(master, value="flac")
        self.cd_ripper_tracks = tk.StringVar(master, value="")
        self.cd_ripper_cue = tk.BooleanVar(master, value=False)

        # ── Stem Separator controls ──────────────────────────────────────────
        # No output directory default: a separation writes whole new trees, so
        # the driver must not guess a destination.
        self.stem_separator_output_dir = tk.StringVar(master, value="")
        self.stem_separator_model = tk.StringVar(master, value="htdemucs")
        self.stem_separator_device = tk.StringVar(master, value="auto")
        self.stem_separator_mix = tk.BooleanVar(master, value=False)
        self.stem_separator_vocals = tk.BooleanVar(master, value=True)
        self.stem_separator_drums = tk.BooleanVar(master, value=True)
        self.stem_separator_bass = tk.BooleanVar(master, value=True)
        self.stem_separator_other = tk.BooleanVar(master, value=True)

        # ── ML Denoiser controls ─────────────────────────────────────────────
        # A percentage, the same unit the tool's slider and CLI use.
        self.ml_denoiser_amount = tk.StringVar(master, value="100")

        # ── Duplicate Finder controls ────────────────────────────────────────
        # The threshold is the measured default (0.10 bit-error rate), and the
        # quarantine folder is blank until the user picks one: the tool then
        # derives ``_Duplicates`` beside the scanned folder, which is the only
        # destination it can choose without moving files somewhere unexpected.
        self.duplicate_threshold = tk.StringVar(master, value="0.10")
        self.duplicate_quarantine_dir = tk.StringVar(master, value="")
        self.duplicate_disposition = tk.StringVar(master, value="quarantine")
        # Changed in 2.6.0: exact matching is off unless the card asks for it, so
        # a batch that never touches the control behaves as it did before F-E9.
        self.duplicate_exact_mode = tk.StringVar(master, value="off")

    def _init_tool_option_vars(self, master: tk.Misc | None) -> None:
        """Create the option variables of the tools that take their own settings.

        Kept out of :meth:`__init__` so its statement count stays inside the
        lint budget as tools gain options.
        """
        # Changed in 2.6.0: the Artwork Extractor's sidecar name and its two
        # switches, which its batch step passes to the window.
        self.artwork_sidecar_name = tk.StringVar(master, value="cover")
        self.artwork_force = tk.BooleanVar(master, value=False)
        self.artwork_recursive = tk.BooleanVar(master, value=False)

        # Changed in 2.5.0: the Track Splitter's gap settings (F-E4).  Its
        # module toggle comes from the registry like every other tool's.
        self.track_splitter_min_silence = tk.StringVar(master, value="700")
        self.track_splitter_silence_db = tk.StringVar(master, value="-45")
        self.track_splitter_min_track = tk.StringVar(master, value="5000")
        self.track_splitter_boundary = tk.StringVar(master, value="midpoint")
        self.track_splitter_output_dir = tk.StringVar(master, value="")
        self.track_splitter_cue = tk.BooleanVar(master, value=True)

        # Changed in 2.5.0: the Audio Joiner's boundary settings (F-E5).  Its
        # module toggle comes from the registry like every other tool's.
        self.audio_joiner_order = tk.StringVar(master, value="")
        self.audio_joiner_output = tk.StringVar(master, value="")
        self.audio_joiner_gap_ms = tk.StringVar(master, value="0")
        self.audio_joiner_crossfade_ms = tk.StringVar(master, value="0")
        self.audio_joiner_copy = tk.BooleanVar(master, value=True)

        # ── ASX Playlist Extractor controls ──────────────────────────────────
        # Off by default, matching the extractor's CLI and preserving today's
        # top-level-only discovery unless the user asks for a library sweep.
        self.asx_recursive = tk.BooleanVar(master, value=False)

        # ── Restoration (declip) controls ────────────────────────────────────
        # 0.98 of the file's own peak is the ceiling a clipped sample sits at;
        # 50 ms is the longest plateau the reconstruction will attempt.
        self.restore_threshold = tk.StringVar(master, value="0.98")
        self.restore_max_run = tk.StringVar(master, value="50")

        # Changed in 2.5.0: the channel utility's rule and parameters (F-E6).
        # The values are the shared operation ids, so the card cannot offer a
        # rule the CLI would refuse.
        self.channel_tools_operation = tk.StringVar(master, value="mono_mean")
        self.channel_tools_width = tk.StringVar(master, value="100")
        self.channel_tools_source_channel = tk.StringVar(master, value="left")
        self.channel_tools_invert = tk.StringVar(master, value="both")

    # ── Backward-compatible property aliases for utility toggles ──────────────
    # These delegate to the module_toggles dict so existing card code and
    # tests continue to work unchanged.  New code should use
    # state.module_toggles["converter"] directly.

    @property
    def converter_toggle(self) -> tk.BooleanVar:
        """Return ``module_toggles['converter']`` (legacy alias)."""
        return self.module_toggles["converter"]

    @converter_toggle.setter
    def converter_toggle(self, value: tk.BooleanVar) -> None:
        self.module_toggles["converter"] = value

    @property
    def asx_extractor_toggle(self) -> tk.BooleanVar:
        """Return ``module_toggles['asx_extractor']`` (legacy alias)."""
        return self.module_toggles["asx_extractor"]

    @asx_extractor_toggle.setter
    def asx_extractor_toggle(self, value: tk.BooleanVar) -> None:
        self.module_toggles["asx_extractor"] = value

    @property
    def cd_ripper_toggle(self) -> tk.BooleanVar:
        """Return ``module_toggles['cd_ripper']`` (legacy alias)."""
        return self.module_toggles["cd_ripper"]

    @cd_ripper_toggle.setter
    def cd_ripper_toggle(self, value: tk.BooleanVar) -> None:
        self.module_toggles["cd_ripper"] = value

    @property
    def mood_analysis_batch_toggle(self) -> tk.BooleanVar:
        """Return ``module_toggles['mood_analysis_batch']`` (legacy alias)."""
        return self.module_toggles["mood_analysis_batch"]

    @mood_analysis_batch_toggle.setter
    def mood_analysis_batch_toggle(self, value: tk.BooleanVar) -> None:
        self.module_toggles["mood_analysis_batch"] = value

    @property
    def library_stats_toggle(self) -> tk.BooleanVar:
        """Return ``module_toggles['library_stats']`` (legacy alias)."""
        return self.module_toggles["library_stats"]

    @library_stats_toggle.setter
    def library_stats_toggle(self, value: tk.BooleanVar) -> None:
        self.module_toggles["library_stats"] = value

    @property
    def track_splitter_toggle(self) -> tk.BooleanVar:
        """Return ``module_toggles['track_splitter']`` (legacy alias).

        Changed in 2.5.0: the Track Splitter's card reads it by name (F-E4).
        """
        return self.module_toggles["track_splitter"]

    @track_splitter_toggle.setter
    def track_splitter_toggle(self, value: tk.BooleanVar) -> None:
        self.module_toggles["track_splitter"] = value
