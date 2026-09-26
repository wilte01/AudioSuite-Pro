"""Generate the Tag Editor User Guide .docx."""

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

OUTPUT = Path(__file__).resolve().parent / "Tag_Editor_User_Guide.docx"

doc = Document()

heading = doc.add_heading("Tag Editor — User Guide", level=0)
heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
doc.add_paragraph("Version 1.0 — September 2026").alignment = WD_ALIGN_PARAGRAPH.CENTER

doc.add_heading("Overview", level=1)
doc.add_paragraph(
    "The Tag Editor is an interactive grid for common audio metadata fields. "
    "It recursively loads supported audio files, displays their tag values in "
    "an editable table, and applies validated single-field edits and bulk "
    "transformations to the selected files. Every live write "
    "is recorded as one undoable batch, so an entire apply run can be restored "
    "from Undo Tag Edits."
)

doc.add_heading("Quick Start", level=1)
doc.add_paragraph(
    "1. Launch Tag_Editor.pyw.\n"
    "2. Click Browse... and choose your music library folder.\n"
    "3. Click Load Grid.\n"
    "4. Select one or more file rows.\n"
    "5. Choose a field, type a value, and click Apply to Selection.\n"
    "6. Choose a bulk operation and click Apply Bulk to transform every "
    "highlighted row at once.\n"
    "7. Keep Dry Run checked to preview changes, or clear it to write tags."
)

doc.add_heading("Supported File Formats", level=1)
doc.add_paragraph(
    "The Tag Editor uses the AudioSuite shared tag handlers and supports the "
    "suite's canonical audio extensions:"
)

formats = doc.add_table(rows=10, cols=3)
formats.style = "Table Grid"
header = formats.rows[0].cells
header[0].text = "Format"
header[1].text = "Extensions"
header[2].text = "Tag Convention"
for cell in header:
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            run.bold = True

format_rows = [
    ("MP3", ".mp3", "ID3v2"),
    ("FLAC", ".flac", "Vorbis comments"),
    ("Ogg Vorbis", ".ogg", "Vorbis comments"),
    ("MPEG-4 Audio", ".m4a, .mp4", "iTunes atoms"),
    ("Opus", ".opus", "Vorbis comments"),
    ("WAV", ".wav", "Embedded ID3v2"),
    ("AIFF", ".aiff, .aif", "Embedded ID3v2"),
]
for index, (name, extensions, tags) in enumerate(format_rows, start=1):
    cells = formats.rows[index].cells
    cells[0].text = name
    cells[1].text = extensions
    cells[2].text = tags

doc.add_heading("Editable Fields", level=1)
fields = doc.add_table(rows=9, cols=3)
fields.style = "Table Grid"
field_header = fields.rows[0].cells
field_header[0].text = "Field"
field_header[1].text = "Validation"
field_header[2].text = "Clear Behaviour"
for cell in field_header:
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            run.bold = True

field_rows = [
    ("Title", "Free-form text up to 4096 characters", "Removes the title tag"),
    ("Artist", "Free-form text up to 4096 characters", "Removes the artist tag"),
    ("Album", "Free-form text up to 4096 characters", "Removes the album tag"),
    (
        "Album Artist",
        "Free-form text up to 4096 characters",
        "Removes the album-artist tag",
    ),
    ("Track", "'N' or 'N/M', numbers 1–9999", "Removes the track tag"),
    ("Year", "Four-digit year or ISO date", "Removes the year/date tag"),
    ("Genre", "Free-form text up to 4096 characters", "Removes the genre tag"),
    (
        "Comment",
        "Multiline text up to 4096 characters",
        "Removes the comment tag",
    ),
]
for index, (field, validation, clearing) in enumerate(field_rows, start=1):
    cells = fields.rows[index].cells
    cells[0].text = field
    cells[1].text = validation
    cells[2].text = clearing

doc.add_heading("Using the Grid", level=1)
doc.add_paragraph(
    "The File column shows each filename; the remaining columns show the "
    "current editable values. Rows can be selected individually or with the "
    "keyboard and mouse. Selecting one row loads its current value into the "
    "edit form."
)
doc.add_paragraph(
    "Apply to Selection sends the same field edit to every highlighted file. "
    "Files whose current value already matches the requested value are "
    "reported as unchanged and are not rewritten."
)

doc.add_heading("Bulk Operations", level=1)
doc.add_paragraph(
    "The Bulk Operations panel applies a transformation to every selected row "
    "in one undoable apply run."
)

bulk = doc.add_table(rows=6, cols=2)
bulk.style = "Table Grid"
bulk_header = bulk.rows[0].cells
bulk_header[0].text = "Operation"
bulk_header[1].text = "Effect"
for cell in bulk_header:
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            run.bold = True

bulk_rows = [
    (
        "Set Blank",
        "Stores an empty string in the selected field without removing the tag.",
    ),
    ("Clear Field", "Removes the selected field from each highlighted file."),
    (
        "Swap Fields",
        "Exchanges the selected field with the second field on every row.",
    ),
    (
        "Case Convert",
        "Converts the selected field to Title Case, Upper Case, or Lower Case.",
    ),
    (
        "Normalize Slashes (TXXX Rule)",
        "Replaces bare '/' separators with '; ' while preserving ' / ', "
        "matching the Tag Field Updater rule.",
    ),
]
for index, (operation, effect) in enumerate(bulk_rows, start=1):
    cells = bulk.rows[index].cells
    cells[0].text = operation
    cells[1].text = effect

doc.add_paragraph(
    "Swap Fields uses both field selectors and ignores rows where the two "
    "values are already equal. Normalize Slashes is limited to text fields so "
    "track totals and dates cannot be corrupted."
)

doc.add_heading("Dry Run and Live Update", level=1)
doc.add_paragraph(
    "Dry Run is selected by default. A dry run reads current values and "
    "reports the proposed old/new comparison, but never writes tags. Clear "
    "Dry Run to write changes. When launched from the Master Driver, the "
    "utility mode selection chooses the initial Dry Run / Live Update state."
)

doc.add_heading("Undo", level=1)
doc.add_paragraph(
    "Every live Apply to Selection or Apply Bulk run creates one "
    "tag_editor undo batch. Open Undo_Tag_Edits.pyw and revert that batch to "
    "restore every file changed by the run. Files that had no tags before the "
    "run are restored to their tagless state."
)

doc.add_heading("Command Line", level=1)
doc.add_paragraph(
    "The headless command edits one field in one audio file. It defaults to "
    "live mode; add --dry to preview the change without writing."
)
doc.add_paragraph('audiosuite tag-edit PATH --field title --value "New Title"')
doc.add_paragraph("audiosuite tag-edit PATH --field comment --clear --dry")
doc.add_paragraph(
    "Use --json for machine-readable output. The command exits with a nonzero "
    "status when validation or the tag write fails."
)

doc.add_heading("Master Driver", level=1)
doc.add_paragraph(
    "The Tag Editor card appears on the Utilities tab. Selecting the card and "
    "starting the selected utility opens the editor with the driver's music "
    "directory preloaded. The driver's Dry Run / Live Update mode is passed "
    "to the editor; Clear Logs and Parallel Run remain driver-owned controls."
)

doc.save(str(OUTPUT))
print(f"Saved to {OUTPUT}")
