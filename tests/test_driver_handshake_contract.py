"""
Lock: one driver handshake, proven against each tool's real parser.

The audit (C-M8) found the handshake read four different ways: four tools each
carried a ``_scan_value_options``, four carried their own
``looks_like_driver_argv``, ``album_art_sync`` had ``_flag_value``, and nothing
checked that the argv ``master_driver.runner.arg_builder`` emits is the argv a
tool can read. A tool whose parser drifted simply ignored the driver's mode.

This file holds the contract:

1. ``HANDSHAKE_TOOLS`` covers the first-party registry exactly, so a new tool
   cannot join the suite without declaring how it reads the handshake (or why
   it is not driven here).
2. The nine tools this item moved onto the shared grammar are driven with the
   **real builder's** argv — the state below stands in for ``AppState``, the
   builder is the shipped one — and each one's **real** ``parse()`` must report
   the same reading the shared grammar takes from that argv. Agreeing with the
   grammar is the contract; reading it *differently* is the drift being closed.
3. Every launched tool is told the driver's mode and its auto-start/auto-end
   pair, so no builder can silently drop the handshake (finding F-WP4-1,
   fixed in decision D-30). The ASX Extractor is the one named exception:
   its argv carries the mode as the label its own dropdown displays, so a
   shared-mode token there would be a second source nothing reads.
4. Two real ``.pyw`` launchers are executed with a handshake argv and must
   reach window construction.

Changed in 2.4.1: new contract over the shared driver grammar (plan WP-4).
Changed in 2.5.0: the handshake table gains the Track Splitter (F-E4).
"""

from __future__ import annotations

import importlib
import sys
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from audio_suite_shared.cli_helpers import (
    DRIVER_MODE_TOKENS,
    parse_driver_handshake,
    scan_value_options,
)
from audio_suite_shared.tool_plugin import get_registry
from master_driver.runner import arg_builder

REPO_ROOT = Path(__file__).resolve().parents[1]


class _Var:
    """Stand-in for a ``tk.StringVar``/``BooleanVar`` the builder reads."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def get(self) -> Any:
        return self._value


class _Toggles:
    """``state.module_toggles`` stand-in: every module is switched on."""

    def __getitem__(self, key: str) -> _Var:
        return _Var(True)


class _DriverState:
    """The ``AppState`` surface ``arg_builder`` reads, with known values.

    Everything the builder asks for resolves to a string, which is what makes
    the emitted argv a real argv rather than a list of mocks. The overrides are
    the values a tool's own parser validates, so a failure here means the
    builder and the parser disagree rather than that a value was malformed.
    """

    #: Values a driven tool's parser validates, or which a falsy "" suppresses.
    OVERRIDES: dict[str, Any] = {
        "converter_output_format": "mp3",
        "converter_quality": "0",
        "converter_target_lufs": "-16",
        "converter_sample_rate": "",
        "converter_bit_depth": "",
        "art_res": "800",
        "art_min_dim": "500",
        "art_match_threshold": "0.85",
        "rg_lufs": "-16.0",
        "tempo_scheme": "Italian",
        "duplicate_threshold": "0.9",
        "dup_disposition": "quarantine",
        "duplicate_disposition": "quarantine",
        "file_reorg_action": "copy",
        "restore_threshold": "0.9",
        "restore_max_run": "3",
        "track_splitter_min_silence": "700",
        "track_splitter_silence_db": "-45",
        "track_splitter_min_track": "5000",
        "track_splitter_boundary": "midpoint",
        "track_splitter_cue": True,
        "audio_joiner_order": "",
        "audio_joiner_output": "",
        "audio_joiner_gap_ms": "0",
        "audio_joiner_crossfade_ms": "0",
        "audio_joiner_copy": True,
        "library_stats_incremental": "",
        "spectral_output_dir": "",
        "parallel_var": False,
        "util_parallel_var": False,
        "clear_logs_var": True,
        "util_clear_logs_var": True,
    }

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self.dir_path = _Var(str(directory))
        self.refinery_source = _Var(str(directory))
        self.refinery_output = _Var("")
        self.global_mode = _Var("Live Update")
        self.util_global_mode = _Var("Live Update")
        self.auto_start = _Var(True)
        self.auto_end = _Var(True)
        self.util_auto_start = _Var(True)
        self.util_auto_end = _Var(True)
        self.module_toggles = _Toggles()

    def __getattr__(self, name: str) -> _Var:
        if name in self.OVERRIDES:
            return _Var(self.OVERRIDES[name])
        # A destination folder the parser validates: point it at the driver's
        # folder, which exists, rather than at a placeholder.
        if "output_dir" in name:
            return _Var(str(self._directory))
        # Numeric settings the driven tools validate against a range; the
        # spelling differs per tool, so resolve by what the name is about.
        if "fft" in name:
            return _Var("2048")
        if "threshold" in name:
            return _Var("0.9")
        if "db_range" in name or "colour_range" in name:
            return _Var("80")
        return _Var("1")


@dataclass(frozen=True)
class ToolSpec:
    """How one tool reads the handshake, or why it is not driven here.

    Attributes:
        parse_module: Importable module holding the tool's ``parse()``.
        path_attribute: The attribute the parsed path lands in.
        reason: Why the tool is not driven by this contract. Empty means it is
            driven.
    """

    parse_module: str = ""
    path_attribute: str = "folder_path"
    reason: str = ""


#: Why a tool that reads the handshake is not driven here: WP-4 changed the
#: nine below and left the membership parsers to their own suites.
_UNCHANGED = (
    "reads the handshake with apply_handshake_membership, which this item did "
    "not touch; its own test_cli_args.py locks the reading"
)

#: Every first-party manifest, and how its handshake is read. The registry
#: comparison below is exact: a new tool fails here until it is declared.
HANDSHAKE_TOOLS: dict[str, ToolSpec] = {
    "scrubber": ToolSpec(reason=_UNCHANGED),
    "fingerprinter": ToolSpec(reason=_UNCHANGED),
    "replaygain": ToolSpec(reason=_UNCHANGED),
    "album_genre": ToolSpec(reason=_UNCHANGED),
    "genre_sync": ToolSpec(reason=_UNCHANGED),
    "bpm": ToolSpec(reason=_UNCHANGED),
    "tempo": ToolSpec(reason=_UNCHANGED),
    "key": ToolSpec(reason=_UNCHANGED),
    "mood_analyzer": ToolSpec(reason=_UNCHANGED),
    "art": ToolSpec("album_art_sync.utils.cli_args"),
    "lyrics_manager": ToolSpec(reason=_UNCHANGED),
    "converter": ToolSpec(reason=_UNCHANGED),
    "asx_extractor": ToolSpec(
        reason=(
            "parses through argparse and conveys the mode as the label for "
            "its own --mode dropdown, which its window displays, instead of "
            "the shared --live/--dry token; a second token would be a source "
            "nothing reads. Its own test_cli_args.py locks the parse"
        )
    ),
    "album_art_normalizer": ToolSpec(reason=_UNCHANGED),
    "mood_analysis_batch": ToolSpec(reason=_UNCHANGED),
    "library_stats": ToolSpec("library_stats.utils.cli_args"),
    "spectral_viewer": ToolSpec("spectral_viewer.utils.cli_args"),
    "file_reorganizer": ToolSpec("file_reorganizer.utils.cli_args"),
    "tag_field_updater": ToolSpec("tag_field_updater.utils.cli_args"),
    "tag_editor": ToolSpec("tag_editor.utils.cli_args"),
    "ml_denoiser": ToolSpec(reason=_UNCHANGED),
    "duplicate_finder": ToolSpec("duplicate_finder.utils.cli_args"),
    "restoration": ToolSpec("restoration.utils.cli_args"),
    "track_splitter": ToolSpec("track_splitter.utils.cli_args"),
    "audio_joiner": ToolSpec("audio_joiner.utils.cli_args"),
    "cd_ripper": ToolSpec("cd_ripper.utils.cli_args", path_attribute="output_dir"),
    "stem_separator": ToolSpec(
        reason=(
            "its builder returns an empty argv until an output folder and a "
            "stem are chosen, which the driver reports as 'cannot run as "
            "configured' — there is no handshake to read"
        )
    ),
    "audio_refinery": ToolSpec(
        reason=(
            "its argv is the Refine tab's own grammar (--source, --auto-start, "
            "--auto-end), not the shared --start/--end spelling; WP-4 leaves "
            "that spelling alone rather than silently redefining it"
        )
    ),
    "undo_tag_edits": ToolSpec(
        reason=(
            "opens the undo window with no argv contract; its launcher parses "
            "nothing, so there is no handshake to read"
        )
    ),
}

#: The tools this item moved onto the shared grammar.
DRIVEN_TOOLS: tuple[str, ...] = tuple(
    tool_id for tool_id, spec in HANDSHAKE_TOOLS.items() if not spec.reason
)

#: Tools the driver launches with no shared mode flag. The ASX Extractor
#: carries the mode as its dropdown label instead (D-30 names why).
NO_MODE_IN_ARGV: tuple[str, ...] = ("asx_extractor",)


def _builder_argv(directory: Path) -> dict[str, list[str]]:
    """Return each tool's driver argv, built by the shipped builder.

    Args:
        directory: The folder the driver is pointed at.

    Returns:
        Mapping of tool id to the argv ``arg_builder`` emits for it.
    """
    state = _DriverState(directory)
    built: dict[str, list[str]] = {}
    for specs in (
        arg_builder.build_enrich_args(state),
        arg_builder.build_utility_args(state),
    ):
        for _toggle, manifest, argv in specs:
            built[manifest.id] = list(argv)
    return built


class TestTheTableCoversTheRegistry:
    def test_every_first_party_tool_is_declared(self) -> None:
        declared = set(HANDSHAKE_TOOLS)
        registry = {manifest.id for manifest in get_registry().first_party}
        assert declared == registry, (
            f"undeclared: {sorted(registry - declared)}; "
            f"stale: {sorted(declared - registry)}"
        )

    def test_the_table_is_not_empty_and_records_its_exceptions(self) -> None:
        assert len(HANDSHAKE_TOOLS) == 29
        assert len(DRIVEN_TOOLS) == 11, DRIVEN_TOOLS
        excluded = {t for t, spec in HANDSHAKE_TOOLS.items() if spec.reason}
        assert len(excluded) == 18


class TestTheParserAgreesWithTheGrammar:
    @pytest.mark.parametrize("tool_id", DRIVEN_TOOLS)
    def test_the_real_parser_reads_the_real_builder_argv(
        self, tool_id: str, tmp_path: Path
    ) -> None:
        argv = _builder_argv(tmp_path)[tool_id]
        assert argv, f"{tool_id}: the builder emitted nothing to parse"

        # The driver launches ``[python, <launcher>.pyw, *argv]`` and each tool
        # parses ``sys.argv``, so the program name sits at index 0.
        launched = [f"{tool_id}.pyw", *argv]
        reading = parse_driver_handshake(launched)
        spec = HANDSHAKE_TOOLS[tool_id]
        module = importlib.import_module(spec.parse_module)
        args = module.parse(launched)

        assert getattr(args, spec.path_attribute) == str(tmp_path), (
            f"{tool_id}: {spec.path_attribute} did not survive the round trip"
        )
        assert args.live_mode is reading.live_mode, f"{tool_id}: mode differs"
        assert args.auto_start is reading.auto_start, f"{tool_id}: auto-start"
        assert args.auto_end is reading.auto_end, f"{tool_id}: auto-end"
        assert args.clear_logs is bool(reading.clear_logs), f"{tool_id}: logs"


class TestTheBuilderEmitsAHandshake:
    def test_every_launched_tool_carries_a_mode_flag(self, tmp_path: Path) -> None:
        """Every launched tool is told which mode the driver is in.

        The contract found three builders that emitted no mode flag at all, so
        their windows could not display the driver's live/dry choice. This is
        the lock (F-WP4-1, fixed in D-30): a builder that drops it fails here.
        """
        built = _builder_argv(tmp_path)
        missing = sorted(
            tool_id
            for tool_id, argv in built.items()
            if argv and not (DRIVER_MODE_TOKENS & set(argv))
        )
        assert missing == sorted(NO_MODE_IN_ARGV)

    def test_every_other_launched_tool_carries_a_mode_and_a_pair(
        self, tmp_path: Path
    ) -> None:
        built = _builder_argv(tmp_path)
        checked = [
            tool_id
            for tool_id, argv in built.items()
            if argv and tool_id not in NO_MODE_IN_ARGV
        ]
        assert len(checked) >= 20, checked
        for tool_id in checked:
            tokens = set(built[tool_id])
            assert tokens & DRIVER_MODE_TOKENS, tool_id
            assert tokens & {"--start", "--no-start", "--end", "--no-end"}, tool_id


class TestTheGrammarItself:
    def test_an_option_value_is_never_read_as_the_path(self) -> None:
        # A driver that puts its options first must not make the output path
        # the folder the tool scans.
        handshake = parse_driver_handshake(
            ["prog", "--output-dir", "D:/out", "D:/music", "--dry"],
            {"--output-dir"},
        )
        assert handshake.path == "D:/music"
        assert handshake.mode == "dry"

    def test_a_flag_with_no_value_is_reported_as_missing(self) -> None:
        values, positionals = scan_value_options(["--n-fft"], {"--n-fft"})
        assert values == {"--n-fft": None}
        assert positionals == ()

    def test_the_last_spelling_of_a_pair_wins(self) -> None:
        handshake = parse_driver_handshake(
            ["prog", "D:/music", "--start", "--no-start", "--live"]
        )
        assert handshake.auto_start is False
        assert handshake.live_mode is True

    def test_a_silent_display_flag_is_none_not_false(self) -> None:
        handshake = parse_driver_handshake(["prog", "D:/music", "--dry"])
        assert handshake.clear_logs is None
        assert handshake.parallel_run is None

    def test_the_cd_ripper_accepts_an_argv_with_no_positional_path(self) -> None:
        # Its only path is --output-dir, which the shared grammar treats as an
        # option value, so the handshake must still carry the flags.
        handshake = parse_driver_handshake(
            ["prog", "--output-dir", "D:/out", "--live", "--start", "--end"],
            {"--output-dir"},
        )
        assert handshake.path == ""
        assert handshake.mode == "live"
        assert handshake.auto_start is True
        assert handshake.auto_end is True


#: (launcher, app module, app attribute) — one enrich tool and one utility.
SMOKE_LAUNCHERS: tuple[tuple[str, str, str], ...] = (
    ("BPM_Analyzer.pyw", "bpm_analyzer.app", "BPMAnalyzerApp"),
    ("Library_Stats.pyw", "library_stats.app", "LibraryStatsApp"),
)


class TestALauncherTakesTheHandshake:
    @pytest.mark.parametrize(("launcher", "app_module", "app_attr"), SMOKE_LAUNCHERS)
    def test_the_real_pyw_reaches_window_construction(
        self,
        launcher: str,
        app_module: str,
        app_attr: str,
        tmp_path: Path,
        root: tk.Tk,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Run the shipped launcher source with a driver-shaped argv.

        The launcher's own preamble (venv bootstrap, pre-flight guard, logging)
        is neutralised — it would re-exec the process or open dialogs — and the
        window class is recorded instead of built. Everything between them is
        the shipped code: the real ``parse`` and the real construction call.
        """
        source = (REPO_ROOT / launcher).read_text(encoding="utf-8")
        recorder = MagicMock(name="app_class")
        argv = [launcher, str(tmp_path), "--dry", "--no-start", "--no-end"]
        monkeypatch.setattr(sys, "argv", argv)
        monkeypatch.setattr(
            "audio_suite_shared.venv_bootstrap.ensure_venv_interpreter",
            lambda _root: None,
        )
        monkeypatch.setattr(
            "audio_suite_shared.preflight.guard_or_exit", lambda _root: True
        )
        monkeypatch.setattr(
            "audio_suite_shared.app_bootstrap.configure_logging", lambda _name: None
        )
        monkeypatch.setattr(
            "audio_suite_shared.styles.bootstrap_theme", lambda *a, **k: None
        )
        monkeypatch.setattr(f"{app_module}.{app_attr}", recorder)
        monkeypatch.setattr(tk, "Tk", lambda *a, **k: root)
        monkeypatch.setattr(root, "mainloop", MagicMock())

        exec(
            compile(source, launcher, "exec"),
            {"__name__": "__main__", "__file__": str(REPO_ROOT / launcher)},
        )

        assert recorder.call_count == 1, f"{launcher} did not build a window"
