#!/usr/bin/env python3
"""capture_guide_shots.py - capture the screenshots a user guide shows.

A guide can carry figures, and every figure is a PNG captured from the real tool
window.  This script is the only writer of those PNGs, exactly as
``build_user_guides.py`` is the only writer of the ``.docx`` beside them.

Why a capture step exists at all
--------------------------------
Tk has no window-to-image API, so a figure is a screen grab of a window the tool
itself built: this script constructs the real application class, drives the
tool's own render helpers (``_update_progress_ui``, ``_update_ui_on_complete``)
with the sample run declared for that tool, and grabs the client area with
``PIL.ImageGrab``.
Nothing is drawn into a mock window, so a figure cannot show a layout the tool
no longer has - the picture came from the tool.

Two halves, one pipeline
------------------------
Capture is **not** reproducible across machines: font rendering, display scaling
and the Windows version all change the pixels.  It therefore runs here, on
Windows, and its output is committed.  Rendering *is*
reproducible, because ``build_user_guides.py`` embeds the committed PNG bytes -
so the ``.docx`` freshness check keeps its meaning and no CI job needs a GUI.

Each capture writes ``images/<shot>.png`` beside the guide plus a
``<shot>.json`` sidecar (size, DPI, palette, SHA-256 of the PNG).
``tests/test_user_guide_hygiene.py`` holds the committed binaries to those
sidecars and to the guides that reference them.

Determinism
-----------
A capture run must not read or write the developer's own state, or two
developers photograph different windows:

* the shared config module is answered from memory - the saved palette, theme,
  typography, geometry and last directory are all machine state;
* ``platform_utils.setup_window`` is replaced with a fixed geometry, so every
  figure is the same size and no geometry is written back on close;
* ``AUDIOSUITE_WHATS_NEW=0`` keeps the release-notes panel out of frame;
* ``sys.argv`` is neutralised, because a tool that believes the Master Driver
  launched it locks its controls and lays itself out differently;
* a tool's own saved panel state is replaced through its declared setup
  override, so a figure shows the defaults rather than one person's last run;
* ``AUDIOSUITE_LOG_DIR`` points at a temporary directory, so a capture run does
  not append to the shipped diagnostic logs.

Changed in 2.7.0: a tool's setup panel is filled from a declared override table,
so a regenerated figure shows the defaults the guide documents instead of the
capturing machine's last saved run.

An occluded window is the failure mode that matters: ``ImageGrab`` copies the
screen, so the window is raised and made topmost before each grab, and every
frame is checked for a plausible number of distinct colours.  A locked or
disconnected desktop yields a blank frame, which fails loudly instead of
committing a black screenshot.

A figure is captured from the tool's own window, and its position is calibrated
rather than computed.  A borderless window was tried first, to make the rect
trivial, but the decorated window is what the tool actually shows and the marker
block works either way - so decorations stay and the title bar simply falls
outside the grab.  ``PrintWindow`` and ``BitBlt`` from the window's own DC are
no escape: both return a near-flat frame for a Tk window (283 distinct colours
against the grab's 13,000+).  So the capture measures once: a marker block at the
client's top-left corner is located in a screen grab, and the origin the OS will
not report is taken from its pixels.  The size needs no measurement - Tk's
client size is the area the window paints, and it is asserted against the plan
before a single figure is written.

Display scaling is the other half of that measurement, and the reason the
process asks to be DPI aware before Tk starts.  Unaware, Tk reports logical
pixels while ``ImageGrab`` copies physical ones, so on a 125% display a grab of
``winfo_height`` covered only the top 80% of the window: the rest of the figure
was window background, and the BPM Setup tab's start button - docked against the
bottom edge - never appeared in its guide at all.  Aware, Tk, Win32 and the grab
agree.  Every plan's window is then requested at ``dpi / 96`` times its pinned
size, so the tool lays itself out exactly as it does on a 100% display, and the
grabbed frame is scaled back down to the pinned size before it is written.

The window is captured at the size the plan declares, not at the size the layout
asks for.  The shared run-controls panel positions part of itself with
``place()``, so a ``winfo_reqwidth`` walk cannot see the controls it clips: a
natural-size window silently cut the Setup tab off at the Parallel checkbox.  A
declared size, a capture-time assertion that the window really is that size, and
a human look at the committed PNG are what hold that; the plan comment records
why each number is what it is.

Usage:
    python utilities/capture_guide_shots.py              # every planned tool
    python utilities/capture_guide_shots.py bpm_analyzer # one tool
    python utilities/capture_guide_shots.py --force-dpi  # capture off 100%

Conventions (AGENTS.md "Utility Script Markers"): ASCII-only [START] / [OK] /
[INFO] / [ERROR] / [DONE] markers on stdout/stderr.

Changed in 2.4.4: new file - the one screenshot capture step behind the guide
figures, and the reason a guide can show the window it describes.

Changed in 2.5.0: each figure is filled from the sample run declared for its own
tool (``SAMPLE_RUNS``), so a Processing figure shows that tool's per-file status
lines and counters rather than one shared set of lines borrowed from BPM
Analyzer.  A tool that wants filled figures and declares no run fails the
capture instead of inheriting another's vocabulary.

Changed in 2.5.0: the Track Splitter's three tabs are captured from its own
sample run, and its Setup figure is filled in the live mode its written-file
lines report (F-E4 follow-on).

Changed in 2.5.0: Channel Tools joins the plans, so its guide shows the window
it describes.  Its sample run is in the shared in-place workflow's own
``[STATUS] name -> rule`` shape (the line ``process_audio_file_inplace``
publishes, with the rule sentence ``channel_ops.apply_operation`` returns), and
its Setup figure is filled in the Dry Run mode those ``[FOUND]`` lines report.
"""

from __future__ import annotations

import ctypes
import hashlib
import importlib
import json
import os
import re
import sys
import tempfile
import time
import tkinter as tk
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import ttk
from typing import Any

from PIL import Image, ImageGrab

REPO_ROOT = Path(__file__).resolve().parents[1]
# The script is run from ``utilities/``, so the suite's packages are not on the
# import path yet.  Insert rather than append: a tool module must resolve to
# this tree, never to something already installed.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

#: The tree each PNG belongs in: one folder per tool, beside its guide.
GUIDE_ROOT = REPO_ROOT / "documentation" / "user_guides" / "individual_programs"

#: Sub-folder inside a tool's guide folder that holds its screenshots.
IMAGE_DIRNAME = "images"

#: The DPI the committed screenshots were captured at.  A different scaling
#: factor produces different pixels, so the run refuses rather than silently
#: replacing every committed figure with a differently-sized one.
CAPTURE_DPI = 96

#: Palette and theme every figure is captured in.  Both are user preferences,
#: so a capture that read them would photograph whoever ran it.
CAPTURE_PALETTE = "Purple"
CAPTURE_THEME = "Light"

#: Where the window is parked while it is photographed, in screen pixels.
WINDOW_ORIGIN = (120, 120)

#: The smallest inset the placement will accept.  A window taller than the
#: screen minus twice this cannot be grabbed whole, which is the point: the grab
#: refuses rather than copying the desktop down one edge.
MIN_WINDOW_INSET = 20

#: Height reserved at the bottom of the screen for the taskbar.  A window whose
#: bottom lands under it is grabbed with taskbar pixels across its last rows,
#: and Windows will not raise it above the bar for us.
WORK_AREA_MARGIN = 64

#: How long the window is given to finish drawing before the grab.
SETTLE_SECONDS = 0.4

#: A frame with fewer colours than this is not a rendered window.  A real window
#: carries thousands (text antialiasing alone); a blank, all-black or covered
#: frame carries a handful.
MIN_FRAME_COLOURS = 64

#: Upper bound for the colour census; reaching it means "plenty".
MAX_FRAME_COLOURS = 200_000

# Changed in 2.5.0: the origin marker is a solid 40 px block rather than a 6 px
# frame, and the grab is retried while a decorated toplevel composites.  A
# single-matching-pixel search found a coincidental desktop pixel during
# development and measured the window 279 px too wide.  The process also asks to
# be DPI aware before Tk starts: a 125% display used to crop every figure to its
# top 80% while ``winfo_fpixels`` still reported 96 dpi to the guard.

#: Colour of the marker frame :func:`_calibrate` reads the window origin from.
#: Not a colour any tool paints, so a match in the screen grab is unambiguous.
TOP_LEFT_MARKER = "#ff00fe"

#: Marker side in pixels: big enough to survive any border the desktop adds,
#: small enough to vanish from the corner once it is removed.
MARKER_SIZE = 40

#: Inset of the marker from the client corner, so a rounded window frame cannot
#: clip its outermost pixels.
MARKER_INSET = 4

#: Arrow the BPM processor puts between a file name and its outcome.
_ARROW = "\u2192"

#: The sample run every BPM Analyzer figure shows: a plausible nine-track album.
#: The names are invented and the tempos are round numbers, so a figure cannot be
#: mistaken for a measurement of somebody's library.
SAMPLE_TRACKS: tuple[tuple[str, int], ...] = (
    ("01 - Alpha Intro.flac", 128),
    ("02 - Beta Motion.flac", 124),
    ("03 - Gamma Drift.mp3", 96),
    ("04 - Delta Line.flac", 140),
    ("05 - Epsilon Down.mp3", 88),
    ("06 - Zeta Pull.flac", 132),
    ("07 - Eta Reprise.mp3", 126),
    ("08 - Theta Room.flac", 60),
    ("09 - Iota Outro.flac", 118),
)

#: The track the sample run reports as skipped, and why.
SAMPLE_SKIP = ("07 - Eta Reprise.mp3", "No tempo detected - no discernible beat.")

#: The track the sample run measured outside the configured band.
SAMPLE_OUTSIDE = "08 - Theta Room.flac"

#: Files the Processing figure shows as finished, of the nine in the run.
SAMPLE_DONE = 6

#: Elapsed time the Results figure reports, in seconds.
SAMPLE_SECONDS = 41

#: Folder the sample run names.  Deliberately generic: it is not a path on any
#: machine and not a real album.
SAMPLE_FOLDER = "C:\\Music\\Sample Album"


@dataclass(frozen=True)
class SampleRun:
    """One invented run, in the vocabulary the tool's own processor publishes.

    A figure is only honest if its per-file lines are the lines that tool
    writes during a run.  One shared set of lines put BPM Analyzer's tempo
    results on every batch tool's Processing tab, so a run is declared per tool
    and :func:`_fillers` refuses a tool that has none.

    Attributes:
        status: The overall status line shown while the run is in progress.
        lines: One Processing-tab display line per finished file, in the exact
            shape the tool's processor publishes.
        slots: Worker-slot text for the busy slots, in slot order.  Remaining
            slots are set to ``IDLE``.
        summary: The Results tab's summary text.  Empty means the shared
            processed / skipped / errors line.
        stats: The Processing tab's counter line.  Empty means the shared
            processed / skipped / errors line.
        completion: The Results heading.  Empty means the tool's own
            ``completion_text``, which is what its live run shows.
        seconds: Elapsed time the Results figure reports.
    """

    status: str
    lines: tuple[str, ...]
    slots: tuple[str, ...] = ()
    summary: str = ""
    stats: str = ""
    completion: str = ""
    seconds: int = SAMPLE_SECONDS


#: File names of the invented album, in run order.
_NAMES: tuple[str, ...] = tuple(name for name, _bpm in SAMPLE_TRACKS)

#: The files the Processing figure shows as finished.
_FINISHED: tuple[str, ...] = _NAMES[:SAMPLE_DONE]

#: The two files the worker slots show as busy in the same figure.
_NEXT: tuple[str, ...] = _NAMES[SAMPLE_DONE : SAMPLE_DONE + 2]

#: Per-segment lengths for the Audio Joiner's sample run, in run order.  They
#: sum to the joined length its Results figure reports, so the Setup preview and
#: the completed run state the same arithmetic.
_JOINER_MS: tuple[int, ...] = (4400, 4100, 4300, 4200, 4400, 4100, 4300, 4200, 4412)


def _joiner_clock(ms: int) -> str:
    """Render a segment length the way the joiner's run publishes it.

    Args:
        ms: The segment's length in milliseconds.

    Returns:
        ``MM:SS.mmm``, the shape ``run_join`` writes on its per-segment line.
    """
    minutes, rest = divmod(ms, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


#: The sample folder with the separator a Windows tool displays.
_SAMPLE_PATH_PREFIX = SAMPLE_FOLDER + "\\"


def _busy_slots(verb: str) -> tuple[str, ...]:
    """Return worker-slot text for the two files a mid-run figure shows.

    Args:
        verb: The tool's own slot verb, e.g. ``"Scrubbing"``.

    Returns:
        Two slot labels; the remaining slots are set to ``IDLE``.
    """
    return (f"{verb}: {_NEXT[0][:22]}...", f"{verb}: {_NEXT[1][:22]}...")


#: The sample run each tool's figures show, keyed by guide folder.  Every line
#: here is in the shape that tool's own processor publishes (the processors are
#: the authority: ``core/file_processor.py`` in each package), so the Processing
#: tab reads as that tool's run and not another's.
SAMPLE_RUNS: Mapping[str, SampleRun] = {
    "album_art_normalizer": SampleRun(
        status="Normalizing album art...",
        lines=tuple(
            f"[UPDATED] {name} \u2192 Embedded image was 500\u00d7500; would be "
            "resized to 1200\u00d71200 (dry run)."
            for name in _FINISHED
        ),
        slots=_busy_slots("Processing"),
    ),
    "album_art_sync": SampleRun(
        status="Fetching artwork...",
        lines=(
            "--- SESSION START: DRY RUN ---",
            f"Directory: {SAMPLE_FOLDER}",
            "Album: Aeon Drift - Alpha Intro",
            "Files: 9 audio file(s)",
            "",
            "[Dry Run] Would apply artwork from Fanart.tv",
            "[Dry Run] Would embed at 1200\u00d71200",
        ),
    ),
    "album_genre_tagger": SampleRun(
        status="Consolidating genres...",
        lines=tuple(f"[OK] {name}: Ambient" for name in _FINISHED),
        slots=_busy_slots("Reading"),
    ),
    "asx_extractor": SampleRun(
        status="Extracting ASX playlists...",
        lines=tuple(
            f"  [OK] Sample_Album_{index:02d}.asx -> {_SAMPLE_PATH_PREFIX}{name}"
            for index, name in enumerate(_FINISHED, start=1)
        ),
    ),
    "audio_fingerprinter": SampleRun(
        status="Fingerprinting...",
        lines=tuple(
            f"[MATCHED] {name} \u2014 Alpha Intro \u2014 Aeon Drift "
            f"(score {0.97 - index * 0.01:.2f})"
            for index, name in enumerate(_FINISHED)
        ),
        slots=_busy_slots("Fingerprinting"),
    ),
    "audio_refinery": SampleRun(
        status="Processing...",
        lines=tuple(f"[DONE] {name}" for name in _FINISHED),
        slots=(
            f"Hashing: {_NEXT[0][:22]}...",
            f"Processing: {_NEXT[1][:18]}...",
        ),
    ),
    "channel_tools": SampleRun(
        status="Processing channels...",
        lines=(
            *(f"[FOUND] {name} \u2192 mono sum: 0.5 x (L + R)" for name in _FINISHED),
            "[SKIP] 07 - Eta Reprise.mp3 \u2192 already mono - unchanged",
            "[FOUND] 08 - Theta Room.flac \u2192 stereo width 200 %: side "
            "scaled, decoded",
        ),
        slots=(
            f"Processing channels: {_NEXT[0][:25]}...",
            f"Processing channels: {_NEXT[1][:25]}...",
        ),
        stats=f"Files: {SAMPLE_DONE}/9  |  Errors: 0",
        summary=(
            f"Files: {len(SAMPLE_TRACKS)}\n"
            f"Changed: {SAMPLE_DONE}\n"
            "Unchanged: 2\n"
            "Errors: 0\n"
            "Rule: Mono, arithmetic mean (0.5 x (L + R))"
        ),
    ),
    "duplicate_finder": SampleRun(
        status="Fingerprinting files...",
        lines=tuple(f"[FINGERPRINT] {name}" for name in _FINISHED),
        slots=_busy_slots("Fingerprinting"),
    ),
    "file_reorganizer": SampleRun(
        status=f"Current File: {_NEXT[0]}",
        lines=tuple(f"{_SAMPLE_PATH_PREFIX}{name}" for name in _FINISHED),
        stats="Scanned: 9 | Processed: 6 | Skipped: 1 | Errors: 0",
    ),
    "genre_sync": SampleRun(
        status="Resolving genres...",
        lines=tuple(
            f"[DRY_RUN] {name} \u2192 Would set: Ambient" for name in _FINISHED
        ),
        slots=_busy_slots("Resolving"),
        completion="Analysis Complete!",
        summary=(
            "Total: 9 files\nUpdated: 6\nSkipped (already correct): 2\n"
            "No genre fields: 1\nErrors: 0"
        ),
    ),
    "key_detector": SampleRun(
        status="Detecting keys...",
        lines=(
            "[DETECTED] 01 - Alpha Intro.flac \u2192 8A",
            "[DETECTED] 02 - Beta Motion.flac \u2192 9A",
            "[DETECTED] 03 - Gamma Drift.mp3 \u2192 5B",
            "[DETECTED] 04 - Delta Line.flac \u2192 10A",
            "[DETECTED] 05 - Epsilon Down.mp3 \u2192 4B",
            "[DETECTED] 06 - Zeta Pull.flac \u2192 7A",
        ),
        slots=_busy_slots("Analyzing"),
    ),
    "library_stats": SampleRun(
        status="Scanned 9 files in 0.8s.",
        lines=(f"9 files scanned in {SAMPLE_FOLDER}",),
        stats="Files: 9 | Albums: 2 | Artists: 4",
    ),
    "lyrics_manager": SampleRun(
        status="Looking up lyrics...",
        lines=tuple(
            f"[DRY RUN] {name} \u2192 would embed synced lyrics" for name in _FINISHED
        ),
    ),
    "metadata_scrubber": SampleRun(
        status="Scrubbing metadata...",
        lines=tuple(
            f"[DRY RUN] {name} \u2192 Would scrub metadata" for name in _FINISHED
        ),
        slots=_busy_slots("Scrubbing"),
    ),
    "ml_denoiser": SampleRun(
        status="Reducing noise...",
        lines=tuple(
            f"[FOUND] {name} \u2192 Attenuated 6.2 dB (noise floor -54.0 dBFS)"
            for name in _FINISHED
        ),
        slots=_busy_slots("Reducing noise"),
    ),
    "mood_analysis_batch_tagger": SampleRun(
        status="Scanning: Sample Album",
        lines=(
            "\u25b6  Sample Album  (9 files)",
            "    OK   01 - Alpha Intro.flac  ->  Calm / medium energy",
            "    OK   02 - Beta Motion.flac  ->  Energetic / high energy",
            "    SKIP 03 - Gamma Drift.mp3  --  no audible content",
            "    OK   04 - Delta Line.flac  ->  Melancholic / medium energy",
            "    OK   05 - Epsilon Down.mp3  ->  Calm / low energy",
            "    OK   06 - Zeta Pull.flac  ->  Bright / high energy",
        ),
        slots=(
            f"Analyzing: {_NEXT[0][:22]}...",
            f"Analyzing: {_NEXT[1][:22]}...",
            "IDLE",
            "IDLE",
        ),
    ),
    "mood_analyzer": SampleRun(
        status="Analyzing mood...",
        lines=(
            "[DETECTED] 01 - Alpha Intro.flac \u2192 Calm (conf 0.82)",
            "[DETECTED] 02 - Beta Motion.flac \u2192 Energetic (conf 0.76)",
            "[DETECTED] 03 - Gamma Drift.mp3 \u2192 Melancholic (conf 0.71)",
            "[DETECTED] 04 - Delta Line.flac \u2192 Bright (conf 0.88)",
            "[DETECTED] 05 - Epsilon Down.mp3 \u2192 Calm (conf 0.69)",
            "[DETECTED] 06 - Zeta Pull.flac \u2192 Dark (conf 0.74)",
        ),
        slots=_busy_slots("Analyzing"),
    ),
    "music_format_converter": SampleRun(
        status="Converting...",
        lines=tuple(
            f"[DRY RUN] {name} \u2192 {name.rsplit('.', 1)[0]}.flac"
            for name in _FINISHED
        ),
        slots=_busy_slots("Converting"),
    ),
    "replaygain_analyzer": SampleRun(
        # A measured file publishes an empty display line, so the list stays
        # empty during a healthy run; the slot grid and counters carry the
        # progress instead.
        status="Measuring loudness...",
        lines=(),
        slots=_busy_slots("Analyzing"),
    ),
    "restoration": SampleRun(
        status="Reconstructing peaks...",
        lines=tuple(
            f"[FOUND] {name} \u2192 Restored 4 clipped peak(s) - peak now -0.3 dBFS"
            for name in _FINISHED
        ),
        slots=_busy_slots("Reconstructing"),
    ),
    "stem_separator": SampleRun(
        status="Separating stems...",
        lines=tuple(
            f"[DRY RUN] {name} - would write 4 stems (4-stem)" for name in _FINISHED
        ),
        slots=_busy_slots("Separating"),
    ),
    "tag_editor": SampleRun(
        status="Applying edits...",
        lines=tuple(f"{name}: would write album -> Sample Album" for name in _FINISHED),
    ),
    "tag_field_updater": SampleRun(
        status="Scanning folder...",
        lines=_FINISHED,
        completion="Scan Complete!",
    ),
    "tempo_analyzer": SampleRun(
        status="Analyzing tempo...",
        lines=(
            "[DRY RUN] 01 - Alpha Intro.flac \u2192 Allegro (128 BPM)",
            "[DRY RUN] 02 - Beta Motion.flac \u2192 Allegro (124 BPM)",
            "[DRY RUN] 03 - Gamma Drift.mp3 \u2192 Andante (96 BPM)",
            "[DRY RUN] 04 - Delta Line.flac \u2192 Presto (140 BPM)",
            "[DRY RUN] 05 - Epsilon Down.mp3 \u2192 Andante (88 BPM)",
            "[DRY RUN] 06 - Zeta Pull.flac \u2192 Allegro (132 BPM)",
        ),
        slots=_busy_slots("Reading"),
    ),
    "track_splitter": SampleRun(
        status="Splitting: Sample Album",
        lines=tuple(f"[{name}] 3 tracks (3 written)" for name in _FINISHED),
        slots=_busy_slots("Splitting"),
        stats=f"Files: {SAMPLE_DONE}/9  |  Errors: 0",
        summary=(
            f"Files: {len(SAMPLE_TRACKS)}\n"
            f"Tracks: {len(SAMPLE_TRACKS) * 3}\n"
            f"Written: {len(SAMPLE_TRACKS) * 3}\n"
            "Errors: 0"
        ),
    ),
    "audio_joiner": SampleRun(
        status="Joining: Sample Album",
        lines=tuple(
            f"{name}  {_joiner_clock(ms)}" for name, ms in zip(_FINISHED, _JOINER_MS)
        ),
        slots=_busy_slots("Joining"),
        stats=f"Segments: {SAMPLE_DONE}/{len(SAMPLE_TRACKS)}  |  Errors: 0",
        summary=(
            f"Segments: {len(SAMPLE_TRACKS)}\n"
            f"Length: {_joiner_clock(sum(_JOINER_MS))}\n"
            "Writer: stream copy\n"
            "Errors: 0"
        ),
    ),
}


@dataclass(frozen=True)
class ToolPlan:
    """How one tool's figures are produced.

    Every tab of the tool's notebook becomes one figure, named after the tab
    label, so a tool with a tab the plan never mentions still gets a picture of
    it.  What varies per tool is only how to build it, how big its window is,
    and - where the opening state is empty - which sample state to put on each
    tab.

    Attributes:
        tool_id: The guide folder under ``individual_programs/``.
        module: Dotted module that holds the application class.
        class_name: The application class, constructed with the Tk root.
        window: ``(width, height)`` every figure is captured at, and a window
            that paints another size fails the run.  ``None`` accepts the size
            the tool opens at and reports it, which is how a new tool's size is
            measured before it is pinned here.
        populate: Filler per figure name (``setup``, ``processing``, ...).  A
            figure with no filler shows the state the tool opens in, which is
            honest for a viewer and empty for a batch tool.
    """

    tool_id: str
    module: str
    class_name: str
    window: tuple[int, int] | None = None
    populate: Mapping[str, Callable[[Any], None]] = field(default_factory=dict)
    #: Tabs that are not photographed: one that only renders a finished scan's
    #: results shows empty panels and an empty chart on a fresh window, which is
    #: a picture of nothing.  The guide describes those tabs in prose instead.
    skip_tabs: frozenset[str] = frozenset()

    def build(self, root: tk.Tk) -> Any:
        """Construct the real application class on *root*.

        Imported here rather than at module scope so ``--help`` and the linters
        do not pay for twenty-seven tool imports, and so a broken tool module
        fails only the plan that needs it.

        Args:
            root: The Tk root the application composes itself into.

        Returns:
            The application instance.
        """
        module = importlib.import_module(self.module)
        factory: Callable[[tk.Tk], Any] = getattr(module, self.class_name)
        return factory(root)


def _sample_lines() -> list[str]:
    """Return the per-file status lines the sample run shows.

    The shape matches what ``bpm_analyzer.core.file_processor`` publishes, so the
    Processing figure reads like a real run rather than invented prose.

    Returns:
        One display line per sample track, in order.
    """
    skip_name, skip_reason = SAMPLE_SKIP
    lines: list[str] = []
    for name, bpm in SAMPLE_TRACKS:
        if name == skip_name:
            lines.append(f"[SKIP] {name}: {skip_reason}")
        elif name == SAMPLE_OUTSIDE:
            lines.append(f"[DRY RUN] {name} {_ARROW} {bpm} BPM (outside 75-175)")
        else:
            lines.append(f"[DRY RUN] {name} {_ARROW} {bpm} BPM")
    return lines


_TOKEN_PATTERN = re.compile(r"^\[([A-Z][A-Z0-9 _-]*)\]")


def _status_token(line: str) -> str | None:
    """Return the bracketed status token a per-file line opens with.

    Args:
        line: One display line, e.g. ``"[FINGERPRINT] song.mp3"``.

    Returns:
        The token without its brackets, or ``None`` when the line has none.
    """
    match = _TOKEN_PATTERN.match(line.strip())
    return match.group(1) if match else None


def _tokens_of(lines: Iterable[str]) -> frozenset[str]:
    """Return every status token the given lines open with.

    Args:
        lines: Display lines, with or without a bracketed token.

    Returns:
        The tokens, without brackets.
    """
    tokens: set[str] = set()
    for line in lines:
        token = _status_token(line)
        if token is not None:
            tokens.add(token)
    return frozenset(tokens)


def _declared_lines() -> Mapping[str, frozenset[str]]:
    """Return every tool's declared sample lines, BPM Analyzer's included.

    Returns:
        One frozenset of display lines per tool.  BPM Analyzer's lines are
        generated by :func:`_sample_lines` rather than declared in
        :data:`SAMPLE_RUNS`, so they are added here: its vocabulary is the one
        every other tool's Processing figure used to carry.
    """
    declared = {tool_id: frozenset(run.lines) for tool_id, run in SAMPLE_RUNS.items()}
    declared["bpm_analyzer"] = frozenset(_sample_lines())
    return declared


#: Every display line any tool's sample run declares, so a figure that carries
#: another tool's line can be named rather than silently shipped.
DECLARED_LINES: Mapping[str, frozenset[str]] = _declared_lines()

#: Inverted :data:`DECLARED_LINES`: one line to the tools that declare it.
_LINE_OWNERS: Mapping[str, frozenset[str]] = {
    line: frozenset(
        tool_id for tool_id, lines in DECLARED_LINES.items() if line in lines
    )
    for lines in DECLARED_LINES.values()
    for line in lines
}

#: Every bracketed status token any sample run declares, to the tools using it.
#: A token only one tool publishes is how a leaked vocabulary is recognised.
TOKEN_OWNERS: Mapping[str, frozenset[str]] = {
    token: frozenset(
        tool_id
        for tool_id, lines in DECLARED_LINES.items()
        if token in _tokens_of(lines)
    )
    for token in {
        token
        for tool_id in DECLARED_LINES
        for token in _tokens_of(DECLARED_LINES[tool_id])
    }
}


def _displayed_lines(widget: Any) -> list[str]:
    """Return the lines a Processing-tab widget currently shows.

    Args:
        widget: The tab's listbox, text widget or tree.

    Returns:
        The displayed lines; empty for a widget that holds none (a Treeview, or
        a tab whose filler changed nothing).
    """
    if isinstance(widget, tk.Listbox):
        return [str(line) for line in widget.get(0, tk.END)]
    if isinstance(widget, tk.Text):
        return widget.get("1.0", "end-1c").splitlines()
    return []


def _check_sample_content(tool_id: str, run: SampleRun, shown: Sequence[str]) -> None:
    """Fail when a filled figure is empty or shows another tool's vocabulary.

    The capture's silent failure mode is a filler that changes nothing: the
    figure then looks like an idle window under a "part-way through a run"
    caption, which no compile, lint or type check can see.  A filled figure must
    therefore show the run it was filled with and nothing another tool declares.

    Args:
        tool_id: The guide folder of the tool being captured.
        run: The sample run declared for this tool.
        shown: The lines the filled widget displays.

    Raises:
        RuntimeError: If the figure is empty, carries another tool's declared
            line or status token, or no longer shows this tool's own lines.
    """
    if not run.lines:
        return
    if not shown:
        raise RuntimeError(
            "the Processing tab is still empty after the sample run was filled into it"
        )

    foreign = [
        line
        for line in shown
        if line not in run.lines and _LINE_OWNERS.get(line, frozenset()) - {tool_id}
    ]
    if foreign:
        others = ", ".join(sorted(_LINE_OWNERS[foreign[0]] - {tool_id}))
        raise RuntimeError(
            f"the Processing tab shows {foreign[0]!r}, which {others} declares"
        )

    own_tokens = _tokens_of(run.lines)
    for token in sorted(_tokens_of(shown) - own_tokens):
        owners = TOKEN_OWNERS.get(token, frozenset()) - {tool_id}
        if owners:
            raise RuntimeError(
                f"the Processing tab shows [{token}], which "
                f"{', '.join(sorted(owners))} publishes"
            )

    if shown[-len(run.lines) :] != list(run.lines):
        raise RuntimeError(
            f"the Processing tab shows {len(shown)} line(s) that are not this "
            "tool's sample run"
        )


def _populate_setup(app: Any) -> None:
    """Put the Setup tab in the state the guide's first figure shows.

    Args:
        app: The live BPM Analyzer application.
    """
    app.folder_path.set(SAMPLE_FOLDER)
    app.run_mode.set("Dry Run")
    app.bpm_range_min.set(75)
    app.bpm_range_max.set(175)
    app.analysis_duration.set(90)
    app.parallel_mode.set(False)


def _populate_processing(app: Any) -> None:
    """Fill the Processing tab with the sample run part-way through.

    The tab is filled through the tool's own ``_update_progress_ui``, so the
    progress bar, the counters and the per-file lines are the widgets a real run
    writes rather than labels set here.

    Args:
        app: The live BPM Analyzer application.
    """
    lines = _sample_lines()
    for index, line in enumerate(lines[:SAMPLE_DONE]):
        app._update_progress_ui(index + 1, len(lines), 0, 0, line)
    app.overall_status.set("Analyzing BPM...")
    app.start_btn.config(state="disabled")
    for position, slot in enumerate(app.slot_vars):
        if position < 2:
            name = SAMPLE_TRACKS[SAMPLE_DONE + position][0]
            slot.set(f"Analyzing: {name[:25]}...")
        else:
            slot.set("IDLE")


def _populate_results(app: Any) -> None:
    """Fill the Results tab with the sample run's finished summary.

    ``_update_ui_on_complete`` is the tool's own Results renderer: it labels the
    completion from the run mode and adds the out-of-band row the BPM guide
    documents, so the figure shows what a finished Dry Run actually shows.

    Args:
        app: The live BPM Analyzer application.
    """
    total = len(SAMPLE_TRACKS)
    app.run_mode.set("Dry Run")
    app._update_ui_on_complete(
        total=total,
        tagged=total - 1,
        skipped=1,
        errors=0,
        minutes=0,
        seconds=SAMPLE_SECONDS,
        summary_extras=[("Outside BPM range", f"1 of {total} tracks (band 75-175)")],
    )


def _figure_name(title: str) -> str:
    """Return the figure name for a notebook tab title.

    ``" 1. Setup "`` becomes ``setup`` and ``"  Setup & Lookup  "`` becomes
    ``setup_lookup``: the leading step number is dropped, so a tool that numbers
    its tabs and one that does not produce the same file names, and every
    non-alphanumeric run becomes a single underscore.

    Args:
        title: The tab label the tool added to its notebook.

    Returns:
        A lower-case file stem.
    """
    words: list[str] = []
    for word in re.findall(r"[a-z0-9]+", title.lower()):
        if not words and word.isdigit():
            continue
        words.append(word)
    return "_".join(words) or "tab"


def _find_widget(app: Any, *names: str) -> Any:
    """Return the first of *names* the application holds.

    A tool may keep the shell's widget as ``file_listbox`` or ``_file_listbox``,
    and the mood batch tagger keeps its widgets in a ``_proc`` dict, so a figure
    filler cannot assume one spelling.

    Args:
        app: The live application.
        *names: Attribute (or dict) names to try, in order.

    Returns:
        The widget or Tk variable, or ``None`` when the tool has none of them.
    """
    for name in names:
        widget = getattr(app, name, None)
        if widget is not None:
            return widget
    for group_name in ("_proc", "_res"):
        group = getattr(app, group_name, None)
        if isinstance(group, Mapping):
            for name in names:
                widget = group.get(name)
                if widget is not None:
                    return widget
    return None


def _set_text(widget: Any, text: str) -> None:
    """Show *text* in a label or a Tk string variable.

    Args:
        widget: A label, a string variable, or ``None`` when the tool has none.
        text: The text to show.
    """
    if isinstance(widget, tk.StringVar):
        widget.set(text)
    elif widget is not None and hasattr(widget, "configure"):
        widget.configure(text=text)


def _progress_of(app: Any, anchor: Any) -> ttk.Progressbar | None:
    """Return the tool's progress bar.

    ``SuiteApp`` publishes it as ``progress``; a hand-built tab keeps it in a
    local variable, so the widget is also looked for among the listbox's
    ancestors' children.

    Args:
        app: The live application.
        anchor: A widget on the Processing tab, used to search its ancestors.

    Returns:
        The bar, or ``None`` when the tool has none.
    """
    bar = _find_widget(app, "progress")
    if isinstance(bar, ttk.Progressbar):
        return bar
    frame = getattr(anchor, "master", None)
    while frame is not None:
        for child in frame.winfo_children():
            if isinstance(child, ttk.Progressbar):
                return child
        frame = getattr(frame, "master", None)
    return None


def _slot_variables(app: Any) -> list[Any]:
    """Return the tool's worker-slot variables.

    Args:
        app: The live application.

    Returns:
        The slot variables, or an empty list for a tool without a worker grid.
    """
    for name in ("slot_vars", "_safe_slot_vars"):
        value = getattr(app, name, None)
        if isinstance(value, list):
            return value
    return []


def _populate_run_setup(app: Any) -> None:
    """Fill the source folder and run mode a Setup tab opens empty.

    Args:
        app: The live application.
    """
    for attribute in (
        "folder_path",
        "source_folder",
        "input_folder",
        "source_path",
        "directory",
    ):
        variable = getattr(app, attribute, None)
        if variable is not None and hasattr(variable, "set"):
            variable.set(SAMPLE_FOLDER)
            break
    mode = getattr(app, "run_mode", None)
    if isinstance(mode, tk.StringVar):
        mode.set("Dry Run")


def _populate_refinery_setup(app: Any) -> None:
    """Show the stage selection a first launch starts with.

    The six stage switches are restored from the pipeline's saved settings, so a
    capture would otherwise photograph whichever stages the person running it
    last left enabled: the figure committed for 2.7.0 showed Parametric EQ as the
    only active stage, while the guide described the four defaults.  The panel's
    own BooleanVars are set and ``app.config`` with them, so the figure and the
    configuration it depicts agree - nothing here changes what a click writes.

    Args:
        app: The live Audio Refinery application.
    """
    toggles = {
        "declick": True,
        "trim": True,
        "reduce_noise": False,
        "eq": False,
        "enhance": True,
        "normalise": True,
    }
    stage_vars = app._setup_state["stage_vars"]
    for name, enabled in toggles.items():
        stage_vars[name].set(enabled)
        setattr(app.config, name, enabled)


def _populate_run_processing(app: Any, run: SampleRun, tool_id: str) -> None:
    """Show *run* part-way through on the tool's Processing tab.

    The lines are the tool's own vocabulary, so the figure reads as that tool's
    run.  What the tab then displays is read back and checked, so a filler that
    changes nothing - or one that leaves another tool's lines in place - fails
    the capture instead of shipping an idle frame under a "part-way through a
    run" caption.

    Args:
        app: The live application.
        run: The sample run declared for this tool.
        tool_id: The guide folder of the tool being captured.

    Raises:
        RuntimeError: If the tab has no listbox to show the lines in, or the
            filled figure fails :func:`_check_sample_content`.
    """
    box = _find_widget(
        app, "file_listbox", "_file_listbox", "log_list", "log_text", "tree"
    )
    if box is None:
        raise RuntimeError(
            "the Processing tab has no listbox, text or tree for the sample "
            "run's per-file lines"
        )
    if isinstance(box, tk.Listbox):
        for line in run.lines:
            box.insert(tk.END, line)
        box.see(tk.END)
    elif isinstance(box, tk.Text):
        for line in run.lines:
            box.insert(tk.END, line + "\n")
        box.see(tk.END)
    # A Treeview keeps its rows untouched: ReplayGain Analyzer's tree receives a
    # row only when a measurement lands, so its mid-run frame is the worker grid
    # and the counters, which are still filled above.

    total = len(SAMPLE_TRACKS)
    bar = _progress_of(app, box)
    if bar is not None:
        bar.configure(maximum=total, value=SAMPLE_DONE)

    _set_text(
        _find_widget(app, "stats_label", "_stats_label"),
        run.stats or f"Processed: {SAMPLE_DONE}/{total}  |  Skipped: 1  |  Errors: 0",
    )
    _set_text(
        _find_widget(app, "overall_status", "status_txt", "_status_var"),
        run.status,
    )
    for position, variable in enumerate(_slot_variables(app)):
        label = run.slots[position] if position < len(run.slots) else "IDLE"
        variable.set(label)

    _check_sample_content(tool_id, run, _displayed_lines(box))


def _populate_run_results(app: Any, run: SampleRun) -> None:
    """Show *run*'s finished summary on the tool's Results tab.

    Args:
        app: The live application.
        run: The sample run declared for this tool.
    """
    total = len(SAMPLE_TRACKS)
    heading = run.completion or str(getattr(app, "completion_text", "Complete!"))
    _set_text(_find_widget(app, "completion_label"), heading)
    _set_text(
        _find_widget(app, "summary_label"),
        run.summary or f"Processed: {total}  |  Skipped: 1  |  Errors: 0",
    )
    minutes, seconds = divmod(run.seconds, 60)
    _set_text(
        _find_widget(app, "time_label"),
        f"Total Time: {minutes:02d}:{seconds:02d}",
    )
    button = getattr(app, "start_btn", None)
    if button is not None and hasattr(button, "configure"):
        button.configure(state="normal")


def _populate_asx_processing(app: Any) -> None:
    """Show the ASX extractor part-way through its six-step run.

    That tab animates six step labels instead of listing files, so the sample
    run is driven through the tool's own ``_update_step`` callable: three steps
    done and the fourth active with the file counter its run appends.

    Args:
        app: The live ASX Playlist Extractor application.

    Raises:
        RuntimeError: If the window does not publish its step updater, which
            would leave the figure showing an untouched tab.
    """
    update_step = getattr(app, "_update_step", None)
    if not callable(update_step):
        raise RuntimeError("the Processing tab does not publish its step updater")
    reset = getattr(update_step, "reset", None)
    if callable(reset):
        reset()
    for index in range(3):
        update_step(index, "done")
    update_step(3, "active", "  - 6 of 9 files")


def _populate_audio_joiner_setup(app: Any) -> None:
    """Fill the Setup tab with the sample segments, in join order.

    The folder in the figure does not exist on this host, so the list is filled
    from the declared plan rather than by reading the disk: the figure shows
    the order and the planned length the window displays for that order.

    Args:
        app: The live Audio Joiner application.
    """
    _populate_run_setup(app)
    mode = getattr(app, "run_mode", None)
    if isinstance(mode, tk.StringVar):
        mode.set("Live Update")
    segments = [Path(SAMPLE_FOLDER) / name for name in _NAMES]
    app._segments = segments
    app._durations = dict(zip(segments, _JOINER_MS))
    output = getattr(app, "output_path", None)
    if isinstance(output, tk.StringVar):
        output.set(SAMPLE_FOLDER + "\\Sample Album_joined.flac")
    app._render_segments()


def _populate_track_splitter_setup(app: Any) -> None:
    """Fill the Setup tab with the sample folder, in the mode its run shows.

    The shared filler selects Dry Run, which would contradict a Processing
    figure whose lines report files written; the sample run is a live one, so
    the mode control says so too.

    Args:
        app: The live Track Splitter application.
    """
    _populate_run_setup(app)
    mode = getattr(app, "run_mode", None)
    if isinstance(mode, tk.StringVar):
        mode.set("Live Update")


#: Figures whose tab is not a list of per-file lines and so needs its own
#: filler: the extractor animates six step labels instead.
_PROCESSING_OVERRIDES: Mapping[str, Callable[[Any], None]] = {
    "asx_extractor": _populate_asx_processing,
}

#: Tools whose Setup tab opens with more state than a folder and a run mode.
#: The refinery's stage selection is a saved preference, so without this its
#: figure shows the last person to run the capture's stages, not the defaults.
_SETUP_OVERRIDES: Mapping[str, Callable[[Any], None]] = {
    "audio_refinery": _populate_refinery_setup,
}


def _fillers(tool_id: str) -> Mapping[str, Callable[[Any], None]]:
    """Return the figure fillers for one tool.

    Args:
        tool_id: The guide folder of the tool being captured.

    Returns:
        A filler for Setup, Processing and Results, each closing over that
        tool's own declared run.

    Raises:
        KeyError: If the tool wants filled figures and declares no run, which
            would otherwise put another tool's lines on its figure.
    """
    run = SAMPLE_RUNS.get(tool_id)
    if run is None:
        raise KeyError(
            f"{tool_id} has no entry in SAMPLE_RUNS: declare the run its figures "
            "should show, in the vocabulary its processor publishes"
        )

    def setup(app: Any) -> None:
        """Fill the Setup tab with the sample folder and the tool's own state."""
        _populate_run_setup(app)
        override = _SETUP_OVERRIDES.get(tool_id)
        if override is not None:
            override(app)

    def processing(app: Any) -> None:
        """Fill the Processing tab with this tool's run part-way through."""
        _populate_run_processing(app, run, tool_id)

    def results(app: Any) -> None:
        """Fill the Results tab with this tool's finished summary."""
        _populate_run_results(app, run)

    return {
        "setup": setup,
        "processing": _PROCESSING_OVERRIDES.get(tool_id) or processing,
        "results": results,
    }


def _plan_fillers(plan: ToolPlan) -> Mapping[str, Callable[[Any], None]]:
    """Return the fillers for *plan*'s figures.

    A plan that keeps :data:`GENERIC_POPULATE` takes its content from the run
    declared for its own tool, so no tool can be captured showing another
    tool's per-file lines.

    Args:
        plan: The tool plan being captured.

    Returns:
        One filler per figure name.
    """
    if plan.populate is GENERIC_POPULATE:
        return _fillers(plan.tool_id)
    return plan.populate


#: Sentinel for "this plan's figures are filled from the run declared for its
#: own tool".  A plan keeps this mapping, or passes ``{}`` for a window that
#: starts no run; no plan can supply another tool's lines by accident.
GENERIC_POPULATE: Mapping[str, Callable[[Any], None]] = {}

#: Every GUI tool that has a guide, in guide-folder order.  ``window`` is
#: ``None`` until a capture has measured what the tool paints; the run prints the
#: realised size so it can be pinned, and a pinned size is then asserted, so a
#: layout change that moves the window fails the run instead of silently
#: re-framing the guide's figures.
TOOL_PLANS: tuple[ToolPlan, ...] = (
    ToolPlan(
        "album_art_normalizer",
        "album_art_normalizer.app",
        "ArtNormalizerApp",
        # Every ``window`` below is what the tool painted when it was measured,
        # and is now asserted, so a layout change that resizes a window fails
        # the capture instead of silently re-framing a committed figure.
        window=(900, 572),
        populate=GENERIC_POPULATE,
    ),
    ToolPlan(
        "album_art_sync",
        "album_art_sync.app",
        "AudioSuiteV6",
        window=(900, 639),
        populate=GENERIC_POPULATE,
    ),
    ToolPlan(
        "album_genre_tagger",
        "album_genre_tagger.app",
        "GenreConsolidatorApp",
        window=(1600, 672),
        populate=GENERIC_POPULATE,
    ),
    ToolPlan(
        "asx_extractor",
        "asx_extractor.app",
        "ASXExtractorTool",
        window=(900, 576),
        populate=GENERIC_POPULATE,
    ),
    ToolPlan(
        "audio_fingerprinter",
        "audio_fingerprinter.app",
        "FingerprinterApp",
        window=(1000, 1007),
        populate=GENERIC_POPULATE,
    ),
    ToolPlan(
        "audio_refinery",
        "audio_refinery.app",
        "AudioRefineryApp",
        window=(900, 675),
        populate=GENERIC_POPULATE,
    ),
    ToolPlan(
        "bpm_analyzer",
        "bpm_analyzer.app",
        "BPMAnalyzerApp",
        # 1120 wide is what the Setup tab's run-controls row needs before the
        # Parallel checkbox and the "(driver only)" note are cut off; 760 tall
        # shows the start button at the frame's bottom edge and leaves the
        # Processing tab a file list with room to read.  Both were measured on
        # the real window, not guessed from the layout's request.
        window=(1120, 760),
        populate={
            "setup": _populate_setup,
            "processing": _populate_processing,
            "results": _populate_results,
        },
    ),
    ToolPlan(
        "channel_tools",
        "channel_tools.app",
        "ChannelToolsApp",
        # The tab is wider than the size the window asks for: its rule line and
        # the note under the start button wrap at 760 px, and the tool's own
        # request (660x440 at 100 %) cuts both off.  900x640 shows the whole
        # Setup tab, the start button and the note, measured on the real window.
        window=(900, 640),
        populate=GENERIC_POPULATE,
    ),
    ToolPlan(
        "cd_ripper",
        "cd_ripper.app",
        "CDRipperApp",
        window=(900, 950),
        # Ripping needs a disc in a drive, which a capture run cannot provide,
        # so its tabs are photographed in the state they open in.
        populate={},
    ),
    ToolPlan(
        "duplicate_finder",
        "duplicate_finder.ui.app",
        "DuplicateFinderApp",
        window=(900, 795),
        populate=GENERIC_POPULATE,
    ),
    ToolPlan(
        "file_reorganizer",
        "file_reorganizer.app",
        "FileReorganizerApp",
        window=(900, 770),
        populate=GENERIC_POPULATE,
    ),
    ToolPlan(
        "genre_sync",
        "genre_sync.app",
        "GenreSetterApp",
        window=(900, 577),
        populate=GENERIC_POPULATE,
    ),
    ToolPlan(
        "key_detector",
        "key_detector.app",
        "KeyDetectorApp",
        window=(900, 551),
        populate=GENERIC_POPULATE,
    ),
    ToolPlan(
        "library_stats",
        "library_stats.app",
        "LibraryStatsApp",
        window=(1334, 533),
        populate=GENERIC_POPULATE,
        # Changed in 2.6.0: the Artwork Gaps view has no data until a scan
        # runs, like the other dashboard tabs, so it is skipped for the reason.
        skip_tabs=frozenset(
            {"summary", "charts", "missing_data", "completeness", "artwork_gaps"}
        ),
    ),
    ToolPlan(
        "lyrics_manager",
        "lyrics_manager.app",
        "LyricsManagerApp",
        window=(900, 738),
        populate=GENERIC_POPULATE,
    ),
    ToolPlan(
        "master_driver",
        "master_driver.app",
        "AudioSuiteDriver",
        window=(1250, 950),
        # The driver validates its source directory on change and clears the
        # field when the path does not exist, so its figure shows the window as
        # it opens - no music selected - rather than a folder that is not there.
        # It starts no batch run of its own, so there is none to show.
        populate={},
    ),
    ToolPlan(
        "metadata_scrubber",
        "metadata_scrubber.app",
        "MetadataScrubberApp",
        window=(900, 804),
        populate=GENERIC_POPULATE,
    ),
    ToolPlan(
        "ml_denoiser",
        "ml_denoiser.app",
        "MlDenoiserApp",
        window=(900, 625),
        populate=GENERIC_POPULATE,
    ),
    ToolPlan(
        "mood_analysis_batch_tagger",
        "mood_analysis_batch_tagger.app",
        "MoodAnalysisBatchTaggerApp",
        window=(900, 754),
        populate=GENERIC_POPULATE,
    ),
    ToolPlan(
        "mood_analyzer",
        "mood_analyzer.app",
        "MoodAnalyzerApp",
        window=(900, 670),
        populate=GENERIC_POPULATE,
    ),
    ToolPlan(
        "music_format_converter",
        "music_format_converter.app",
        "MusicFormatConverterApp",
        # The Setup tab asks for 1106 rows, which does not fit above a 1152 px
        # screen's taskbar; 1040 is the height it still lays out in, measured on
        # the real window.
        window=(900, 1040),
        populate=GENERIC_POPULATE,
    ),
    ToolPlan(
        "replaygain_analyzer",
        "replaygain_analyzer.app",
        "ReplayGainAnalyzerApp",
        window=(900, 652),
        populate=GENERIC_POPULATE,
    ),
    ToolPlan(
        "restoration",
        "restoration.ui.app",
        "RestorationApp",
        window=(900, 684),
        populate=GENERIC_POPULATE,
    ),
    ToolPlan(
        "spectral_viewer",
        "spectral_viewer.app",
        "SpectralViewerApp",
        # A single-pane viewer: no notebook, so its one figure is the window,
        # and it starts no run to show on it.
        window=(1200, 800),
        populate={},
    ),
    ToolPlan(
        "stem_separator",
        "stem_separator.app",
        "StemSeparatorApp",
        window=(900, 880),
        populate=GENERIC_POPULATE,
    ),
    ToolPlan(
        "tag_editor",
        "tag_editor.ui.app",
        "TagEditorApp",
        window=(1239, 868),
        populate=GENERIC_POPULATE,
    ),
    ToolPlan(
        "tag_field_updater",
        "tag_field_updater.ui.app",
        "TagFieldUpdaterApp",
        window=(900, 707),
        populate=GENERIC_POPULATE,
    ),
    ToolPlan(
        "tempo_analyzer",
        "tempo_analyzer.app",
        "TempoAnalyzerApp",
        window=(900, 767),
        populate=GENERIC_POPULATE,
    ),
    ToolPlan(
        "audio_joiner",
        "audio_joiner.app",
        "AudioJoinerApp",
        window=(900, 700),
        populate={
            **_fillers("audio_joiner"),
            "setup": _populate_audio_joiner_setup,
        },
    ),
    ToolPlan(
        "track_splitter",
        "track_splitter.app",
        "TrackSplitterApp",
        window=(900, 700),
        populate={
            **_fillers("track_splitter"),
            "setup": _populate_track_splitter_setup,
        },
    ),
    ToolPlan(
        "undo_tag_edits",
        "audio_suite_shared.undo_gui",
        "UndoTagEditsApp",
        # 760x620 is the size the tool asks ``setup_window`` for; a single-pane
        # window, so its one figure is the window itself - and its content is
        # the user's own run history, not a sample run.
        window=(760, 620),
        populate={},
    ),
)


def _install_overrides(plan: ToolPlan) -> list[tuple[Any, str, Any]]:
    """Answer the tools' machine state from memory, returning what to restore.

    The shared config is patched at module-attribute level because every consumer
    calls ``suite_config.<name>`` at call time, so a saved palette, theme,
    typography, geometry or last directory cannot reach the captured window.

    Args:
        plan: The plan whose fixed window size is installed.

    Returns:
        ``(module, attribute, original)`` triples, for :func:`_restore`.
    """
    import audio_suite_shared.suite_config as suite_config
    from audio_suite_shared import platform_utils

    store: dict[str, Any] = {}

    def load_value(key: str, default: Any = None) -> Any:
        """Return a value saved earlier in this capture run."""
        return store.get(key, default)

    def save_value(key: str, value: Any) -> None:
        """Keep a value in memory instead of the shipped configuration file."""
        store[key] = value

    def load_last_directory() -> str:
        """Return no directory, so the figure shows only the sample folder."""
        return ""

    def _constant(value: Any) -> Callable[..., Any]:
        """Return a reader that always answers *value*."""

        def _reader(*_args: Any, **_kwargs: Any) -> Any:
            return value

        return _reader

    def setup_window(
        root: Any, width: int, height: int, config_module: Any, config_key: str
    ) -> None:
        """Open the window at the plan's fixed size and origin."""
        if plan.window is None:
            # No pinned size yet: the tool's own geometry is what is measured,
            # and :func:`capture_tool` reports it so it can be pinned here.
            return
        width_px, height_px = plan.window
        left, top = _window_origin(root, width_px, height_px)
        root.geometry(f"{width_px}x{height_px}+{left}+{top}")

    replacements: tuple[tuple[Any, str, Any], ...] = (
        (suite_config, "load_value", load_value),
        (suite_config, "save_value", save_value),
        (suite_config, "load_last_directory", load_last_directory),
        (suite_config, "load_palette", _constant(CAPTURE_PALETTE)),
        (suite_config, "load_theme_mode", _constant(CAPTURE_THEME)),
        (suite_config, "load_font_family", _constant(None)),
        # An empty mapping, not None: the Master Driver iterates the saved sizes
        # (``font_sizes.items()``) before it builds a widget, so a None here
        # fails the one tool whose window is the hub.
        (suite_config, "load_font_sizes", _constant({})),
        (platform_utils, "setup_window", setup_window),
    )
    restore: list[tuple[Any, str, Any]] = []
    for module, name, replacement in replacements:
        restore.append((module, name, getattr(module, name)))
        setattr(module, name, replacement)
    return restore


def _restore(restore: list[tuple[Any, str, Any]]) -> None:
    """Put every patched attribute back.

    Args:
        restore: The triples :func:`_install_overrides` returned.
    """
    for module, name, original in restore:
        setattr(module, name, original)


def _notebook_of(app: Any) -> Any:
    """Return the tool's notebook, whichever name it stores the widget under.

    ``SuiteApp`` publishes the notebook as ``notebook``; the hand-built windows
    keep the same widget as ``_notebook``.  Both are the tool's tabs, so the
    capture must not depend on which name a tool happens to use.

    Args:
        app: The live application.

    Returns:
        The ``ttk.Notebook``, or ``None`` for a single-pane window.
    """
    for attribute in ("notebook", "_notebook"):
        widget = getattr(app, attribute, None)
        if isinstance(widget, ttk.Notebook):
            return widget
    return None


def _window_origin(root: tk.Tk, width: int, height: int) -> tuple[int, int]:
    """Return a screen position that keeps the whole client area on screen.

    A tall window (the format converter's Setup tab is 1106 px) does not fit
    below a fixed 120 px inset on a 1152 px display, and the grab refuses a
    rectangle that runs off the edge - correctly, because the part that does not
    fit would be copied from whatever is underneath.  The inset is kept where it
    fits and reduced towards :data:`MIN_WINDOW_INSET` where it does not.

    Args:
        root: The window being positioned.
        width: Client width in pixels.
        height: Client height in pixels.

    Returns:
        ``(left, top)`` in screen pixels.
    """
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    left = min(WINDOW_ORIGIN[0], max(0, screen_width - width - MIN_WINDOW_INSET))
    top = min(WINDOW_ORIGIN[1], max(0, screen_height - height - WORK_AREA_MARGIN))
    return left, top


def _capture_geometry(width: int, height: int, dpi: int) -> tuple[int, int]:
    """Return the window size to request so a plan's layout is unchanged.

    Every plan pins its window in the pixels of a 100% display.  Once the
    process is DPI aware, Tk measures in the display's own pixels, so asking for
    1120 on a 125% display would lay the tool out in 896 logical px and clip it.
    The request is therefore scaled, and :func:`_grab` scales the figure back
    down to the plan's size.

    Args:
        width: Client width the plan pins, at 100% scaling.
        height: Client height the plan pins, at 100% scaling.
        dpi: The display's pixels per inch.

    Returns:
        ``(width, height)`` in the display's own pixels.
    """
    return (
        round(width * dpi / CAPTURE_DPI),
        round(height * dpi / CAPTURE_DPI),
    )


def _enable_dpi_awareness() -> None:
    """Let Tk, Win32 and the grab share one pixel grid.

    A DPI-unaware process is told a different story by each: Tk reports logical
    sizes while ``ImageGrab`` copies physical pixels, so on a scaled display a
    grab of ``winfo_height`` reaches only part of the window.  The remainder of
    the figure is window background, and anything docked at the bottom - a Setup
    tab's start button - never reaches the picture.  Awareness also makes the
    :data:`CAPTURE_DPI` guard meaningful, because Tk then reports the display's
    real scaling instead of a flat 96.
    """
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return
    try:
        windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            return


def _fit_window(root: tk.Tk, width: int, height: int) -> tuple[int, int, int, int]:
    """Place the window so its whole client area is grabbable, and measure it.

    Windows applies its own frame offset to a requested position: asking for
    ``+120+120`` puts Tk at ``128,151`` and the paint a further 34 px right and
    40 px down.  A requested origin is therefore never the painted one, and a
    tall window asked for at the top can still paint past the bottom of the
    screen.  The first calibration measures the error, the request is corrected
    by it, and the corrected window is measured again - the offset is constant
    for a window style, so one correction is enough.

    Args:
        root: The window to place.
        width: Client width in pixels.
        height: Client height in pixels.

    Returns:
        ``(left, top, width, height)`` as painted, ready for the grab.
    """
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    left, top = _window_origin(root, width, height)
    root.geometry(f"{width}x{height}+{left}+{top}")
    root.update_idletasks()
    root.update()
    rect = _calibrate(root)
    for _ in range(2):
        target_left = min(max(rect[0], 0), max(0, screen_width - width))
        target_top = min(
            max(rect[1], 0), max(0, screen_height - height - WORK_AREA_MARGIN)
        )
        if (target_left, target_top) == (rect[0], rect[1]):
            break
        left += target_left - rect[0]
        top += target_top - rect[1]
        root.geometry(f"{width}x{height}+{left}+{top}")
        root.update_idletasks()
        root.update()
        rect = _calibrate(root)
    return rect


def _select_tab(app: Any, index: int) -> None:
    """Show the notebook tab at *index*.

    Args:
        app: The live application.
        index: The tab's position in the notebook.
    """
    notebook = _notebook_of(app)
    if notebook is None:
        return
    # A tool may open with a tab disabled until the state that fills it exists -
    # the CD Ripper disables Rip and Results until a disc is read.  A guide
    # documents those tabs, so the capture enables the one it is photographing
    # instead of pointing the camera at a tab that cannot be shown.
    try:
        notebook.tab(index, state="normal")
    except tk.TclError:
        pass
    notebook.select(index)


def _tab_titles(app: Any) -> list[str]:
    """Return the tool's notebook tab labels, in order.

    Args:
        app: The live application.

    Returns:
        One stripped label per tab, or an empty list when the window has no
        notebook (a single-pane viewer, or a build that failed early).
    """
    notebook = _notebook_of(app)
    if notebook is None:
        return []
    labels: list[str] = []
    for index in range(len(notebook.tabs())):
        labels.append(str(notebook.tab(index, "text")).strip())
    return labels


def _hex_rgb(colour: str) -> tuple[int, int, int]:
    """Return a ``#rrggbb`` colour as an RGB triple.

    Args:
        colour: A six-digit hex colour.

    Returns:
        The red, green and blue channels.
    """
    return int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16)


def _locate_colour(
    image: Image.Image, colour: tuple[int, int, int]
) -> tuple[int, int] | None:
    """Return the first pixel of *colour* in *image*, top to bottom.

    Args:
        image: The screen grab to search.
        colour: The RGB triple to look for.

    Returns:
        ``(x, y)`` of the first match, or ``None`` when the colour is absent.
    """
    import numpy as np

    pixels = np.asarray(image.convert("RGB"))
    rows, columns = np.nonzero(
        (pixels[:, :, 0] == colour[0])
        & (pixels[:, :, 1] == colour[1])
        & (pixels[:, :, 2] == colour[2])
    )
    if not rows.size:
        return None
    return int(columns[0]), int(rows[0])


def _locate_block(
    image: Image.Image, colour: tuple[int, int, int], minimum: int
) -> tuple[int, int] | None:
    """Return the top-left pixel of the first solid block of *colour*.

    One matching pixel is not evidence: the desktop behind the window can hold
    the marker's exact colour by coincidence, which measured a window 279 px too
    wide during development.  A run of *minimum* matching pixels across and down
    is a widget, not a screenshot's stray dot.

    Args:
        image: The screen grab to search.
        colour: The RGB triple to look for.
        minimum: How many pixels the run must hold in both directions.

    Returns:
        ``(x, y)`` of the block's top-left corner, or ``None`` when absent.
    """
    import numpy as np

    pixels = np.asarray(image.convert("RGB"))
    mask = (
        (pixels[:, :, 0] == colour[0])
        & (pixels[:, :, 1] == colour[1])
        & (pixels[:, :, 2] == colour[2])
    )
    rows, columns = np.nonzero(mask)
    for row, column in zip(rows.tolist(), columns.tolist()):
        if not mask[row, column : column + minimum].all():
            continue
        if not mask[row : row + minimum, column].all():
            continue
        return column, row
    return None


def _calibrate(root: tk.Tk) -> tuple[int, int, int, int]:
    """Measure where the window's client area really is, in screen pixels.

    Only the *origin* has to be measured.  Tk's ``winfo_width``/``winfo_height``
    are the client area the window paints, and :func:`capture_tool` asserts them
    against the plan, so the size is known.  The origin is not: the position a
    decorated window is asked for is never the one it paints at (see the module
    docstring).

    A marker frame at the client's top-left corner supplies it.  A second marker
    at the opposite corner was tried first and abandoned: at the window's
    extreme edge Windows clips the corner pixels away, so it never appeared,
    while a full-desktop search for its colour found an unrelated pixel 279 px
    away and silently measured the window too wide.

    Args:
        root: The positioned, raised, updated window.

    Returns:
        ``(left, top, width, height)`` in screen pixels.

    Raises:
        RuntimeError: If the marker is not on screen, which means the window is
            covered, off-screen or was never mapped.
    """
    marker = tk.Frame(root, bg=TOP_LEFT_MARKER, width=MARKER_SIZE, height=MARKER_SIZE)
    marker.place(
        x=MARKER_INSET,
        y=MARKER_INSET,
        width=MARKER_SIZE,
        height=MARKER_SIZE,
    )
    marker.lift()
    root.deiconify()
    root.update_idletasks()
    root.update()

    # A decorated toplevel is composited asynchronously, so the first grab can be
    # taken before the window has painted at all - which looks exactly like a
    # covered window.  Poll briefly instead of failing on the first attempt.
    import time

    found = None
    for _ in range(8):
        found = _locate_block(ImageGrab.grab(), _hex_rgb(TOP_LEFT_MARKER), MARKER_SIZE)
        if found is not None:
            break
        time.sleep(0.25)
        root.update()
    origin = (found[0] - MARKER_INSET, found[1] - MARKER_INSET) if found else None

    marker.destroy()
    root.update_idletasks()
    root.update()

    if origin is None:
        raise RuntimeError(
            "the capture marker is not on screen, so the window is covered, "
            "off-screen or was never mapped"
        )
    return origin[0], origin[1], root.winfo_width(), root.winfo_height()


def _grab(
    root: tk.Tk,
    plan: ToolPlan,
    figure: str,
    *,
    dpi: int,
) -> list[str]:
    """Raise the window, grab the calibrated rectangle, write PNG and sidecar.

    Args:
        root: The root window carrying the application.
        plan: The tool plan being captured.
        figure: The figure's file stem, e.g. ``setup``.
        dpi: The display's pixels per inch, recorded in the sidecar.

    Returns:
        Human-readable problems; empty when the figure was written.
    """
    # Position and calibrate per figure, not once per tool: a tool can restore
    # its own saved geometry from an idle callback, so a rectangle measured
    # before the first grab is stale by the second (the fingerprinter parked
    # itself 191 px down, which runs a 1007 px window off a 1152 px screen).
    root.lift()
    root.attributes("-topmost", True)
    if plan.window is not None:
        window = _capture_geometry(plan.window[0], plan.window[1], dpi)
        left, top, width, height = _fit_window(root, *window)
    else:
        root.update_idletasks()
        root.update()
        left, top, width, height = _calibrate(root)
    time.sleep(SETTLE_SECONDS)
    label = f"{plan.tool_id}/{IMAGE_DIRNAME}/{figure}.png"
    screen_width, screen_height = root.winfo_screenwidth(), root.winfo_screenheight()
    if (
        left < 0
        or top < 0
        or left + width > screen_width
        or top + height > screen_height
    ):
        return [
            f"{label}: the client area ({width}x{height} at {left},{top}) does not "
            f"fit the {screen_width}x{screen_height} screen, so part of it would "
            "be grabbed from whatever is underneath; close other windows or "
            "raise the display resolution"
        ]
    frame = ImageGrab.grab(bbox=(left, top, left + width, top + height))
    frame = frame.convert("RGB")

    if frame.size != (width, height):
        return [
            f"{label}: grabbed {frame.size[0]}x{frame.size[1]} for a "
            f"{width}x{height} window"
        ]
    census = frame.getcolors(maxcolors=MAX_FRAME_COLOURS)
    distinct = len(census) if census is not None else MAX_FRAME_COLOURS
    if distinct < MIN_FRAME_COLOURS:
        return [
            f"{label}: the frame has only {distinct} colours, so the window was "
            "blank or covered; unlock the desktop, close anything on top of the "
            "window and re-run"
        ]

    # The figure is committed at the size the plan pins, in the 100% layout, so
    # a scaled display's larger grab is scaled back down rather than shipped.
    committed = (
        round(width * CAPTURE_DPI / dpi),
        round(height * CAPTURE_DPI / dpi),
    )
    if frame.size != committed:
        frame = frame.resize(committed, Image.Resampling.LANCZOS)
    committed_colours = frame.getcolors(maxcolors=MAX_FRAME_COLOURS)
    distinct = (
        len(committed_colours) if committed_colours is not None else MAX_FRAME_COLOURS
    )

    destination = GUIDE_ROOT / plan.tool_id / IMAGE_DIRNAME
    destination.mkdir(parents=True, exist_ok=True)
    png = destination / f"{figure}.png"
    frame.save(png, format="PNG", optimize=True)
    sidecar = png.with_suffix(".json")
    sidecar.write_text(
        json.dumps(
            {
                "tool": plan.tool_id,
                "shot": figure,
                "tab": figure,
                "width": frame.size[0],
                "height": frame.size[1],
                "dpi": dpi,
                "palette": CAPTURE_PALETTE,
                "theme": CAPTURE_THEME,
                "png_sha256": hashlib.sha256(png.read_bytes()).hexdigest(),
                "png_bytes": png.stat().st_size,
                "captured_by": "utilities/capture_guide_shots.py",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"[OK] {label} ({frame.size[0]}x{frame.size[1]}, {distinct} colours)")
    return []


def capture_tool(plan: ToolPlan, *, force_dpi: bool) -> list[str]:
    """Capture every figure in *plan*.

    Args:
        plan: The tool's capture plan.
        force_dpi: Capture even when the display is not at :data:`CAPTURE_DPI`.

    Returns:
        Human-readable problems; empty when every figure was written.
    """
    problems: list[str] = []
    _enable_dpi_awareness()
    root = tk.Tk()
    # A normal, decorated toplevel: an ``overrideredirect`` window was tried
    # first, to make the client rect trivially measurable, but the marker
    # calibration supplies the client origin whatever the decorations are, so the
    # title bar is simply outside the grab.
    restore: list[tuple[Any, str, Any]] = []
    try:
        dpi = round(root.winfo_fpixels("1i"))
        if dpi != CAPTURE_DPI and not force_dpi:
            return [
                f"{plan.tool_id}: the display is at {dpi} dpi, not {CAPTURE_DPI}. "
                "Set Windows display scaling to 100% and re-run, or pass "
                "--force-dpi to accept figures no other host reproduces"
            ]
        restore = _install_overrides(plan)
        app = plan.build(root)
        window = (
            _capture_geometry(plan.window[0], plan.window[1], dpi)
            if plan.window is not None
            else None
        )
        if window is not None:
            # Re-assert the declared size after the tool has drawn itself: a tool
            # that resizes its own window must not silently change what the guide
            # shows, and the size is what the sidecar records.
            left, top = _window_origin(root, *window)
            root.geometry(f"{window[0]}x{window[1]}+{left}+{top}")
        root.update_idletasks()
        root.update()
        # Raise before calibrating: the markers are read off the screen, so a
        # window still sitting behind the developer's editor has neither marker
        # in view and the run reports it as covered.
        root.lift()
        root.attributes("-topmost", True)
        root.update()
        rect = _calibrate(root)
        if window is not None and (rect[2], rect[3]) != window:
            return [
                f"{plan.tool_id}: the window paints {rect[2]}x{rect[3]}, "
                f"not the plan's {window[0]}x{window[1]}"
            ]
        tabs = _tab_titles(app)
        if not tabs:
            # A single-pane window has no tabs to name; its one figure is the
            # window itself, which is what a viewer's guide needs to show.
            tabs = ["Window"]
        print(
            f"[INFO] {plan.tool_id}: paints {rect[2]}x{rect[3]}, "
            f"tabs: {', '.join(tabs)}"
        )
        for index, title in enumerate(tabs):
            figure = _figure_name(title)
            if figure in plan.skip_tabs:
                continue
            filler = _plan_fillers(plan).get(figure)
            try:
                _select_tab(app, index)
                if filler is not None:
                    filler(app)
                _select_tab(app, index)
                root.update_idletasks()
            except Exception as exc:  # noqa: BLE001 - one tab must not abort the rest
                problems.append(
                    f"{plan.tool_id}/{figure}: could not fill the tab - "
                    f"{type(exc).__name__}: {exc}"
                )
                continue
            problems.extend(_grab(root, plan, figure, dpi=dpi))
    except Exception as exc:  # noqa: BLE001 - one tool must not abort the rest
        problems.append(f"{plan.tool_id}: capture failed - {type(exc).__name__}: {exc}")
    finally:
        _restore(restore)
        root.destroy()
    return problems


def main(argv: list[str]) -> int:
    """Capture the figures for the tools named in *argv*, or all of them.

    Args:
        argv: Command-line arguments after the program name.

    Returns:
        Process exit code: 0 when every figure was written, 1 on a problem.
    """
    # A capability check rather than a platform branch: this utility needs the
    # Win32 API, and the tree's platform-conditional branches are declared in
    # ``audio_suite_shared/platform_support.py`` and enumerated by
    # ``test_platform_support.py`` - it is not another fork of shipped behaviour.
    if not hasattr(sys, "getwindowsversion"):
        print(
            "[ERROR] capturing guide figures needs Windows: the capture reads "
            "the desktop with ImageGrab and calibrates against its pixels",
            file=sys.stderr,
        )
        return 1

    force_dpi = "--force-dpi" in argv
    wanted = [argument for argument in argv if not argument.startswith("--")]
    plans = [plan for plan in TOOL_PLANS if not wanted or plan.tool_id in wanted]
    if not plans:
        print(
            "[ERROR] no capture plan matches the tools named; known tools: "
            + ", ".join(plan.tool_id for plan in TOOL_PLANS),
            file=sys.stderr,
        )
        return 1

    # Machine state the tools would otherwise read or write.  Set before any
    # tool module is imported (see the module docstring).
    os.environ["AUDIOSUITE_WHATS_NEW"] = "0"
    os.environ["AUDIOSUITE_LOG_DIR"] = tempfile.mkdtemp(prefix="audiosuite_capture_")
    saved_argv = sys.argv
    sys.argv = saved_argv[:1]

    problems: list[str] = []
    try:
        print(f"[START] Capturing guide figures for {len(plans)} tool(s)")
        for plan in plans:
            print(f"[INFO] {plan.tool_id}: one figure per notebook tab")
            problems.extend(capture_tool(plan, force_dpi=force_dpi))
    finally:
        sys.argv = saved_argv

    if problems:
        print("[ERROR] capture problems:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print("[DONE]")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
