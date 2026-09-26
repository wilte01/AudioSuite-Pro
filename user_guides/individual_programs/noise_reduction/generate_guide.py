"""Generate a fresh Noise Reduction guide from current code."""

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

OUTPUT = (
    "D:\\Users\\wilte\\Desktop\\AudioSuite-Pro\\user_guides\\individual_programs\\"
    "noise_reduction\\Noise_Reduction_User_Guide.docx"
)


def bullet(doc: Document, title: str, text: str) -> None:
    paragraph = doc.add_paragraph(style="List Bullet")
    paragraph.add_run(title).bold = True
    paragraph.add_run(text)


doc = Document()
title = doc.add_heading("Noise Reduction - User Guide", level=0)
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
subtitle = doc.add_paragraph("Based on the current Noise Reduction implementation")
subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER

doc.add_heading("Overview", level=1)
doc.add_paragraph(
    "Noise Reduction removes unwanted mains hum and/or stationary broadband noise from "
    "supported audio files. Hum removal uses cascaded IIR notch filters; "
    "broadband reduction "
    "uses STFT spectral gating based on a selected noise-profile region. "
    "Both stages can be "
    "enabled independently or together, with hum removal applied first."
)
doc.add_paragraph(
    "The tool processes files in place in Live Update, preserves existing tags, "
    "and uses temporary "
    "working files before replacing the original only after successful processing."
)

doc.add_heading("Supported Files", level=1)
doc.add_paragraph(
    "The processor uses the shared Audio Suite supported formats, "
    "including MP3, FLAC, OGG, M4A, "
    "MP4, Opus, WAV, and AIFF variants. The selected directory "
    "must contain at least one supported file."
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
    "Open Noise_Reduction.pyw.",
    "Select the music directory.",
    "Enable Hum Removal, Broadband Noise Reduction, or both.",
    "Set the noise controls and leave Dry Run selected for the first pass.",
    "Start processing and review the per-file statuses.",
    "Run again in Live Update when the result is acceptable.",
    "Use Results audition controls to compare an original and "
    "reduced file when available.",
):
    doc.add_paragraph(step, style="List Number")

doc.add_heading("Setup", level=1)
doc.add_paragraph(
    "Setup contains the directory picker, run mode, "
    "two reduction stage controls, presets, and "
    "shared run controls. At least one of Hum Removal or Broadband Noise Reduction "
    "must be enabled."
)
bullet(doc, "Hum Removal: ", "Enables mains-hum notch filtering.")
bullet(
    doc, "Broadband Noise Reduction: ", "Enables spectral gating using a noise profile."
)
bullet(
    doc,
    "Dry Run / Live Update: ",
    "Dry Run analyzes without writing; Live Update exports and replaces files.",
)
bullet(
    doc,
    "Presets: ",
    "Save and restore all reduction parameters and run mode "
    "through shared suite presets.",
)

doc.add_heading("Hum Removal", level=1)
doc.add_paragraph(
    "Hum removal designs second-order notch filters "
    "at the selected fundamental and each harmonic "
    "below the Nyquist frequency. The filters are applied per channel "
    "using numerically stable "
    "second-order sections processing. A result is considered modified "
    "only when attenuation reaches "
    "the implementation's minimum meaningful threshold of 3 dB."
)
bullet(doc, "Hum frequency: ", "50 or 60 Hz mains frequency.")
bullet(
    doc,
    "Harmonics: ",
    "1 through 20 harmonic notches; default 8. "
    "More harmonics remove more of the hum series "
    "but may affect nearby musical content.",
)
bullet(
    doc,
    "Quality (Q): ",
    "1 through 100; default 30. Higher Q creates narrower notches "
    "and preserves more adjacent content.",
)

doc.add_heading("Broadband Noise Reduction", level=1)
doc.add_paragraph(
    "Broadband reduction uses a short noise-only region to estimate "
    "the mean magnitude spectrum. "
    "The gate threshold is that noise profile plus configurable dB headroom; "
    "spectral bins below "
    "the threshold are zeroed, then the signal is reconstructed with inverse STFT."
)
bullet(
    doc,
    "Noise start / end: ",
    "Profile window in milliseconds; defaults "
    "0 to 500 ms and must be at least 100 ms wide.",
)
bullet(
    doc,
    "Gate threshold: ",
    "Headroom above the measured noise floor, default 3 dB. Lower values suppress "
    "more but risk removing quiet detail.",
)
bullet(
    doc,
    "Profile selection: ",
    "Choose a section containing noise "
    "without desired music or speech for the most reliable gate.",
)

doc.add_heading("Processing Behavior", level=1)
for step in (
    "Discover supported files in the selected directory.",
    "Read original tags and copy the source to a worker temporary directory.",
    "Load the temporary audio and apply hum removal first when enabled.",
    "Apply broadband spectral gating when enabled.",
    "Skip clean files when no meaningful modification is detected.",
    "In Live Update, export the reduced audio, restore original tags, and "
    "copy the result over the source.",
    "Remove temporary worker files and report the result.",
):
    doc.add_paragraph(step, style="List Number")

doc.add_heading("Dry Run and Live Update", level=1)
bullet(
    doc,
    "Dry Run: ",
    "Calculates the reduction path without exporting or changing files. "
    "Result audio is unavailable for playback because nothing was written.",
)
bullet(
    doc,
    "Live Update: ",
    "Exports modified audio, restores tags, and "
    "replaces the source file after successful processing.",
)
bullet(
    doc,
    "Clean files: ",
    "Files with no detectable modification are marked skipped and are not rewritten.",
)
bullet(
    doc,
    "Undo: ",
    "Live tag edits are recorded in the suite's tag-edit batch for available recovery.",
)

doc.add_heading("Processing and Results", level=1)
doc.add_paragraph(
    "Processing displays four worker slots, progress, "
    "succeeded/skipped/error counts, and per-file "
    "statuses such as FIXED, SKIP, or ERROR. Results reports total, "
    "reduced, skipped, errors, and "
    "elapsed time. The Results tab can open the log and source folder and audition "
    "before/after audio "
    "when a successful live result is available."
)

doc.add_heading("Command Line", level=1)
doc.add_paragraph("The registered command is reduce. Examples:")
doc.add_paragraph(
    "python -m audio_suite_shared.cli_app reduce <folder> --reduce-hum --dry\n"
    "python -m audio_suite_shared.cli_app reduce <folder> "
    "--reduce-hum --hum-frequency 50 --hum-harmonics 8\n"
    "python -m audio_suite_shared.cli_app reduce <folder> "
    "--reduce-broadband --noise-start 0 --noise-end 500\n"
    "python -m audio_suite_shared.cli_app reduce <folder> "
    "--reduce-hum --reduce-broadband --live --json"
)
doc.add_paragraph(
    "Options include --reduce-hum, --hum-frequency 50|60, "
    "--hum-harmonics, --hum-quality, "
    "--reduce-broadband, --noise-start, --noise-end, --gate-threshold, "
    "the shared dry-run/live "
    "option, and --json. At least one reduction flag should be enabled."
)

doc.add_heading("Audio Refinery Use", level=1)
doc.add_paragraph(
    "Noise Reduction is also available as a stage in Audio Refinery. "
    "Enable its stage panel and "
    "choose hum and/or broadband reduction settings. "
    "In the Refinery, it runs after trim and before "
    "the enhancement stage, while the combined pipeline "
    "manages its own tag and output handling."
)

doc.add_heading("Master Driver Use", level=1)
doc.add_paragraph(
    "From the Master Driver, open UTIL "
    "and select Noise Reduction. The driver passes the directory, "
    "mode, start/end behavior, stage settings, and orchestration state "
    "through the launch handshake."
)

doc.add_heading("Troubleshooting", level=1)
bullet(doc, "No files found: ", "Select a directory containing supported audio files.")
bullet(
    doc,
    "Nothing changed: ",
    "A clean file may have been skipped, "
    "or both reduction stages may not have been enabled.",
)
bullet(
    doc,
    "Hum remains: ",
    "Confirm the correct 50/60 Hz setting and consider increasing harmonics carefully.",
)
bullet(
    doc,
    "Music sounds dull: ",
    "Increase notch Q, reduce harmonics, "
    "increase gate threshold, or improve the noise-profile region.",
)
bullet(
    doc,
    "Broadband reduction is ineffective: ",
    "Choose a genuine noise-only profile region and "
    "verify the start/end window is at least 100 ms.",
)
bullet(
    doc,
    "A file errors: ",
    "Check codec support, file permissions, temporary disk space, and "
    "the per-file status/log.",
)

doc.add_heading("Safety and Recovery", level=1)
doc.add_paragraph(
    "Use Dry Run first and audition representative results. "
    "Live Update replaces source files after "
    "successful temporary export, but retain backups of important audio. "
    "Use the suite's Undo Tag "
    "Edits workflow for available metadata snapshots."
)

doc.save(OUTPUT)
print(f"Saved to {OUTPUT}")
