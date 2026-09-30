"""Generate a fresh Tempo Analyzer guide from the current implementation.

The tempo naming-scheme tables are imported from
``tempo_analyzer.core.tempo_schemes`` (a pure, I/O-free module) so the
published BPM ranges can never drift from the code that assigns them.

Per-tool logging guides were removed suite-wide (plan iteration 7, item A2),
so this generator produces only ``Tempo_Analyzer_User_Guide.docx``. The
log-file behaviour is documented in that guide's "Log Files" section instead.
The absence of a ``Tempo_Analyzer_Logging_Guide.docx`` is therefore a
deliberate decision, not a gap: no logging guide is registered in
``audio_suite_shared.platform_utils.guide_to_program``, and
``tests/test_user_guide_hygiene.py`` locks that absence in place.
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from tempo_analyzer.core.tempo_schemes import DEFAULT_SCHEME, TEMPO_SCHEMES

OUTPUT = Path(__file__).resolve().parent / "Tempo_Analyzer_User_Guide.docx"

FORMATS = "MP3, FLAC, OGG, M4A, MP4, Opus, WAV, AIFF, and AIF"

WORKER_COUNT = 4


def bullet(doc: Document, title: str, text: str) -> None:
    """Add a bulleted line with a bold lead-in."""
    paragraph = doc.add_paragraph(style="List Bullet")
    paragraph.add_run(title).bold = True
    paragraph.add_run(text)


def numbered(doc: Document, steps: tuple[str, ...]) -> None:
    """Add a numbered list."""
    for step in steps:
        doc.add_paragraph(step, style="List Number")


def shade(cell, hex_fill: str) -> None:
    """Apply a solid background fill to a table cell."""
    element = cell._tc.get_or_add_tcPr().makeelement(qn("w:shd"), {})
    element.set(qn("w:val"), "clear")
    element.set(qn("w:color"), "auto")
    element.set(qn("w:fill"), hex_fill)
    cell._tc.get_or_add_tcPr().append(element)


def callout(doc: Document, title: str, text: str) -> None:
    """Add a shaded single-cell note box."""
    table = doc.add_table(rows=1, cols=1)
    table.style = "Table Grid"
    cell = table.cell(0, 0)
    shade(cell, "FFF4CE")
    paragraph = cell.paragraphs[0]
    paragraph.add_run(f"{title}\n").bold = True
    paragraph.add_run(text)
    doc.add_paragraph()


def code_box(doc: Document, lines: str) -> None:
    """Add a shaded monospaced box for command syntax or output."""
    table = doc.add_table(rows=1, cols=1)
    table.style = "Table Grid"
    cell = table.cell(0, 0)
    shade(cell, "F2F2F2")
    paragraph = cell.paragraphs[0]
    for index, line in enumerate(lines.strip("\n").split("\n")):
        if index:
            paragraph.add_run("\n")
        run = paragraph.add_run(line)
        run.font.name = "Consolas"
        run.font.size = Pt(9)
    doc.add_paragraph()


def grid(doc: Document, headers: tuple[str, ...], rows) -> None:
    """Add a bordered table with a bold header row."""
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for index, header in enumerate(headers):
        cell = table.cell(0, index)
        shade(cell, "D9E2F3")
        run = cell.paragraphs[0].add_run(header)
        run.bold = True
    for row in rows:
        cells = table.add_row().cells
        for index, value in enumerate(row):
            cells[index].paragraphs[0].add_run(str(value))
    doc.add_paragraph()


def bpm_range(low: int, high: int | None) -> str:
    """Render an inclusive BPM band, using '+' for the open top band."""
    if high is None:
        return f"{low}+"
    if low == high:
        return str(low)
    return f"{low}-{high}"


doc = Document()
title = doc.add_heading("Tempo Analyzer & Tagger - User Guide", level=0)
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
subtitle = doc.add_paragraph("Based on the current Tempo Analyzer implementation")
subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
subtitle.runs[0].font.color.rgb = RGBColor(0x44, 0x44, 0x44)

callout(
    doc,
    "Prerequisite - BPM tags required",
    "This program reads existing BPM values already present in your files' "
    "tags (the TBPM ID3 frame for MP3/WAV/AIFF, or the equivalent field for "
    "FLAC, OGG, Opus, MP4, and M4A). It does not detect or calculate BPM. Run "
    "the BPM Analyzer tool first if your files do not already carry BPM tags.",
)

doc.add_heading("Overview", level=1)
doc.add_paragraph(
    "Tempo Analyzer & Tagger reads existing BPM tags from your music files "
    "and automatically adds human-readable tempo markings. Supported formats "
    f"are {FORMATS}. Musical terms like Allegro, Andante, and Presto convey "
    "both speed and character in a way that a bare number cannot. The "
    f"program offers {len(TEMPO_SCHEMES)} built-in naming schemes - from "
    "traditional Italian classical terms to dance music genres and running "
    "paces - and saves your preferred scheme automatically between sessions."
)

doc.add_heading("What Are Tempo Markings?", level=2)
doc.add_paragraph(
    "Tempo markings are musical terms that describe the speed and character "
    "of a piece of music, providing more context than a bare number. Allegro "
    '(lively, fast) at 140 BPM conveys both speed and mood; "140 BPM" is '
    "purely numerical. These markings help musicians and listeners understand "
    "the intended feel of the music, and in digital libraries they provide an "
    "elegant way to browse and organise tracks by musical character."
)

doc.add_heading("Key Features", level=2)
bullet(
    doc,
    "Reads existing BPM tags: ",
    f"Reads existing BPM tags from {FORMATS} files.",
)
bullet(
    doc,
    f"{len(TEMPO_SCHEMES)} built-in tempo naming schemes: ",
    ", ".join(TEMPO_SCHEMES),
)
bullet(
    doc,
    "Format-correct tag writing: ",
    "Writes a custom TEMPO tag to each file - TXXX:TEMPO for MP3, WAV, and "
    "AIFF/AIF; a Vorbis tempo comment for FLAC, OGG, and Opus; an "
    "iTunes-style ----:com.apple.iTunes:TEMPO atom for M4A and MP4.",
)
bullet(
    doc,
    "Automatic scheme saving: ",
    "Your preferred scheme is stored in the shared suite configuration and "
    "restored automatically on the next run.",
)
bullet(
    doc,
    "Re-tagging: ",
    "An existing TEMPO tag is updated when the BPM or the selected scheme has "
    "changed; the previous value is shown in the log.",
)
bullet(
    doc,
    "Parallel processing: ",
    f"{WORKER_COUNT} concurrent worker slots show live per-file progress.",
)
bullet(doc, "Dry Run mode: ", "Preview every assignment before writing tags.")
bullet(
    doc,
    "In-app scheme reference: ",
    "A reference table of BPM ranges and markings updates as you switch schemes.",
)
bullet(doc, "Detailed categorised logging: ", "See Log Files below.")

doc.add_heading("System Requirements", level=1)
grid(
    doc,
    ("Requirement", "Detail"),
    (
        ("Python", "3.11 or higher (the suite's declared floor)"),
        ("Operating System", "Windows, macOS, or Linux"),
        (
            "mutagen",
            "Audio tag reading and writing - installed with the suite "
            "(pip install mutagen)",
        ),
        (
            "CPU",
            f"Multi-core recommended ({WORKER_COUNT}+ workers for full "
            "parallel performance)",
        ),
        ("RAM", "Minimal - only tag metadata in memory"),
    ),
)

doc.add_heading("Tempo Naming Schemes", level=1)
doc.add_paragraph(
    "Choose the scheme that best fits your collection and use case. Your "
    "selection is saved to the shared suite configuration and restored "
    f"automatically on the next run. The default is {DEFAULT_SCHEME}."
)
grid(
    doc,
    ("Scheme", "Best For"),
    (
        ("Italian", "Classical music collections, educational use, musicians"),
        ("English", "General libraries where plain language is preferred"),
        (
            "Descriptive",
            "Workout playlists, mood-based organisation, energy filtering",
        ),
        ("Numeric", "Technical users who prefer direct BPM range labels"),
        ("Simplified", "Minimalist libraries, quick four-tier categorisation"),
        ("Dance", "EDM, DJ collections, electronic music libraries"),
        ("Running", "Fitness playlists, exercise apps, running coaching"),
    ),
)

doc.add_heading("Full Scheme Reference", level=2)
doc.add_paragraph(
    "Each scheme below uses its own BPM ranges. The ranges are not aligned "
    'across schemes - for example, the Descriptive scheme\'s "Easy Pace" band '
    "(61-90) does not start or end at the same BPM as any Italian band, so "
    "each scheme is listed with its own boundaries rather than sharing a "
    "single combined column. Bands are inclusive at both ends; the top band "
    "of each scheme is open-ended."
)

for scheme_name, markings in TEMPO_SCHEMES.items():
    doc.add_heading(scheme_name, level=3)
    grid(
        doc,
        ("BPM Range", "Marking"),
        [(bpm_range(low, high), marking) for low, high, marking in markings],
    )

callout(
    doc,
    "Note on the Allegro range",
    "In the Italian scheme, Allegro spans a wide range (121-168 BPM), covering "
    "light, moderate, and brisk fast tempos. This reflects traditional "
    "musical practice where Allegro is a broad category rather than a precise "
    "marking. Vivace and Presto distinguish the upper reaches.",
)

doc.add_heading("Getting Started", level=1)
doc.add_heading("Launching the Program", level=2)
doc.add_paragraph(
    "Double-click Tempo_Analyzer.pyw to launch the graphical interface. The "
    ".pyw extension runs the program without showing a console window."
)

doc.add_heading("Interface Overview", level=1)
doc.add_paragraph(
    "The program uses a three-tab interface to guide you through "
    "configuration, tagging, and review."
)

doc.add_heading("Tab 1 - Setup", level=2)
doc.add_paragraph("Configure all parameters before starting.")

doc.add_heading("Run Controls Panel (Master Driver Options)", level=3)
doc.add_paragraph(
    "The top of the Setup tab contains a Run Controls panel that mirrors the "
    "Master Driver source bar and control strip. It shows exactly the source "
    "directory and control options the Master Driver passes to this program:"
)
for text in (
    "Source Music Directory - the folder containing music files with BPM "
    "tags, with a Browse button",
    "Mode - Dry Run or Live Update",
    "Auto Start - begin the tempo analysis automatically on launch",
    "Auto End - close the window automatically once processing finishes",
    "Clear Logs / Parallel - Master Driver orchestration options shown here "
    "for reference; they mirror the driver's settings but stay greyed out "
    "because only the driver executes them",
):
    doc.add_paragraph(text, style="List Bullet")
doc.add_paragraph(
    "When the program is launched via the Master Driver, every inherited "
    "value is displayed but locked (greyed out), because those settings are "
    "owned by the driver. When the program is launched standalone, the Source "
    "directory, Mode, and Auto End remain editable, while Auto Start stays "
    "greyed out because an automatic start-up can only be requested by the "
    "Master Driver."
)

doc.add_heading("Music Directory", level=3)
for text in (
    "Choose the folder via the Source Music Directory field in the Run "
    "Controls panel above",
    f"The program processes all supported audio files ({FORMATS}) in the directory",
    "Does not recurse into subdirectories",
):
    doc.add_paragraph(text, style="List Bullet")

doc.add_heading("Tempo Naming Scheme", level=3)
for text in (
    "Choose your preferred scheme in the dropdown: " + ", ".join(TEMPO_SCHEMES),
    "Your selection is saved to the shared suite configuration and restored "
    "automatically on the next launch",
):
    doc.add_paragraph(text, style="List Bullet")

doc.add_heading("Tempo Marking Reference", level=3)
for text in (
    "A scrollable reference table showing all BPM ranges and their markings "
    "for the currently selected scheme",
    "Updates automatically when you change schemes - useful for reviewing "
    "ranges before processing",
):
    doc.add_paragraph(text, style="List Bullet")

doc.add_heading("Select Mode", level=3)
doc.add_paragraph(
    "Choose the mode from the Mode dropdown on the Run Controls panel at the "
    "top of the tab:"
)
grid(
    doc,
    ("Mode", "Behaviour"),
    (
        (
            "Dry Run",
            "Reads BPM tags and shows what tempo marking would be assigned to "
            "each file, without writing anything. Always use this first.",
        ),
        (
            "Live Update",
            "Writes a TEMPO tag to your music files (format-specific - see "
            "Tag Format in Technical Details). Only use after verifying Dry "
            "Run results.",
        ),
    ),
)

doc.add_heading("Tool Configuration Presets", level=3)
doc.add_paragraph(
    "Each tool supports saving and loading named configuration presets. This "
    "lets you quickly switch between different setups - for example, "
    '"Archive Quality" for final storage and "Quick Draft" for rough cuts.'
)
doc.add_paragraph("Saving a Preset", style="List Bullet").runs[0].bold = True
for text in (
    "Configure all settings in the Setup tab as desired.",
    "Type a name in the Presets field (or choose a name from the dropdown).",
    "Click Save to store the current settings under that name.",
    "The preset is saved per-tool and persists across sessions.",
):
    doc.add_paragraph(text, style="List Bullet")
doc.add_paragraph("Loading a Preset", style="List Bullet").runs[0].bold = True
doc.add_paragraph(
    "Choose a preset name in the dropdown to instantly restore all saved settings.",
    style="List Bullet",
)
doc.add_paragraph("Deleting a Preset", style="List Bullet").runs[0].bold = True
for text in (
    "Choose the preset name in the dropdown.",
    "Click Delete and confirm the deletion.",
    "The preset is removed permanently.",
):
    doc.add_paragraph(text, style="List Bullet")
doc.add_paragraph(
    "Presets are stored in the shared suite configuration file and are "
    "independent of the tool's last-used settings."
)

doc.add_heading("Tab 2 - Processing", level=2)
doc.add_paragraph("Becomes active when you click BEGIN TEMPO ANALYSIS.")
doc.add_paragraph("Displays:")
for text in (
    "Overall status showing the current operation phase",
    "Progress bar with completion percentage",
    "Running statistics: Processed, Skipped, Errors",
    f"Worker status panel showing all {WORKER_COUNT} parallel workers and the "
    "file each is currently processing",
    "Real-time file list showing the assigned tempo marking and BPM value for "
    "each file",
):
    doc.add_paragraph(text, style="List Bullet")
code_box(
    doc,
    """[DRY RUN] Track01.mp3 -> Allegro (128 BPM)
[TAGGED]  Track02.mp3 -> Andante (84 BPM)
[TAGGED]  Track03.mp3 -> House (122 BPM)
[SKIP]    Track04.mp3 (No BPM tag)
[SKIP]    Track05.mp3 (No tags found)
[ERROR]   Track06.mp3""",
)

doc.add_heading("Tab 3 - Results", level=2)
doc.add_paragraph("Displays the final summary after processing completes:")
for text in (
    "Summary statistics - total files, tagged, skipped, errors, and processing time",
    "View Log - opens the detailed log file with all tempo assignments",
    "Open Folder - opens the source music directory in your file explorer",
):
    doc.add_paragraph(text, style="List Bullet")

doc.add_heading("Step-by-Step Guide", level=1)
numbered(
    doc,
    (
        "Ensure files have BPM tags. Verify your music files already have BPM "
        "tags. If not, run BPM Analyzer first.",
        "Launch the program. Double-click Tempo_Analyzer.pyw.",
        "Select your music folder. Click Browse and navigate to your music directory.",
        "Choose your tempo scheme. Select from the dropdown. The reference "
        "table updates to show the BPM ranges for your chosen scheme. Your "
        "selection is saved automatically.",
        "Run Dry Run first. Select Dry Run mode and click BEGIN TEMPO "
        "ANALYSIS. Review the assigned markings in the file list.",
        "Verify results. Check that the markings look appropriate. If files "
        "are showing SKIP (No BPM tag), the file has tags but no BPM value - "
        "run BPM Analyzer on those files first. If files show SKIP (No tags "
        "found), the file has no tag block at all and also needs BPM Analyzer "
        "run on it. If the scheme doesn't feel right for your collection, try "
        "a different one.",
        "Tag your files. Return to the Setup tab, change mode to Live Update, "
        "and run again. TEMPO tags will be written to all files with BPM "
        "values.",
        "Check in your music player. The TEMPO custom tag field should now be "
        "visible in tag editors and players such as Foobar2000 or MusicBee "
        "(shown as a TXXX frame for MP3/WAV/AIFF/AIF, a Vorbis comment for "
        "FLAC/OGG/Opus, or an iTunes-style atom for M4A/MP4).",
    ),
)

doc.add_heading("Processing Status Reference", level=1)
grid(
    doc,
    ("Status", "Meaning"),
    (
        (
            "[TAGGED]",
            "Tempo marking successfully written (or would be written in Dry "
            "Run mode - see below)",
        ),
        (
            "[DRY RUN]",
            "Dry Run mode - marking calculated and displayed but not written",
        ),
        (
            "[SKIP] No BPM tag",
            "File has tag metadata but no BPM value set - run BPM Analyzer first",
        ),
        (
            "[SKIP] No tags found",
            "File has no tag metadata at all - the file needs tagging before "
            "Tempo Analyzer can help",
        ),
        ("[ERROR]", "Unexpected error during processing - check the log"),
    ),
)

doc.add_heading("Configuration", level=1)
doc.add_paragraph(
    "Tempo Analyzer stores its preferences in the suite-wide shared "
    "configuration file, alongside every other tool's preferences. It does "
    "not create a tool-local file."
)
grid(
    doc,
    ("Property", "Detail"),
    (
        ("Filename", "audio_suite_config.json"),
        ("Location", "The Audio Suite root directory (shared by all tools)"),
        ("Format", 'JSON - { "tempo_scheme": "Italian" }'),
        ("Written", "Whenever you change the scheme selection"),
        ("Read", "On every startup to restore the last-used scheme"),
    ),
)
doc.add_paragraph(
    "If the value is missing, unreadable, or names a scheme that no longer "
    f"exists, the program falls back to {DEFAULT_SCHEME}. If the shared "
    "configuration cannot be written, the program still runs - the choice is "
    "simply not remembered."
)

doc.add_heading("Log Files", level=1)
grid(
    doc,
    ("Log File", "Created When"),
    (
        ("tempo_dry_run_log.txt", "After every Dry Run"),
        ("tempo_analysis_log.txt", "After every Live Update run"),
    ),
)
doc.add_paragraph("Log contents include:")
for text in (
    "Selected tempo scheme name and processing mode",
    "Tempo marking and BPM value assigned to each file",
    "Previous TEMPO tag value (if updating an existing tag)",
    "Status for each file: TAGGED, DRY RUN, SKIP, or ERROR",
    "Summary statistics and total processing time",
):
    doc.add_paragraph(text, style="List Bullet")

doc.add_heading("Command-Line Operation", level=1)
doc.add_paragraph(
    "Tempo Analyzer can be launched from the command line in two ways: the "
    "positional handshake the Master Driver uses, and the suite's unified "
    "command."
)

doc.add_heading("Master Driver Handshake (.pyw)", level=2)
doc.add_paragraph(
    "The Master Driver launches the program with a fixed positional layout."
)
code_box(
    doc,
    r"""python Tempo_Analyzer.pyw <folder> <unused>
    <--live|--dry> <--start|--no-start> <--end|--no-end>
    [--scheme <SchemeName>]""",
)
grid(
    doc,
    ("Position / Flag", "Value / Description"),
    (
        (
            "1 - folder",
            "Path to the directory containing supported audio files (required)",
        ),
        ("2 - (unused)", "Reserved positional slot - pass any value; ignored"),
        ("3 - mode", "--live or --dry"),
        ("4 - auto_start", "--start or --no-start"),
        ("5 - auto_end", "--end or --no-end"),
        (
            "--scheme <name>",
            "Override the saved scheme: "
            + ", ".join(TEMPO_SCHEMES)
            + ". If omitted, the saved scheme is used.",
        ),
        (
            "--clear-logs / --parallel-run",
            "Display-only flags mirrored from the driver; they are shown in "
            "the interface but not executed by this tool",
        ),
    ),
)

doc.add_heading("Unified Suite Command", level=2)
code_box(
    doc,
    """audiosuite tempo <directory> [--dry|--live] [--json|--text]
    [--scheme <SchemeName>]""",
)
grid(
    doc,
    ("Argument / Option", "Description"),
    (
        (
            "directory",
            "Required positional path to the music directory. The directory "
            "must already exist.",
        ),
        (
            "--dry / --live",
            "Preview only, or write TEMPO tags. Omitting the flag is "
            "equivalent to --dry.",
        ),
        (
            "--json / --text",
            "Emit machine-readable JSON (default) or a one-line text summary.",
        ),
        (
            "--scheme <name>",
            f"Scheme to apply. Omitting the flag uses {DEFAULT_SCHEME}.",
        ),
    ),
)
doc.add_paragraph("Examples:")
code_box(
    doc,
    r"""audiosuite tempo "C:\Music\Classical" --dry
audiosuite tempo "C:\Music\House Collection" --live --scheme Dance
audiosuite tempo "C:\Music\Classical" --live --scheme Italian --text""",
)
callout(
    doc,
    "Two different defaults",
    "The unified command always defaults to the "
    f"{DEFAULT_SCHEME} scheme and does not read your saved preference, "
    "because it is a batch entry point rather than an interactive launch. "
    "Pass --scheme explicitly if you want a specific scheme. The .pyw "
    "handshake is the opposite: it restores your saved preference when "
    "--scheme is omitted.",
)

doc.add_heading("Undo", level=2)
doc.add_paragraph(
    "Live Update tag changes participate in the suite's batch undo context, "
    "so they can be reverted through the Undo Tag Edits workflow using the "
    "tag snapshots taken at processing time. Dry Run never writes, so it "
    "creates no undo entry."
)

doc.add_heading("Troubleshooting", level=1)

doc.add_heading("Scheme Not Remembered", level=2)
for text in (
    "The shared audio_suite_config.json lives in the Audio Suite root "
    "directory - confirm you are running the suite from its installed "
    "location and that the directory is writable",
    "If the file exists but is read-only, the scheme change is not saved",
    "If the stored value is not a valid scheme name, the program falls back "
    f"to {DEFAULT_SCHEME}",
):
    doc.add_paragraph(text, style="List Bullet")

doc.add_heading("Wrong Tempo Scheme Applied", level=2)
for text in (
    "Check the selected scheme in the Setup tab dropdown before processing",
    "Review the reference table to confirm BPM ranges match your expectations",
    "Run Dry Run mode first to preview assignments before committing",
    "Re-run with the correct scheme - existing TEMPO tags will be updated",
):
    doc.add_paragraph(text, style="List Bullet")

doc.add_heading("Files Showing SKIP Status", level=2)
for text in (
    "The Tempo Analyzer requires an existing BPM value in the file's tags. "
    "Run the BPM Analyzer tool on these files first",
    "Verify BPM tags are present by opening one file in a tag editor such as "
    "Mp3tag and checking for the BPM field",
    "[SKIP] No tags found means the file has no tag block at all; "
    "[SKIP] No BPM tag means the file has tags but no BPM value set",
):
    doc.add_paragraph(text, style="List Bullet")

doc.add_heading("mutagen Not Found", level=2)
for text in (
    "Install mutagen: pip install mutagen",
    'Verify: python -c "import mutagen; print(mutagen.version)"',
):
    doc.add_paragraph(text, style="List Bullet")

doc.add_heading("Common Use Cases", level=1)

doc.add_heading("Classical Collection Cataloguing", level=2)
doc.add_paragraph(
    "Apply the Italian scheme to a classical library to annotate tracks with "
    "the tempo markings that composers and performers use. Allegretto, "
    "Andante, and Vivace sit naturally alongside other classical metadata, "
    "and the TEMPO tag makes it easy to filter by tempo in Foobar2000 or "
    "MusicBee."
)

doc.add_heading("DJ Library Organisation", level=2)
doc.add_paragraph(
    "Apply the Dance scheme to an electronic music collection to group tracks "
    "by genre-approximate tempo bands - House, Techno, Drum and Bass, and so "
    "on. Combined with BPM tags already written by BPM Analyzer, this gives "
    "DJ software an additional human-readable dimension for track selection."
)

doc.add_heading("Workout and Running Playlists", level=2)
doc.add_paragraph(
    "Apply the Running scheme to a fitness music collection to tag tracks by "
    "exercise intensity: Walking Pace, Easy Run, Moderate Run, Fast Run, "
    "Sprint. Filter by the TEMPO tag to quickly assemble a playlist matched "
    "to a specific training zone."
)

doc.add_heading("Mood-Based Library Browsing", level=2)
doc.add_paragraph(
    "Apply the Descriptive scheme to tag tracks by energy level: Relaxed, "
    "Easy Pace, Moderate Energy, Energetic, High Energy, Intense, Frantic. "
    "Combined with genre and rating tags, this enables fine-grained filtering "
    "for mood-based playlist creation."
)

doc.add_heading("Tips and Best Practices", level=1)
numbered(
    doc,
    (
        "Run BPM Analyzer first. Tempo Analyzer is a downstream tool - it "
        "needs accurate BPM tags to produce useful tempo markings.",
        "Always use Dry Run first. Preview assignments before writing tags, "
        "especially when switching schemes.",
        "Match scheme to genre. Italian for classical; Dance for EDM; Running "
        "or Descriptive for fitness playlists; English or Simplified for "
        "general libraries.",
        "Process by genre if using multiple schemes. Run Tempo Analyzer "
        "separately on each genre folder with its most appropriate scheme - "
        "the scheme can be overridden per run with --scheme.",
        "Verify BPM accuracy first. Incorrect BPM values lead to incorrect "
        "tempo markings. Spot-check BPM tags before running Tempo Analyzer on "
        "a large library.",
        "Re-run freely. Existing TEMPO tags are overwritten if the BPM or "
        "scheme has changed. There is no need to clear tags manually before "
        "switching schemes.",
        "Review the reference table. Check the in-app reference table for the "
        "currently selected scheme before processing to confirm the BPM "
        "ranges match your expectations.",
        "Check the log. The log shows both the assigned marking and the source "
        "BPM value, making it easy to spot files where the BPM tag might be "
        "wrong.",
    ),
)

doc.add_heading("Technical Details", level=1)

doc.add_heading("Tag Format", level=2)
doc.add_paragraph(
    "The tag written depends on file format. The table below covers the "
    "ID3-based formats. For FLAC, OGG, and Opus, the marking is stored in a "
    "Vorbis comment field named tempo. For M4A and MP4, it is stored in an "
    "iTunes-style freeform atom."
)
grid(
    doc,
    ("Property", "Value"),
    (
        ("Frame type (MP3/WAV/AIFF/AIF)", "TXXX (User Defined Text Information)"),
        ("Description", "TEMPO"),
        (
            "Value",
            "Tempo marking text from the selected scheme (e.g. Allegro, "
            "House, Fast Run)",
        ),
        ("Encoding", "UTF-8 (encoding=3)"),
        ("Compatibility", "ID3v2.3 and ID3v2.4"),
    ),
)

doc.add_heading("Processing Pipeline", level=2)
numbered(
    doc,
    (
        f"File scan. All supported audio files ({FORMATS}) in the directory "
        "are queued for processing.",
        "Tag reading. mutagen reads the file's tag block and locates the BPM "
        "value: the TBPM ID3 frame for MP3/WAV/AIFF/AIF, the Vorbis bpm "
        "comment for FLAC/OGG/Opus, or the tmpo atom for M4A/MP4.",
        "BPM validation. If the file has no tag metadata at all, [SKIP] No "
        "tags found. If tags exist but no BPM value is set, [SKIP] No BPM "
        "tag.",
        "Scheme lookup. The BPM value is matched against the selected "
        "scheme's BPM ranges to determine the marking.",
        "Tag writing. In Live Update mode, the format-specific TEMPO tag is "
        "written or updated. In Dry Run mode, the result is only reported.",
        "Logging. Status, marking, and BPM value are written to the log file.",
    ),
)

doc.add_heading("Performance Characteristics", level=2)
grid(
    doc,
    ("Metric", "Detail"),
    (
        (
            "Parallel workers",
            f"{WORKER_COUNT} concurrent worker slots via a thread pool",
        ),
        ("CPU usage", "Very low - only tag read/write operations"),
        ("Memory usage", "Minimal - only tag metadata in RAM per worker"),
        (
            "Processing speed",
            "Very fast - hundreds of files per second on typical hardware",
        ),
    ),
)

end = doc.add_paragraph("- End of User Guide -")
end.alignment = WD_ALIGN_PARAGRAPH.CENTER

doc.save(OUTPUT)
print(f"Saved to {OUTPUT}")
