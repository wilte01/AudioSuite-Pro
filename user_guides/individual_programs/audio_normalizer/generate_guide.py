"""Generate a fresh Audio Normalizer guide from the current implementation.

Changed in 1.1.0: documented the widened supported-format list (WavPack .wv
and Speex .spx) and updated the "why only seven formats normalise" explanation.
"""

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

OUTPUT = (
    "D:\\Users\\wilte\\Desktop\\AudioSuite-Pro\\user_guides\\individual_programs\\"
    "audio_normalizer\\Audio_Normalizer_User_Guide.docx"
)


def bullet(doc: Document, title: str, text: str) -> None:
    paragraph = doc.add_paragraph(style="List Bullet")
    paragraph.add_run(title).bold = True
    paragraph.add_run(text)


doc = Document()
title = doc.add_heading("Audio Normalizer - User Guide", level=0)
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
subtitle = doc.add_paragraph("Based on the current Audio Normalizer implementation")
subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER

doc.add_heading("Overview", level=1)
doc.add_paragraph(
    "Audio Normalizer measures integrated loudness and "
    "brings supported audio files "
    "toward a selected LUFS target. It measures each "
    "file, calculates the gain needed, "
    "skips files already within tolerance, and either "
    "previews or applies the result. "
    "The normal re-encode path uses FFmpeg's two-pass "
    "loudnorm filter and preserves the "
    "original metadata."
)
doc.add_paragraph(
    "The tool processes files in parallel worker slots "
    "and operates in place. Use Dry "
    "Run first, or keep an independent backup before "
    "a live run."
)

doc.add_heading("Supported Audio", level=1)
doc.add_paragraph(
    "The processor discovers the shared Audio Suite "
    "audio extensions in the selected "
    "directory. The FFmpeg normalization path has "
    "configured codecs for MP3, FLAC, OGG, "
    "M4A, Opus, WavPack (.wv), and Speex (.spx). "
    "Unsupported extensions are "
    "rejected rather than being silently "
    "written with the wrong codec."
)

doc.add_heading("Why Only Seven Formats Normalise", level=1)
doc.add_paragraph(
    "This is a deliberate design decision, not a gap. Normalisation "
    "re-encodes the audio stream, and the suite only configures an FFmpeg "
    "codec and quality setting for the seven formats listed above. A file "
    "whose extension has no configured codec is therefore rejected with an "
    "unsupported-format error instead of being processed anyway."
)
doc.add_paragraph(
    "The reason is that the alternative is silent data damage. Without a "
    "configured codec, the obvious fallback is to encode the audio as MP3 "
    "while keeping the original extension. That would leave a WAV container "
    "holding MP3 data, or an OGG file holding MP3 data: the library would "
    "still play, but the mislabelled codec would be discovered only later, by "
    "a player, a tagger, or a rip comparison. Rejecting the file keeps the "
    "library's format claims true, and reports the reason instead."
)
bullet(
    doc,
    "What you see: ",
    "Each unsupported file is reported as an error naming its extension and "
    "listing the seven supported formats. Other files in the same run "
    "continue; one unsupported file never aborts the batch.",
)
bullet(
    doc,
    "MP3 lossless mode: ",
    "The lossless mode adjusts the MP3 global_gain tag in place and does not "
    "re-encode, so it is not subject to this format set. A non-MP3 file falls "
    "back to the normalise path and is then subject to it.",
)
bullet(
    doc,
    "Adding a format: ",
    "Adding one means adding its codec and quality arguments to the "
    "normaliser's format table, so the guarantee is only as good as that "
    "table.",
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
    "Open Audio_Normalizer.pyw.",
    "Select the music directory.",
    "Choose Dry Run first, a target LUFS value, and a tolerance.",
    "Click BEGIN NORMALIZATION.",
    "Review the processed, skipped, and error entries and the log.",
    "Run again in Normalize or Lossless Normalize mode when the preview is acceptable.",
    "Use the Results audition controls to compare the "
    "original and normalized audio when available.",
):
    doc.add_paragraph(step, style="List Number")

doc.add_heading("Setup", level=1)
doc.add_paragraph(
    "The Setup tab contains the shared Source "
    "directory bar with the Mode dropdown "
    "(Dry Run, Normalize, Lossless Normalize), "
    "Auto Start/End, Clear Logs, and Parallel "
    "options, the Configuration panel, preset "
    "controls, and the BEGIN NORMALIZATION button. "
    "When launched from the Master Driver, the "
    "directory, mode, and option controls are driven "
    "by the driver's orchestration state. The "
    "last-used directory is restored from "
    "shared suite configuration."
)
bullet(
    doc,
    "Select Mode: ",
    "Dry Run previews gain changes. Normalize applies "
    "FFmpeg loudnorm re-encoding. Lossless Normalize "
    "adjusts MP3 global_gain in place and falls back "
    "to normal re-encoding for non-MP3 files.",
)
bullet(
    doc,
    "Target LUFS: ",
    "Choose one of the permitted loudness targets: "
    "-12.0, -14.0, -16.0, -18.0, or -23.0 LUFS. "
    "The app default is -14.0.",
)
bullet(
    doc,
    "Tolerance: ",
    "Choose 0.1 to 2.0 LUFS. A file whose required "
    "gain is within plus or minus this value "
    "is skipped.",
)
bullet(
    doc,
    "Presets: ",
    "Save, load, and delete target LUFS, tolerance, "
    "and run-mode settings through shared suite "
    "preset storage.",
)

doc.add_heading("How a File Is Handled", level=1)
for step in (
    "Measure the file's integrated loudness and related loudnorm values.",
    "Calculate gain needed as target LUFS minus current integrated LUFS.",
    "Skip the file when the absolute gain needed is no greater than tolerance.",
    "In Dry Run, log the gain that would be applied without changing the file.",
    "In Normalize mode, run FFmpeg loudnorm with "
    "measured first-pass values and write a "
    "temporary output.",
    "Restore original tags to the temporary output "
    "and atomically replace the original file.",
):
    doc.add_paragraph(step, style="List Number")
doc.add_paragraph(
    "The temporary-output and atomic-replace sequence "
    "means a failed encode does not "
    "leave a partially written destination in place. "
    "Live tag edits are recorded in the "
    "suite batch undo system."
)

doc.add_heading("Normalization Modes", level=1)
bullet(
    doc,
    "Dry Run: ",
    "Measures every file and logs [DRY RUN] with the "
    "proposed gain. No audio or tags are written.",
)
bullet(
    doc,
    "Normalize: ",
    "Uses FFmpeg's two-pass loudnorm filter with "
    "integrated loudness target, -1.5 dB true-peak "
    "target, LRA 11, measured input values, and "
    "format-specific output codec settings.",
)
bullet(
    doc,
    "Lossless Normalize: ",
    "For MP3 files, changes global_gain in place "
    "without re-encoding. Non-MP3 files use the "
    "normal FFmpeg loudnorm path instead.",
)

doc.add_heading("Processing and Results", level=1)
doc.add_paragraph(
    "Processing shows four worker slots, a progress "
    "bar, and per-file status lines. "
    "Typical statuses include SKIPPED for files "
    "within tolerance, DRY RUN with proposed "
    "gain, NORMALIZED with applied gain, and ERROR "
    "with a readable failure message."
)
doc.add_paragraph(
    "Results reports total files, normalized files, "
    "skipped files, errors, and elapsed "
    "time. Dry Run ends with Dry Run Complete; live "
    "modes end with Normalization Complete. "
    "The Results tab can open the source folder and "
    "provides original/result auditioning "
    "when a suitable pair is available."
)

doc.add_heading("Logs", level=1)
bullet(doc, "Dry Run log: ", "normalization_dry_run_log.txt in the selected directory.")
bullet(doc, "Live log: ", "audio_normalization_log.txt in the selected directory.")
bullet(
    doc,
    "Contents: ",
    "Mode, target LUFS, tolerance, per-file statuses "
    "and gains, normalized/skipped/error counts, "
    "and elapsed time.",
)

doc.add_heading("Command Line", level=1)
doc.add_paragraph("The registered command is normalise. Examples:")
doc.add_paragraph(
    "python -m audio_suite_shared.cli_app normalise "
    "<folder> --dry\n"
    "python -m audio_suite_shared.cli_app normalise "
    "<folder> --target-lufs -14 --tolerance 0.5\n"
    "python -m audio_suite_shared.cli_app normalise "
    "<folder> --mode lossless\n"
    "python -m audio_suite_shared.cli_app normalise "
    "<folder> --mode normalise --json"
)
doc.add_paragraph(
    "The CLI accepts --target-lufs, --tolerance, "
    "--mode normalise|lossless, the shared "
    "dry-run option, and --json. Target LUFS is "
    "validated against the permitted values; "
    "tolerance must not be negative. Text output "
    "reports processed, skipped, errors, and "
    "elapsed time."
)

doc.add_heading("Master Driver Use", level=1)
doc.add_paragraph(
    "Audio Normalizer is registered as an Enrich tool "
    "in the Master Driver. Open the "
    "ENRICH workflow, select Audio Normalizer, and "
    "use the shared directory and mode "
    "controls. The driver passes target LUFS, "
    "tolerance, normalization mode, and its "
    "orchestration state through the launch arguments."
)

doc.add_heading("Troubleshooting", level=1)
bullet(
    doc,
    "Files are skipped: ",
    "Their measured loudness is already within the "
    "selected tolerance of the target. This is "
    "expected and avoids unnecessary rewriting.",
)
bullet(
    doc,
    "No files found: ",
    "Confirm that the selected directory contains "
    "supported audio files directly discoverable "
    "by the processor.",
)
bullet(
    doc,
    "FFmpeg error: ",
    "Check FFmpeg availability, codec support, file "
    "permissions, disk space, and the live log.",
)
bullet(
    doc,
    "Lossless mode re-encoded a file: ",
    "Lossless global_gain adjustment applies only "
    "to MP3. FLAC, OGG, M4A, Opus, WavPack, and "
    "Speex use the FFmpeg loudnorm path.",
)
bullet(
    doc,
    "The output sounds wrong: ",
    "Try a less extreme target, adjust tolerance, "
    "compare the audition controls, and retain the "
    "original before live processing.",
)
bullet(
    doc,
    "Tags changed or disappeared: ",
    "The normalizer restores readable source tags "
    "after encoding. Check the log and the file's "
    "format-specific metadata support.",
)

doc.add_heading("Safety and Recovery", level=1)
doc.add_paragraph(
    "Dry Run is the recommended first step. Normalize "
    "mode replaces source files after "
    "successful temporary encoding, while Lossless "
    "Normalize changes MP3 frame gain in "
    "place. Keep independent backups and use the "
    "suite's Undo Tag Edits workflow for "
    "available metadata snapshots."
)

doc.save(OUTPUT)
print(f"Saved to {OUTPUT}")
