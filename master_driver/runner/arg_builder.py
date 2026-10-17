"""
arg_builder.py — Constructs the CLI argument list for each child module.

Returns a list of (toggle_var, manifest, args) tuples that run_modules()
iterates over.  Adding a new module means adding a manifest entry to
the registry (tool_plugin.py) and registering a builder function below.

Changed in 1.0.1: drops the non-functional ``--completeness``/``--detail`` args for
Library Statistics.

Changed in 1.2.0: emits the fingerprinter's ``--musicbrainz`` and
``--write-isrc`` pair.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from typing import Any

from audio_suite_shared.tool_plugin import ToolManifest, get_registry

from ..state.app_state import AppState


class _AlwaysOn:
    """Placeholder toggle that is always truthy — no tkinter dependency."""

    def get(self) -> bool:
        return True


_ALWAYS_ON = _AlwaysOn()

_ToggleVar = tk.BooleanVar | _AlwaysOn


def _driver_display_flags(
    logs_var: tk.BooleanVar, parallel_var: tk.BooleanVar
) -> list[str]:
    """Return display-only handshake flags mirroring driver orchestration.

    Children show these states on their Run Controls panel but keep the
    controls inert — Clear Logs and Parallel are executed by the driver,
    never by the child. ``--parallel-run`` is deliberately distinct from
    the tool-specific ``--parallel`` worker flag used by BPM/Key.
    """
    return [
        "--clear-logs" if logs_var.get() else "--no-clear-logs",
        "--parallel-run" if parallel_var.get() else "--no-parallel-run",
    ]


def build_enrich_args(
    state: AppState,
) -> list[tuple[_ToggleVar, ToolManifest, list[str]]]:
    """Return argument specs for all Enrich-tab modules (tag/metadata tools)."""
    path = state.dir_path.get()
    mode_flag = "--live" if state.global_mode.get() == "Live Update" else "--dry"
    start_flag = "--start" if state.auto_start.get() else "--no-start"
    end_flag = "--end" if state.auto_end.get() else "--no-end"

    specs: list[tuple[_ToggleVar, ToolManifest, list[str]]] = []
    registry = get_registry()
    for manifest in registry.by_category("enrich"):
        toggle = state.module_toggles[manifest.id]
        args = _build_enrich_tool_args(
            manifest.id, path, mode_flag, start_flag, end_flag, state
        )
        specs.append((toggle, manifest, args))
    return specs


def _build_enrich_tool_args(
    tool_id: str,
    path: str,
    mode_flag: str,
    start_flag: str,
    end_flag: str,
    state: AppState,
) -> list[str]:
    """Return the CLI argument list for a single enrich tool."""
    builders: dict[str, Callable[[], list[str]]] = {
        "scrubber": lambda: [
            path,
            "0",
            mode_flag,
            start_flag,
            end_flag,
            "--preserve-lyrics"
            if state.scrubber_preserve_lyrics.get()
            else "--no-preserve-lyrics",
            "--preserve-album-artist"
            if state.scrubber_preserve_album_artist.get()
            else "--no-preserve-album-artist",
            "--preserve-embedded-art"
            if state.scrubber_preserve_embedded_art.get()
            else "--no-preserve-embedded-art",
        ],
        "replaygain": lambda: [
            path,
            state.rg_lufs.get(),
            mode_flag,
            start_flag,
            end_flag,
        ],
        "album_genre": lambda: [
            path,
            mode_flag,
            start_flag,
            end_flag,
            "--coverage",
            state.album_genre_coverage.get(),
        ],
        "genre_sync": lambda: [
            path,
            "0",
            mode_flag,
            start_flag,
            end_flag,
        ],
        "bpm": lambda: _build_bpm_args(path, mode_flag, start_flag, end_flag, state),
        "lyrics_manager": lambda: _build_lyrics_args(
            path, mode_flag, start_flag, end_flag, state
        ),
        "tempo": lambda: [
            path,
            "0",
            mode_flag,
            start_flag,
            end_flag,
            "--scheme",
            state.tempo_scheme.get(),
        ],
        "key": lambda: _build_key_args(path, mode_flag, start_flag, end_flag, state),
        "fingerprinter": lambda: (
            [
                path,
                mode_flag,
                start_flag,
                end_flag,
                "--lookup" if state.fingerprinter_lookup.get() else "--no-lookup",
                "--write-tags"
                if state.fingerprinter_write_tags.get()
                else "--no-write-tags",
                "--write-mbids"
                if state.fingerprinter_write_mbids.get()
                else "--no-write-mbids",
                "--musicbrainz"
                if state.fingerprinter_musicbrainz.get()
                else "--no-musicbrainz",
                "--write-isrc"
                if state.fingerprinter_write_isrc.get()
                else "--no-write-isrc",
                "--threshold",
                state.fingerprinter_threshold.get(),
                "--max-length",
                state.fingerprinter_max_length.get(),
            ]
            + (
                ["--fpcalc", state.fingerprinter_fpcalc.get()]
                if state.fingerprinter_fpcalc.get()
                else []
            )
            + (
                ["--mbid-region", state.fingerprinter_mbid_region.get()]
                if state.fingerprinter_mbid_region.get()
                else []
            )
        ),
        "mood_analyzer": lambda: _build_mood_analyzer_args(
            path, mode_flag, start_flag, end_flag, state
        ),
        "art": lambda: [
            path,
            mode_flag,
            start_flag,
            end_flag,
            "--embed-size",
            state.art_res.get(),
            "--purge" if state.art_purge.get() else "--no-purge",
            "--min-dimension",
            state.art_min_dim.get(),
            "--match-threshold",
            state.art_match_threshold.get(),
        ],
    }
    builder = builders.get(tool_id)
    if builder is None:
        return []
    return builder() + _driver_display_flags(state.clear_logs_var, state.parallel_var)


def build_utility_args(
    state: AppState,
) -> list[tuple[_ToggleVar, ToolManifest, list[str]]]:
    """Return argument specs for Utility-tab modules."""
    path = state.dir_path.get()
    mode_flag = "--live" if state.util_global_mode.get() == "Live Update" else "--dry"
    start_flag = "--start" if state.util_auto_start.get() else "--no-start"
    end_flag = "--end" if state.util_auto_end.get() else "--no-end"

    specs: list[tuple[_ToggleVar, ToolManifest, list[str]]] = []
    registry = get_registry()
    for manifest in registry.by_category("utility"):
        toggle = state.module_toggles[manifest.id]
        args = _build_utility_tool_args(
            manifest.id, path, mode_flag, start_flag, end_flag, state
        )
        specs.append((toggle, manifest, args))
    return specs


def _build_utility_tool_args(
    tool_id: str,
    path: str,
    mode_flag: str,
    start_flag: str,
    end_flag: str,
    state: AppState,
) -> list[str]:
    """Return the CLI argument list for a single utility tool."""
    builders: dict[str, Callable[[], list[str]]] = {
        "converter": lambda: _build_converter_args(
            path, mode_flag, start_flag, end_flag, state
        ),
        "asx_extractor": lambda: [
            path,
            "--mode",
            "Execute Extraction (Permanent)"
            if state.util_global_mode.get() == "Live Update"
            else "Dry Run (Simulated)",
            start_flag,
            end_flag,
        ],
        "album_art_normalizer": lambda: [
            path,
            "0",
            mode_flag,
            start_flag,
            end_flag,
            "--size",
            state.art_normalizer_size.get(),
        ],
        "cd_ripper": lambda: _build_cd_ripper_args(state),
        "mood_analysis_batch": lambda: _build_mood_analysis_batch_args(
            path, mode_flag, start_flag, end_flag, state
        ),
        "library_stats": lambda: (
            [path]
            + (
                ["--incremental"]
                if state.library_stats_incremental.get() == "incremental"
                else []
            )
            + (["--refresh"] if state.library_stats_refresh.get() else [])
            + (
                ["--export-csv", state.library_stats_export_csv.get()]
                if state.library_stats_export_csv.get()
                else []
            )
            + (
                ["--export-json", state.library_stats_export_json.get()]
                if state.library_stats_export_json.get()
                else []
            )
        ),
        "file_reorganizer": lambda: (
            [
                path,
                "--output-dir",
                state.file_reorg_output_dir.get(),
                "--action",
                state.file_reorg_action.get(),
            ]
            + (
                ["--specific-pattern", state.file_reorg_specific_pattern.get()]
                if state.file_reorg_specific_pattern.get()
                else []
            )
            + (
                ["--various-pattern", state.file_reorg_various_pattern.get()]
                if state.file_reorg_various_pattern.get()
                else []
            )
        ),
        "noise_reduction": lambda: _build_noise_reduction_args(
            path, mode_flag, start_flag, end_flag, state
        ),
        "tag_field_updater": lambda: [path, mode_flag],
        "tag_editor": lambda: [path, mode_flag],
        "audio_enhancer": lambda: _build_audio_enhancer_args(path, state),
        "audio_normalizer": lambda: [
            path,
            state.normalizer_target_lufs.get(),
            mode_flag,
            start_flag,
            end_flag,
            "--tolerance",
            state.normalizer_tolerance.get(),
            "--mode",
            state.normalizer_mode.get(),
        ],
        "pop_click_remover": lambda: [
            path,
            mode_flag,
            start_flag,
            end_flag,
            "--sensitivity",
            state.declick_sensitivity.get(),
            "--width",
            state.declick_max_width.get(),
        ],
        "silence_trimmer": lambda: _build_silence_trimmer_args(
            path, mode_flag, start_flag, end_flag, state
        ),
    }
    builder = builders.get(tool_id)
    if builder is None:
        return []
    args = builder()
    # The Audio Enhancer GUI parser is strict argparse (parse_args, no
    # parse_known_args); the driver display flags would fatal at launch,
    # so the enhancer never receives them.
    if tool_id == "audio_enhancer":
        return args
    return args + _driver_display_flags(state.util_clear_logs_var, state.parallel_var)


def _build_converter_args(
    path: str,
    mode_flag: str,
    start_flag: str,
    end_flag: str,
    state: AppState,
) -> list[str]:
    args = [
        path,
        state.converter_output_format.get(),
        mode_flag,
        start_flag,
        end_flag,
        "--quality",
        state.converter_quality.get(),
    ]
    sample_rate = state.converter_sample_rate.get()
    if sample_rate != "source":
        args += ["--sample-rate", sample_rate]
    bit_depth = state.converter_bit_depth.get()
    if bit_depth != "auto":
        args += ["--bit-depth", bit_depth]
    if state.converter_normalize_mp3.get():
        args.append("--normalize-mp3")
    args += ["--target-lufs", state.converter_target_lufs.get()]
    if state.converter_delete_originals.get():
        args.append("--delete-originals")
    if state.converter_output_dir.get():
        args.extend(["--output-dir", state.converter_output_dir.get()])
    return args


# (StageConfig field, --stages name) pairs for the Refinery's stage toggles.
#
# Single source of truth (audit M12a): `build_refinery_args` emits this list
# and the Master Driver's Refine-tab select-all iterates the same constant, so
# a new stage cannot appear in one place and not the other. The field name and
# the CLI stage name are asserted equal by test_runner.py.
REFINERY_STAGES: tuple[tuple[str, str], ...] = (
    ("declick", "declick"),
    ("trim", "trim"),
    ("enhance", "enhance"),
    ("normalise", "normalise"),
    ("reduce_noise", "reduce_noise"),
)


def build_refinery_args(
    state: AppState, config: Any
) -> list[tuple[_ToggleVar, ToolManifest, list[str]]]:
    """Return the single argument spec for Audio Refinery.

    config is an audio_refinery.core.models.StageConfig instance,
    populated directly from the embedded setup UI.
    """
    registry = get_registry()
    manifest = registry.get("audio_refinery")
    if manifest is None:
        return []

    source = state.refinery_source.get()
    output = state.refinery_output.get()

    stage_map = [(getattr(config, field), name) for field, name in REFINERY_STAGES]
    active_stages = ",".join(s for enabled, s in stage_map if enabled)

    p = config.enhance_params
    d = config.declick_params
    t = config.trim_params
    n = config.normalise_params
    nr = config.noise_reduction_params

    args: list[str] = [
        "--source",
        source,
        "--stages",
        active_stages,
        "--preset",
        p.preset,
        "--target-lufs",
        str(n.target_lufs),
        "--tolerance",
        str(n.tolerance),
        "--sensitivity",
        str(d.sensitivity),
        "--width",
        str(d.max_width_ms),
        "--threshold",
        str(t.threshold),
    ]
    if t.apply_fade:
        args.append("--fade")
        args.extend(["--fade-in", str(t.fade_in_ms)])
        args.extend(["--fade-out", str(t.fade_out_ms)])
    if nr.reduce_hum:
        args.append("--reduce-hum")
    if nr.reduce_broadband:
        args.append("--reduce-broadband")
    args.extend(
        [
            "--hum-frequency",
            str(nr.hum_frequency),
            "--hum-harmonics",
            str(nr.hum_harmonics),
            "--hum-quality",
            str(nr.hum_quality),
            "--noise-start",
            str(nr.noise_start_ms),
            "--noise-end",
            str(nr.noise_end_ms),
            "--gate-threshold",
            str(nr.gate_threshold_db),
        ]
    )
    if output:
        args.extend(["--output", output])
    if state.global_mode.get() == "Dry Run":
        args.append("--dry")
    if state.refinery_auto_start.get():
        args.append("--auto-start")
    if state.refinery_auto_end.get():
        args.append("--auto-end")

    # Display flags (audit M12b + iteration-8 C5 decision): the Refine tab
    # shows Clear Logs but hides the Parallel checkbox, so only the clear-logs
    # flag is emitted and it must read the Refine tab's own binding
    # (`state.clear_logs_var`), never the Utility tab's. The parallel display
    # flags are not emitted at all — the child keeps its own default.
    args.append("--clear-logs" if state.clear_logs_var.get() else "--no-clear-logs")

    always_on = _ALWAYS_ON
    return [(always_on, manifest, args)]


def _base_tokens(
    path: str, mode_flag: str, start_flag: str, end_flag: str
) -> list[str]:
    """Return the positional prefix shared by most enrich/utility tools."""
    return [path, "0", mode_flag, start_flag, end_flag]


def _build_bpm_args(
    path: str,
    mode_flag: str,
    start_flag: str,
    end_flag: str,
    state: AppState,
) -> list[str]:
    args = _base_tokens(path, mode_flag, start_flag, end_flag)
    args.extend(
        [
            "--bpm-min",
            state.bpm_range_min.get(),
            "--bpm-max",
            state.bpm_range_max.get(),
            "--duration",
            state.bpm_duration.get(),
        ]
    )
    if state.bpm_parallel.get():
        args.append("--parallel")
    else:
        args.append("--no-parallel")
    args.extend(["--workers", state.bpm_workers.get()])
    return args


def _build_lyrics_args(
    path: str,
    mode_flag: str,
    start_flag: str,
    end_flag: str,
    state: AppState,
) -> list[str]:
    args = _base_tokens(path, mode_flag, start_flag, end_flag)
    args.extend(
        [
            "--provider",
            state.lyrics_provider.get(),
            "--request-timeout",
            state.lyrics_request_timeout.get(),
            "--skip-existing"
            if state.lyrics_skip_existing.get()
            else "--no-skip-existing",
            "--plain-fallback"
            if state.lyrics_plain_fallback.get()
            else "--no-plain-fallback",
        ]
    )
    if state.lyrics_parallel.get():
        args.append("--parallel")
    else:
        args.append("--no-parallel")
    args.extend(["--workers", state.lyrics_workers.get()])
    return args


def _build_key_args(
    path: str,
    mode_flag: str,
    start_flag: str,
    end_flag: str,
    state: AppState,
) -> list[str]:
    args = _base_tokens(path, mode_flag, start_flag, end_flag)
    args.extend(
        [
            "--duration",
            state.key_duration.get(),
        ]
    )
    if state.key_parallel.get():
        args.append("--parallel")
    else:
        args.append("--no-parallel")
    args.extend(["--workers", state.key_workers.get()])
    return args


def _build_mood_analyzer_args(
    path: str,
    mode_flag: str,
    start_flag: str,
    end_flag: str,
    state: AppState,
) -> list[str]:
    args = _base_tokens(path, mode_flag, start_flag, end_flag)
    args.extend(
        [
            "--duration",
            state.mood_duration.get(),
        ]
    )
    if state.mood_parallel.get():
        args.append("--parallel")
    else:
        args.append("--no-parallel")
    args.extend(["--workers", state.mood_workers.get()])
    return args


def _build_noise_reduction_args(
    path: str,
    mode_flag: str,
    start_flag: str,
    end_flag: str,
    state: AppState,
) -> list[str]:
    args = [path, mode_flag, start_flag, end_flag]
    if state.nr_reduce_hum.get():
        args += [
            "--reduce-hum",
            "--hum-frequency",
            state.nr_hum_frequency.get(),
            "--hum-harmonics",
            state.nr_hum_harmonics.get(),
            "--hum-quality",
            state.nr_hum_quality.get(),
        ]
    if state.nr_reduce_broadband.get():
        args += [
            "--reduce-broadband",
            "--noise-start",
            state.nr_noise_start.get(),
            "--noise-end",
            state.nr_noise_end.get(),
            "--gate-threshold",
            state.nr_gate_threshold.get(),
        ]
    return args


def _build_audio_enhancer_args(path: str, state: AppState) -> list[str]:
    """Return the CLI argument list for the Audio Enhancer.

    The enhancer GUI parses strict ``parse_args`` — it has no positional
    path and no live/dry or start/end flags.  When the output directory is
    empty the tool cannot run, so return ``[]`` (the card renders a
    required-field hint); an empty list never emits a broken flag.
    """
    output = state.enhancer_output_dir.get()
    if not output:
        return []
    args = [
        "--source",
        path,
        "--output",
        output,
        "--preset",
        state.enhancer_preset.get() or "Moderate",
    ]
    if state.util_auto_start.get():
        args.append("--auto-start")
    if state.util_auto_end.get():
        args.append("--auto-end")
    return args


def _build_silence_trimmer_args(
    path: str,
    mode_flag: str,
    start_flag: str,
    end_flag: str,
    state: AppState,
) -> list[str]:
    """Return the CLI argument list for the Silence Trimmer."""
    args = [
        path,
        mode_flag,
        start_flag,
        end_flag,
        "--threshold",
        state.trimmer_threshold.get(),
    ]
    if state.trimmer_apply_fade.get():
        args += [
            "--fade",
            "--fade-in",
            state.trimmer_fade_in_ms.get(),
            "--fade-out",
            state.trimmer_fade_out_ms.get(),
        ]
    return args


def _build_mood_analysis_batch_args(
    path: str,
    mode_flag: str,
    start_flag: str,
    end_flag: str,
    state: AppState,
) -> list[str]:
    args = _base_tokens(path, mode_flag, start_flag, end_flag)
    args.extend(
        [
            "--duration",
            state.mood_analysis_batch_duration.get(),
        ]
    )
    if state.mood_analysis_batch_parallel.get():
        args.append("--parallel")
    else:
        args.append("--no-parallel")
    args.extend(["--workers", state.mood_analysis_batch_workers.get()])
    return args


def _build_cd_ripper_args(state: AppState) -> list[str]:
    """Return the CLI argument list for the CD Ripper."""
    args: list[str] = []
    output_dir = state.cd_ripper_output_dir.get()
    if output_dir:
        args += ["--output-dir", output_dir]
    args += ["--format", state.cd_ripper_format.get()]
    tracks = state.cd_ripper_tracks.get()
    if tracks:
        args += ["--tracks", tracks]
    if state.cd_ripper_cue.get():
        args.append("--cue")
    args += _driver_display_flags(state.util_clear_logs_var, state.parallel_var)
    return args


def get_fingerprinter_api_key_env(state: AppState) -> dict[str, dict[str, str]]:
    """Return the AcoustID API key as a tool_id→env-var mapping.

    The API key is passed to the fingerprinter subprocess via the
    ``ACOUSTID_API_KEY`` environment variable rather than a ``--api-key``
    command-line argument, so it is not exposed to local process listing
    (``GetCommandLine``).  The fingerprinter CLI resolves
    ``ACOUSTID_API_KEY`` via ``load_api_key()`` before falling back to
    the stored config value.
    """
    key = state.fingerprinter_api_key.get()
    if key:
        return {"fingerprinter": {"ACOUSTID_API_KEY": key}}
    return {}
