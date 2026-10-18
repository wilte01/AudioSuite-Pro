"""
Tests for master_driver.state.app_state (AppState) and
         audio_suite_shared.suite_config (replaces former master_driver.state.config)

Strategy — real tkinter, shared session root (see conftest.py)
-------------------------------------------------------------------------------
conftest.py creates one hidden Tk() root for the whole pytest session before
any test module is collected, so real tk.BooleanVar / StringVar / IntVar
work normally here without each test needing to pass a root around
explicitly. AppState's variables are genuine tkinter Var objects; their
.get() and .set() behave exactly as in production.

What is tested
--------------
AppState
  • All attributes exist after __init__
  • Default values for every field
  • module_toggles dict has the expected keys
  • font_sizes_vars dict has the expected keys and IntVar defaults
  • converter_all_formats composition
  • converter_available_formats initial state

suite_config (load_app_state / save_app_state / save_palette)
  • load_app_state() sets dir_path, palette_var, font_family_var from a JSON file
  • load_app_state() with a missing file leaves state at defaults (empty/Purple/Arial)
  • load_app_state() with corrupt JSON leaves state at defaults
  • save_app_state() writes last_directory, palette, font_family, font_sizes to JSON
  • save_app_state() round-trips with load_app_state()
  • save_palette() persists palette, preserving other keys
  • save_palette() on a missing file creates the file
  • font_sizes round-trip

Changed in 1.0.1: updates the expected key set after the completeness/detail keys were
removed.

Changed in 1.2.0: covers the new fingerprinter MusicBrainz / ISRC keys.

Changed in 1.3.0: the expected toggle-key set adds ``spectral_viewer``.
"""

import json

import pytest

from audio_suite_shared import suite_config
from master_driver.state.app_state import AppState

# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture()
def state(root):
    """A fresh AppState. Depends on the shared session `root` (conftest.py)
    so tkinter has a default root to attach its Var objects to; AppState
    itself doesn't take root as a parameter, it relies on tkinter's
    implicit default-root mechanism."""
    return AppState()


@pytest.fixture()
def cfg_path(tmp_path, monkeypatch):
    """Redirect suite_config to write its JSON file inside tmp_path."""
    suite_config._invalidate_cache()
    cfg_file = tmp_path / "audio_suite_config.json"
    monkeypatch.setattr(suite_config, "CONFIG_PATH", cfg_file)
    return cfg_file


# ===========================================================================
# AppState — attribute existence
# ===========================================================================


class TestAppStateAttributeExistence:
    # ── Core controls ──────────────────────────────────────────────────────

    def test_dir_path_exists(self, state):
        assert hasattr(state, "dir_path")

    def test_global_mode_exists(self, state):
        assert hasattr(state, "global_mode")

    def test_auto_start_exists(self, state):
        assert hasattr(state, "auto_start")

    def test_auto_end_exists(self, state):
        assert hasattr(state, "auto_end")

    def test_select_all_var_exists(self, state):
        assert hasattr(state, "select_all_var")

    def test_clear_logs_var_exists(self, state):
        assert hasattr(state, "clear_logs_var")

    # ── Settings ───────────────────────────────────────────────────────────

    def test_palette_var_exists(self, state):
        assert hasattr(state, "palette_var")

    def test_theme_mode_var_exists(self, state):
        assert hasattr(state, "theme_mode_var")

    def test_font_family_var_exists(self, state):
        assert hasattr(state, "font_family_var")

    def test_font_sizes_vars_exists(self, state):
        assert hasattr(state, "font_sizes_vars")

    # ── Module toggles ─────────────────────────────────────────────────────

    def test_module_toggles_exists(self, state):
        assert hasattr(state, "module_toggles")

    # ── Per-module options ─────────────────────────────────────────────────

    def test_scrubber_preserve_lyrics_exists(self, state):
        assert hasattr(state, "scrubber_preserve_lyrics")

    def test_album_genre_coverage_exists(self, state):
        assert hasattr(state, "album_genre_coverage")

    def test_rg_lufs_exists(self, state):
        assert hasattr(state, "rg_lufs")

    def test_bpm_range_min_exists(self, state):
        assert hasattr(state, "bpm_range_min")

    def test_bpm_range_max_exists(self, state):
        assert hasattr(state, "bpm_range_max")

    def test_bpm_duration_exists(self, state):
        assert hasattr(state, "bpm_duration")

    def test_lyrics_provider_exists(self, state):
        assert hasattr(state, "lyrics_provider")

    def test_lyrics_request_timeout_exists(self, state):
        assert hasattr(state, "lyrics_request_timeout")

    def test_lyrics_skip_existing_exists(self, state):
        assert hasattr(state, "lyrics_skip_existing")

    def test_lyrics_plain_fallback_exists(self, state):
        assert hasattr(state, "lyrics_plain_fallback")

    def test_lyrics_parallel_exists(self, state):
        assert hasattr(state, "lyrics_parallel")

    def test_lyrics_workers_exists(self, state):
        assert hasattr(state, "lyrics_workers")

    def test_tempo_scheme_exists(self, state):
        assert hasattr(state, "tempo_scheme")

    def test_key_duration_exists(self, state):
        assert hasattr(state, "key_duration")

    def test_art_res_exists(self, state):
        assert hasattr(state, "art_res")

    def test_art_purge_exists(self, state):
        assert hasattr(state, "art_purge")

    # ── Utilities ──────────────────────────────────────────────────────────

    def test_converter_toggle_exists(self, state):
        assert hasattr(state, "converter_toggle")

    def test_converter_output_format_exists(self, state):
        assert hasattr(state, "converter_output_format")

    def test_converter_quality_exists(self, state):
        assert hasattr(state, "converter_quality")

    def test_converter_delete_originals_exists(self, state):
        assert hasattr(state, "converter_delete_originals")

    def test_converter_output_dir_exists(self, state):
        assert hasattr(state, "converter_output_dir")

    def test_asx_extractor_toggle_exists(self, state):
        assert hasattr(state, "asx_extractor_toggle")

    def test_cd_ripper_toggle_exists(self, state):
        assert hasattr(state, "cd_ripper_toggle")

    def test_util_global_mode_exists(self, state):
        assert hasattr(state, "util_global_mode")

    def test_util_auto_start_exists(self, state):
        assert hasattr(state, "util_auto_start")

    def test_util_auto_end_exists(self, state):
        assert hasattr(state, "util_auto_end")

    def test_util_select_all_var_exists(self, state):
        assert hasattr(state, "util_select_all_var")

    def test_util_clear_logs_var_exists(self, state):
        assert hasattr(state, "util_clear_logs_var")

    # ── Format lists ───────────────────────────────────────────────────────

    def test_converter_lossy_formats_exists(self, state):
        assert hasattr(state, "converter_lossy_formats")

    def test_converter_lossless_formats_exists(self, state):
        assert hasattr(state, "converter_lossless_formats")

    def test_converter_all_formats_exists(self, state):
        assert hasattr(state, "converter_all_formats")

    def test_converter_available_formats_exists(self, state):
        assert hasattr(state, "converter_available_formats")

    # ── Refinery ───────────────────────────────────────────────────────────

    def test_refinery_source_exists(self, state):
        assert hasattr(state, "refinery_source")

    def test_refinery_output_exists(self, state):
        assert hasattr(state, "refinery_output")

    def test_refinery_auto_start_exists(self, state):
        assert hasattr(state, "refinery_auto_start")

    def test_refinery_auto_end_exists(self, state):
        assert hasattr(state, "refinery_auto_end")

    def test_refinery_select_all_var_exists(self, state):
        assert hasattr(state, "refinery_select_all_var")

    # ── Fingerprinter ──────────────────────────────────────────────────────

    def test_fingerprinter_lookup_exists(self, state):
        assert hasattr(state, "fingerprinter_lookup")

    def test_fingerprinter_write_tags_exists(self, state):
        assert hasattr(state, "fingerprinter_write_tags")

    def test_fingerprinter_write_mbids_exists(self, state):
        assert hasattr(state, "fingerprinter_write_mbids")

    def test_fingerprinter_mbid_region_exists(self, state):
        assert hasattr(state, "fingerprinter_mbid_region")

    def test_fingerprinter_musicbrainz_exists(self, state):
        assert hasattr(state, "fingerprinter_musicbrainz")

    def test_fingerprinter_write_isrc_exists(self, state):
        assert hasattr(state, "fingerprinter_write_isrc")

    def test_fingerprinter_threshold_exists(self, state):
        assert hasattr(state, "fingerprinter_threshold")

    def test_fingerprinter_max_length_exists(self, state):
        assert hasattr(state, "fingerprinter_max_length")

    def test_fingerprinter_fpcalc_exists(self, state):
        assert hasattr(state, "fingerprinter_fpcalc")

    def test_fingerprinter_api_key_exists(self, state):
        assert hasattr(state, "fingerprinter_api_key")

    # ── Noise Reduction ────────────────────────────────────────────────────

    def test_nr_reduce_hum_exists(self, state):
        assert hasattr(state, "nr_reduce_hum")

    def test_nr_reduce_broadband_exists(self, state):
        assert hasattr(state, "nr_reduce_broadband")

    def test_nr_hum_frequency_exists(self, state):
        assert hasattr(state, "nr_hum_frequency")

    def test_nr_hum_harmonics_exists(self, state):
        assert hasattr(state, "nr_hum_harmonics")

    def test_nr_hum_quality_exists(self, state):
        assert hasattr(state, "nr_hum_quality")

    def test_nr_noise_start_exists(self, state):
        assert hasattr(state, "nr_noise_start")

    def test_nr_noise_end_exists(self, state):
        assert hasattr(state, "nr_noise_end")

    def test_nr_gate_threshold_exists(self, state):
        assert hasattr(state, "nr_gate_threshold")

    # ── Converter extras ───────────────────────────────────────────────────

    def test_converter_sample_rate_exists(self, state):
        assert hasattr(state, "converter_sample_rate")

    def test_converter_bit_depth_exists(self, state):
        assert hasattr(state, "converter_bit_depth")

    def test_converter_normalize_mp3_exists(self, state):
        assert hasattr(state, "converter_normalize_mp3")

    def test_converter_target_lufs_exists(self, state):
        assert hasattr(state, "converter_target_lufs")

    # ── Album Art Normalizer ───────────────────────────────────────────────

    def test_art_normalizer_size_exists(self, state):
        assert hasattr(state, "art_normalizer_size")

    # ── Library Stats ──────────────────────────────────────────────────────

    def test_library_stats_incremental_exists(self, state):
        assert hasattr(state, "library_stats_incremental")

    def test_library_stats_refresh_exists(self, state):
        assert hasattr(state, "library_stats_refresh")

    def test_library_stats_export_csv_exists(self, state):
        assert hasattr(state, "library_stats_export_csv")

    def test_library_stats_export_json_exists(self, state):
        assert hasattr(state, "library_stats_export_json")

    # ── File Reorganizer ───────────────────────────────────────────────────

    def test_file_reorg_output_dir_exists(self, state):
        assert hasattr(state, "file_reorg_output_dir")

    def test_file_reorg_action_exists(self, state):
        assert hasattr(state, "file_reorg_action")

    def test_file_reorg_specific_pattern_exists(self, state):
        assert hasattr(state, "file_reorg_specific_pattern")

    def test_file_reorg_various_pattern_exists(self, state):
        assert hasattr(state, "file_reorg_various_pattern")

    # ── CD Ripper ──────────────────────────────────────────────────────────

    def test_cd_ripper_output_dir_exists(self, state):
        assert hasattr(state, "cd_ripper_output_dir")

    def test_cd_ripper_format_exists(self, state):
        assert hasattr(state, "cd_ripper_format")

    def test_cd_ripper_tracks_exists(self, state):
        assert hasattr(state, "cd_ripper_tracks")

    def test_cd_ripper_cue_exists(self, state):
        assert hasattr(state, "cd_ripper_cue")

    # ── Audio Enhancer ────────────────────────────────────────────────────

    def test_enhancer_output_dir_exists(self, state):
        assert hasattr(state, "enhancer_output_dir")

    def test_enhancer_preset_exists(self, state):
        assert hasattr(state, "enhancer_preset")

    # ── Audio Normalizer ──────────────────────────────────────────────────

    def test_normalizer_target_lufs_exists(self, state):
        assert hasattr(state, "normalizer_target_lufs")

    def test_normalizer_tolerance_exists(self, state):
        assert hasattr(state, "normalizer_tolerance")

    def test_normalizer_mode_exists(self, state):
        assert hasattr(state, "normalizer_mode")

    # ── Pop & Click Remover ───────────────────────────────────────────────

    def test_declick_sensitivity_exists(self, state):
        assert hasattr(state, "declick_sensitivity")

    def test_declick_max_width_exists(self, state):
        assert hasattr(state, "declick_max_width")

    # ── Silence Trimmer ───────────────────────────────────────────────────

    def test_trimmer_threshold_exists(self, state):
        assert hasattr(state, "trimmer_threshold")

    def test_trimmer_apply_fade_exists(self, state):
        assert hasattr(state, "trimmer_apply_fade")

    def test_trimmer_fade_in_ms_exists(self, state):
        assert hasattr(state, "trimmer_fade_in_ms")

    def test_trimmer_fade_out_ms_exists(self, state):
        assert hasattr(state, "trimmer_fade_out_ms")


# ===========================================================================
# AppState — default values
# ===========================================================================


class TestAppStateDefaults:
    def test_global_mode_default(self, state):
        assert state.global_mode.get() == "Dry Run"

    def test_auto_start_default_false(self, state):
        assert state.auto_start.get() is False

    def test_auto_end_default_false(self, state):
        assert state.auto_end.get() is False

    def test_select_all_var_default_false(self, state):
        assert state.select_all_var.get() is False

    def test_clear_logs_var_default_false(self, state):
        assert state.clear_logs_var.get() is False

    def test_palette_var_default(self, state):
        assert state.palette_var.get() == "Purple"

    def test_theme_mode_var_default(self, state):
        assert state.theme_mode_var.get() == "Light"

    def test_font_family_var_default(self, state):
        assert state.font_family_var.get() == "Arial"

    def test_scrubber_preserve_lyrics_default_true(self, state):
        assert state.scrubber_preserve_lyrics.get() is True

    def test_album_genre_coverage_default(self, state):
        assert state.album_genre_coverage.get() == "50"

    def test_rg_lufs_default(self, state):
        assert state.rg_lufs.get() == "-16.0"

    def test_bpm_range_min_default(self, state):
        assert state.bpm_range_min.get() == "75"

    def test_bpm_range_max_default(self, state):
        assert state.bpm_range_max.get() == "175"

    def test_bpm_duration_default(self, state):
        assert state.bpm_duration.get() == "90"

    def test_lyrics_provider_default(self, state):
        assert state.lyrics_provider.get() == "lrclib"

    def test_lyrics_request_timeout_default(self, state):
        assert state.lyrics_request_timeout.get() == "10.0"

    def test_lyrics_skip_existing_default_true(self, state):
        assert state.lyrics_skip_existing.get() is True

    def test_lyrics_plain_fallback_default_true(self, state):
        assert state.lyrics_plain_fallback.get() is True

    def test_lyrics_parallel_default_false(self, state):
        assert state.lyrics_parallel.get() is False

    def test_lyrics_workers_default(self, state):
        assert state.lyrics_workers.get() == "4"

    def test_tempo_scheme_default(self, state):
        assert state.tempo_scheme.get() == "Italian"

    def test_key_duration_default(self, state):
        assert state.key_duration.get() == "90"

    def test_art_res_default(self, state):
        assert state.art_res.get() == "800"

    def test_art_purge_default_true(self, state):
        assert state.art_purge.get() is True

    def test_converter_output_format_default(self, state):
        assert state.converter_output_format.get() == "mp3"

    def test_converter_quality_default(self, state):
        assert state.converter_quality.get() == "highest"

    def test_converter_delete_originals_default_false(self, state):
        assert state.converter_delete_originals.get() is False

    def test_converter_output_dir_default_empty(self, state):
        assert state.converter_output_dir.get() == ""

    def test_converter_toggle_default_false(self, state):
        assert state.converter_toggle.get() is False

    def test_asx_extractor_toggle_default_false(self, state):
        assert state.asx_extractor_toggle.get() is False

    def test_cd_ripper_toggle_default_false(self, state):
        assert state.cd_ripper_toggle.get() is False

    def test_util_global_mode_default(self, state):
        assert state.util_global_mode.get() == "Dry Run"

    def test_util_auto_start_default_false(self, state):
        assert state.util_auto_start.get() is False

    def test_util_auto_end_default_false(self, state):
        assert state.util_auto_end.get() is False

    def test_util_select_all_var_default_false(self, state):
        assert state.util_select_all_var.get() is False

    def test_util_clear_logs_var_default_false(self, state):
        assert state.util_clear_logs_var.get() is False

    def test_refinery_source_default_empty(self, state):
        assert state.refinery_source.get() == ""

    def test_refinery_output_default_empty(self, state):
        assert state.refinery_output.get() == ""

    def test_refinery_auto_start_default_false(self, state):
        assert state.refinery_auto_start.get() is False

    def test_refinery_auto_end_default_false(self, state):
        assert state.refinery_auto_end.get() is False

    def test_refinery_select_all_var_default_false(self, state):
        assert state.refinery_select_all_var.get() is False

    def test_dir_path_default_empty(self, state):
        assert state.dir_path.get() == ""

    def test_fingerprinter_lookup_default_true(self, state):
        assert state.fingerprinter_lookup.get() is True

    def test_fingerprinter_write_tags_default_false(self, state):
        assert state.fingerprinter_write_tags.get() is False

    def test_fingerprinter_write_mbids_default_false(self, state):
        assert state.fingerprinter_write_mbids.get() is False

    def test_fingerprinter_mbid_region_default_empty(self, state):
        assert state.fingerprinter_mbid_region.get() == ""

    def test_fingerprinter_musicbrainz_default_false(self, state):
        assert state.fingerprinter_musicbrainz.get() is False

    def test_fingerprinter_write_isrc_default_false(self, state):
        assert state.fingerprinter_write_isrc.get() is False

    def test_fingerprinter_threshold_default(self, state):
        assert state.fingerprinter_threshold.get() == "0.5"

    def test_fingerprinter_max_length_default(self, state):
        assert state.fingerprinter_max_length.get() == "120"

    def test_fingerprinter_fpcalc_default_empty(self, state):
        assert state.fingerprinter_fpcalc.get() == ""

    def test_fingerprinter_api_key_default_empty(self, state):
        assert state.fingerprinter_api_key.get() == ""

    def test_nr_reduce_hum_default_false(self, state):
        assert state.nr_reduce_hum.get() is False

    def test_nr_reduce_broadband_default_false(self, state):
        assert state.nr_reduce_broadband.get() is False

    def test_nr_hum_frequency_default(self, state):
        assert state.nr_hum_frequency.get() == "60"

    def test_nr_hum_harmonics_default(self, state):
        assert state.nr_hum_harmonics.get() == "8"

    def test_nr_hum_quality_default(self, state):
        assert state.nr_hum_quality.get() == "30.0"

    def test_nr_noise_start_default(self, state):
        assert state.nr_noise_start.get() == "0"

    def test_nr_noise_end_default(self, state):
        assert state.nr_noise_end.get() == "500"

    def test_nr_gate_threshold_default(self, state):
        assert state.nr_gate_threshold.get() == "3.0"

    def test_converter_sample_rate_default(self, state):
        assert state.converter_sample_rate.get() == "source"

    def test_converter_bit_depth_default(self, state):
        assert state.converter_bit_depth.get() == "auto"

    def test_converter_normalize_mp3_default_false(self, state):
        assert state.converter_normalize_mp3.get() is False

    def test_converter_target_lufs_default(self, state):
        assert state.converter_target_lufs.get() == "-16.0"

    def test_art_normalizer_size_default(self, state):
        assert state.art_normalizer_size.get() == "800"

    def test_library_stats_incremental_default_full(self, state):
        assert state.library_stats_incremental.get() == "full"

    def test_library_stats_refresh_default_false(self, state):
        assert state.library_stats_refresh.get() is False

    def test_library_stats_export_csv_default_empty(self, state):
        assert state.library_stats_export_csv.get() == ""

    def test_library_stats_export_json_default_empty(self, state):
        assert state.library_stats_export_json.get() == ""

    def test_file_reorg_output_dir_default_empty(self, state):
        assert state.file_reorg_output_dir.get() == ""

    def test_file_reorg_action_default_copy(self, state):
        assert state.file_reorg_action.get() == "copy"

    def test_file_reorg_specific_pattern_default_empty(self, state):
        assert state.file_reorg_specific_pattern.get() == ""

    def test_file_reorg_various_pattern_default_empty(self, state):
        assert state.file_reorg_various_pattern.get() == ""

    def test_cd_ripper_output_dir_default_empty(self, state):
        assert state.cd_ripper_output_dir.get() == ""

    def test_cd_ripper_format_default(self, state):
        assert state.cd_ripper_format.get() == "flac"

    def test_cd_ripper_tracks_default_empty(self, state):
        assert state.cd_ripper_tracks.get() == ""

    def test_cd_ripper_cue_default_false(self, state):
        assert state.cd_ripper_cue.get() is False

    def test_enhancer_output_dir_default_empty(self, state):
        assert state.enhancer_output_dir.get() == ""

    def test_enhancer_preset_default_moderate(self, state):
        assert state.enhancer_preset.get() == "Moderate"

    def test_normalizer_target_lufs_default(self, state):
        assert state.normalizer_target_lufs.get() == "-14.0"

    def test_normalizer_tolerance_default(self, state):
        assert state.normalizer_tolerance.get() == "0.5"

    def test_normalizer_mode_default(self, state):
        assert state.normalizer_mode.get() == "normalise"

    def test_declick_sensitivity_default(self, state):
        assert state.declick_sensitivity.get() == "0.25"

    def test_declick_max_width_default(self, state):
        assert state.declick_max_width.get() == "5"

    def test_trimmer_threshold_default(self, state):
        assert state.trimmer_threshold.get() == "-50"

    def test_trimmer_apply_fade_default_false(self, state):
        assert state.trimmer_apply_fade.get() is False

    def test_trimmer_fade_in_ms_default_is_gui_valid(self, state):
        assert state.trimmer_fade_in_ms.get() == "500"

    def test_trimmer_fade_out_ms_default_is_gui_valid(self, state):
        assert state.trimmer_fade_out_ms.get() == "1000"


# ===========================================================================
# AppState — module_toggles
# ===========================================================================


class TestModuleToggles:
    EXPECTED_KEYS = {
        # Enrich tools
        "scrubber",
        "album_genre",
        "genre_sync",
        "replaygain",
        "bpm",
        "tempo",
        "key",
        "fingerprinter",
        "mood_analyzer",
        "art",
        # Utility tools
        "converter",
        "asx_extractor",
        "album_art_normalizer",
        "cd_ripper",
        "mood_analysis_batch",
        "library_stats",
        "file_reorganizer",
        "tag_field_updater",
        "tag_editor",
        "noise_reduction",
        "lyrics_manager",
        "undo_tag_edits",
        "audio_enhancer",
        "audio_normalizer",
        "pop_click_remover",
        "silence_trimmer",
        "spectral_viewer",
        # Refinery
        "audio_refinery",
    }

    def test_all_expected_keys_present(self, state):
        assert self.EXPECTED_KEYS == set(state.module_toggles.keys())

    def test_all_toggles_default_false(self, state):
        for key, var in state.module_toggles.items():
            assert var.get() is False, f"{key} should default to False"

    def test_toggle_can_be_set(self, state):
        state.module_toggles["bpm"].set(True)
        assert state.module_toggles["bpm"].get() is True

    def test_toggles_are_independent(self, state):
        state.module_toggles["bpm"].set(True)
        assert state.module_toggles["tempo"].get() is False


# ===========================================================================
# AppState — font_sizes_vars
# ===========================================================================


class TestFontSizesVars:
    EXPECTED_SIZES = {
        "Header": 16,
        "Title_L": 22,
        "Title": 14,
        "Button": 11,
        "Label": 10,
        "Body": 9,
        "Caption": 8,
        "Micro": 7,
        "Mono": 9,
    }

    def test_all_size_keys_present(self, state):
        assert set(self.EXPECTED_SIZES.keys()) == set(state.font_sizes_vars.keys())

    @pytest.mark.parametrize(
        "key,expected",
        [
            ("Header", 16),
            ("Title_L", 22),
            ("Title", 14),
            ("Button", 11),
            ("Label", 10),
            ("Body", 9),
            ("Caption", 8),
            ("Micro", 7),
            ("Mono", 9),
        ],
    )
    def test_default_value(self, state, key, expected):
        assert state.font_sizes_vars[key].get() == expected

    def test_size_can_be_updated(self, state):
        state.font_sizes_vars["Header"].set(20)
        assert state.font_sizes_vars["Header"].get() == 20


# ===========================================================================
# AppState — format lists
# ===========================================================================


class TestConverterFormatLists:
    def test_lossy_formats_non_empty(self, state):
        assert len(state.converter_lossy_formats) > 0

    def test_lossless_formats_non_empty(self, state):
        assert len(state.converter_lossless_formats) > 0

    def test_all_formats_is_union(self, state):
        expected = state.converter_lossy_formats + state.converter_lossless_formats
        assert state.converter_all_formats == expected

    def test_available_formats_matches_all(self, state):
        assert state.converter_available_formats == list(state.converter_all_formats)

    def test_mp3_in_lossy(self, state):
        assert "mp3" in state.converter_lossy_formats

    def test_mp4_in_lossy(self, state):
        assert "mp4" in state.converter_lossy_formats

    def test_flac_in_lossless(self, state):
        assert "flac" in state.converter_lossless_formats

    def test_aiff_aif_in_lossless(self, state):
        assert "aiff" in state.converter_lossless_formats
        assert "aif" in state.converter_lossless_formats

    def test_no_overlap_between_lossy_and_lossless(self, state):
        overlap = set(state.converter_lossy_formats) & set(
            state.converter_lossless_formats
        )
        assert overlap == set()


# ===========================================================================
# suite_config.load_app_state
# ===========================================================================


class TestSuiteConfigLoad:
    def test_load_sets_dir_path(self, state, cfg_path):
        cfg_path.write_text(json.dumps({"last_directory": "/music/jazz"}))
        suite_config.load_app_state(state)
        assert state.dir_path.get() == "/music/jazz"

    def test_load_sets_palette(self, state, cfg_path):
        cfg_path.write_text(json.dumps({"palette": "Blue"}))
        suite_config.load_app_state(state)
        assert state.palette_var.get() == "Blue"

    def test_load_sets_font_family(self, state, cfg_path):
        cfg_path.write_text(json.dumps({"font_family": "Helvetica"}))
        suite_config.load_app_state(state)
        assert state.font_family_var.get() == "Helvetica"

    def test_load_sets_font_sizes(self, state, cfg_path):
        cfg_path.write_text(json.dumps({"font_sizes": {"Header": 20, "Body": 12}}))
        suite_config.load_app_state(state)
        assert state.font_sizes_vars["Header"].get() == 20
        assert state.font_sizes_vars["Body"].get() == 12

    def test_load_missing_file_uses_defaults(self, state, cfg_path):
        suite_config.load_app_state(state)
        assert state.dir_path.get() == ""
        assert state.palette_var.get() == "Purple"
        assert state.font_family_var.get() == "Arial"

    def test_load_corrupt_json_uses_defaults(self, state, cfg_path):
        cfg_path.write_text("{ this is not json }")
        suite_config.load_app_state(state)
        assert state.dir_path.get() == ""
        assert state.palette_var.get() == "Purple"

    def test_load_partial_json_only_updates_present_keys(self, state, cfg_path):
        cfg_path.write_text(json.dumps({"last_directory": "/rock"}))
        suite_config.load_app_state(state)
        assert state.palette_var.get() == "Purple"
        assert state.dir_path.get() == "/rock"

    def test_load_ignores_unknown_keys(self, state, cfg_path):
        cfg_path.write_text(
            json.dumps({"last_directory": "/x", "unknown_key": "value"})
        )
        suite_config.load_app_state(state)
        assert state.dir_path.get() == "/x"

    def test_load_font_size_only_updates_present_keys(self, state, cfg_path):
        cfg_path.write_text(json.dumps({"font_sizes": {"Header": 24}}))
        suite_config.load_app_state(state)
        assert state.font_sizes_vars["Header"].get() == 24
        assert state.font_sizes_vars["Body"].get() == 9


# ===========================================================================
# suite_config.save_app_state
# ===========================================================================


class TestSuiteConfigSave:
    def test_save_writes_last_directory(self, state, cfg_path):
        state.dir_path.set("/my/music")
        suite_config.save_app_state(state)
        data = json.loads(cfg_path.read_text())
        assert data["last_directory"] == "/my/music"

    def test_save_creates_file_if_missing(self, state, cfg_path):
        assert not cfg_path.exists()
        state.dir_path.set("/new/path")
        suite_config.save_app_state(state)
        assert cfg_path.exists()

    def test_save_preserves_unknown_keys(self, state, cfg_path):
        cfg_path.write_text(
            json.dumps({"custom_tool_window": "1024x768+0+0", "api_key": "secret123"})
        )
        state.dir_path.set("/new")
        state.palette_var.set("Green")
        suite_config.save_app_state(state)
        data = json.loads(cfg_path.read_text())
        assert data["custom_tool_window"] == "1024x768+0+0"
        assert data["api_key"] == "secret123"
        assert data["last_directory"] == "/new"
        assert data["palette"] == "Green"

    def test_save_load_round_trip(self, state, cfg_path):
        state.dir_path.set("/round/trip")
        suite_config.save_app_state(state)
        state2 = AppState()
        suite_config.load_app_state(state2)
        assert state2.dir_path.get() == "/round/trip"

    def test_save_empty_dir_path(self, state, cfg_path):
        state.dir_path.set("")
        suite_config.save_app_state(state)
        data = json.loads(cfg_path.read_text())
        assert data["last_directory"] == ""


# ===========================================================================
# suite_config.save_palette
# ===========================================================================


class TestSuiteConfigSavePalette:
    def test_save_palette_writes_palette_key(self, cfg_path):
        suite_config.save_palette("Teal")
        data = json.loads(cfg_path.read_text())
        assert data["palette"] == "Teal"

    def test_save_palette_creates_file_if_missing(self, cfg_path):
        assert not cfg_path.exists()
        suite_config.save_palette("Red")
        assert cfg_path.exists()

    def test_save_palette_preserves_other_keys(self, cfg_path):
        cfg_path.write_text(json.dumps({"last_directory": "/keep/me"}))
        suite_config.save_palette("Blue")
        data = json.loads(cfg_path.read_text())
        assert data["last_directory"] == "/keep/me"
        assert data["palette"] == "Blue"

    def test_save_palette_overwrites_existing_palette(self, cfg_path):
        cfg_path.write_text(json.dumps({"palette": "Green"}))
        suite_config.save_palette("Orange")
        data = json.loads(cfg_path.read_text())
        assert data["palette"] == "Orange"

    def test_save_palette_round_trip_via_load(self, cfg_path, root):
        suite_config.save_palette("Purple")
        state = AppState()
        suite_config.load_app_state(state)
        assert state.palette_var.get() == "Purple"


# ===========================================================================
# suite_config — cross-operation consistency
# ===========================================================================


class TestSuiteConfigCrossOp:
    def test_multiple_saves_do_not_corrupt_file(self, state, cfg_path):
        for path in ["/a", "/b", "/c"]:
            state.dir_path.set(path)
            suite_config.save_app_state(state)
        data = json.loads(cfg_path.read_text())
        assert data["last_directory"] == "/c"

    def test_save_then_palette_then_load_all_present(self, state, cfg_path):
        state.dir_path.set("/combo")
        suite_config.save_app_state(state)
        suite_config.save_palette("Crimson")

        state2 = AppState()
        suite_config.load_app_state(state2)
        assert state2.dir_path.get() == "/combo"
        assert state2.palette_var.get() == "Crimson"

    def test_load_does_not_raise_on_empty_json_object(self, state, cfg_path):
        cfg_path.write_text("{}")
        suite_config.load_app_state(state)
        assert state.dir_path.get() == ""

    def test_save_app_state_preserves_unknown_keys(self, state, cfg_path):
        cfg_path.write_text(
            json.dumps({"custom_tool_window": "1024x768+0+0", "api_key": "secret123"})
        )
        state.dir_path.set("/preserve")
        state.palette_var.set("Red")
        suite_config.save_app_state(state)
        data = json.loads(cfg_path.read_text())
        assert data["custom_tool_window"] == "1024x768+0+0"
        assert data["api_key"] == "secret123"
        assert data["last_directory"] == "/preserve"
        assert data["palette"] == "Red"
