"""Generate the Master Driver user guide from the current application code.

Changed in 1.0.1: documents that the four standalone tools now consume the driver's
argv.

Changed in 1.1.0: documents the Audio Enhancer card (required output folder and
all four presets, Custom included) and notes that the REFINE tab's enhancer
stage opens the same Custom DSP editor window as the standalone tool.

Changed in 1.2.0: documents the per-step note a finished tool can leave on its
batch-report line (and that such a report stays on screen).
"""

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

OUTPUT = (
    "D:\\Users\\wilte\\Desktop\\AudioSuite-Pro"
    "\\user_guides\\individual_programs\\master_driver"
    "\\Master_Driver_User_Guide.docx"
)


def add_bullet(doc: Document, title: str, text: str) -> None:
    paragraph = doc.add_paragraph(style="List Bullet")
    paragraph.add_run(title).bold = True
    paragraph.add_run(text)


doc = Document()

title = doc.add_heading("Audio Suite Master Driver - User Guide", level=0)
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
subtitle = doc.add_paragraph("Based on the current Master Driver implementation")
subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER

doc.add_heading("What the Master Driver Does", level=1)
doc.add_paragraph(
    "The Master Driver is the central desktop application for "
    "running Audio Suite "
    "tools from one window. It groups the audio-processing "
    "Refinery, metadata "
    "Enrich tools, and Utility tools behind a shared folder, "
    "mode, selection, "
    "progress, and settings interface. Tools are discovered from"
    " the shared tool "
    "registry, so the cards shown by the application reflect the"
    " registered suite "
    "tools."
)

doc.add_heading("Start the Application", level=1)
doc.add_paragraph(
    "From the AudioSuite-Pro folder, double-click "
    "Master_Driver.pyw. The launcher "
    "sets the suite folder as the working directory, runs a "
    "pre-flight check that "
    "compiles first-party Python files, configures logging, "
    "applies the theme, "
    "and then opens the Master Driver window. A pre-flight "
    "failure blocks startup "
    "so a broken import or syntax error is reported before the "
    "UI begins."
)
doc.add_paragraph(
    "The window title is Audio Suite Master Driver. The "
    "application remembers the "
    "last directory and saved appearance settings through the "
    "shared suite "
    "configuration. Closing the window saves the current "
    "application state."
)

doc.add_heading("Basic Workflow", level=1)
doc.add_paragraph("Use this sequence for a normal batch operation:")
for text in (
    "Choose the REFINE, ENRICH, or UTIL tab.",
    "Select the folder or source and output paths required by that tab.",
    "Leave Dry Run selected while checking a new operation.",
    "Expand tool cards and set their tool-specific options.",
    "Select the tools or Refinery stages to run.",
    "Review Auto Start, Auto End, Clear Logs, and Parallel settings.",
    "Launch the process and monitor the progress area and log output.",
    "Repeat with Live Update only after the dry-run result is acceptable.",
):
    doc.add_paragraph(text, style="List Number")

doc.add_heading("The Main Window", level=1)
doc.add_heading("REFINE", level=2)
doc.add_paragraph(
    "REFINE embeds the Audio Refinery setup. Choose a source "
    "folder and, if "
    "needed, an output folder. A blank output folder means "
    "process in place. "
    "Select one or more stages: declick, trim, enhance, "
    "normalise, and reduce "
    "noise. SELECT ALL changes all five stage selections "
    "together. The embedded "
    "controls also provide Dry Run, Auto Start, Auto End, and "
    "Clear Logs. The "
    "Refinery does not use the shared Parallel option. Reset "
    "Progress clears the "
    "completion record for the selected source so files are "
    "eligible for another "
    "run. At least one stage and a valid source directory are "
    "required. In the Audio Enhancer stage, selecting Custom opens "
    "the same Custom DSP editor window the standalone Audio "
    "Enhancer uses, so the stage stays compact and every control "
    "is reachable."
)

doc.add_heading("ENRICH", level=2)
doc.add_paragraph(
    "ENRICH displays the registered tag and metadata tools as "
    "cards in a scrollable "
    "list. Check a card to include it, expand Settings when a "
    "card has options, "
    "and click LAUNCH ENRICH PROCESS. The shared directory bar "
    "supplies the folder "
    "to process. Tools that open their own window are launched "
    "separately from "
    "the batch subprocesses."
)

doc.add_heading("UTIL", level=2)
doc.add_paragraph(
    "UTIL displays the registered utility cards and the LAUNCH "
    "UTILITY PROCESS "
    "button. Most utilities use the shared directory bar. "
    "Standalone utilities "
    "such as CD Ripper, Library Statistics Dashboard, Tag-Based"
    " File Reorganizer, "
    "Mood Analysis Batch Tagger, Noise Reduction, and Undo Tag "
    "Edits open their "
    "own window or workflow. Undo Tag Edits is opened with its "
    "Open Undo button "
    "and is not part of a batch run."
)

doc.add_heading("SETTINGS", level=2)
doc.add_paragraph(
    "SETTINGS contains the Colour Palette, Theme Mode, and "
    "Typography controls. "
    "Use Save to persist the choices. The interface reports "
    "that saved changes "
    "take effect when each tool is next opened. The Windows "
    "Accent palette can "
    "refresh while the application is running when Windows "
    "accent information is "
    "available."
)

doc.add_heading("Shared Run Controls", level=1)
add_bullet(
    doc,
    "Folder: ",
    "The shared directory used by ENRICH and directory-based "
    "UTIL tools. Use Browse "
    "Folder or enter a path, then confirm that it exists.",
)
add_bullet(
    doc,
    "SELECT ALL: ",
    "Selects or clears the available cards in the current "
    "batch-oriented area. In REFINE "
    "it controls the five Refinery stages.",
)
add_bullet(
    doc,
    "Mode: ",
    "Dry Run previews the operation without committing changes."
    " Live Update permits the "
    "selected tool to write tags or files.",
)
add_bullet(
    doc,
    "Auto Start / Auto End: ",
    "Passes the corresponding start and end processing options to supported tools.",
)
add_bullet(doc, "Clear Logs: ", "Requests log cleanup before the selected run begins.")
add_bullet(
    doc,
    "Parallel: ",
    "Allows independent Enrich or Utility subprocesses to run "
    "concurrently. Dependency-aware"
    " scheduling still preserves required ordering.",
)
add_bullet(
    doc,
    "Progress area: ",
    "During a batch run, the driver can show per-step status, "
    "an overall summary, estimated"
    " remaining time, and a progress bar.",
)
add_bullet(
    doc,
    "Step notes: ",
    "A step can finish with something the run still owes you - "
    "CD Ripper tracks that did not rip, files a tag writer "
    "skipped or could not update, conversions skipped or failed. "
    "The driver prints that on the step's own line, and keeps the "
    "report on screen while it carries a note instead of hiding it "
    "when the batch ends. A note never means the step failed: the "
    "work it did was done.",
)

doc.add_heading("Enrich Tools", level=1)
for name, description in (
    (
        "Metadata Scrubber",
        "Removes metadata while offering preservation choices "
        "for lyrics, Album Artist, and "
        "embedded artwork.",
    ),
    (
        "Audio Fingerprinter",
        "Generates fingerprints and identifies tracks through "
        "AcoustID. New card options "
        "cover AcoustID lookup, writing matched tags, the "
        "minimum match threshold, the "
        "fpcalc analysis window, an explicit fpcalc binary path,"
        " and a one-off API key.",
    ),
    (
        "ReplayGain Analyzer",
        "Measures and writes ReplayGain tags using a reference LUFS value.",
    ),
    (
        "Album Genre Tagger",
        "Builds album-level genre metadata with a minimum coverage percentage.",
    ),
    (
        "Genre Sync",
        "Copies genre information from the configured custom-field hierarchy.",
    ),
    (
        "BPM Analyzer",
        "Detects BPM within a configured range and analysis "
        "duration, with optional worker "
        "parallelism.",
    ),
    (
        "Tempo Analyzer",
        "Derives tempo markings from BPM tags using the selected naming scheme.",
    ),
    (
        "Key Detector",
        "Detects musical key for each file, with analysis "
        "duration and optional worker "
        "parallelism.",
    ),
    (
        "Mood Analyzer",
        "Performs signal-based mood tagging with configurable "
        "duration and worker "
        "parallelism.",
    ),
    (
        "Album Art Sync",
        "Embeds and synchronises artwork using maximum "
        "resolution, minimum dimension, purge,"
        " and album-match settings.",
    ),
):
    add_bullet(doc, f"{name}: ", description)

doc.add_heading("Utility Tools", level=1)
for name, description in (
    (
        "Music Format Converter",
        "Detects the input format, then converts to a selected "
        "output format and quality. "
        "Card options add sample rate, bit depth, MP3 "
        "normalisation target LUFS, an optional"
        " output directory, and delete-originals. Mixed input "
        "formats are rejected by format "
        "detection.",
    ),
    (
        "ASX Playlist Extractor",
        "Extracts audio streams from ASX playlist files; Live "
        "Update uses permanent "
        "extraction.",
    ),
    (
        "Album Art Normalizer",
        "Resizes and normalizes embedded artwork with a "
        "selectable target size and supports"
        " folder.jpg normalization.",
    ),
    (
        "CD Ripper",
        "Rips CDs to WAV, MP3, FLAC, OGG, M4A, or Opus with "
        "MusicBrainz metadata lookup. "
        "Card options cover the output directory, output format,"
        " a specific track list, and "
        "CUE sheet generation.",
    ),
    (
        "Mood Analysis Batch Tagger",
        "Recursively analyses audio and applies signal-based batch mood tags.",
    ),
    (
        "Noise Reduction",
        "Provides independent hum removal (mains frequency, "
        "harmonics, notch quality) and "
        "broadband noise reduction (noise profile window and gate"
        " threshold).",
    ),
    (
        "Audio Enhancer",
        "Enhances each file with the DSP chain. The card requires an "
        "output folder and offers Mild, Moderate, Aggressive, or "
        "Custom. Custom runs with the tool's currently loaded DSP "
        "values, which are tuned in the Audio Enhancer window's "
        "Custom DSP editor.",
    ),
    ("Tag Field Updater", "Scans and updates tag fields."),
    (
        "Library Statistics Dashboard",
        "Reads existing tags and presents read-only library "
        "statistics. Card options select "
        "a full or incremental scan, cache refresh, "
        "and CSV/JSON export paths.",
    ),
    (
        "Tag-Based File Reorganizer",
        "Moves or copies files into a folder hierarchy based on "
        "tags, with configurable "
        "output directory, action, and artist-specific and "
        "Various Artists patterns.",
    ),
    (
        "Lyrics Manager",
        "Imports and exports synced (LRC) lyrics for a single "
        "audio file: MP3, WAV and AIFF "
        "use the ID3 SYLT frame while FLAC, OGG and Opus store "
        "the text in a SYNCEDLYRICS "
        "Vorbis comment.",
    ),
    ("Undo Tag Edits", "Restores tags from snapshots recorded before batch edits."),
):
    add_bullet(doc, f"{name}: ", description)

doc.add_heading("Batch Execution", level=1)
doc.add_paragraph(
    "The driver builds a step for every selected registered "
    "tool. In sequential "
    "mode, steps run in the displayed order. In Parallel mode, "
    "independent steps "
    "may run together, while declared dependencies are held "
    "until their required "
    "step completes. Tempo depends on BPM when both are "
    "selected. Standalone "
    "tools are marked as skipped by the parallel batch path "
    "because they open their "
    "own interface."
)
doc.add_paragraph(
    "Each step reports pending, waiting, running, completed, "
    "failed, or skipped "
    "status. The orchestrator retries failed subprocess steps "
    "using the suite's "
    "retry policy. The final report includes totals, failed and"
    " skipped counts, "
    "individual step results, and elapsed time."
)

doc.add_heading("Safe Operating Practices", level=1)
for text in (
    "Use Dry Run first, especially for conversion, "
    "reorganization, artwork changes, and "
    "metadata cleanup.",
    "Keep a backup of important audio files before Live Update "
    "or any operation that moves,"
    " copies, deletes, or overwrites files.",
    "Confirm the directory path before launching. The driver "
    "validates that required "
    "directories exist.",
    "For conversion, review the detected input format, output "
    "format, quality, output "
    "directory, and delete-originals setting.",
    "Do not close the application while a batch is running "
    "unless you accept that child "
    "processes may be interrupted.",
    "Use Undo Tag Edits for supported tag-edit snapshots after "
    "a batch run; it does not "
    "undo audio processing or file moves.",
):
    doc.add_paragraph(text, style="List Bullet")

doc.add_heading("Troubleshooting", level=1)
add_bullet(
    doc,
    "The process will not start: ",
    "Select the required directory, verify that it exists, and "
    "select at least one tool or "
    "Refinery stage.",
)
add_bullet(
    doc,
    "A card is missing: ",
    "The card is loaded from the registry and its card module. "
    "Check the application log "
    "for an import or card-build warning.",
)
add_bullet(
    doc,
    "A standalone tool does not run in the batch: ",
    "Open it from its card. Standalone tools are designed to "
    "launch their own window and "
    "are not ordinary blocking batch steps.",
)
add_bullet(
    doc,
    "The output is unchanged: ",
    "Confirm that the run was Live Update rather than Dry Run, "
    "and check the per-step status"
    " and logs for failures or skips.",
)
add_bullet(
    doc,
    "Startup is blocked: ",
    "The launcher pre-flight check found a compile or "
    "import-chain problem. Correct the "
    "reported source or dependency issue, then start the "
    "launcher again.",
)

doc.add_heading("Related Launchers", level=1)
doc.add_paragraph(
    "Every registered tool also has its own suite launcher where"
    " one exists. "
    "The Master Driver uses the registry's script filename and "
    "category to decide "
    "how to launch it; direct launchers are useful when a tool "
    "needs its own "
    "dedicated workflow or window."
)

doc.save(OUTPUT)
print(f"Saved to {OUTPUT}")
