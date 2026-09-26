"""Generate a fresh Pop & Click Remover guide from current code."""

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

OUTPUT = (
    "D:\\Users\\wilte\\Desktop\\AudioSuite-Pro\\user_guides\\individual_programs\\"
    "pop_click_remover\\Pop_Click_Remover_User_Guide.docx"
)


def bullet(doc: Document, title: str, text: str) -> None:
    paragraph = doc.add_paragraph(style="List Bullet")
    paragraph.add_run(title).bold = True
    paragraph.add_run(text)


doc = Document()
title = doc.add_heading("Pop & Click Remover - User Guide", level=0)
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
subtitle = doc.add_paragraph("Based on the current Pop & Click Remover implementation")
subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER

doc.add_heading("Overview", level=1)
doc.add_paragraph(
    "Pop & Click Remover detects short discontinuities in audio "
    "and repairs them with "
    "interpolation. It uses a local noise-floor detector on the "
    "first-difference signal, "
    "merges neighboring spike samples into defect regions, and "
    "repairs eligible regions "
    "with cubic-spline interpolation or a linear fallback near "
    "file boundaries."
)
doc.add_paragraph(
    "The tool processes supported audio files in a selected "
    "directory, preserves existing "
    "metadata, and can preview or commit repairs."
)

doc.add_heading("Supported Files", level=1)
doc.add_paragraph(
    "The processor uses the shared Audio Suite supported formats"
    ", including MP3, FLAC, OGG, "
    "M4A, MP4, Opus, WAV, and AIFF variants. The directory must "
    "contain at least one "
    "supported file."
)

doc.add_heading("System Requirements", level=1)
doc.add_paragraph(
    "This tool requires ffmpeg and ffprobe to be installed and on PATH. "
    "ffmpeg decodes and encodes the audio formats the suite reads and "
    "writes; ffprobe reads stream metadata (duration, codec, bitrate) "
    "for analysis tools. The suite shows a startup warning naming any "
    "missing binary and how to install it."
)
for _hint in (
    "Windows: winget install Gyan.FFmpeg",
    "macOS:   brew install ffmpeg",
    "Linux:   sudo apt install ffmpeg",
):
    doc.add_paragraph(_hint, style="List Bullet")

doc.add_heading("Quick Start", level=1)
for step in (
    "Open Pop_Click_Remover.pyw.",
    "Select the music directory.",
    "Choose a sensitivity and maximum click width.",
    "Leave Dry Run selected for the first pass.",
    "Click BEGIN POP & CLICK REMOVAL.",
    "Review detected/clean/error statuses and audition the result when available.",
    "Run again in Live Update when the repairs are acceptable.",
):
    doc.add_paragraph(step, style="List Number")

doc.add_heading("Setup", level=1)
doc.add_paragraph(
    "Setup contains the directory picker, execution mode, "
    "sensitivity slider, maximum click "
    "width, presets, and shared run controls. The last-used "
    "directory is restored from shared "
    "suite configuration."
)
bullet(
    doc,
    "Click Sensitivity: ",
    "Range 0.01 through 0.40. Lower values are more aggressive "
    "and detect quieter clicks; "
    "the default is 0.31.",
)
bullet(
    doc,
    "Max Click Width: ",
    "Range 1 through 10 ms. Defect regions wider than this are "
    "left untouched to avoid "
    "altering legitimate transients; the default is 2 ms.",
)
bullet(
    doc,
    "Dry Run / Live Update: ",
    "Dry Run detects without writing. Live Update exports "
    "repaired audio and replaces the "
    "source.",
)
bullet(doc, "Presets: ", "Save and restore sensitivity, maximum width, and run mode.")

doc.add_heading("Detection and Repair", level=1)
for step in (
    "Copy each source file into a per-worker temporary directory"
    " and preserve its tags.",
    "Decode the audio and calculate first-order sample differences.",
    "Estimate a local noise floor with a 20 ms windowed mean absolute deviation.",
    "Flag differences above the sensitivity-derived threshold "
    "and merge nearby spike "
    "samples.",
    "Reject regions wider than Max Click Width, near-silent "
    "artifacts, or saturated-neighbor "
    "cases.",
    "Repair accepted regions with cubic-spline interpolation "
    "over clean neighboring samples, "
    "using linear interpolation near boundaries.",
    "Apply clipping protection and report whether any click regions were repaired.",
):
    doc.add_paragraph(step, style="List Number")
doc.add_paragraph(
    "The repair includes an overshoot guard and is designed to "
    "be idempotent: a second pass "
    "on already repaired audio should find no new defects."
)

doc.add_heading("Sensitivity Semantics", level=1)
doc.add_paragraph(
    "Sensitivity maps to an internal detector multiplier. Lower "
    "slider values produce a lower "
    "threshold multiplier and therefore more aggressive "
    "detection. Higher values are gentler. "
    "The detector is calibrated to avoid ordinary music "
    "transients, but review aggressive "
    "settings with auditioning before applying them to a large "
    "library."
)

doc.add_heading("Dry Run and Live Update", level=1)
bullet(
    doc,
    "Dry Run: ",
    "Detects and counts clicks without exporting repaired audio "
    "or changing source files. "
    "Result playback is unavailable because nothing was written.",
)
bullet(
    doc,
    "Live Update: ",
    "Exports repaired audio to a temporary file, restores "
    "original tags, then copies the "
    "result over the source.",
)
bullet(
    doc,
    "Clean files: ",
    "Files with no eligible defects are skipped and not rewritten.",
)
bullet(
    doc,
    "Undo: ",
    "Live tag edits participate in the suite's tag-edit batch; "
    "keep backups for complete "
    "audio recovery.",
)

doc.add_heading("Processing and Results", level=1)
doc.add_paragraph(
    "Processing displays four worker slots, progress, "
    "succeeded/skipped/error counts, and "
    "per-file messages. Results reports total, succeeded, "
    "skipped, errors, and elapsed time. "
    "The Results tab can open the log and source folder and "
    "audition original versus repaired "
    "audio for a successful live run."
)

doc.add_heading("Command Line", level=1)
doc.add_paragraph("The registered command is declick. Examples:")
doc.add_paragraph(
    "python -m audio_suite_shared.cli_app declick <folder> "
    "--dry\n"
    "python -m audio_suite_shared.cli_app declick <folder> "
    "--sensitivity 0.05 --width 3\n"
    "python -m audio_suite_shared.cli_app declick <folder> "
    "--live --json"
)
doc.add_paragraph(
    "Options include --sensitivity, --max-width, the shared "
    "dry-run/live option, and --json. "
    "CLI defaults are sensitivity 0.25 and width 5 ms, while "
    "the GUI defaults are 0.31 and "
    "2 ms."
)

doc.add_heading("Audio Refinery and Master Driver", level=1)
doc.add_paragraph(
    "Pop & Click Remover is available as the declick stage in "
    "Audio Refinery, where the "
    "pipeline can combine it with trimming, noise reduction, "
    "enhancement, and normalization. "
    "From the Master Driver, it is available through the Refinery"
    " workflow and receives "
    "inherited run controls."
)

doc.add_heading("Troubleshooting", level=1)
bullet(doc, "No files found: ", "Select a directory containing supported audio files.")
bullet(
    doc,
    "Everything is clean: ",
    "The detector found no eligible regions; this is expected "
    "for files without short "
    "discontinuities.",
)
bullet(
    doc,
    "Too many repairs: ",
    "Increase sensitivity value, reduce maximum width, or "
    "review the output with auditioning.",
)
bullet(
    doc,
    "A real transient was untouched: ",
    "It may exceed Max Click Width, be near silence, or be "
    "rejected by saturation guards. "
    "Adjust width cautiously.",
)
bullet(
    doc,
    "A file errors: ",
    "Check codec support, file permissions, temporary disk "
    "space, and the per-file "
    "processing message.",
)
bullet(
    doc,
    "Tags changed unexpectedly: ",
    "Confirm Live Update was selected and use the suite's undo "
    "workflow or backups for "
    "recovery.",
)

doc.add_heading("Safety and Recovery", level=1)
doc.add_paragraph(
    "Run Dry Run first and audition representative repairs. Live"
    " Update replaces source files "
    "only after temporary export succeeds, but keep backups of "
    "important audio. Use available "
    "tag-edit undo snapshots for metadata recovery."
)

doc.save(OUTPUT)
print(f"Saved to {OUTPUT}")
