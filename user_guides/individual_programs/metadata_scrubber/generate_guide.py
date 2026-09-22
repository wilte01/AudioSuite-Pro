"""Generate a fresh Metadata Scrubber guide from the current implementation."""

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

OUTPUT = (
    "D:\\Users\\wilte\\Desktop\\AudioSuite-Pro\\user_guides\\individual_programs\\"
    "metadata_scrubber\\Metadata_Scrubber_User_Guide.docx"
)


def bullet(doc: Document, title: str, text: str) -> None:
    paragraph = doc.add_paragraph(style="List Bullet")
    paragraph.add_run(title).bold = True
    paragraph.add_run(text)


doc = Document()
title = doc.add_heading("Metadata Scrubber - User Guide", level=0)
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
subtitle = doc.add_paragraph("Based on the current Metadata Scrubber implementation")
subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER

doc.add_heading("Overview", level=1)
doc.add_paragraph(
    "Metadata Scrubber removes metadata from supported "
    "audio files and restores only "
    "the fields you choose to keep. Artist, album, "
    "and title are always preserved as "
    "essential identity tags. The scrubber can also "
    "preserve selected custom fields, "
    "lyrics, Album Artist, and embedded artwork."
)
doc.add_paragraph(
    "Dry Run reports what would be scrubbed without "
    "changing files. Live Update performs "
    "a tag wipe followed by restoration and records "
    "tag-edit snapshots for undo support."
)

doc.add_heading("Supported Files", level=1)
doc.add_paragraph(
    "The core scrubber supports all nine suite audio "
    "formats except WMA: MP3, FLAC, OGG, M4A, MP4, "
    "Opus, WAV, AIFF, and AIF. WMA is excluded "
    "because mutagen has no ASF tag handler. The GUI "
    "discovers custom tags by sampling up to 100 "
    "supported audio files in the selected directory. "
    "Processing then scans the supported files in that "
    "directory."
)
bullet(
    doc,
    "Always preserved: ",
    "Artist, album, and title, using format-specific tag representations.",
)
bullet(
    doc,
    "Optional lyrics: ",
    "MP3 USLT/SYLT, Vorbis lyrics/syncedlyrics, and "
    "the M4A/MP4 lyrics atom where supported.",
)
bullet(
    doc,
    "Optional Album Artist: ",
    "MP3 TPE2 and corresponding Album Artist fields in supported containers.",
)
bullet(
    doc,
    "Optional artwork: ",
    "MP3 APIC, Vorbis metadata block picture, and MP4/M4A cover art.",
)
bullet(
    doc,
    "Custom tags: ",
    "Discovered custom fields are selectable and "
    "restored through the shared format-aware "
    "tag handler.",
)

doc.add_heading("Quick Start", level=1)
for step in (
    "Open Metadata_Scrubber.pyw.",
    "Use Browse & Scan to select the directory.",
    "Review the discovered custom tags and choose which to preserve.",
    "Set Lyrics, Album Artist, and Embedded Art preservation as needed.",
    "Leave Dry Run selected for the first pass.",
    "Click BEGIN SCRUBBING and review Processing and Results.",
    "Run again in Live Update only after confirming the preservation choices.",
):
    doc.add_paragraph(step, style="List Number")

doc.add_heading("Setup", level=1)
doc.add_paragraph(
    "Setup contains the directory/run-controls panel, "
    "presets, preservation toggles, "
    "custom-tag checklist, and start button. Browse "
    "& Scan both selects the folder and "
    "discovers custom tags. Previously preserved "
    "custom-tag choices are marked saved and "
    "automatically ticked when they are found again."
)
bullet(
    doc,
    "Preserve Lyrics (USLT/SYLT): ",
    "Keeps lyrics frames or equivalent format-specific lyrics fields.",
)
bullet(
    doc,
    "Preserve Album Artist (TPE2): ",
    "Keeps the Album Artist field; enabled by default.",
)
bullet(
    doc,
    "Preserve Embedded Art (APIC): ",
    "Keeps embedded cover art; enabled by default.",
)
bullet(
    doc,
    "Custom tag checklist: ",
    "Select discovered TXXX descriptions or equivalent "
    "custom fields to restore after scrubbing.",
)
bullet(
    doc,
    "Presets: ",
    "Save and restore mode plus the three preservation "
    "toggles. Dynamic custom-tag selections are "
    "persisted separately as last-used preferences "
    "after Live Update.",
)

doc.add_heading("Tag Discovery", level=1)
doc.add_paragraph(
    "The GUI scans up to 100 supported audio files for "
    "custom tag descriptions: TXXX descriptions for "
    "ID3-based formats (MP3, WAV, AIFF, AIF), Vorbis "
    "comment keys for FLAC/OGG/Opus, and MP4 freeform "
    "tag names for M4A/MP4. It excludes known system "
    "or technical descriptions containing terms such as "
    "ReplayGain, BPM, Tempo, Initial Key, "
    "MusicBrainz, AcousticID, Barcode, MediaType, or "
    "OriginalDate. This keeps the checklist "
    "focused on user-defined metadata rather than "
    "fields managed by other suite tools."
)
doc.add_paragraph(
    "If no custom tags are found, the checklist "
    "displays No custom tags found, while the "
    "always-preserved identity tags and optional "
    "standard controls remain available."
)

doc.add_heading("Scrubbing Workflow", level=1)
for step in (
    "Load the file with its format-specific mutagen handler.",
    "Verify that tags exist; files without tags report NO TAGS.",
    "Collect essential tags and the selected optional/custom fields.",
    "Record a tag-edit undo snapshot and delete all tags in Live Update.",
    "Save the wiped file.",
    "Reload it, recreate tags if needed, restore the "
    "preserved fields, and save the result.",
):
    doc.add_paragraph(step, style="List Number")
doc.add_paragraph(
    "The operation keeps audio content unchanged; it "
    "changes metadata containers and fields. "
    "The processing uses four worker threads and "
    "reports each file independently."
)

doc.add_heading("Dry Run and Live Update", level=1)
bullet(
    doc,
    "Dry Run: ",
    "Reports Would scrub metadata for each discovered "
    "file and performs no tag deletion or restoration. "
    "It does not update saved tag preferences.",
)
bullet(
    doc,
    "Live Update: ",
    "Wipes and restores metadata according to the "
    "selected preservation settings, then saves tag "
    "preferences for the selected custom fields.",
)
bullet(
    doc, "No tags: ", "Files without tags are reported as errors rather than modified."
)
bullet(
    doc, "Unreadable file: ", "Files that cannot be opened are reported as UNREADABLE."
)
bullet(
    doc,
    "Corrupt tags: ",
    "A failed wipe is reported as CORRUPT TAGS; "
    "a failed restoration is reported as WRITE FAILED.",
)

doc.add_heading("Processing and Results", level=1)
doc.add_paragraph(
    "Processing shows four worker slots, "
    "processed/skipped/error counts, and per-file "
    "status messages. Results reports total files, "
    "successfully processed files, skipped files, "
    "errors, and elapsed time. The results tab can "
    "open the log and source folder."
)

doc.add_heading("Logs", level=1)
bullet(doc, "Dry Run log: ", "metadata_dry_run_log.txt in the selected directory.")
bullet(doc, "Live log: ", "metadata_scrubbing_log.txt in the selected directory.")
bullet(
    doc,
    "Contents: ",
    "Mode, preservation choices, per-file statuses, "
    "preserved-tag counts, errors, totals, and "
    "elapsed time.",
)

doc.add_heading("Command Line", level=1)
doc.add_paragraph("The registered command is scrub. Examples:")
doc.add_paragraph(
    "python -m audio_suite_shared.cli_app scrub "
    "<folder> --dry\n"
    "python -m audio_suite_shared.cli_app scrub "
    "<folder> --live\n"
    "python -m audio_suite_shared.cli_app scrub "
    "<folder> --no-preserve-lyrics --json"
)
doc.add_paragraph(
    "Options include --preserve-lyrics/"
    "--no-preserve-lyrics, "
    "--preserve-album-artist/"
    "--no-preserve-album-artist, "
    "--preserve-embedded-art/"
    "--no-preserve-embedded-art, "
    "the shared dry-run/live option, "
    "and --json. All three preservation options "
    "default to enabled."
)

doc.add_heading("Master Driver Use", level=1)
doc.add_paragraph(
    "From the Master Driver, open ENRICH and select "
    "Metadata Scrubber. The driver passes the "
    "directory, mode, start/end behavior, "
    "preservation flags, and orchestration state "
    "through the launch handshake. A driven launch "
    "can auto-start and locks inherited run controls."
)

doc.add_heading("Troubleshooting", level=1)
bullet(
    doc,
    "No custom tags found: ",
    "The scanner samples up to 100 supported audio "
    "files and filters known system tags. Custom "
    "fields in files beyond the sample limit may not "
    "appear in the dynamic checklist.",
)
bullet(
    doc,
    "Metadata disappeared: ",
    "Confirm the intended fields were checked and "
    "that the run was Live Update. Unchecked custom "
    "tags are intentionally removed.",
)
bullet(
    doc,
    "Artwork was removed: ",
    "Enable Preserve Embedded Art before a live run; "
    "APIC/cover-art preservation is independent of "
    "custom-tag selection.",
)
bullet(
    doc,
    "Lyrics were removed: ",
    "Enable Preserve Lyrics (USLT/SYLT) before a live run.",
)
bullet(
    doc,
    "A file errors: ",
    "Review the per-file status and "
    "metadata_scrubbing_log.txt for unreadable files, "
    "missing tags, corrupt tags, or restoration "
    "failures.",
)
bullet(
    doc,
    "Preferences look stale: ",
    "Custom-tag preferences are updated after Live "
    "Update, not Dry Run. New tags are unticked "
    "until reviewed.",
)

doc.add_heading("Safety and Recovery", level=1)
doc.add_paragraph(
    "Run Dry Run first and verify the preservation "
    "checklist. Live Update rewrites metadata "
    "in place. Keep backups of important files and "
    "use the suite's Undo Tag Edits workflow "
    "for available tag-edit snapshots."
)

doc.save(OUTPUT)
print(f"Saved to {OUTPUT}")
