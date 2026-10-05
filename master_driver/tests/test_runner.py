"""
Tests for master_driver.runner.arg_builder (G-37)
         master_driver.runner.module_runner (G-37)

Strategy — real tkinter, shared session root (see conftest.py)
-------------------------------------------------------------------------------
conftest.py creates one hidden Tk() root for the whole pytest session before
any test module is collected. Most tests here use _make_state(), a hand-built
fake AppState whose fields are plain MagicMock objects (not real tk Vars) and
so don't need a Tk root at all. The one exception is
build_refinery_args' internal tk.BooleanVar(value=True) call (see
TestBuildRefineryArgs.test_toggle_always_truthy below) — that now constructs
a genuine tkinter BooleanVar, which works normally because the shared root
already exists.
"""

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from audio_suite_shared.tool_plugin import ToolManifest
from master_driver.runner.arg_builder import (
    REFINERY_STAGES,
    build_enrich_args,
    build_refinery_args,
    build_utility_args,
)
from master_driver.runner.module_runner import (
    _clear_logs,
    _emit_progress,
    _launch_standalone,
    _suite_root,
    run_modules,
)

# ── AppState builder ──────────────────────────────────────────────────────────


def _bool_var(value: bool) -> MagicMock:
    m = MagicMock()
    m.get.return_value = value
    return m


def _str_var(value: str) -> MagicMock:
    m = MagicMock()
    m.get.return_value = value
    return m


def _make_state(
    dir_path="/music",
    global_mode="Dry Run",
    auto_start=False,
    auto_end=False,
    util_global_mode="Dry Run",
    util_auto_start=False,
    util_auto_end=False,
):
    state = MagicMock()
    state.dir_path = _str_var(dir_path)
    state.global_mode = _str_var(global_mode)
    state.auto_start = _bool_var(auto_start)
    state.auto_end = _bool_var(auto_end)
    state.util_global_mode = _str_var(util_global_mode)
    state.util_auto_start = _bool_var(util_auto_start)
    state.util_auto_end = _bool_var(util_auto_end)

    # Driver-only orchestration options (mirrored to children as display
    # flags; never executed by the children themselves).
    state.clear_logs_var = _bool_var(False)
    state.parallel_var = _bool_var(False)
    state.util_clear_logs_var = _bool_var(False)

    # Module toggles (enrich + utility tools)
    for key in (
        "scrubber",
        "fingerprinter",
        "replaygain",
        "album_genre",
        "genre_sync",
        "bpm",
        "tempo",
        "key",
        "mood_analyzer",
        "art",
        "converter",
        "asx_extractor",
        "cd_ripper",
        "library_stats",
        "audio_enhancer",
        "audio_normalizer",
        "pop_click_remover",
        "silence_trimmer",
        "tag_editor",
    ):
        state.module_toggles[key] = _bool_var(True)

    state.converter_toggle = _bool_var(True)
    state.asx_extractor_toggle = _bool_var(True)
    state.cd_ripper_toggle = _bool_var(False)

    # Enrich params
    state.scrubber_preserve_lyrics = _bool_var(False)
    state.scrubber_preserve_album_artist = _bool_var(True)
    state.scrubber_preserve_embedded_art = _bool_var(True)
    state.rg_lufs = _str_var("-16.0")
    state.album_genre_coverage = _str_var("50")
    state.bpm_range_min = _str_var("40")
    state.bpm_range_max = _str_var("220")
    state.bpm_duration = _str_var("30")
    state.tempo_scheme = _str_var("Italian")
    state.key_duration = _str_var("30")
    state.art_res = _str_var("1000")
    state.art_purge = _bool_var(False)
    state.lyrics_provider = _str_var("lrclib")
    state.lyrics_request_timeout = _str_var("10.0")
    state.lyrics_skip_existing = _bool_var(True)
    state.lyrics_plain_fallback = _bool_var(True)
    state.lyrics_parallel = _bool_var(False)
    state.lyrics_workers = _str_var("4")

    # Utility params
    state.converter_output_format = _str_var("mp3")
    state.converter_quality = _str_var("highest")
    state.converter_delete_originals = _bool_var(False)
    state.converter_output_dir = _str_var("")
    state.converter_sample_rate = _str_var("source")
    state.converter_bit_depth = _str_var("auto")
    state.converter_normalize_mp3 = _bool_var(False)
    state.converter_target_lufs = _str_var("-16.0")
    state.art_normalizer_size = _str_var("800")
    state.library_stats_incremental = _str_var("full")
    state.library_stats_refresh = _bool_var(False)
    state.library_stats_export_csv = _str_var("")
    state.library_stats_export_json = _str_var("")
    state.library_stats_completeness = _bool_var(False)
    state.library_stats_detail = _str_var("")
    state.file_reorg_output_dir = _str_var("")
    state.file_reorg_action = _str_var("copy")
    state.file_reorg_specific_pattern = _str_var("")
    state.file_reorg_various_pattern = _str_var("")
    state.cd_ripper_output_dir = _str_var("")
    state.cd_ripper_format = _str_var("flac")
    state.cd_ripper_tracks = _str_var("")
    state.cd_ripper_cue = _bool_var(False)
    state.enhancer_output_dir = _str_var("")
    state.enhancer_preset = _str_var("Moderate")
    state.normalizer_target_lufs = _str_var("-14.0")
    state.normalizer_tolerance = _str_var("0.5")
    state.normalizer_mode = _str_var("normalise")
    state.declick_sensitivity = _str_var("0.25")
    state.declick_max_width = _str_var("5")
    state.trimmer_threshold = _str_var("-50")
    state.trimmer_apply_fade = _bool_var(False)
    state.trimmer_fade_in_ms = _str_var("500")
    state.trimmer_fade_out_ms = _str_var("1000")

    # Enrich params (noise reduction + fingerprinter)
    state.nr_reduce_hum = _bool_var(False)
    state.nr_reduce_broadband = _bool_var(False)
    state.nr_hum_frequency = _str_var("60")
    state.nr_hum_harmonics = _str_var("8")
    state.nr_hum_quality = _str_var("30.0")
    state.nr_noise_start = _str_var("0")
    state.nr_noise_end = _str_var("500")
    state.nr_gate_threshold = _str_var("3.0")
    state.fingerprinter_lookup = _bool_var(True)
    state.fingerprinter_write_tags = _bool_var(False)
    state.fingerprinter_write_mbids = _bool_var(False)
    state.fingerprinter_mbid_region = _str_var("")
    state.fingerprinter_threshold = _str_var("0.5")
    state.fingerprinter_max_length = _str_var("120")
    state.fingerprinter_fpcalc = _str_var("")
    state.fingerprinter_api_key = _str_var("")

    # Refinery params
    state.refinery_source = _str_var("/music")
    state.refinery_output = _str_var("")
    state.refinery_auto_start = _bool_var(False)
    state.refinery_auto_end = _bool_var(False)

    return state


def _make_refinery_config():
    config = MagicMock()
    config.declick = True
    config.trim = True
    config.enhance = True
    config.normalise = True
    config.reduce_noise = False
    config.enhance_params.preset = "Standard"
    config.declick_params.sensitivity = 0.5
    config.declick_params.max_width_ms = 2
    config.trim_params.threshold = -50.0
    config.trim_params.apply_fade = False
    config.trim_params.fade_in_ms = 500
    config.trim_params.fade_out_ms = 1000
    config.normalise_params.target_lufs = -16.0
    config.normalise_params.tolerance = 1.0
    config.noise_reduction_params.reduce_hum = False
    config.noise_reduction_params.reduce_broadband = False
    config.noise_reduction_params.hum_frequency = 60
    config.noise_reduction_params.hum_harmonics = 8
    config.noise_reduction_params.hum_quality = 30.0
    config.noise_reduction_params.noise_start_ms = 0
    config.noise_reduction_params.noise_end_ms = 500
    config.noise_reduction_params.gate_threshold_db = 3.0
    return config


def _make_manifest(tool_id: str = "bpm", standalone: bool = False) -> ToolManifest:
    """Build a minimal ToolManifest for module_runner tests."""
    return ToolManifest(
        id=tool_id,
        name=tool_id.title(),
        category="enrich",
        pyw_filename=f"{tool_id}.pyw",
        description="",
        standalone=standalone,
    )


def _manifest_from_script(script: Path) -> ToolManifest:
    """Build a ToolManifest whose pyw_filename is the script's full path.

    The tests create scripts in tmp_path (an absolute path), so
    pyw_filename must be absolute so run_modules resolves it correctly
    (it uses the path as-is when os.path.isabs is True).
    """
    return ToolManifest(
        id=script.stem,
        name=script.stem,
        category="",
        pyw_filename=str(script),
        description="",
    )


# ═════════════════════════════════════════════════════════════════════════════
# build_enrich_args
# ═════════════════════════════════════════════════════════════════════════════


class TestBuildEnrichArgs:
    def test_returns_list(self):
        state = _make_state()
        assert isinstance(build_enrich_args(state), list)

    def test_returns_eleven_entries(self):
        """One entry per enrich module."""
        state = _make_state()
        assert len(build_enrich_args(state)) == 11

    def test_each_entry_is_three_tuple(self):
        state = _make_state()
        for toggle, manifest, args in build_enrich_args(state):
            assert hasattr(toggle, "get")
            assert hasattr(manifest, "id")
            assert isinstance(args, list)

    def test_dry_flag_in_args_when_dry_run(self):
        state = _make_state(global_mode="Dry Run")
        for _, _, args in build_enrich_args(state):
            assert "--dry" in args

    def test_live_flag_in_args_when_live(self):
        state = _make_state(global_mode="Live Update")
        for _, _, args in build_enrich_args(state):
            assert "--live" in args

    def test_dir_path_in_args(self):
        state = _make_state(dir_path="/my/music")
        for _, _, args in build_enrich_args(state):
            assert "/my/music" in args

    def test_start_flag_when_auto_start(self):
        state = _make_state(auto_start=True)
        for _, _, args in build_enrich_args(state):
            assert "--start" in args

    def test_no_start_flag_when_auto_start_false(self):
        state = _make_state(auto_start=False)
        for _, _, args in build_enrich_args(state):
            assert "--no-start" in args

    def test_end_flag_when_auto_end(self):
        state = _make_state(auto_end=True)
        for _, _, args in build_enrich_args(state):
            assert "--end" in args

    def test_no_end_flag_when_auto_end_false(self):
        state = _make_state(auto_end=False)
        for _, _, args in build_enrich_args(state):
            assert "--no-end" in args

    def test_replaygain_uses_lufs_value(self):
        state = _make_state()
        state.rg_lufs = _str_var("-23.0")
        args_list = build_enrich_args(state)
        rg_entry = next(e for e in args_list if "ReplayGain" in e[1].name)
        assert "-23.0" in rg_entry[2]

    def test_bpm_includes_range(self):
        state = _make_state()
        state.bpm_range_min = _str_var("60")
        state.bpm_range_max = _str_var("180")
        args_list = build_enrich_args(state)
        bpm_entry = next(e for e in args_list if "BPM" in e[1].name)
        assert "--bpm-min" in bpm_entry[2]
        assert "60" in bpm_entry[2]
        assert "--bpm-max" in bpm_entry[2]
        assert "180" in bpm_entry[2]

    def test_lyrics_parallel_flag_toggle(self):
        state = _make_state()
        state.lyrics_parallel = _bool_var(True)
        args_list = build_enrich_args(state)
        lyrics_entry = next(e for e in args_list if "Lyrics" in e[1].name)
        assert "--parallel" in lyrics_entry[2]
        assert "--no-parallel" not in lyrics_entry[2]

    def test_tempo_includes_scheme(self):
        state = _make_state()
        state.tempo_scheme = _str_var("Dance")
        args_list = build_enrich_args(state)
        tempo_entry = next(e for e in args_list if "Tempo" in e[1].name)
        assert "--scheme" in tempo_entry[2]
        assert "Dance" in tempo_entry[2]

    def test_album_genre_includes_coverage(self):
        state = _make_state()
        state.album_genre_coverage = _str_var("75")
        args_list = build_enrich_args(state)
        ag_entry = next(e for e in args_list if "Album Genre" in e[1].name)
        assert "--coverage" in ag_entry[2]
        assert "75" in ag_entry[2]

    def test_lyrics_includes_all_tool_options(self):
        state = _make_state()
        state.lyrics_provider = _str_var("lrclib")
        state.lyrics_request_timeout = _str_var("15.0")
        state.lyrics_skip_existing = _bool_var(False)
        state.lyrics_plain_fallback = _bool_var(True)
        args_list = build_enrich_args(state)
        lyrics_entry = next(e for e in args_list if "Lyrics" in e[1].name)
        args = lyrics_entry[2]
        assert "--provider" in args
        assert "lrclib" in args
        assert "--request-timeout" in args
        assert "15.0" in args
        assert "--no-skip-existing" in args
        assert "--plain-fallback" in args
        assert "--no-parallel" in args
        assert "--workers" in args
        assert "4" in args
        assert args[:5] == ["/music", "0", "--dry", "--no-start", "--no-end"]

    def test_scrubber_preserve_lyrics_flag(self):
        state = _make_state()
        state.scrubber_preserve_lyrics = _bool_var(True)
        args_list = build_enrich_args(state)
        scrubber_entry = next(e for e in args_list if "Scrubber" in e[1].name)
        assert "--preserve-lyrics" in scrubber_entry[2]

    def test_scrubber_no_preserve_lyrics_flag(self):
        state = _make_state()
        state.scrubber_preserve_lyrics = _bool_var(False)
        args_list = build_enrich_args(state)
        scrubber_entry = next(e for e in args_list if "Scrubber" in e[1].name)
        assert "--no-preserve-lyrics" in scrubber_entry[2]

    def test_scrubber_preserve_album_artist_flag(self):
        state = _make_state()
        state.scrubber_preserve_album_artist = _bool_var(True)
        args_list = build_enrich_args(state)
        scrubber_entry = next(e for e in args_list if "Scrubber" in e[1].name)
        assert "--preserve-album-artist" in scrubber_entry[2]

    def test_scrubber_no_preserve_album_artist_flag(self):
        state = _make_state()
        state.scrubber_preserve_album_artist = _bool_var(False)
        args_list = build_enrich_args(state)
        scrubber_entry = next(e for e in args_list if "Scrubber" in e[1].name)
        assert "--no-preserve-album-artist" in scrubber_entry[2]

    def test_scrubber_preserve_embedded_art_flag(self):
        state = _make_state()
        state.scrubber_preserve_embedded_art = _bool_var(True)
        args_list = build_enrich_args(state)
        scrubber_entry = next(e for e in args_list if "Scrubber" in e[1].name)
        assert "--preserve-embedded-art" in scrubber_entry[2]

    def test_scrubber_no_preserve_embedded_art_flag(self):
        state = _make_state()
        state.scrubber_preserve_embedded_art = _bool_var(False)
        args_list = build_enrich_args(state)
        scrubber_entry = next(e for e in args_list if "Scrubber" in e[1].name)
        assert "--no-preserve-embedded-art" in scrubber_entry[2]

    def test_art_purge_flag(self):
        state = _make_state()
        state.art_purge = _bool_var(True)
        args_list = build_enrich_args(state)
        art_entry = next(e for e in args_list if "Art" in e[1].name)
        assert "--purge" in art_entry[2]

    def test_art_no_purge_flag(self):
        state = _make_state()
        state.art_purge = _bool_var(False)
        args_list = build_enrich_args(state)
        art_entry = next(e for e in args_list if "Art" in e[1].name)
        assert "--no-purge" in art_entry[2]

    def test_art_embed_size_uses_named_flag(self):
        """Resolution must be passed as --embed-size <value>, not as a
        bare positional."""
        state = _make_state()
        args_list = build_enrich_args(state)
        art_entry = next(e for e in args_list if "Art" in e[1].name)
        assert "--embed-size" in art_entry[2]

    def test_art_embed_size_value_follows_flag(self):
        """The resolution value must immediately follow the --embed-size flag."""
        state = _make_state()
        state.art_res = _str_var("1000")
        args_list = build_enrich_args(state)
        art_entry = next(e for e in args_list if "Art" in e[1].name)
        args = art_entry[2]
        idx = args.index("--embed-size")
        assert args[idx + 1] == "1000"

    def test_art_no_positional_placeholder_in_args(self):
        """The legacy '0' placeholder must not appear in the art argument list."""
        state = _make_state()
        args_list = build_enrich_args(state)
        art_entry = next(e for e in args_list if "Art" in e[1].name)
        assert "0" not in art_entry[2]

    def test_fingerprinter_lookup_flag(self):
        state = _make_state()
        state.fingerprinter_lookup = _bool_var(True)
        args_list = build_enrich_args(state)
        fp_entry = next(e for e in args_list if "Audio Fingerprinter" in e[1].name)
        assert "--lookup" in fp_entry[2]

    def test_fingerprinter_no_lookup_flag(self):
        state = _make_state()
        state.fingerprinter_lookup = _bool_var(False)
        args_list = build_enrich_args(state)
        fp_entry = next(e for e in args_list if "Audio Fingerprinter" in e[1].name)
        assert "--no-lookup" in fp_entry[2]

    def test_fingerprinter_write_tags_flag(self):
        state = _make_state()
        state.fingerprinter_write_tags = _bool_var(True)
        args_list = build_enrich_args(state)
        fp_entry = next(e for e in args_list if "Audio Fingerprinter" in e[1].name)
        assert "--write-tags" in fp_entry[2]

    def test_fingerprinter_write_mbids_flag(self):
        state = _make_state()
        state.fingerprinter_write_mbids = _bool_var(True)
        args_list = build_enrich_args(state)
        fp_entry = next(e for e in args_list if "Audio Fingerprinter" in e[1].name)
        assert "--write-mbids" in fp_entry[2]
        assert "--no-write-mbids" not in fp_entry[2]

    def test_fingerprinter_no_write_mbids_flag(self):
        state = _make_state()
        state.fingerprinter_write_mbids = _bool_var(False)
        args_list = build_enrich_args(state)
        fp_entry = next(e for e in args_list if "Audio Fingerprinter" in e[1].name)
        assert "--no-write-mbids" in fp_entry[2]

    def test_fingerprinter_mbid_region_flag_when_set(self):
        state = _make_state()
        state.fingerprinter_mbid_region = _str_var("GB")
        args_list = build_enrich_args(state)
        fp_entry = next(e for e in args_list if "Audio Fingerprinter" in e[1].name)
        args = fp_entry[2]
        assert "--mbid-region" in args
        assert "GB" == args[args.index("--mbid-region") + 1]

    def test_fingerprinter_params_in_args(self):
        state = _make_state()
        state.fingerprinter_threshold = _str_var("0.75")
        state.fingerprinter_max_length = _str_var("90")
        args_list = build_enrich_args(state)
        fp_entry = next(e for e in args_list if "Audio Fingerprinter" in e[1].name)
        args = fp_entry[2]
        assert "0.75" == args[args.index("--threshold") + 1]
        assert "90" == args[args.index("--max-length") + 1]

    def test_fingerprinter_omits_optional_when_empty(self):
        state = _make_state()
        args_list = build_enrich_args(state)
        fp_entry = next(e for e in args_list if "Audio Fingerprinter" in e[1].name)
        assert "--fpcalc" not in fp_entry[2]
        assert "--api-key" not in fp_entry[2]

    def test_fingerprinter_optional_flags_when_set(self):
        state = _make_state()
        state.fingerprinter_fpcalc = _str_var("/opt/bin/fpcalc")
        state.fingerprinter_api_key = _str_var("test-key")
        args_list = build_enrich_args(state)
        fp_entry = next(e for e in args_list if "Audio Fingerprinter" in e[1].name)
        assert "--fpcalc" in fp_entry[2]
        assert "/opt/bin/fpcalc" in fp_entry[2]
        assert "--api-key" in fp_entry[2]
        assert "test-key" in fp_entry[2]


# ═════════════════════════════════════════════════════════════════════════════
# build_utility_args
# ═════════════════════════════════════════════════════════════════════════════


class TestBuildUtilityArgs:
    def test_returns_list(self):
        state = _make_state()
        assert isinstance(build_utility_args(state), list)

    def test_returns_six_entries(self):
        state = _make_state()
        from audio_suite_shared.tool_plugin import get_registry

        expected = len(get_registry().by_category("utility"))
        assert len(build_utility_args(state)) == expected

    def test_converter_entry_present(self):
        state = _make_state()
        manifests = [e[1] for e in build_utility_args(state)]
        assert any(m.pyw_filename == "Music_Format_Converter.pyw" for m in manifests)

    def test_asx_entry_present(self):
        state = _make_state()
        manifests = [e[1] for e in build_utility_args(state)]
        assert any(m.pyw_filename == "ASX_Playlist_Extractor.pyw" for m in manifests)

    def test_converter_dry_mode_flag(self):
        state = _make_state(util_global_mode="Dry Run")
        args_list = build_utility_args(state)
        conv_entry = next(e for e in args_list if "Converter" in e[1].name)
        assert "--dry" in conv_entry[2]

    def test_converter_live_mode_flag(self):
        state = _make_state(util_global_mode="Live Update")
        args_list = build_utility_args(state)
        conv_entry = next(e for e in args_list if "Converter" in e[1].name)
        assert "--live" in conv_entry[2]

    def test_converter_output_format_in_args(self):
        state = _make_state()
        state.converter_output_format = _str_var("flac")
        args_list = build_utility_args(state)
        conv_entry = next(e for e in args_list if "Converter" in e[1].name)
        assert "flac" in conv_entry[2]

    def test_converter_quality_in_args(self):
        state = _make_state()
        state.converter_quality = _str_var("medium")
        args_list = build_utility_args(state)
        conv_entry = next(e for e in args_list if "Converter" in e[1].name)
        assert "medium" in conv_entry[2]

    def test_converter_delete_originals_flag(self):
        state = _make_state()
        state.converter_delete_originals = _bool_var(True)
        args_list = build_utility_args(state)
        conv_entry = next(e for e in args_list if "Converter" in e[1].name)
        assert "--delete-originals" in conv_entry[2]

    def test_converter_output_dir_in_args_when_set(self):
        state = _make_state()
        state.converter_output_dir = _str_var("/output/dir")
        args_list = build_utility_args(state)
        conv_entry = next(e for e in args_list if "Converter" in e[1].name)
        assert "--output-dir" in conv_entry[2]
        assert "/output/dir" in conv_entry[2]

    def test_converter_no_output_dir_when_empty(self):
        state = _make_state()
        state.converter_output_dir = _str_var("")
        args_list = build_utility_args(state)
        conv_entry = next(e for e in args_list if "Converter" in e[1].name)
        assert "--output-dir" not in conv_entry[2]

    def test_asx_live_mode_uses_execute_label(self):
        state = _make_state(util_global_mode="Live Update")
        args_list = build_utility_args(state)
        asx_entry = next(e for e in args_list if "ASX" in e[1].name)
        assert "Execute Extraction" in " ".join(asx_entry[2])

    def test_asx_dry_mode_uses_dry_run_label(self):
        state = _make_state(util_global_mode="Dry Run")
        args_list = build_utility_args(state)
        asx_entry = next(e for e in args_list if "ASX" in e[1].name)
        assert "Dry Run" in " ".join(asx_entry[2])

    def test_converter_sample_rate_flag_when_not_source(self):
        state = _make_state()
        state.converter_sample_rate = _str_var("48000")
        args_list = build_utility_args(state)
        conv_entry = next(e for e in args_list if "Converter" in e[1].name)
        assert "--sample-rate" in conv_entry[2]

    def test_converter_no_sample_rate_flag_when_source(self):
        state = _make_state()
        args_list = build_utility_args(state)
        conv_entry = next(e for e in args_list if "Converter" in e[1].name)
        assert "--sample-rate" not in conv_entry[2]

    def test_converter_bit_depth_flag_when_not_auto(self):
        state = _make_state()
        state.converter_bit_depth = _str_var("24")
        args_list = build_utility_args(state)
        conv_entry = next(e for e in args_list if "Converter" in e[1].name)
        assert "--bit-depth" in conv_entry[2]

    def test_converter_no_bit_depth_flag_when_auto(self):
        state = _make_state()
        args_list = build_utility_args(state)
        conv_entry = next(e for e in args_list if "Converter" in e[1].name)
        assert "--bit-depth" not in conv_entry[2]

    def test_converter_normalize_mp3_flag(self):
        state = _make_state()
        state.converter_normalize_mp3 = _bool_var(True)
        args_list = build_utility_args(state)
        conv_entry = next(e for e in args_list if "Converter" in e[1].name)
        assert "--normalize-mp3" in conv_entry[2]

    def test_converter_target_lufs_in_args(self):
        state = _make_state()
        state.converter_target_lufs = _str_var("-14.0")
        args_list = build_utility_args(state)
        conv_entry = next(e for e in args_list if "Converter" in e[1].name)
        assert "--target-lufs" in conv_entry[2]
        assert "-14.0" == conv_entry[2][conv_entry[2].index("--target-lufs") + 1]

    def test_art_normalizer_size_in_args(self):
        state = _make_state()
        state.art_normalizer_size = _str_var("1000")
        args_list = build_utility_args(state)
        art_entry = next(e for e in args_list if "Album Art Normalizer" in e[1].name)
        args = art_entry[2]
        assert "--size" in args
        assert "1000" == args[args.index("--size") + 1]

    def test_cd_ripper_format_in_args(self):
        state = _make_state()
        args_list = build_utility_args(state)
        rip_entry = next(e for e in args_list if "CD Ripper" in e[1].name)
        assert "--format" in rip_entry[2]

    def test_cd_ripper_tracks_when_set(self):
        state = _make_state()
        state.cd_ripper_tracks = _str_var("1,3,5")
        args_list = build_utility_args(state)
        rip_entry = next(e for e in args_list if "CD Ripper" in e[1].name)
        assert "--tracks" in rip_entry[2]

    def test_cd_ripper_cue_flag(self):
        state = _make_state()
        state.cd_ripper_cue = _bool_var(True)
        args_list = build_utility_args(state)
        rip_entry = next(e for e in args_list if "CD Ripper" in e[1].name)
        assert "--cue" in rip_entry[2]

    def test_library_stats_incremental_when_selected(self):
        state = _make_state()
        state.library_stats_incremental = _str_var("incremental")
        args_list = build_utility_args(state)
        stats_entry = next(e for e in args_list if "Library Statistics" in e[1].name)
        assert "--incremental" in stats_entry[2]

    def test_library_stats_no_incremental_when_full(self):
        state = _make_state()
        args_list = build_utility_args(state)
        stats_entry = next(e for e in args_list if "Library Statistics" in e[1].name)
        assert "--incremental" not in stats_entry[2]

    def test_library_stats_refresh_flag(self):
        state = _make_state()
        state.library_stats_refresh = _bool_var(True)
        args_list = build_utility_args(state)
        stats_entry = next(e for e in args_list if "Library Statistics" in e[1].name)
        assert "--refresh" in stats_entry[2]

    def test_library_stats_completeness_flag(self):
        state = _make_state()
        state.library_stats_completeness = _bool_var(True)
        args_list = build_utility_args(state)
        stats_entry = next(e for e in args_list if "Library Statistics" in e[1].name)
        assert "--completeness" in stats_entry[2]

    def test_library_stats_detail_when_set(self):
        state = _make_state()
        state.library_stats_detail = _str_var("genre")
        args_list = build_utility_args(state)
        stats_entry = next(e for e in args_list if "Library Statistics" in e[1].name)
        assert "--detail" in stats_entry[2]

    def test_library_stats_exports_when_set(self):
        state = _make_state()
        state.library_stats_export_csv = _str_var("/tmp/stats.csv")
        state.library_stats_export_json = _str_var("/tmp/stats.json")
        args_list = build_utility_args(state)
        stats_entry = next(e for e in args_list if "Library Statistics" in e[1].name)
        assert "--export-csv" in stats_entry[2]
        assert "--export-json" in stats_entry[2]

    def test_file_reorganizer_action_in_args(self):
        state = _make_state()
        state.file_reorg_action = _str_var("move")
        args_list = build_utility_args(state)
        reorg_entry = next(e for e in args_list if "File Reorganizer" in e[1].name)
        assert "--action" in reorg_entry[2]

    def test_file_reorganizer_patterns_when_set(self):
        state = _make_state()
        state.file_reorg_specific_pattern = _str_var("{Artist}/{Album}")
        state.file_reorg_various_pattern = _str_var("VA/{Album}")
        args_list = build_utility_args(state)
        reorg_entry = next(e for e in args_list if "File Reorganizer" in e[1].name)
        assert "--specific-pattern" in reorg_entry[2]
        assert "--various-pattern" in reorg_entry[2]

    def test_noise_reduction_reduce_hum_flags(self):
        state = _make_state()
        state.nr_reduce_hum = _bool_var(True)
        state.nr_hum_frequency = _str_var("50")
        state.nr_hum_harmonics = _str_var("4")
        args_list = build_utility_args(state)
        nr_entry = next(e for e in args_list if "Noise Reduction" in e[1].name)
        args = nr_entry[2]
        assert "--reduce-hum" in args
        assert "50" == args[args.index("--hum-frequency") + 1]
        assert "4" == args[args.index("--hum-harmonics") + 1]

    def test_noise_reduction_reduce_broadband_flags(self):
        state = _make_state()
        state.nr_reduce_broadband = _bool_var(True)
        state.nr_noise_start = _str_var("100")
        args_list = build_utility_args(state)
        nr_entry = next(e for e in args_list if "Noise Reduction" in e[1].name)
        args = nr_entry[2]
        assert "--reduce-broadband" in args
        assert "100" == args[args.index("--noise-start") + 1]

    def test_noise_reduction_no_flags_when_off(self):
        state = _make_state()
        args_list = build_utility_args(state)
        nr_entry = next(e for e in args_list if "Noise Reduction" in e[1].name)
        assert "--reduce-hum" not in nr_entry[2]
        assert "--reduce-broadband" not in nr_entry[2]

    def test_tag_field_updater_entry_present(self):
        state = _make_state()
        args_list = build_utility_args(state)
        assert any("Tag Field Updater" in e[1].name for e in args_list)

    def test_tag_editor_entry_present(self):
        state = _make_state()
        args_list = build_utility_args(state)
        entry = next(e for e in args_list if e[1].id == "tag_editor")
        assert entry[2][:2] == ["/music", "--dry"]
        assert entry[2][-2:] == ["--no-clear-logs", "--no-parallel-run"]

    def test_enhancer_returns_empty_args_without_output_dir(self):
        state = _make_state()
        state.enhancer_output_dir = _str_var("")
        args_list = build_utility_args(state)
        enh_entry = next(e for e in args_list if "Audio Enhancer" in e[1].name)
        assert enh_entry[2] == []

    def test_enhancer_emits_source_output_preset(self):
        state = _make_state()
        state.enhancer_output_dir = _str_var("/out/enhanced")
        state.enhancer_preset = _str_var("Mild")
        args_list = build_utility_args(state)
        enh_entry = next(e for e in args_list if "Audio Enhancer" in e[1].name)
        args = enh_entry[2]
        assert "--source" in args
        assert "/music" == args[args.index("--source") + 1]
        assert "--output" in args
        assert "/out/enhanced" == args[args.index("--output") + 1]
        assert "--preset" in args
        assert "Mild" == args[args.index("--preset") + 1]

    def test_enhancer_skips_driver_display_flags(self):
        """The enhancer GUI uses strict parse_args — display handshake
        flags would fatal at launch, so they must never be emitted."""
        state = _make_state()
        state.enhancer_output_dir = _str_var("/out/enhanced")
        state.util_clear_logs_var = _bool_var(True)
        state.parallel_var = _bool_var(True)
        args_list = build_utility_args(state)
        enh_entry = next(e for e in args_list if "Audio Enhancer" in e[1].name)
        assert "--clear-logs" not in enh_entry[2]
        assert "--parallel-run" not in enh_entry[2]

    def test_enhancer_auto_flags_when_set(self):
        state = _make_state(util_auto_start=True)
        state.util_auto_end = _bool_var(True)
        state.enhancer_output_dir = _str_var("/out/enhanced")
        args_list = build_utility_args(state)
        enh_entry = next(e for e in args_list if "Audio Enhancer" in e[1].name)
        assert "--auto-start" in enh_entry[2]
        assert "--auto-end" in enh_entry[2]

    def test_normalizer_args_shape(self):
        state = _make_state()
        args_list = build_utility_args(state)
        norm_entry = next(e for e in args_list if "Audio Normalizer" in e[1].name)
        args = norm_entry[2]
        assert args[0] == "/music"
        assert args[1] == "-14.0"
        assert args[args.index("--tolerance") + 1] == "0.5"
        assert args[args.index("--mode") + 1] == "normalise"

    def test_normalizer_target_lufs_and_mode_from_state(self):
        state = _make_state()
        state.normalizer_target_lufs = _str_var("-23.0")
        state.normalizer_mode = _str_var("lossless")
        args_list = build_utility_args(state)
        norm_entry = next(e for e in args_list if "Audio Normalizer" in e[1].name)
        args = norm_entry[2]
        assert args[1] == "-23.0"
        assert "lossless" == args[args.index("--mode") + 1]

    def test_pop_click_args_use_width_not_max_width(self):
        """The GUI parser's grass width flag is --width (the click CLI's
        --max-width would be silently discarded)."""
        state = _make_state()
        state.declick_sensitivity = _str_var("0.15")
        state.declick_max_width = _str_var("3")
        args_list = build_utility_args(state)
        pc_entry = next(e for e in args_list if "Pop & Click" in e[1].name)
        args = pc_entry[2]
        assert "--sensitivity" in args
        assert "0.15" == args[args.index("--sensitivity") + 1]
        assert "--width" in args
        assert "3" == args[args.index("--width") + 1]
        assert "--max-width" not in args

    def test_silence_trimmer_threshold_in_args(self):
        state = _make_state()
        args_list = build_utility_args(state)
        trim_entry = next(e for e in args_list if "Silence Trimmer" in e[1].name)
        args = trim_entry[2]
        assert "--threshold" in args
        assert "-50" == args[args.index("--threshold") + 1]

    def test_silence_trimmer_fade_flags_only_when_enabled(self):
        state = _make_state()
        state.trimmer_apply_fade = _bool_var(True)
        state.trimmer_fade_in_ms = _str_var("800")
        state.trimmer_fade_out_ms = _str_var("2000")
        args_list = build_utility_args(state)
        trim_entry = next(e for e in args_list if "Silence Trimmer" in e[1].name)
        args = trim_entry[2]
        assert "--fade" in args
        assert "800" == args[args.index("--fade-in") + 1]
        assert "2000" == args[args.index("--fade-out") + 1]

    def test_silence_trimmer_no_fade_when_disabled(self):
        state = _make_state()
        args_list = build_utility_args(state)
        trim_entry = next(e for e in args_list if "Silence Trimmer" in e[1].name)
        assert "--fade" not in trim_entry[2]
        assert "--fade-in" not in trim_entry[2]


# ═════════════════════════════════════════════════════════════════════════════
# build_refinery_args
# ═════════════════════════════════════════════════════════════════════════════


class TestBuildRefineryArgs:
    def test_returns_single_entry_list(self):
        state = _make_state()
        config = _make_refinery_config()
        result = build_refinery_args(state, config)
        assert isinstance(result, list) and len(result) == 1

    def test_filename_is_audio_refinery_manifest(self):
        state = _make_state()
        _, manifest, _ = build_refinery_args(state, _make_refinery_config())[0]
        assert manifest.id == "audio_refinery"
        assert manifest.pyw_filename == "Audio_Refinery.pyw"

    def test_toggle_always_truthy(self, root):
        """The refinery toggle is always enabled (BooleanVar(value=True)).
        This constructs a genuine tkinter BooleanVar against the shared
        session root (see conftest.py), so get() returns real bool True."""
        state = _make_state()
        toggle, _, _ = build_refinery_args(state, _make_refinery_config())[0]
        assert toggle.get()  # truthy — always enabled

    def test_source_in_args(self):
        state = _make_state()
        state.refinery_source = _str_var("/source/music")
        _, _, args = build_refinery_args(state, _make_refinery_config())[0]
        assert "--source" in args
        assert "/source/music" in args

    def test_stages_in_args(self):
        state = _make_state()
        _, _, args = build_refinery_args(state, _make_refinery_config())[0]
        assert "--stages" in args

    def test_all_stages_when_all_enabled(self):
        state = _make_state()
        config = _make_refinery_config()
        _, _, args = build_refinery_args(state, config)[0]
        stage_idx = args.index("--stages")
        stages_str = args[stage_idx + 1]
        for stage in ("declick", "trim", "enhance", "normalise"):
            assert stage in stages_str

    def test_disabled_stages_excluded(self):
        state = _make_state()
        config = _make_refinery_config()
        config.enhance = False
        config.normalise = False
        _, _, args = build_refinery_args(state, config)[0]
        stage_idx = args.index("--stages")
        stages_str = args[stage_idx + 1]
        assert "enhance" not in stages_str
        assert "normalise" not in stages_str

    def test_reduce_noise_included_when_enabled(self):
        state = _make_state()
        config = _make_refinery_config()
        config.reduce_noise = True
        _, _, args = build_refinery_args(state, config)[0]
        stage_idx = args.index("--stages")
        stages_str = args[stage_idx + 1]
        assert "reduce_noise" in stages_str

    def test_reduce_noise_excluded_by_default(self):
        state = _make_state()
        _, _, args = build_refinery_args(state, _make_refinery_config())[0]
        stage_idx = args.index("--stages")
        stages_str = args[stage_idx + 1]
        assert "reduce_noise" not in stages_str

    def test_noise_reduction_flags_in_args(self):
        state = _make_state()
        config = _make_refinery_config()
        config.noise_reduction_params.reduce_hum = True
        config.noise_reduction_params.reduce_broadband = True
        config.noise_reduction_params.hum_frequency = 50
        config.noise_reduction_params.hum_harmonics = 4
        config.noise_reduction_params.hum_quality = 45.0
        config.noise_reduction_params.noise_start_ms = 100
        config.noise_reduction_params.noise_end_ms = 900
        config.noise_reduction_params.gate_threshold_db = 6.0
        _, _, args = build_refinery_args(state, config)[0]
        assert "--reduce-hum" in args
        assert "--reduce-broadband" in args
        assert "50" in args[args.index("--hum-frequency") + 1]
        assert "4" in args[args.index("--hum-harmonics") + 1]
        assert "45.0" in args[args.index("--hum-quality") + 1]
        assert "100" in args[args.index("--noise-start") + 1]
        assert "900" in args[args.index("--noise-end") + 1]
        assert "6.0" in args[args.index("--gate-threshold") + 1]

    def test_noise_reduction_off_by_default_no_flags(self):
        state = _make_state()
        _, _, args = build_refinery_args(state, _make_refinery_config())[0]
        assert "--reduce-hum" not in args
        assert "--reduce-broadband" not in args

    def test_all_toggles_off_emits_empty_stages(self):
        """All five stage toggles off => ``--stages`` is empty (M13).

        Positive contract replacing ``test_all_stages_default_when_none_enabled``,
        which asserted the silent fallback and so pinned the defect: a user
        who turned every stage off had the full default chain silently
        re-enabled. ``launch_refinery`` blocks an all-off run before the args
        are built, so the child never receives the empty list from the driver.
        """
        state = _make_state()
        config = _make_refinery_config()
        config.declick = config.trim = config.enhance = config.normalise = False
        config.reduce_noise = False
        _, _, args = build_refinery_args(state, config)[0]
        stage_idx = args.index("--stages")
        assert args[stage_idx + 1] == ""

    def test_refinery_stage_source_matches_stage_config_toggles(self):
        """``REFINERY_STAGES`` is the single stage list (M12a drift guard).

        Every entry pairs a real boolean ``StageConfig`` field with the
        ``--stages`` name the audio_refinery CLI recognises (field == name),
        and the set covers all five stages — ``reduce_noise`` is the one the
        Refine tab's select-all missed before the fix.
        """
        from audio_refinery.core.models import StageConfig

        cfg = StageConfig()
        for field, name in REFINERY_STAGES:
            assert field == name, (field, name)
            assert isinstance(getattr(cfg, field, None), bool)
        assert {name for _, name in REFINERY_STAGES} == {
            "declick",
            "trim",
            "enhance",
            "normalise",
            "reduce_noise",
        }

    def test_refinery_clear_logs_flag_follows_refine_tab_var(self):
        """The clear-logs flag tracks the Refine tab's binding (M12b).

        Pre-fix the flag read ``util_clear_logs_var``, so the child's inert
        Run Controls panel displayed the *Utility* tab's Clear Logs state.
        """
        state = _make_state()
        state.clear_logs_var = _bool_var(True)
        state.util_clear_logs_var = _bool_var(False)
        _, _, args = build_refinery_args(state, _make_refinery_config())[0]
        assert "--clear-logs" in args
        assert "--no-clear-logs" not in args

        state = _make_state()
        state.clear_logs_var = _bool_var(False)
        state.util_clear_logs_var = _bool_var(True)
        _, _, args = build_refinery_args(state, _make_refinery_config())[0]
        assert "--no-clear-logs" in args
        assert "--clear-logs" not in args

    def test_refinery_args_never_emit_parallel_display_flags(self):
        """No parallel display flag is emitted for Refinery (C5 decision).

        The Refine tab hides its Parallel checkbox, so emitting a state the
        user cannot see or change is dishonest in both directions; the child
        keeps its own default.
        """
        for parallel in (False, True):
            state = _make_state()
            state.parallel_var = _bool_var(parallel)
            _, _, args = build_refinery_args(state, _make_refinery_config())[0]
            assert "--parallel-run" not in args, args
            assert "--no-parallel-run" not in args, args

    def test_target_lufs_in_args(self):
        state = _make_state()
        config = _make_refinery_config()
        config.normalise_params.target_lufs = -23.0
        _, _, args = build_refinery_args(state, config)[0]
        assert "--target-lufs" in args
        assert "-23.0" in args

    def test_dry_flag_when_global_dry(self):
        state = _make_state(global_mode="Dry Run")
        _, _, args = build_refinery_args(state, _make_refinery_config())[0]
        assert "--dry" in args

    def test_no_dry_flag_when_live(self):
        state = _make_state(global_mode="Live Update")
        _, _, args = build_refinery_args(state, _make_refinery_config())[0]
        assert "--dry" not in args

    def test_output_dir_in_args_when_set(self):
        state = _make_state()
        state.refinery_output = _str_var("/output")
        _, _, args = build_refinery_args(state, _make_refinery_config())[0]
        assert "--output" in args
        assert "/output" in args

    def test_no_output_dir_when_empty(self):
        state = _make_state()
        state.refinery_output = _str_var("")
        _, _, args = build_refinery_args(state, _make_refinery_config())[0]
        assert "--output" not in args

    def test_preset_in_args(self):
        state = _make_state()
        config = _make_refinery_config()
        config.enhance_params.preset = "Gentle"
        _, _, args = build_refinery_args(state, config)[0]
        assert "--preset" in args
        assert "Gentle" in args

    def test_tolerance_in_args(self):
        state = _make_state()
        config = _make_refinery_config()
        config.normalise_params.tolerance = 2.0
        _, _, args = build_refinery_args(state, config)[0]
        assert "--tolerance" in args
        assert "2.0" in args

    def test_sensitivity_in_args(self):
        state = _make_state()
        config = _make_refinery_config()
        config.declick_params.sensitivity = 0.8
        _, _, args = build_refinery_args(state, config)[0]
        assert "--sensitivity" in args
        assert "0.8" in args

    def test_width_in_args(self):
        state = _make_state()
        config = _make_refinery_config()
        config.declick_params.max_width_ms = 5
        _, _, args = build_refinery_args(state, config)[0]
        assert "--width" in args
        assert "5" in args

    def test_threshold_in_args(self):
        state = _make_state()
        config = _make_refinery_config()
        config.trim_params.threshold = -60.0
        _, _, args = build_refinery_args(state, config)[0]
        assert "--threshold" in args
        assert "-60.0" in args

    def test_fade_flag_when_apply_fade_true(self):
        state = _make_state()
        config = _make_refinery_config()
        config.trim_params.apply_fade = True
        config.trim_params.fade_in_ms = 300
        config.trim_params.fade_out_ms = 800
        _, _, args = build_refinery_args(state, config)[0]
        assert "--fade" in args
        assert "300" == args[args.index("--fade-in") + 1]
        assert "800" == args[args.index("--fade-out") + 1]

    def test_no_fade_flag_when_apply_fade_false(self):
        state = _make_state()
        config = _make_refinery_config()
        config.trim_params.apply_fade = False
        _, _, args = build_refinery_args(state, config)[0]
        assert "--fade" not in args

    def test_auto_start_flag_when_refinery_auto_start_true(self):
        state = _make_state()
        state.refinery_auto_start = _bool_var(True)
        _, _, args = build_refinery_args(state, _make_refinery_config())[0]
        assert "--auto-start" in args

    def test_auto_start_flag_when_refinery_auto_start_false(self):
        state = _make_state()
        state.refinery_auto_start = _bool_var(False)
        _, _, args = build_refinery_args(state, _make_refinery_config())[0]
        assert "--auto-start" not in args

    def test_auto_end_flag_when_refinery_auto_end_true(self):
        state = _make_state()
        state.refinery_auto_end = _bool_var(True)
        _, _, args = build_refinery_args(state, _make_refinery_config())[0]
        assert "--auto-end" in args

    def test_auto_end_flag_when_refinery_auto_end_false(self):
        state = _make_state()
        state.refinery_auto_end = _bool_var(False)
        _, _, args = build_refinery_args(state, _make_refinery_config())[0]
        assert "--auto-end" not in args


# ═════════════════════════════════════════════════════════════════════════════
# _clear_logs
# ═════════════════════════════════════════════════════════════════════════════


class TestClearLogs:
    def test_deletes_txt_files(self, tmp_path):
        (tmp_path / "run.txt").write_text("log")
        (tmp_path / "other.txt").write_text("log2")
        _clear_logs(str(tmp_path))
        assert not (tmp_path / "run.txt").exists()
        assert not (tmp_path / "other.txt").exists()

    def test_preserves_non_txt_files(self, tmp_path):
        (tmp_path / "track.mp3").write_bytes(b"x")
        (tmp_path / "cover.jpg").write_bytes(b"x")
        _clear_logs(str(tmp_path))
        assert (tmp_path / "track.mp3").exists()
        assert (tmp_path / "cover.jpg").exists()

    def test_nonexistent_dir_calls_on_error(self, tmp_path):
        errors = []
        _clear_logs(str(tmp_path / "missing"), on_error=lambda t, m: errors.append(m))
        assert len(errors) == 1

    def test_empty_directory_no_error(self, tmp_path):
        errors = []
        _clear_logs(str(tmp_path), on_error=lambda t, m: errors.append(m))
        assert len(errors) == 0

    def test_permission_error_calls_on_error(self, tmp_path):
        f = tmp_path / "locked.txt"
        f.write_text("x")
        errors = []
        with patch("os.remove", side_effect=PermissionError("locked")):
            _clear_logs(str(tmp_path), on_error=lambda t, m: errors.append(m))
        assert len(errors) == 1

    def test_non_permission_oserror_calls_on_error(self, tmp_path):
        """A generic OSError (not a PermissionError subclass) must be caught
        by the fallback handler and reported."""
        f = tmp_path / "locked.txt"
        f.write_text("x")
        errors = []
        with patch("os.remove", side_effect=OSError("disk error")):
            _clear_logs(str(tmp_path), on_error=lambda t, m: errors.append(m))
        assert len(errors) == 1


# ═════════════════════════════════════════════════════════════════════════════
# _suite_root
# ═════════════════════════════════════════════════════════════════════════════


class TestSuiteRoot:
    def test_returns_string(self):
        assert isinstance(_suite_root(), str)

    def test_path_exists(self):
        assert os.path.isdir(_suite_root())

    def test_path_is_absolute(self):
        assert os.path.isabs(_suite_root())

    def test_master_driver_is_child_of_root(self):
        root = _suite_root()
        expected_child = os.path.join(root, "master_driver")
        assert os.path.isdir(expected_child)


# ═════════════════════════════════════════════════════════════════════════════
# _launch_standalone
# ═════════════════════════════════════════════════════════════════════════════


class TestLaunchStandalone:
    def test_missing_script_returns_false(self, tmp_path):
        result = _launch_standalone(
            str(tmp_path / "ghost.pyw"), [], "Ghost", on_error=lambda t, m: None
        )
        assert result is False

    def test_missing_script_calls_on_error(self, tmp_path):
        errors = []
        _launch_standalone(
            str(tmp_path / "ghost.pyw"),
            [],
            "Ghost",
            on_error=lambda t, m: errors.append(m),
        )
        assert len(errors) == 1

    def test_valid_script_returns_true(self, tmp_path):
        script = tmp_path / "tool.pyw"
        script.write_text("pass")
        mock_proc = MagicMock()
        mock_proc.wait.return_value = 0
        mock_proc.returncode = 0
        with patch(
            "master_driver.runner.module_runner.start_python_script",
            return_value=mock_proc,
        ):
            result = _launch_standalone(str(script), [], "Tool")
        assert result is True

    def test_security_error_returns_false(self, tmp_path):
        from audio_suite_shared.secure_subprocess import SubprocessSecurityError

        script = tmp_path / "tool.pyw"
        script.write_text("pass")
        errors = []
        with patch(
            "master_driver.runner.module_runner.start_python_script",
            side_effect=SubprocessSecurityError("blocked"),
        ):
            result = _launch_standalone(
                str(script), [], "Tool", on_error=lambda t, m: errors.append(m)
            )
        assert result is False
        assert len(errors) == 1

    def test_general_exception_returns_false(self, tmp_path):
        script = tmp_path / "tool.pyw"
        script.write_text("pass")
        with patch(
            "master_driver.runner.module_runner.start_python_script",
            side_effect=RuntimeError("crash"),
        ):
            result = _launch_standalone(str(script), [], "Tool")
        assert result is False


# ═════════════════════════════════════════════════════════════════════════════
# run_modules
# ═════════════════════════════════════════════════════════════════════════════


class TestRunModules:
    def _toggle(self, value):
        t = MagicMock()
        t.get.return_value = value
        return t

    def test_calls_on_start(self, tmp_path):
        on_start = MagicMock()
        run_modules([], False, str(tmp_path), on_start, lambda n: None)
        on_start.assert_called_once()

    def test_calls_on_complete_with_zero_when_empty(self, tmp_path):
        results = []
        run_modules([], False, str(tmp_path), lambda: None, results.append)
        assert results == [0]

    def test_disabled_toggle_skipped(self, tmp_path):
        results = []
        specs = [(self._toggle(False), _make_manifest("inactive"), [])]
        run_modules(specs, False, str(tmp_path), lambda: None, results.append)
        assert results == [0]

    def test_missing_script_not_counted(self, tmp_path):
        results = []
        ghost = tmp_path / "ghost.pyw"
        specs = [(self._toggle(True), _manifest_from_script(ghost), [])]
        run_modules(specs, False, str(tmp_path), lambda: None, results.append)
        assert results == [0]

    def test_valid_script_counted(self, tmp_path):
        script = tmp_path / "tool.pyw"
        script.write_text("pass")
        results = []
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch(
            "master_driver.runner.module_runner.run_python_script",
            return_value=mock_result,
        ):
            run_modules(
                [(self._toggle(True), _manifest_from_script(script), [])],
                False,
                str(tmp_path),
                lambda: None,
                results.append,
            )
        assert results == [1]

    def test_clear_logs_called_when_enabled(self, tmp_path):
        (tmp_path / "log.txt").write_text("x")
        run_modules([], True, str(tmp_path), lambda: None, lambda n: None)
        assert not (tmp_path / "log.txt").exists()

    def test_clear_logs_not_called_when_disabled(self, tmp_path):
        (tmp_path / "log.txt").write_text("x")
        run_modules([], False, str(tmp_path), lambda: None, lambda n: None)
        assert (tmp_path / "log.txt").exists()

    def test_security_error_not_counted(self, tmp_path):
        from audio_suite_shared.secure_subprocess import SubprocessSecurityError

        script = tmp_path / "tool.pyw"
        script.write_text("pass")
        results = []
        with patch(
            "master_driver.runner.module_runner.run_python_script",
            side_effect=SubprocessSecurityError("blocked"),
        ):
            run_modules(
                [(self._toggle(True), _manifest_from_script(script), [])],
                False,
                str(tmp_path),
                lambda: None,
                results.append,
            )
        assert results == [0]

    def test_security_error_with_on_error(self, tmp_path):
        """A SubprocessSecurityError must also fire the Security Error
        dialog when an on_error callback is registered."""
        from audio_suite_shared.secure_subprocess import SubprocessSecurityError

        script = tmp_path / "tool.pyw"
        script.write_text("pass")
        errors = []
        with patch(
            "master_driver.runner.module_runner.run_python_script",
            side_effect=SubprocessSecurityError("blocked"),
        ):
            run_modules(
                [(self._toggle(True), _manifest_from_script(script), [])],
                False,
                str(tmp_path),
                lambda: None,
                lambda n: None,
                on_error=lambda t, m: errors.append((t, m)),
            )
        assert errors and errors[0][0] == "Security Error"

    def test_nonzero_returncode_calls_on_error(self, tmp_path):
        script = tmp_path / "tool.pyw"
        script.write_text("pass")
        errors = []
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch(
            "master_driver.runner.module_runner.run_python_script",
            return_value=mock_result,
        ):
            run_modules(
                [(self._toggle(True), _manifest_from_script(script), [])],
                False,
                str(tmp_path),
                lambda: None,
                lambda n: None,
                on_error=lambda t, m: errors.append(m),
            )
        assert len(errors) == 1

    def test_called_process_error_during_run_calls_on_error(self, tmp_path):
        """Regression: a CalledProcessError from the subprocess layer must be
        converted into an on_error dialog instead of crashing the worker thread
        and leaving the Run button stuck on PROCESSING."""
        script = tmp_path / "tool.pyw"
        script.write_text("pass")
        errors = []
        with patch(
            "master_driver.runner.module_runner.run_python_script",
            side_effect=subprocess.CalledProcessError(1, ["cmd"]),
        ):
            run_modules(
                [(self._toggle(True), _manifest_from_script(script), [])],
                False,
                str(tmp_path),
                lambda: None,
                lambda n: None,
                on_error=lambda t, m: errors.append(m),
            )
        assert len(errors) == 1

    def test_batch_continues_after_called_process_error(self, tmp_path):
        """A module that raises CalledProcessError must not abort the batch:
        the following module still runs and on_complete still fires."""
        script1 = tmp_path / "tool1.pyw"
        script2 = tmp_path / "tool2.pyw"
        script1.write_text("pass")
        script2.write_text("pass")

        calls = {"n": 0}

        def _flaky_first(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise subprocess.CalledProcessError(1, ["cmd"])
            result = MagicMock()
            result.returncode = 0
            return result

        completed = []
        with patch(
            "master_driver.runner.module_runner.run_python_script",
            side_effect=_flaky_first,
        ):
            run_modules(
                [
                    (self._toggle(True), _manifest_from_script(script1), []),
                    (self._toggle(True), _manifest_from_script(script2), []),
                ],
                False,
                str(tmp_path),
                lambda: None,
                completed.append,
            )
        assert completed == [1]

    def test_permission_error_during_run_calls_on_error(self, tmp_path):
        script = tmp_path / "tool.pyw"
        script.write_text("pass")
        errors = []
        with patch(
            "master_driver.runner.module_runner.run_python_script",
            side_effect=PermissionError("access denied"),
        ):
            run_modules(
                [(self._toggle(True), _manifest_from_script(script), [])],
                False,
                str(tmp_path),
                lambda: None,
                lambda n: None,
                on_error=lambda t, m: errors.append(m),
            )
        assert len(errors) == 1

    def test_oserror_during_run_calls_on_error(self, tmp_path):
        script = tmp_path / "tool.pyw"
        script.write_text("pass")
        errors = []
        with patch(
            "master_driver.runner.module_runner.run_python_script",
            side_effect=OSError("disk error"),
        ):
            run_modules(
                [(self._toggle(True), _manifest_from_script(script), [])],
                False,
                str(tmp_path),
                lambda: None,
                lambda n: None,
                on_error=lambda t, m: errors.append(m),
            )
        assert len(errors) == 1

    def test_multiple_modules_counted_correctly(self, tmp_path):
        script1 = tmp_path / "tool1.pyw"
        script2 = tmp_path / "tool2.pyw"
        script1.write_text("pass")
        script2.write_text("pass")
        results = []
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch(
            "master_driver.runner.module_runner.run_python_script",
            return_value=mock_result,
        ):
            run_modules(
                [
                    (self._toggle(True), _manifest_from_script(script1), []),
                    (
                        self._toggle(False),
                        _manifest_from_script(script2),
                        [],
                    ),  # disabled
                    (self._toggle(True), _manifest_from_script(script1), []),
                ],
                False,
                str(tmp_path),
                lambda: None,
                results.append,
            )
        assert results == [2]

    def test_toolmanifest_spec_direct(self, tmp_path):
        """A ToolManifest instance as the spec must be accepted directly
        (no sentinel mapping) and run as a blocking subprocess."""
        script = tmp_path / "bpm.pyw"
        script.write_text("pass")
        manifest = _make_manifest("bpm", standalone=False)
        results = []
        mock_result = MagicMock()
        mock_result.returncode = 0
        with (
            patch(
                "master_driver.runner.module_runner._suite_root",
                return_value=str(tmp_path),
            ),
            patch(
                "master_driver.runner.module_runner.run_python_script",
                return_value=mock_result,
            ),
        ):
            run_modules(
                [(self._toggle(True), manifest, [])],
                False,
                str(tmp_path),
                lambda: None,
                results.append,
            )
        assert results == [1]

    def test_invalid_spec_calls_on_error(self, tmp_path):
        """A spec that is neither a ToolManifest nor a str must trigger the
        Plugin Error path and be skipped."""
        errors = []
        results = []
        run_modules(
            [(self._toggle(True), 12345, [])],
            False,
            str(tmp_path),
            lambda: None,
            results.append,
            on_error=lambda t, m: errors.append((t, m)),
        )
        assert results == [0]
        assert errors and errors[0][0] == "Plugin Error"
        assert "Invalid module spec" in errors[0][1]

    def test_missing_script_with_on_error(self, tmp_path):
        """A missing script with an on_error callback must fire
        'Module Not Found' (not just silently skip)."""
        errors = []
        results = []
        manifest = ToolManifest(
            id="ghost",
            name="Ghost",
            category="",
            pyw_filename="ghost.pyw",
            description="",
        )
        run_modules(
            [(self._toggle(True), manifest, [])],
            False,
            str(tmp_path),
            lambda: None,
            results.append,
            on_error=lambda t, m: errors.append((t, m)),
        )
        assert results == [0]
        assert errors and errors[0][0] == "Module Not Found"

    def test_standalone_failure_appends_failed_steps(self, tmp_path):
        """When a standalone launch returns a non-zero exit code, the tool
        must be recorded in failed_steps on the final progress event."""
        script = tmp_path / "CD_Ripper.pyw"
        script.write_text("pass")
        manifest = _make_manifest("CD_Ripper", standalone=True)
        mock_proc = MagicMock()
        mock_proc.wait.return_value = None
        mock_proc.returncode = 2
        captured: list = []
        with (
            patch(
                "master_driver.runner.module_runner._suite_root",
                return_value=str(tmp_path),
            ),
            patch(
                "master_driver.runner.module_runner.start_python_script",
                return_value=mock_proc,
            ),
        ):
            run_modules(
                [(self._toggle(True), manifest, [])],
                False,
                str(tmp_path),
                lambda: None,
                lambda n: None,
                progress_callback=captured.append,
            )
        if captured:
            assert "CD_Ripper" in captured[-1].failed_steps

    def test_standalone_missing_script_fails(self, tmp_path):
        """A standalone manifest whose script file is absent must reach the
        Module Not Found error (not be counted as executed)."""
        manifest = _make_manifest("CD_Ripper", standalone=True)
        errors = []
        results = []
        with patch(
            "master_driver.runner.module_runner._suite_root",
            return_value=str(tmp_path),
        ):
            run_modules(
                [(self._toggle(True), manifest, [])],
                False,
                str(tmp_path),
                lambda: None,
                results.append,
                progress_callback=lambda *_: None,
                on_error=lambda t, m: errors.append(t),
            )
        assert results == [0]
        assert "Module Not Found" in errors

    def test_parallel_routes_through_orchestrator(self, tmp_path):
        """In parallel mode, module_runner must hand off to the
        BatchOrchestrator and report every failed step via on_error."""
        script1 = tmp_path / "bpm.pyw"
        script2 = tmp_path / "key.pyw"
        script1.write_text("pass")
        script2.write_text("pass")
        results = []
        errors = []
        captured: list = []

        calls = {"n": 0}

        def _flaky(*args, **kwargs):
            calls["n"] += 1
            r = MagicMock()
            r.returncode = 1 if calls["n"] == 2 else 0
            return r

        with (
            patch(
                "master_driver.runner.module_runner._suite_root",
                return_value=str(tmp_path),
            ),
            patch(
                "master_driver.batch_orchestrator.run_python_script",
                side_effect=_flaky,
            ),
        ):
            run_modules(
                [
                    (self._toggle(True), _make_manifest("bpm", standalone=False), []),
                    (self._toggle(True), _make_manifest("key", standalone=False), []),
                ],
                False,
                str(tmp_path),
                lambda: None,
                results.append,
                on_error=lambda t, m: errors.append((t, m)),
                progress_callback=captured.append,
                parallel=True,
                max_workers=2,
            )
        assert results == [1]
        assert any(t == "Module Error" for t, _ in errors)
        assert captured


# ═════════════════════════════════════════════════════════════════════════════
# _emit_progress — timing / ETA
# ═════════════════════════════════════════════════════════════════════════════


class TestEmitProgress:
    def test_callback_not_called_when_none(self):
        """No callback → no error, returns immediately."""
        _emit_progress(None, 5, 2, "bpm", [])

    def test_callback_receives_completed_steps(self):
        captured: list = []
        _emit_progress(
            captured.append,
            total_steps=5,
            completed_steps=2,
            current_step="bpm",
            failed=[],
        )
        assert captured[0].completed_steps == 2

    def test_callback_receives_total_steps(self):
        captured: list = []
        _emit_progress(
            captured.append,
            total_steps=5,
            completed_steps=2,
            current_step="bpm",
            failed=[],
        )
        assert captured[0].total_steps == 5

    def test_callback_receives_current_step(self):
        captured: list = []
        _emit_progress(
            captured.append,
            total_steps=5,
            completed_steps=2,
            current_step="bpm",
            failed=[],
        )
        assert captured[0].current_step == "bpm"

    def test_callback_receives_failed_steps(self):
        captured: list = []
        _emit_progress(
            captured.append,
            total_steps=5,
            completed_steps=2,
            current_step="bpm",
            failed=["key"],
        )
        assert captured[0].failed_steps == ["key"]

    def test_current_progress_is_ratio(self):
        captured: list = []
        _emit_progress(
            captured.append,
            total_steps=4,
            completed_steps=1,
            current_step="bpm",
            failed=[],
        )
        assert captured[0].current_progress == 0.25

    def test_progress_zero_when_total_zero(self):
        captured: list = []
        _emit_progress(
            captured.append,
            total_steps=0,
            completed_steps=0,
            current_step="",
            failed=[],
        )
        assert captured[0].current_progress == 0.0

    def test_elapsed_greater_than_zero(self):
        """When batch_start is provided, elapsed must be > 0."""
        import time

        captured: list = []
        _emit_progress(
            captured.append,
            total_steps=2,
            completed_steps=1,
            current_step="bpm",
            failed=[],
            batch_start=time.monotonic() - 10,  # 10 s ago
        )
        assert captured[0].elapsed.total_seconds() >= 9

    def test_estimated_remaining_based_on_step_times(self):
        """With step_times, ETA should reflect average duration × remaining."""
        captured: list = []
        _emit_progress(
            captured.append,
            total_steps=4,
            completed_steps=2,
            current_step="key",
            failed=[],
            batch_start=0.0,
            step_times=[5.0, 7.0],  # avg 6 s per step
        )
        # 2 remaining steps × 6 s avg = 12 s
        assert captured[0].estimated_remaining.total_seconds() == 12

    def test_estimated_remaining_zero_when_no_step_times(self):
        captured: list = []
        _emit_progress(
            captured.append,
            total_steps=4,
            completed_steps=2,
            current_step="key",
            failed=[],
            step_times=[],
        )
        assert captured[0].estimated_remaining.total_seconds() == 0

    def test_estimated_remaining_zero_when_none_left(self):
        captured: list = []
        _emit_progress(
            captured.append,
            total_steps=4,
            completed_steps=4,
            current_step="key",
            failed=[],
            step_times=[5.0],
        )
        assert captured[0].estimated_remaining.total_seconds() == 0

    def test_running_steps_empty(self):
        captured: list = []
        _emit_progress(
            captured.append,
            total_steps=2,
            completed_steps=1,
            current_step="bpm",
            failed=[],
        )
        assert captured[0].running_steps == []

    def test_pending_steps_empty(self):
        captured: list = []
        _emit_progress(
            captured.append,
            total_steps=2,
            completed_steps=1,
            current_step="bpm",
            failed=[],
        )
        assert captured[0].pending_steps == []


# ═════════════════════════════════════════════════════════════════════════════
# run_modules — progress callback integration
# ═════════════════════════════════════════════════════════════════════════════


class TestRunModulesProgress:
    """run_modules with a progress_callback must emit BatchProgress events
    with correct step counts and timing."""

    def _toggle(self, value):
        t = MagicMock()
        t.get.return_value = value
        return t

    def test_progress_callback_fires_during_run(self, tmp_path):
        script = tmp_path / "tool.pyw"
        script.write_text("pass")
        captured: list = []
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch(
            "master_driver.runner.module_runner.run_python_script",
            return_value=mock_result,
        ):
            run_modules(
                [(self._toggle(True), _manifest_from_script(script), [])],
                False,
                str(tmp_path),
                lambda: None,
                lambda n: None,
                progress_callback=captured.append,
            )
        assert len(captured) >= 1

    def test_progress_tracks_completed_steps(self, tmp_path):
        script1 = tmp_path / "tool1.pyw"
        script2 = tmp_path / "tool2.pyw"
        script1.write_text("pass")
        script2.write_text("pass")
        captured: list = []
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch(
            "master_driver.runner.module_runner.run_python_script",
            return_value=mock_result,
        ):
            run_modules(
                [
                    (self._toggle(True), _manifest_from_script(script1), []),
                    (self._toggle(True), _manifest_from_script(script2), []),
                ],
                False,
                str(tmp_path),
                lambda: None,
                lambda n: None,
                progress_callback=captured.append,
            )
        if captured:
            assert captured[-1].completed_steps == 2

    def test_progress_reports_failed_steps(self, tmp_path):
        script = tmp_path / "tool.pyw"
        script.write_text("pass")
        captured: list = []
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch(
            "master_driver.runner.module_runner.run_python_script",
            return_value=mock_result,
        ):
            run_modules(
                [(self._toggle(True), _manifest_from_script(script), [])],
                False,
                str(tmp_path),
                lambda: None,
                lambda n: None,
                progress_callback=captured.append,
            )
        if captured:
            has_failed = any(c.failed_steps for c in captured)
            assert has_failed

    def test_missing_module_is_reported_failed_not_completed(self, tmp_path):
        """A spec whose .pyw is absent must be shown as 'failed'.

        Positive contract, keyed off the emitted status line: the not-found
        step appears in ``failed_steps`` and its status line reads 'failed'.
        Pre-fix it appeared in neither, so the index-based mapping in
        ``_emit_progress`` fell through to ``i < completed_steps`` and printed
        'completed' for a module that never ran.
        """
        ghost = tmp_path / "ghost.pyw"
        real = tmp_path / "real.pyw"
        real.write_text("pass")
        captured: list = []
        on_error = MagicMock()
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch(
            "master_driver.runner.module_runner.run_python_script",
            return_value=mock_result,
        ):
            run_modules(
                [
                    (self._toggle(True), _manifest_from_script(ghost), []),
                    (self._toggle(True), _manifest_from_script(real), []),
                ],
                False,
                str(tmp_path),
                lambda: None,
                lambda n: None,
                progress_callback=captured.append,
                on_error=on_error,
            )
        on_error.assert_called_once()
        assert captured, "no progress callback fired - the test would prove nothing"

        ghost_key = "ghost"
        ghost_lines = [
            p for p in captured if any(t == ghost_key for t, _, _ in p.steps)
        ]
        assert ghost_lines, f"ghost step never appeared in progress: {captured}"

        ghost_status = dict((t, s) for t, _n, s in ghost_lines[-1].steps)[ghost_key]
        assert ghost_status == "failed"

        # The found sibling still executes normally (M8 must not disturb it).
        assert captured[-1].completed_steps == 1

    def test_missing_module_does_not_shift_its_siblings_status(self, tmp_path):
        """A not-found step must never be shown as 'completed'.

        Pre-fix, `executed` did not advance for the ghost, so once the *sibling*
        finished, the index-based mapping (`i < completed_steps`) painted the
        ghost green. The sibling's own rendering is a separate pre-existing
        quirk of that index mapping and is deliberately not asserted here.
        """
        ghost = tmp_path / "ghost.pyw"
        real = tmp_path / "real.pyw"
        real.write_text("pass")
        captured: list = []
        with patch(
            "master_driver.runner.module_runner.run_python_script",
            return_value=MagicMock(returncode=0),
        ):
            run_modules(
                [
                    (self._toggle(True), _manifest_from_script(ghost), []),
                    (self._toggle(True), _manifest_from_script(real), []),
                ],
                False,
                str(tmp_path),
                lambda: None,
                lambda n: None,
                progress_callback=captured.append,
                on_error=MagicMock(),
            )
        ghost_key = "ghost"
        ghost_statuses = [
            dict((t, s) for t, _n, s in p.steps).get(ghost_key) for p in captured
        ]
        assert "completed" not in ghost_statuses, ghost_statuses
        assert ghost_statuses[-1] == "failed"
        assert "ghost" in captured[-1].failed_steps

    def test_missing_module_status_line_fires_when_no_other_step_runs(self, tmp_path):
        """The not-found branch emits its own progress event (no successor).

        Guards the `continue`-only path: with nothing else in the batch there
        is no later ``_emit_progress`` that could surface the failure.
        """
        ghost = tmp_path / "ghost.pyw"
        captured: list = []
        run_modules(
            [(self._toggle(True), _manifest_from_script(ghost), [])],
            False,
            str(tmp_path),
            lambda: None,
            lambda n: None,
            progress_callback=captured.append,
            on_error=MagicMock(),
        )
        assert len(captured) == 2, captured
        assert captured[-1].steps == [("ghost", "ghost", "failed")]
        assert captured[-1].failed_steps == ["ghost"]


# ═════════════════════════════════════════════════════════════════════════════
# _driver_display_flags (Clear Logs / Parallel mirroring)
# ═════════════════════════════════════════════════════════════════════════════


class TestDriverDisplayFlags:
    """Every child receives display-only flags for the driver-only
    Clear Logs / Parallel options so its Run Controls panel mirrors
    exactly what was chosen in the Master Driver."""

    def test_enrich_defaults_append_negative_flags(self):
        state = _make_state()
        for _, _, args in build_enrich_args(state):
            assert "--no-clear-logs" in args
            assert "--no-parallel-run" in args

    def test_enrich_ticked_options_append_positive_flags(self):
        state = _make_state()
        state.clear_logs_var = _bool_var(True)
        state.parallel_var = _bool_var(True)
        for _, _, args in build_enrich_args(state):
            assert "--clear-logs" in args
            assert "--parallel-run" in args

    def test_utility_mirrors_util_clear_logs_and_shared_parallel(self):
        state = _make_state()
        state.util_clear_logs_var = _bool_var(True)
        state.parallel_var = _bool_var(True)
        converter_entry = next(
            e for e in build_utility_args(state) if "Converter" in e[1].name
        )
        assert "--clear-logs" in converter_entry[2]
        assert "--parallel-run" in converter_entry[2]

    def test_bpm_keeps_own_worker_parallel_flag_distinct(self):
        """BPM's tool-specific --parallel must not collide with the
        driver's --parallel-run display flag."""
        state = _make_state()
        state.bpm_parallel = _bool_var(True)
        state.parallel_var = _bool_var(True)
        bpm_entry = next(e for e in build_enrich_args(state) if "BPM" in e[1].name)
        assert "--parallel" in bpm_entry[2]
        assert "--no-clear-logs" in bpm_entry[2]
        assert "--parallel-run" in bpm_entry[2]
        assert bpm_entry[2].count("--parallel") == 1

    def test_display_flags_are_last_tokens(self):
        """Flags are appended so positional parsers stay stable."""
        state = _make_state()
        rg_entry = next(
            e for e in build_enrich_args(state) if "ReplayGain" in e[1].name
        )
        assert rg_entry[2][-2:] == ["--no-clear-logs", "--no-parallel-run"]
