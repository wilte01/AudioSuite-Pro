"""Generate a fresh BPM Analyzer guide from the current implementation.

Changed in 1.4.0: the Workers description states the machine default
(one per logical CPU, capped at 8) instead of a fixed 4.
Changed in 1.4.0: the Command Line section documents the JSON
``skipped_files`` records (filename, reason, onset-periodicity score).
"""

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

OUTPUT = (
    "D:\\Users\\wilte\\Desktop\\AudioSuite-Pro\\user_guides\\individual_programs\\"
    "bpm_analyzer\\BPM_Analyzer_User_Guide.docx"
)


def bullet(doc: Document, title: str, text: str) -> None:
    paragraph = doc.add_paragraph(style="List Bullet")
    paragraph.add_run(title).bold = True
    paragraph.add_run(text)


doc = Document()
title = doc.add_heading("BPM Analyzer - User Guide", level=0)
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
subtitle = doc.add_paragraph("Based on the current BPM Analyzer implementation")
subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER

doc.add_heading("Overview", level=1)
doc.add_paragraph(
    "BPM Analyzer estimates the tempo of audio files with "
    "librosa beat tracking and "
    "can write the detected BPM into the file's metadata. It "
    "scans a selected directory, "
    "analyzes a configurable leading portion of each file, "
    "constrains the estimate to a "
    "chosen BPM range, and reports each result in the Processing"
    " tab and log."
)
doc.add_paragraph(
    "Dry Run is analysis-only. Live Update writes the BPM tag "
    "and participates in the "
    "suite's tag-edit undo batch."
)

doc.add_heading("Supported Audio", level=1)
doc.add_paragraph(
    "The analyzer uses the shared Audio Suite supported-format "
    "list, including MP3, FLAC, "
    "OGG, M4A, Opus, WAV, and AIFF variants. The selected "
    "directory must contain at least "
    "one supported audio file."
)

doc.add_heading("Quick Start", level=1)
for step in (
    "Open BPM_Analyzer.pyw.",
    "Select the music directory.",
    "Set the BPM minimum and maximum and choose an analysis duration.",
    "Leave Dry Run selected for the first pass.",
    "Click BEGIN BPM ANALYSIS.",
    "Review the detected values and errors in Processing and Results.",
    "Run again in Live Update when the detections are acceptable"
    " and you want tags written.",
):
    doc.add_paragraph(step, style="List Number")

doc.add_heading("Setup", level=1)
doc.add_paragraph(
    "Setup contains the directory picker, mode, BPM range, "
    "analysis duration, optional "
    "parallel processing, worker count, presets, and the start "
    "button. The GUI restores "
    "the last directory and saves parallel settings through "
    "shared suite configuration."
)
bullet(
    doc,
    "BPM Range: ",
    "The GUI requires minimum BPM from 40 through 300 and "
    "maximum BPM from 60 through 400,"
    " with minimum less than maximum. Defaults are 75 to 175.",
)
bullet(
    doc,
    "Analysis Duration: ",
    "The GUI accepts 10 to 300 seconds. The default is 90 "
    "seconds. Shorter analysis is "
    "faster but may be less accurate.",
)
bullet(
    doc,
    "Parallel Processing: ",
    "When enabled, CPU-bound detection uses "
    "ProcessPoolExecutor to bypass the GIL. When disabled, "
    "the shared thread-based processing path is used.",
)
bullet(
    doc,
    "Workers: ",
    "Controls the maximum worker count and must be at least 1. "
    "The default is one worker per logical CPU, capped at 8.",
)
bullet(
    doc,
    "Presets: ",
    "Save and load BPM range, duration, parallel mode, worker "
    "count, and run mode settings "
    "through shared configuration.",
)

doc.add_heading("Detection Behavior", level=1)
doc.add_paragraph(
    "For each file, librosa loads mono audio for the configured "
    "maximum duration using its "
    "beat tracker. The signal is upcast to float64 for the "
    "tool's internal processing. The "
    "raw tempo estimate is then normalized to a scalar, "
    "octave-corrected by doubling or "
    "halving when possible, rounded to an integer, and "
    "hard-clamped to the requested range."
)
bullet(
    doc,
    "Outside-range tempo: ",
    "The result is constrained to the nearest configured "
    "boundary when octave correction "
    "cannot place it inside the range.",
)
bullet(
    doc,
    "No detectable beat or silence: ",
    "A non-positive estimate is not doubled; the final clamp "
    "resolves it to the configured "
    "minimum.",
)
bullet(
    doc,
    "Existing BPM: ",
    "In Live Update, the log and on-screen status include the "
    "prior BPM when it differs from "
    "the new detected value.",
)

doc.add_heading("Dry Run and Live Update", level=1)
bullet(doc, "Dry Run: ", "Detects BPM and reports [DRY RUN] without changing metadata.")
bullet(
    doc,
    "Live Update: ",
    "Detects BPM and writes the result with the shared BPM tag "
    "writer, reporting [TAGGED].",
)
bullet(
    doc, "Undo: ", "Live tag changes are recorded in the suite's batch undo context."
)
bullet(
    doc,
    "Failure: ",
    "A detection error is reported for that file and counted as "
    "an error while other files "
    "continue.",
)

doc.add_heading("Processing and Results", level=1)
doc.add_paragraph(
    "Processing shows four worker-slot labels, a progress bar, "
    "processed/skipped/error "
    "counts, and per-file status lines. Results reports total "
    "files, analyzed or tagged "
    "files, skipped files, errors, and elapsed time. The "
    "completion label distinguishes "
    "Analysis Complete from BPM Tagging Complete."
)
doc.add_paragraph(
    "BPM Analyzer does not treat an out-of-range detection as a"
    " skip: the detector clamps "
    "the value into the configured range. Skips and errors in "
    "the summary are therefore "
    "reserved for processing infrastructure outcomes rather than"
    " tempo values outside the "
    "range."
)

doc.add_heading("Logs", level=1)
bullet(doc, "Dry Run log: ", "bpm_dry_run_log.txt in the selected directory.")
bullet(doc, "Live log: ", "bpm_sync_log.txt in the selected directory.")
bullet(
    doc,
    "Contents: ",
    "Mode, BPM range, analysis duration, parallel settings, "
    "per-file BPM results, errors, "
    "counts, and elapsed time.",
)

doc.add_heading("Command Line", level=1)
doc.add_paragraph(
    "The registered command is bpm. CLI defaults differ from the"
    " GUI defaults: the CLI "
    "defaults to 60-200 BPM and 30 seconds. Examples:"
)
doc.add_paragraph(
    "python -m audio_suite_shared.cli_app bpm <folder> --dry\n"
    "python -m audio_suite_shared.cli_app bpm <folder> "
    "--bpm-min 75 --bpm-max 175 --duration 90\n"
    "python -m audio_suite_shared.cli_app bpm <folder> "
    "--parallel --workers 4\n"
    "python -m audio_suite_shared.cli_app bpm <folder> --json"
)
doc.add_paragraph(
    "The command accepts --bpm-min, --bpm-max, --duration, "
    "--parallel/--no-parallel, "
    "--workers, the shared dry-run option, and --json. It "
    "reports processed, skipped, "
    "errors, and elapsed time in text mode. JSON mode returns the "
    "same counts as top-level fields plus skipped_files, one record "
    "per refused file with its filename, reason, and "
    "onset_periodicity score (null when no tempo estimate existed), "
    "and error_files, one record per failed file with its filename, "
    "reason, and error_type."
)

doc.add_heading("Master Driver Use", level=1)
doc.add_paragraph(
    "From the Master Driver, open ENRICH and select BPM "
    "Analyzer. The driver passes the "
    "directory, mode, BPM range, duration, worker settings, and"
    " orchestration flags through "
    "the launch handshake. A driven launch can auto-start and "
    "displays inherited controls."
)

doc.add_heading("Troubleshooting", level=1)
bullet(
    doc,
    "No audio files found: ",
    "Select a directory containing supported audio files.",
)
bullet(
    doc,
    "Invalid BPM range: ",
    "Ensure minimum is below maximum, minimum is 40-300, and "
    "maximum is 60-400 in the GUI.",
)
bullet(
    doc,
    "Invalid duration: ",
    "Use 10-300 seconds in the GUI; shorter windows trade accuracy for speed.",
)
bullet(
    doc,
    "Results seem too high or low: ",
    "Check the configured range for octave expectations and "
    "increase analysis duration for "
    "more context.",
)
bullet(
    doc,
    "Detection error: ",
    "Check whether the file is readable and decodable; review "
    "the per-file error and log.",
)
bullet(
    doc,
    "Tags did not change: ",
    "Confirm Live Update was selected. Dry Run never writes BPM metadata.",
)
bullet(
    doc,
    "Parallel run fails: ",
    "Try disabling parallel mode or lowering worker count if "
    "process startup or system "
    "resources are constrained.",
)

doc.add_heading("Safety and Recovery", level=1)
doc.add_paragraph(
    "Run Dry Run first and review the detected BPM values. Live"
    " Update changes audio metadata "
    "in place, so keep backups of important files. Use the "
    "suite's Undo Tag Edits workflow "
    "for available tag snapshots."
)

doc.save(OUTPUT)
print(f"Saved to {OUTPUT}")
