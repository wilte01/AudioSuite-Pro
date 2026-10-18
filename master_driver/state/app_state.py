"""
app_state.py — Single container for all Master Driver tk variables.

Passing this object as a dependency instead of 'self' makes each UI card
and runner function explicit about what state it touches.

Changed in 1.0.1: removes the unused ``library_stats_completeness``/``_detail`` toggle
keys.

Changed in 1.2.0: adds the fingerprinter MusicBrainz / ISRC toggles.
Changed in 1.3.0: adds the Spectral Viewer option variables (PLAN D42).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

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
        self.module_toggles: dict[str, tk.BooleanVar] = {}
        for manifest in registry.all:
            self.module_toggles[manifest.id] = tk.BooleanVar(
                master, value=manifest.default_on
            )

        # ── Per-module options ────────────────────────────────────────────────
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
        self.bpm_workers = tk.StringVar(master, value="4")

        self.lyrics_parallel = tk.BooleanVar(master, value=False)
        self.lyrics_workers = tk.StringVar(master, value="4")

        self.key_parallel = tk.BooleanVar(master, value=False)
        self.key_workers = tk.StringVar(master, value="4")

        self.mood_duration = tk.StringVar(master, value="90")
        self.mood_parallel = tk.BooleanVar(master, value=False)
        self.mood_workers = tk.StringVar(master, value="4")

        self.mood_analysis_batch_duration = tk.StringVar(master, value="90")
        self.mood_analysis_batch_parallel = tk.BooleanVar(master, value=False)
        self.mood_analysis_batch_workers = tk.StringVar(master, value="4")

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

        # ── Noise Reduction controls ──────────────────────────────────────────
        self.nr_reduce_hum = tk.BooleanVar(master, value=False)
        self.nr_reduce_broadband = tk.BooleanVar(master, value=False)
        self.nr_hum_frequency = tk.StringVar(master, value="60")
        self.nr_hum_harmonics = tk.StringVar(master, value="8")
        self.nr_hum_quality = tk.StringVar(master, value="30.0")
        self.nr_noise_start = tk.StringVar(master, value="0")
        self.nr_noise_end = tk.StringVar(master, value="500")
        self.nr_gate_threshold = tk.StringVar(master, value="3.0")

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

        # ── Audio Enhancer controls ──────────────────────────────────────────
        self.enhancer_output_dir = tk.StringVar(master, value="")
        self.enhancer_preset = tk.StringVar(master, value="Moderate")

        # ── Audio Normalizer controls ────────────────────────────────────────
        self.normalizer_target_lufs = tk.StringVar(master, value="-14.0")
        self.normalizer_tolerance = tk.StringVar(master, value="0.5")
        self.normalizer_mode = tk.StringVar(master, value="normalise")

        # ── Pop & Click Remover controls ─────────────────────────────────────
        self.declick_sensitivity = tk.StringVar(master, value="0.25")
        self.declick_max_width = tk.StringVar(master, value="5")

        # ── Silence Trimmer controls ─────────────────────────────────────────
        # Fade defaults are the GUI app's own valid defaults (500/1000 ms),
        # not the click CLI's 25/25 — the GUI parser validates 100–3000 /
        # 100–5000 and would SystemExit at launch on out-of-range values.
        self.trimmer_threshold = tk.StringVar(master, value="-50")
        self.trimmer_apply_fade = tk.BooleanVar(master, value=False)
        self.trimmer_fade_in_ms = tk.StringVar(master, value="500")
        self.trimmer_fade_out_ms = tk.StringVar(master, value="1000")

    # ── Backward-compatible property aliases for utility toggles ──────────────
    # These delegate to the module_toggles dict so existing card code and
    # tests continue to work unchanged.  New code should use
    # state.module_toggles["converter"] directly.

    @property
    def converter_toggle(self) -> tk.BooleanVar:
        return self.module_toggles["converter"]

    @converter_toggle.setter
    def converter_toggle(self, value: tk.BooleanVar) -> None:
        self.module_toggles["converter"] = value

    @property
    def asx_extractor_toggle(self) -> tk.BooleanVar:
        return self.module_toggles["asx_extractor"]

    @asx_extractor_toggle.setter
    def asx_extractor_toggle(self, value: tk.BooleanVar) -> None:
        self.module_toggles["asx_extractor"] = value

    @property
    def cd_ripper_toggle(self) -> tk.BooleanVar:
        return self.module_toggles["cd_ripper"]

    @cd_ripper_toggle.setter
    def cd_ripper_toggle(self, value: tk.BooleanVar) -> None:
        self.module_toggles["cd_ripper"] = value

    @property
    def mood_analysis_batch_toggle(self) -> tk.BooleanVar:
        return self.module_toggles["mood_analysis_batch"]

    @mood_analysis_batch_toggle.setter
    def mood_analysis_batch_toggle(self, value: tk.BooleanVar) -> None:
        self.module_toggles["mood_analysis_batch"] = value

    @property
    def library_stats_toggle(self) -> tk.BooleanVar:
        return self.module_toggles["library_stats"]

    @library_stats_toggle.setter
    def library_stats_toggle(self, value: tk.BooleanVar) -> None:
        self.module_toggles["library_stats"] = value
