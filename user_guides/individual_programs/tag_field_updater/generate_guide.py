"""Generate the Tag Field Updater User Guide .docx."""

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

doc = Document()

# ── Title ──
h = doc.add_heading("Tag Field Updater \u2014 User Guide", level=0)
h.alignment = WD_ALIGN_PARAGRAPH.CENTER
doc.add_paragraph(
    "Version 1.0 \u2014 August 2026"
).alignment = WD_ALIGN_PARAGRAPH.CENTER

# ── Overview ──
doc.add_heading("Overview", level=1)
doc.add_paragraph(
    "The Tag Field Updater is a specialised audio metadata tool that recursively "
    "scans your music library and normalises slash characters in custom TXXX "
    "genre-related tag fields. It replaces bare / (forward-slash) characters "
    'with "; " (semicolon-space) in existing tag values, while preserving '
    'values that use the " / " (space-slash-space) pattern. This standardises '
    "how multi-genre or genre-artist combinations are delimited in tag metadata "
    "across an entire library."
)

# ── Quick Start ──
doc.add_heading("Quick Start", level=1)
doc.add_paragraph(
    "1. Launch Tag_Field_Updater.pyw.\n"
    "2. Click 'Browse...' to select your music library directory.\n"
    "3. Click 'Start Scanning' to begin processing.\n"
    "4. Monitor progress in real-time as files are processed.\n"
    "5. Review the completion summary when the scan finishes."
)

# ── Supported Formats ──
doc.add_heading("Supported File Formats", level=1)
doc.add_paragraph("The tool processes the following audio formats:")

table = doc.add_table(rows=10, cols=3)
table.style = "Table Grid"
hdr = table.rows[0].cells
hdr[0].text = "Format"
hdr[1].text = "Extensions"
hdr[2].text = "Tag Type"
for c in hdr:
    for p in c.paragraphs:
        for r in p.runs:
            r.bold = True

formats = [
    ("MP3", ".mp3", "ID3 (v2.3 / v2.4)"),
    ("FLAC", ".flac", "Vorbis Comments"),
    ("MP4 / M4A", ".mp4, .m4a", "iTunes Atoms"),
    ("OGG Vorbis", ".ogg", "Vorbis Comments"),
    ("Opus", ".opus", "Vorbis Comments"),
    ("WAV", ".wav", "ID3 (v2.4)"),
    ("AIFF / AIF", ".aiff, .aif", "ID3 (v2.4)"),
    ("WMA", ".wma", "ASF"),
]
for i, (fmt, exts, tag) in enumerate(formats, 1):
    r = table.rows[i].cells
    r[0].text = fmt
    r[1].text = exts
    r[2].text = tag

# ── Tag Fields Updated ──
doc.add_heading("Tag Fields Updated", level=1)
doc.add_paragraph(
    "The tool targets specific custom TXXX fields and standard genre-related "
    "fields. Only fields that already exist in a file are processed \u2014 no "
    "new fields are created."
)

doc.add_heading("Custom TXXX Fields", level=2)
p = doc.add_paragraph()
p.add_run("TXXX/ALBUMARTISTGENRE").bold = True
p.add_run(" \u2014 Album Artist Genre")
p = doc.add_paragraph()
p.add_run("TXXX/ALBUMGENRE").bold = True
p.add_run(" \u2014 Album Genre")
p = doc.add_paragraph()
p.add_run("TXXX/ARTISTGENRE").bold = True
p.add_run(" \u2014 Artist Genre")
doc.add_paragraph(
    "On non-ID3 formats these custom fields are stored with the "
    "format-equivalent convention: Vorbis comment keys (FLAC, OGG, Opus) "
    "and MP4 freeform tags (M4A/MP4, \u201c----:TXXX:<name>\u201d)."
)

doc.add_heading("Standard Fields by Format", level=2)

table2 = doc.add_table(rows=10, cols=4)
table2.style = "Table Grid"
hdr2 = table2.rows[0].cells
hdr2[0].text = "Format"
hdr2[1].text = "Field 1"
hdr2[2].text = "Field 2"
hdr2[3].text = "Field 3"
for c in hdr2:
    for p in c.paragraphs:
        for r in p.runs:
            r.bold = True

std_fields = [
    ("MP3", "TIT1 (Content Group)", "TCON (Genre)", ""),
    ("FLAC", "CONTENTGROUP", "GENRE", ""),
    ("MP4 / M4A", "\u00a9grp (Group)", "\u00a9gen (Genre)", ""),
    ("OGG", "CONTENTGROUP", "GENRE", ""),
    ("Opus", "CONTENTGROUP", "GENRE", ""),
    ("WAV", "TIT1 (Content Group)", "TCON (Genre)", ""),
    ("AIFF / AIF", "TIT1 (Content Group)", "TCON (Genre)", ""),
    ("WMA", "ContentGroupDescription", "Genre", ""),
]
for i, (fmt, f1, f2, f3) in enumerate(std_fields, 1):
    r = table2.rows[i].cells
    r[0].text = fmt
    r[1].text = f1
    r[2].text = f2
    r[3].text = f3

# ── Slash Replacement Rules ──
doc.add_heading("Slash Replacement Rules", level=1)
doc.add_paragraph(
    "The tool applies a smart slash-replacement algorithm. The rules are "
    "hardcoded and not user-configurable."
)

doc.add_heading("Values That WILL Be Updated", level=2)
table3 = doc.add_table(rows=5, cols=2)
table3.style = "Table Grid"
hdr3 = table3.rows[0].cells
hdr3[0].text = "Before"
hdr3[1].text = "After"
for c in hdr3:
    for p in c.paragraphs:
        for r in p.runs:
            r.bold = True

updated = [
    ('"Rock/Pop"', '"Rock; Pop"'),
    ('"Electronic/Dance"', '"Electronic; Dance"'),
    ('"Jazz/Blues/Rock"', '"Jazz; Blues; Rock"'),
    (
        '"Reggae/Dancehall / Ska/Regional Music"',
        '"Reggae; Dancehall / Ska; Regional Music"',
    ),
]
for i, (before, after) in enumerate(updated, 1):
    r = table3.rows[i].cells
    r[0].text = before
    r[1].text = after

doc.add_heading("Values That Will NOT Be Updated", level=2)
table4 = doc.add_table(rows=5, cols=2)
table4.style = "Table Grid"
hdr4 = table4.rows[0].cells
hdr4[0].text = "Value"
hdr4[1].text = "Reason"
for c in hdr4:
    for p in c.paragraphs:
        for r in p.runs:
            r.bold = True

not_updated = [
    ('"Rock / Pop"', "Preserved \u2014 space-slash-space pattern"),
    ('"Single Genre"', "No slash present"),
    ('""', "Empty value"),
    ('"Artist / Band / Genre"', "All slashes use space-slash-space"),
]
for i, (val, reason) in enumerate(not_updated, 1):
    r = table4.rows[i].cells
    r[0].text = val
    r[1].text = reason

doc.add_paragraph(
    "The algorithm also handles mixed patterns. For example, "
    '"A/B / C/D" becomes "A; B / C; D" \u2014 bare slashes are replaced '
    "while space-slash-space delimiters are preserved."
)

# ── GUI Mode ──
doc.add_heading("Using the GUI", level=1)
doc.add_paragraph(
    "Double-click Tag_Field_Updater.pyw to launch the graphical interface. "
    "The window is divided into the following sections:"
)

doc.add_heading("Music Library Directory", level=2)
doc.add_paragraph(
    "Type or paste a directory path directly, or click Browse... to open a "
    "folder chooser dialog. This is the root directory for the recursive scan."
)

doc.add_heading("Tag Fields to Update", level=2)
doc.add_paragraph(
    "A read-only information panel listing all target tag fields and the "
    "replacement rules. Refer to this section during a scan to understand "
    "which fields are being modified."
)

doc.add_heading("Progress", level=2)
doc.add_paragraph(
    "Shows the name of the file currently being processed, updated in "
    "real-time via a background thread."
)

doc.add_heading("Statistics", level=2)
doc.add_paragraph("Three counters displayed during and after the scan:")
p = doc.add_paragraph()
p.add_run("Files Processed: ").bold = True
p.add_run("Total number of files scanned")
p = doc.add_paragraph()
p.add_run("Files Updated: ").bold = True
p.add_run("Files that had at least one tag field modified")
p = doc.add_paragraph()
p.add_run("Errors: ").bold = True
p.add_run("Files that encountered processing errors")

doc.add_heading("Controls", level=2)
p = doc.add_paragraph()
p.add_run("Start Scanning: ").bold = True
p.add_run(
    "Begins the recursive scan. The button is disabled while scanning is in progress."
)
p = doc.add_paragraph()
p.add_run("Stop: ").bold = True
p.add_run(
    "Requests the processor to stop after the current file completes. "
    "The scan stops cooperatively between file iterations."
)

doc.add_heading("Completion Summary", level=2)
doc.add_paragraph(
    "When the scan finishes (or is stopped), a summary dialog appears showing "
    "Files Processed, Files Updated, Files Skipped, and Errors. The status "
    'bar at the bottom of the window changes from "Scanning..." to '
    '"Scan Complete".'
)

# ── Command-Line Interface ──
doc.add_heading("Command-Line Interface", level=1)
doc.add_paragraph(
    "The tool can also be run from the command line via the shared "
    "AudioSuite CLI group."
)

doc.add_heading("Click CLI (Recommended)", level=2)
doc.add_paragraph(
    "Usage:\n\n"
    "    audiosuite tag-update <DIRECTORY> [OPTIONS]\n\n"
    "Arguments:\n"
    "    DIRECTORY          Path to the music library (required)\n\n"
    "Options:\n"
    "    --dry / --live   Run without writing changes (default: --live)\n"
    "    --json / --text      Output format (default: --text)\n"
    "    --log-level LEVEL    Logging verbosity: DEBUG, INFO, WARNING, ERROR\n"
)

doc.add_paragraph(
    "Examples:\n\n"
    "    audiosuite tag-update D:\\Music --dry --json\n"
    "    audiosuite tag-update /home/user/music --log-level DEBUG"
)

doc.add_heading("Module Entry Point", level=2)
doc.add_paragraph(
    "Usage:\n\n"
    "    python -m tag_field_updater [--directory PATH]\n\n"
    "If --directory is provided, the GUI launches with that path pre-filled "
    "and scanning starts immediately."
)

# ── Logging ──
doc.add_heading("Logging", level=1)
doc.add_paragraph(
    "The tool uses Python's standard logging module. Log output is routed "
    "to the Audio Suite unified log directory alongside other program logs."
)

doc.add_heading("What Is Logged", level=2)
p = doc.add_paragraph()
p.add_run("INFO: ").bold = True
p.add_run(
    'Directory scan start; per-tag update details (e.g. "Updated TIT1 in '
    "song.mp3: 'Rock/Pop' -> 'Rock; Pop'\"); skip reasons; scan completion "
    "summary."
)
p = doc.add_paragraph()
p.add_run("ERROR: ").bold = True
p.add_run(
    "Per-file processing errors with full exception details; directory walk "
    "errors; unhandled scan errors."
)

doc.add_heading("Skip Logging", level=2)
doc.add_paragraph(
    "Files are skipped (not errored) for several reasons. The log records "
    "the specific reason for each skip:"
)
p = doc.add_paragraph(style="List Bullet")
p.add_run("Unsupported format: ").bold = True
p.add_run("File extension not in the supported list (e.g. .txt, .jpg)")
p = doc.add_paragraph(style="List Bullet")
p.add_run("No ID3 tags: ").bold = True
p.add_run("MP3 file with no ID3 tag header")
p = doc.add_paragraph(style="List Bullet")
p.add_run("No target tags found: ").bold = True
p.add_run("File has tags but none of the target fields contain a slash")

doc.add_paragraph('Search the log file for "Skipped file" to see all skip reasons.')

# ── Safety ──
doc.add_heading("Safety Features", level=1)

doc.add_heading("Minimal Modification", level=2)
doc.add_paragraph(
    "The tool only modifies existing tag fields \u2014 it never creates new "
    "fields. Only values containing a bare slash are changed. All other tag "
    "data, audio content, and file timestamps are preserved."
)

doc.add_heading("Error Resilience", level=2)
doc.add_paragraph(
    "Individual file errors never halt the scan. If a file is corrupted or "
    "inaccessible, the error is logged and the tool continues to the next "
    "file. The error count is displayed in the statistics and completion "
    "summary."
)

doc.add_heading("MP3 Version Preservation", level=2)
doc.add_paragraph(
    "For MP3 files, the tool detects the ID3 version (v2.3 vs v2.4) and "
    "preserves it when writing tags. v2.3 files use Latin-1 encoding; v2.4 "
    "files use UTF-8. No version migration is performed."
)

doc.add_heading("Cooperative Stop", level=2)
doc.add_paragraph(
    "The Stop button requests the processor to stop after the current file "
    "completes. This ensures no file is left in a partially-written state. "
    "The scan cannot be interrupted mid-file."
)

# ── Troubleshooting ──
doc.add_heading("Troubleshooting", level=1)

doc.add_paragraph(
    "No files processed: "
    "Verify the directory contains supported audio formats (.mp3, .flac, "
    ".mp4, .m4a, .ogg, .opus, .wav, .aiff, .aif, .wma). "
    "Check directory permissions."
)
doc.add_paragraph(
    "Files updated: 0: "
    "This is normal if your files already use the semicolon-space delimiter "
    "or if none of the target fields contain a bare slash. Check the log "
    "file for skip details."
)
doc.add_paragraph(
    "Permission errors: "
    "Ensure you have read/write access to the music directory. On Windows, "
    "try running as administrator if files are read-only."
)
doc.add_paragraph(
    "Large libraries: "
    "Processing is threaded so the UI remains responsive. SSD drives "
    "provide faster file access than HDDs. Network drives may be slower."
)

# ── Technical Details ──
doc.add_heading("Technical Details", level=1)

doc.add_heading("Dependencies", level=2)
p = doc.add_paragraph(style="List Bullet")
p.add_run("Python 3.10+: ").bold = True
p.add_run("Core runtime")
p = doc.add_paragraph(style="List Bullet")
p.add_run("Mutagen: ").bold = True
p.add_run("Audio file tag reading and writing")
p = doc.add_paragraph(style="List Bullet")
p.add_run("Tkinter: ").bold = True
p.add_run("GUI framework (included with Python)")

doc.add_heading("Architecture", level=2)
doc.add_paragraph(
    "The tool is structured as a clean Python package with separated concerns:"
)
p = doc.add_paragraph(style="List Bullet")
p.add_run("core/mapping_engine.py: ").bold = True
p.add_run("Tag field mappings, supported extensions, and slash-replacement logic")
p = doc.add_paragraph(style="List Bullet")
p.add_run("core/transformation_rules.py: ").bold = True
p.add_run("Per-format processing functions (Mutagen I/O)")
p = doc.add_paragraph(style="List Bullet")
p.add_run("core/processor.py: ").bold = True
p.add_run("TagProcessor orchestrating directory scanning and file dispatch")
p = doc.add_paragraph(style="List Bullet")
p.add_run("ui/app.py: ").bold = True
p.add_run("Tkinter GUI application")
p = doc.add_paragraph(style="List Bullet")
p.add_run("cli.py: ").bold = True
p.add_run("Click CLI command registered under the audiosuite group")

doc.add_heading("Performance", level=2)
p = doc.add_paragraph(style="List Bullet")
p.add_run("Memory: ").bold = True
p.add_run("Low \u2014 files are processed individually")
p = doc.add_paragraph(style="List Bullet")
p.add_run("CPU: ").bold = True
p.add_run("Moderate during tag reading/writing")
p = doc.add_paragraph(style="List Bullet")
p.add_run("Disk I/O: ").bold = True
p.add_run("Primary bottleneck \u2014 files are opened, read, and rewritten")
p = doc.add_paragraph(style="List Bullet")
p.add_run("Scalability: ").bold = True
p.add_run("Tested with libraries of 10,000+ files")

# ── Save ──
output = (
    "D:\\Users\\wilte\\Desktop\\AudioSuite-Pro\\user_guides\\individual_programs\\"
    "tag_field_updater\\Tag_Field_Updater_User_Guide.docx"
)
doc.save(output)
print(f"Saved to {output}")
