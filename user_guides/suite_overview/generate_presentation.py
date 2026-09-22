"""Generate the AudioSuite-Pro new-user presentation (.pptx).

Builds a guided tour of the suite for new users: what the suite is, the
three-stage map, every tool grouped by category, format support, and
where to go for detail. Content is compiled from the current tool
registry (audio_suite_shared.tool_plugin), each tool's own User Guide
generator, and the suite Overview Guide.

Usage:
    python user_guides/suite_overview/generate_presentation.py
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.slide import Slide
from pptx.table import _Cell
from pptx.text.text import _Paragraph, _Run
from pptx.util import Inches, Pt

OUTPUT = Path(__file__).resolve().parent / "AudioSuite-Pro_New_User_Presentation.pptx"

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)

NAVY = RGBColor(0x1F, 0x38, 0x64)
INK = RGBColor(0x2E, 0x2E, 0x2E)
GREY_TEXT = RGBColor(0x5A, 0x5A, 0x5A)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT_BLUE = RGBColor(0xBD, 0xD7, 0xEE)

REFINE = RGBColor(0xC5, 0x5A, 0x11)
ENRICH = RGBColor(0x0F, 0x76, 0x6E)
UTIL = RGBColor(0x2E, 0x75, 0xB6)
REFINE_LIGHT = RGBColor(0xFB, 0xEE, 0xE3)
ENRICH_LIGHT = RGBColor(0xE2, 0xF1, 0xEF)
UTIL_LIGHT = RGBColor(0xE7, 0xF0, 0xF9)
CARD_GREY = RGBColor(0xF2, 0xF2, 0xF2)
ROW_ALT = RGBColor(0xF7, 0xF7, 0xF7)

FONT = "Segoe UI"

YES = "\u2713"
NO = "\u2014"


@dataclass(frozen=True)
class Line:
    """A single paragraph rendered inside a text box or card."""

    text: str
    size: int = 14
    bold: bool = False
    italic: bool = False
    color: RGBColor = INK
    font: str = FONT
    space_after: int = 6
    marker: str = ""
    lead: str = ""
    accent: RGBColor = NAVY
    align: PP_ALIGN = PP_ALIGN.LEFT


def _style(
    run: _Run,
    size: int,
    *,
    bold: bool = False,
    italic: bool = False,
    color: RGBColor = INK,
    font: str = FONT,
) -> None:
    """Apply font styling to a run."""
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    run.font.name = font


def _render_paragraph(para: _Paragraph, line: Line) -> None:
    para.alignment = line.align
    para.space_after = Pt(line.space_after)
    if line.marker:
        run = para.add_run()
        run.text = line.marker + "  "
        _style(run, line.size, bold=True, color=line.accent)
    if line.lead:
        run = para.add_run()
        run.text = line.lead + "  "
        _style(run, line.size, bold=True, color=line.accent)
    run = para.add_run()
    run.text = line.text
    _style(run, line.size, bold=line.bold, italic=line.italic, color=line.color)


def new_slide(prs: Presentation) -> Slide:
    """Add a blank slide and return it."""
    return prs.slides.add_slide(prs.slide_layouts[6])


def add_textbox(
    slide: Slide,
    left: float,
    top: float,
    width: float,
    height: float,
    lines: list[Line],
    *,
    anchor: MSO_ANCHOR = MSO_ANCHOR.TOP,
) -> None:
    """Add a text box rendering one paragraph per Line."""
    box = slide.shapes.add_textbox(
        Inches(left), Inches(top), Inches(width), Inches(height)
    )
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    for idx, line in enumerate(lines):
        para = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        _render_paragraph(para, line)


def add_card(
    slide: Slide,
    left: float,
    top: float,
    width: float,
    height: float,
    title: str,
    body: list[Line],
    accent: RGBColor,
    fill: RGBColor,
    *,
    title_size: int = 15,
    body_size: int = 12,
) -> None:
    """Add a rounded-rectangle card with a colored title and bullet body."""
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE,
        Inches(left),
        Inches(top),
        Inches(width),
        Inches(height),
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.color.rgb = accent
    shape.line.width = Pt(1.25)
    shape.shadow.inherit = False
    shape.adjustments[0] = 0.05
    tf = shape.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.TOP
    tf.margin_left = Inches(0.18)
    tf.margin_right = Inches(0.15)
    tf.margin_top = Inches(0.12)
    tf.margin_bottom = Inches(0.1)
    title_para = tf.paragraphs[0]
    title_para.space_after = Pt(6)
    run = title_para.add_run()
    run.text = title
    _style(run, title_size, bold=True, color=accent)
    for line in body:
        para = tf.add_paragraph()
        _render_paragraph(para, replace(line, size=body_size, accent=accent))


def add_flow(
    slide: Slide,
    left: float,
    top: float,
    width: float,
    height: float,
    steps: list[str],
    accent: RGBColor,
) -> None:
    """Add a left-to-right chevron flow of stage names."""
    overlap = 0.18
    count = len(steps)
    step_w = (width + overlap * (count - 1)) / count
    for i, step in enumerate(steps):
        shape_kind = MSO_SHAPE.PENTAGON if i == 0 else MSO_SHAPE.CHEVRON
        shape = slide.shapes.add_shape(
            shape_kind,
            Inches(left + i * (step_w - overlap)),
            Inches(top),
            Inches(step_w),
            Inches(height),
        )
        shape.fill.solid()
        shape.fill.fore_color.rgb = accent
        shape.line.fill.background()
        shape.shadow.inherit = False
        tf = shape.text_frame
        tf.word_wrap = True
        tf.margin_left = Inches(0.14)
        tf.margin_right = Inches(0.04)
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        para = tf.paragraphs[0]
        para.alignment = PP_ALIGN.CENTER
        run = para.add_run()
        run.text = step
        _style(run, 13, bold=True, color=WHITE)


def add_title(
    slide: Slide,
    title: str,
    subtitle: str | None = None,
    accent: RGBColor = NAVY,
) -> None:
    """Add the slide title with a colored accent bar."""
    bar = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0.3), Inches(0.44), Inches(0.09), Inches(0.5)
    )
    bar.fill.solid()
    bar.fill.fore_color.rgb = accent
    bar.line.fill.background()
    bar.shadow.inherit = False
    lines = [Line(title, size=27, bold=True, color=NAVY, space_after=2)]
    if subtitle:
        lines.append(
            Line(subtitle, size=13, italic=True, color=GREY_TEXT, space_after=0)
        )
    add_textbox(slide, 0.55, 0.38, 12.4, 1.0, lines)


def add_footer(slide: Slide, number: int) -> None:
    """Add the suite name (left) and slide number (right)."""
    add_textbox(
        slide,
        0.55,
        7.14,
        6.0,
        0.3,
        [
            Line(
                "AudioSuite-Pro - New User Tour", size=9, color=GREY_TEXT, space_after=0
            )
        ],
    )
    add_textbox(
        slide,
        11.9,
        7.14,
        0.9,
        0.3,
        [
            Line(
                str(number),
                size=9,
                color=GREY_TEXT,
                align=PP_ALIGN.RIGHT,
                space_after=0,
            )
        ],
    )


def add_divider(
    prs: Presentation,
    label: str,
    title: str,
    subtitle: str,
    accent: RGBColor,
) -> None:
    """Add a full-bleed colored section divider."""
    slide = new_slide(prs)
    bg = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), SLIDE_W, SLIDE_H
    )
    bg.fill.solid()
    bg.fill.fore_color.rgb = accent
    bg.line.fill.background()
    bg.shadow.inherit = False
    rule = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0.95), Inches(2.55), Inches(2.2), Inches(0.045)
    )
    rule.fill.solid()
    rule.fill.fore_color.rgb = WHITE
    rule.line.fill.background()
    rule.shadow.inherit = False
    lines = [
        Line(label.upper(), size=15, bold=True, color=LIGHT_BLUE, space_after=10),
        Line(title, size=38, bold=True, color=WHITE, space_after=12),
        Line(subtitle, size=16, color=LIGHT_BLUE, space_after=0),
    ]
    add_textbox(slide, 0.95, 2.85, 11.4, 3.0, lines)


def _fill_cell(
    cell: _Cell,
    text: str,
    *,
    size: int,
    bold: bool = False,
    color: RGBColor = INK,
    fill: RGBColor | None = None,
    align: PP_ALIGN = PP_ALIGN.LEFT,
) -> None:
    """Write styled text into a table cell."""
    if fill is not None:
        cell.fill.solid()
        cell.fill.fore_color.rgb = fill
    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    cell.margin_left = Inches(0.06)
    cell.margin_right = Inches(0.06)
    cell.margin_top = Inches(0.02)
    cell.margin_bottom = Inches(0.02)
    tf = cell.text_frame
    tf.word_wrap = True
    para = tf.paragraphs[0]
    para.alignment = align
    run = para.add_run()
    run.text = text
    _style(run, size, bold=bold, color=color)


def add_table(
    slide: Slide,
    left: float,
    top: float,
    width: float,
    height: float,
    headers: list[str],
    rows: list[list[str]],
    col_widths: list[float],
    *,
    font_size: int = 11,
    accent: RGBColor = NAVY,
    center_cols: tuple[int, ...] = (),
) -> None:
    """Add a table with a colored header row and banded body rows."""
    count = len(rows) + 1
    gf = slide.shapes.add_table(
        count, len(headers), Inches(left), Inches(top), Inches(width), Inches(height)
    )
    table = gf.table
    table.first_row = False
    table.horz_banding = False
    for i, width_in in enumerate(col_widths):
        table.columns[i].width = Inches(width_in)
    for i in range(count):
        table.rows[i].height = Inches(height / count)
    for c, header in enumerate(headers):
        _fill_cell(
            table.cell(0, c),
            header,
            size=font_size,
            bold=True,
            color=WHITE,
            fill=accent,
            align=PP_ALIGN.CENTER if c in center_cols else PP_ALIGN.LEFT,
        )
    for r, row in enumerate(rows, start=1):
        fill = WHITE if r % 2 == 1 else ROW_ALT
        for c, value in enumerate(row):
            _fill_cell(
                table.cell(r, c),
                value,
                size=font_size,
                fill=fill,
                align=PP_ALIGN.CENTER if c in center_cols else PP_ALIGN.LEFT,
            )


# ---------------------------------------------------------------------------
# Slide content
# ---------------------------------------------------------------------------

FORMAT_HEADERS = ["Tool", "MP3", "FLAC", "OGG", "M4A", "Opus", "Notes"]

FORMAT_ROWS: list[list[str]] = [
    ["Audio Refinery", YES, YES, YES, YES, YES, "Plus WAV, AIFF/AIF"],
    ["Audio Enhancer", YES, YES, YES, YES, YES, "Plus WAV, AIFF/AIF"],
    ["Audio Normalizer", YES, YES, YES, YES, YES, "Plus WAV, AIFF"],
    [
        "Pop & Click Remover",
        YES,
        YES,
        YES,
        YES,
        YES,
        "Plus WAV, AIFF/AIF - existing ID3 tags preserved through re-encode",
    ],
    ["Silence Trimmer", YES, YES, YES, YES, YES, "Plus WAV, AIFF"],
    ["BPM Analyzer", YES, YES, YES, YES, YES, "Plus WAV, AIFF"],
    [
        "Tempo Analyzer",
        YES,
        YES,
        YES,
        YES,
        YES,
        "Plus MP4, WAV, AIFF/AIF - reads native BPM tags",
    ],
    ["Key Detector", YES, YES, YES, YES, YES, "Plus WAV, AIFF/AIF"],
    ["ReplayGain Analyzer", YES, YES, YES, YES, YES, "Plus WAV"],
    [
        "Metadata Scrubber",
        YES,
        YES,
        YES,
        YES,
        YES,
        "Plus WAV, AIFF/AIF - no WMA",
    ],
    [
        "Album Genre Tagger",
        YES,
        YES,
        YES,
        YES,
        YES,
        "Plus WAV, AIFF/AIF - format-aware genre tags",
    ],
    ["Genre Sync", YES, YES, YES, YES, YES, "Plus WAV, AIFF/AIF"],
    ["Mood Analyzer", YES, YES, YES, YES, YES, "Plus MP4, WAV, AIFF - signal-based"],
    ["Mood Batch Tagger", YES, YES, YES, YES, YES, "Same scope as Mood Analyzer"],
    ["Album Art Synchronizer", YES, YES, YES, YES, YES, "Plus WAV, AIFF"],
    [
        "Album Art Normalizer",
        YES,
        YES,
        YES,
        YES,
        YES,
        "Plus WAV, AIFF/AIF",
    ],
    [
        "Lyrics Manager",
        YES,
        YES,
        YES,
        YES,
        YES,
        "Plus WAV, AIFF/AIF",
    ],
    [
        "Tag Field Updater",
        YES,
        YES,
        YES,
        YES,
        YES,
        "Plus WAV, AIFF/AIF, WMA",
    ],
    [
        "Music Format Converter",
        YES,
        YES,
        YES,
        YES,
        YES,
        "Plus WMA, MP4, ALAC, APE, AIFF/AIF, WavPack - 14 total",
    ],
    [
        "CD Ripper",
        YES,
        YES,
        YES,
        YES,
        YES,
        "Output formats only - input is a disc; WAV added",
    ],
    [
        "ASX Playlist Extractor",
        YES,
        YES,
        YES,
        YES,
        YES,
        "Resolves .asx refs to any supported audio format",
    ],
    ["Noise Reduction", YES, YES, YES, YES, YES, "Plus WAV, AIFF"],
    [
        "Audio Fingerprinter",
        YES,
        YES,
        YES,
        YES,
        YES,
        "Plus WAV, AIFF/AIF - shared suite formats",
    ],
    [
        "Library Statistics",
        YES,
        YES,
        YES,
        YES,
        YES,
        "Read-only tag scan - all shared suite formats",
    ],
    [
        "Undo Tag Edits",
        YES,
        YES,
        YES,
        YES,
        YES,
        "Restores tag snapshots for all suite formats",
    ],
]

CHOOSER_HEADERS = ["I want to...", "Use"]

CHOOSER_ROWS: list[list[str]] = [
    [
        "Run a full library pipeline hands-off",
        "Master Driver, with Auto-Start and Auto-End enabled",
    ],
    [
        "Clean up vinyl rip clicks and pops",
        "Pop & Click Remover (or Audio Refinery's Declick stage)",
    ],
    [
        "Make all tracks the same loudness, permanently",
        "Audio Normalizer, or the Normalise stage in Audio Refinery",
    ],
    [
        "Consistent volume without altering the audio",
        "ReplayGain Analyzer - metadata-only and reversible",
    ],
    [
        "Tag BPM for DJ use",
        "BPM Analyzer, then Tempo Analyzer for named tempo markings",
    ],
    [
        "Get mood tags for playlist building",
        "Mood Analyzer - or Mood Batch Tagger for a whole library tree",
    ],
    [
        "Every player sees a consistent Genre field",
        "Album Genre Tagger first (if from track-level tags), then Genre Sync",
    ],
    ["Find and embed missing album art", "Album Art Synchronizer"],
    ["Rip a physical CD", "CD Ripper (Windows + Administrator rights required)"],
    ["Convert a whole library to a different format", "Music Format Converter"],
    ["Strip out junk tags from rippers/streaming services", "Metadata Scrubber"],
    ["Recover audio referenced by old .asx playlists", "ASX Playlist Extractor"],
    [
        "Remove mains hum or hiss/background noise",
        "Noise Reduction (or the Reduce Noise stage in Audio Refinery)",
    ],
]

ENRICH_HEADERS = ["#", "Module", "Why it sits here"]

ENRICH_ROWS: list[list[str]] = [
    [
        "1",
        "Metadata Scrubber",
        "Cleans tag clutter before anything else reads or writes tags",
    ],
    [
        "2",
        "Audio Fingerprinter",
        "AcoustID identification - independent of everything else",
    ],
    [
        "3",
        "ReplayGain Analyzer",
        "Independent loudness analysis - fast, so it runs early",
    ],
    [
        "4",
        "Album Genre Tagger",
        "Consolidates TITLEGENRE into ALBUMGENRE across all supported "
        "formats - before Genre Sync",
    ],
    [
        "5",
        "Genre Sync",
        "Reads the tags Album Genre Tagger just wrote; resolves them into TCON",
    ],
    [
        "6",
        "BPM Analyzer",
        "Writes the native BPM tag - a prerequisite for Tempo Analyzer",
    ],
    [
        "7",
        "Tempo Analyzer",
        "Reads the BPM tag (must run after BPM Analyzer) and writes a marking "
        "to each format's native tag",
    ],
    ["8", "Key Detector", "Writes TKEY - the standard musical key tag"],
    ["9", "Mood Analyzer", "Signal-based mood tagging - independent of the tag chains"],
    [
        "10",
        "Album Art Sync",
        "Runs last so artwork is not disturbed by any later tag rewrite",
    ],
    [
        "11",
        "Lyrics Manager",
        "Fetches and embeds lyrics once tag rewrites have settled",
    ],
]

PIPELINE_HEADERS = ["Step", "What happens"]

PIPELINE_ROWS: list[list[str]] = [
    [
        "1 - Integrity validation",
        "Existence, readability, size, magic bytes, decoding, sample rate, "
        "duration, channel checks",
    ],
    ["2 - Load", "Original tags are read and the source audio is decoded"],
    [
        "3 - Pop & Click Remover",
        "Detects and repairs clicks using sensitivity and maximum defect width",
    ],
    [
        "4 - Silence Trimming / Fading",
        "Removes silence using a dBFS threshold; optional fade-in and fade-out",
    ],
    ["5 - Noise Reduction", "Optional removal of mains hum and/or broadband noise"],
    ["6 - Audio Enhancement", "Mild, Moderate, Aggressive, or Custom DSP preset"],
    ["7 - Export", "Processed audio written once with format-appropriate encoding"],
    [
        "8 - Normalise",
        "Loudness measured; configured LUFS target and tolerance applied",
    ],
    [
        "9 - Finish",
        "Tags restored, undo snapshot recorded, output atomically replaced or created",
    ],
]


def slide_title(prs: Presentation) -> None:
    """Build the dark title slide."""
    slide = new_slide(prs)
    bg = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), SLIDE_W, SLIDE_H
    )
    bg.fill.solid()
    bg.fill.fore_color.rgb = NAVY
    bg.line.fill.background()
    bg.shadow.inherit = False
    centered = PP_ALIGN.CENTER
    add_textbox(
        slide,
        0.9,
        2.15,
        11.53,
        1.3,
        [
            Line(
                "AudioSuite-Pro",
                size=54,
                bold=True,
                color=WHITE,
                align=centered,
                space_after=0,
            )
        ],
    )
    add_textbox(
        slide,
        0.9,
        3.45,
        11.53,
        0.7,
        [
            Line(
                "One Suite for Your Whole Music Library",
                size=24,
                color=LIGHT_BLUE,
                align=centered,
                space_after=0,
            )
        ],
    )
    add_textbox(
        slide,
        0.9,
        4.25,
        11.53,
        0.5,
        [
            Line(
                "A guided tour for new users",
                size=15,
                color=WHITE,
                align=centered,
                space_after=0,
            )
        ],
    )
    add_textbox(
        slide,
        0.9,
        5.65,
        11.53,
        0.5,
        [
            Line(
                "Process   .   Repair   .   Analyse   .   Tag   .   Convert",
                size=14,
                color=LIGHT_BLUE,
                align=centered,
                space_after=0,
            )
        ],
    )
    chip_w = 1.4
    gap = 0.25
    start_x = (13.333 - (3 * chip_w + 2 * gap)) / 2
    for i, color in enumerate((REFINE, ENRICH, UTIL)):
        chip = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(start_x + i * (chip_w + gap)),
            Inches(6.4),
            Inches(chip_w),
            Inches(0.09),
        )
        chip.fill.solid()
        chip.fill.fore_color.rgb = color
        chip.line.fill.background()
        chip.shadow.inherit = False


def slide_what(prs: Presentation, number: int) -> None:
    """Build the overview-of-the-suite slide."""
    slide = new_slide(prs)
    add_title(slide, "What is AudioSuite-Pro?")
    add_textbox(
        slide,
        0.55,
        1.25,
        12.2,
        2.7,
        [
            Line(
                "A suite of 26 Windows desktop tools for processing, "
                "repairing, analysing and tagging a music library - plus "
                "one Master Driver that ties them all together.",
                size=15,
                space_after=10,
                marker="\u2022",
                accent=NAVY,
            ),
            Line(
                "Every tool is a standalone application you can run on its "
                "own; most are designed to run as steps in a sequence, each "
                "building on tags or audio written by the tool before it.",
                size=15,
                space_after=10,
                marker="\u2022",
                accent=NAVY,
            ),
            Line(
                "The tools are grouped into three broad stages that mirror "
                "how a music library gets built:",
                size=15,
                space_after=0,
                marker="\u2022",
                accent=NAVY,
            ),
        ],
    )
    add_card(
        slide,
        0.55,
        4.2,
        3.9,
        1.65,
        "REFINE",
        [
            Line(
                "Fix the audio itself - declick, trim silence, enhance "
                "tone, normalise loudness."
            )
        ],
        REFINE,
        REFINE_LIGHT,
        body_size=12,
    )
    add_card(
        slide,
        4.75,
        4.2,
        3.9,
        1.65,
        "ENRICH",
        [Line("Analyse and tag - BPM, key, mood, genre, artwork, lyrics.")],
        ENRICH,
        ENRICH_LIGHT,
        body_size=12,
    )
    add_card(
        slide,
        8.95,
        4.2,
        3.9,
        1.65,
        "UTIL",
        [Line("Convert, extract, rip, and maintain - day-to-day library upkeep.")],
        UTIL,
        UTIL_LIGHT,
        body_size=12,
    )
    add_textbox(
        slide,
        0.55,
        6.15,
        12.2,
        0.7,
        [
            Line(
                "Most tools also have a command-line equivalent via the "
                "audiosuite command - and every tool's Help button opens its "
                "own User Guide.",
                size=13,
                italic=True,
                color=GREY_TEXT,
                space_after=0,
            )
        ],
    )
    add_footer(slide, number)


def slide_map(prs: Presentation, number: int) -> None:
    """Build the three-stages-plus-control-centre map slide."""
    slide = new_slide(prs)
    add_title(slide, "The Map: Three Stages + a Control Centre")
    add_card(
        slide,
        0.55,
        1.3,
        6.0,
        2.5,
        "REFINE",
        [
            Line(
                "Fix the audio itself - declick, trim silence, enhance tone, "
                "normalise loudness - before anything is tagged.",
            )
        ],
        REFINE,
        REFINE_LIGHT,
        title_size=17,
        body_size=13,
    )
    add_card(
        slide,
        6.75,
        1.3,
        6.0,
        2.5,
        "ENRICH",
        [
            Line(
                "Analyse and tag - BPM, tempo, key, mood, genre, artwork, "
                "lyrics - modules that read and write tags, several building "
                "on tags written by others.",
            )
        ],
        ENRICH,
        ENRICH_LIGHT,
        title_size=17,
        body_size=13,
    )
    add_card(
        slide,
        0.55,
        4.1,
        6.0,
        2.5,
        "UTIL",
        [
            Line(
                "Convert, extract, rip, and batch-process - day-to-day library "
                "maintenance that doesn't fit neatly into Refine or Enrich.",
            )
        ],
        UTIL,
        UTIL_LIGHT,
        title_size=17,
        body_size=13,
    )
    add_card(
        slide,
        6.75,
        4.1,
        6.0,
        2.5,
        "MASTER DRIVER",
        [
            Line(
                "Ties Refine, Enrich, and Util tools into one window with a "
                "fixed, dependency-aware run order.",
            )
        ],
        NAVY,
        CARD_GREY,
        title_size=17,
        body_size=13,
    )
    add_footer(slide, number)


def slide_master_driver(prs: Presentation, number: int) -> None:
    """Build the Master Driver - control centre slide."""
    slide = new_slide(prs)
    add_title(slide, "Master Driver - The Control Centre")
    add_textbox(
        slide,
        0.55,
        1.25,
        12.2,
        2.9,
        [
            Line(
                "Point it at a music folder and it runs a configured set "
                "of tools in a fixed, dependency-aware order - no need to "
                "open 26 separate windows.",
                size=14,
                space_after=9,
                marker="\u2022",
                accent=NAVY,
            ),
            Line(
                "Three tabs: REFINE (the full Audio Refinery pipeline, "
                "embedded), ENRICH (the tag and metadata modules), and "
                "UTIL (the remaining utilities).",
                size=14,
                space_after=9,
                marker="\u2022",
                accent=NAVY,
            ),
            Line(
                "Auto-Start and Auto-End options on each tab enable fully "
                "hands-off batch runs.",
                size=14,
                space_after=9,
                marker="\u2022",
                accent=NAVY,
            ),
            Line(
                "Settings are shared with the standalone tools - the "
                "Refinery tab uses the same refinery_settings.json as the "
                "Audio Refinery app.",
                size=14,
                space_after=9,
                marker="\u2022",
                accent=NAVY,
            ),
        ],
    )
    add_card(
        slide,
        0.55,
        4.35,
        12.2,
        2.35,
        "Why the fixed order matters",
        [
            Line(
                "The ENRICH order encodes real data dependencies: Album Genre "
                "Tagger must run before Genre Sync, and BPM Analyzer before "
                "Tempo Analyzer. Run the tools out of order and files missing "
                "their prerequisite tags are silently skipped - partial or "
                "empty results, not a warning dialog. Use Master Driver's "
                "fixed order, or replicate it manually when chaining tools.",
            )
        ],
        REFINE,
        REFINE_LIGHT,
        title_size=14,
        body_size=12,
    )
    add_footer(slide, number)


def slide_refinery(prs: Presentation, number: int) -> None:
    """Build the Audio Refinery combined-pipeline slide."""
    slide = new_slide(prs)
    add_title(
        slide,
        "Audio Refinery - The Combined Pipeline",
        "One file, one decode, five stages",
        REFINE,
    )
    add_flow(
        slide,
        0.55,
        1.45,
        12.2,
        0.8,
        ["Declick", "Trim", "Reduce Noise", "Enhance", "Normalise"],
        REFINE,
    )
    add_textbox(
        slide,
        0.55,
        2.6,
        12.2,
        4.4,
        [
            Line(
                "Five stages back-to-back in a single decode/encode pass - "
                "the lowest-quality-loss way to run several tools at once.",
                size=14,
                space_after=9,
                marker="\u2022",
                accent=REFINE,
            ),
            Line(
                "Each stage is independently optional; presets save and "
                "reload the complete stage configuration.",
                size=14,
                space_after=9,
                marker="\u2022",
                accent=REFINE,
            ),
            Line(
                "Dry Run first: validates and decodes every file and "
                "reports RMS and duration - writes nothing.",
                size=14,
                space_after=9,
                marker="\u2022",
                accent=REFINE,
            ),
            Line(
                "Completion registry: already-processed files are tracked "
                "and skipped on re-runs, so it is safe to re-launch over a "
                "partially processed folder.",
                size=14,
                space_after=9,
                marker="\u2022",
                accent=REFINE,
            ),
            Line(
                "Supports MP3, FLAC, OGG, M4A, WAV, AIFF/AIF, Opus - "
                "output stays in the source format.",
                size=14,
                space_after=9,
                marker="\u2022",
                accent=REFINE,
            ),
            Line(
                "FFmpeg on PATH is required for the Normalise stage; the "
                "other four stages run via pydub/pedalboard.",
                size=14,
                space_after=9,
                marker="\u2022",
                accent=REFINE,
            ),
        ],
    )
    add_footer(slide, number)


def slide_pipeline_steps(prs: Presentation, number: int) -> None:
    """Build the per-file pipeline walkthrough table."""
    slide = new_slide(prs)
    add_title(
        slide,
        "Inside the Pipeline - What Happens to Each File",
        accent=REFINE,
    )
    add_table(
        slide,
        0.55,
        1.3,
        12.2,
        5.55,
        PIPELINE_HEADERS,
        PIPELINE_ROWS,
        [3.0, 9.2],
        font_size=12,
        accent=REFINE,
    )
    add_footer(slide, number)


def slide_workhorses(prs: Presentation, number: int) -> None:
    """Build the Audio Enhancer and Noise Reduction cards."""
    slide = new_slide(prs)
    add_title(
        slide,
        "The Repair Workhorses",
        "Also available standalone, or as pieces of the Refinery pipeline",
        REFINE,
    )
    add_card(
        slide,
        0.55,
        1.35,
        6.0,
        5.35,
        "Audio Enhancer",
        [
            Line(
                "Seven-stage DSP chain: noise gate to limiter with EQ, "
                "presence peak, and output gain in between",
                marker="\u2022",
            ),
            Line(
                "Three one-click presets (Mild / Moderate / Aggressive) "
                "or thirteen sliders for full manual control",
                marker="\u2022",
            ),
            Line(
                "Tags are read before and restored after processing",
                marker="\u2022",
            ),
            Line(
                "For dull or dynamically flat recordings",
                marker="\u2022",
            ),
        ],
        REFINE,
        REFINE_LIGHT,
        title_size=16,
        body_size=13,
    )
    add_card(
        slide,
        6.75,
        1.35,
        6.0,
        5.35,
        "Noise Reduction",
        [
            Line(
                "Mains hum: 50/60 Hz and harmonics, removed with high-Q "
                "IIR notch filters",
                marker="\u2022",
            ),
            Line(
                "Broadband noise: hiss, tape noise, room ambience, via "
                "spectral gating on a learned noise profile",
                marker="\u2022",
            ),
            Line(
                "Both engines can be enabled independently",
                marker="\u2022",
            ),
            Line(
                "Runs standalone, from the CLI (audiosuite reduce), or as "
                "Refinery stage 3",
                marker="\u2022",
            ),
        ],
        REFINE,
        REFINE_LIGHT,
        title_size=16,
        body_size=13,
    )
    add_footer(slide, number)


def slide_enrich_order(prs: Presentation, number: int) -> None:
    """Build the ENRICH eleven-module run-order table."""
    slide = new_slide(prs)
    add_title(
        slide,
        "ENRICH: Eleven Modules, One Fixed Order",
        "Run the modules in this order for complete, correct results",
        ENRICH,
    )
    add_table(
        slide,
        0.55,
        1.35,
        12.2,
        5.4,
        ENRICH_HEADERS,
        ENRICH_ROWS,
        [0.6, 3.2, 8.4],
        font_size=11,
        accent=ENRICH,
        center_cols=(0,),
    )
    add_footer(slide, number)


def slide_analysers(prs: Presentation, number: int) -> None:
    """Build the four independent analyser cards."""
    slide = new_slide(prs)
    add_title(
        slide,
        "The Analysers: BPM, Key, ReplayGain & Fingerprinting",
        accent=ENRICH,
    )
    add_card(
        slide,
        0.55,
        1.3,
        6.0,
        2.45,
        "BPM Analyzer",
        [
            Line(
                "Tempo via librosa audio analysis, with half-time/"
                "double-time guarding.",
                lead="Detects:",
            ),
            Line(
                "TBPM (MP3/WAV/AIFF), Vorbis comment (FLAC/OGG/Opus), tmpo atom (M4A).",
                lead="Writes:",
            ),
        ],
        ENRICH,
        ENRICH_LIGHT,
        title_size=15,
        body_size=12,
    )
    add_card(
        slide,
        6.75,
        1.3,
        6.0,
        2.45,
        "Key Detector",
        [
            Line(
                "Musical key via chromagram analysis and template matching (24 keys).",
                lead="Detects:",
            ),
            Line(
                "TKEY (MP3/WAV/AIFF), initialkey Vorbis comment (FLAC/OGG/Opus), "
                "initialkey iTunes atom (M4A/MP4).",
                lead="Writes:",
            ),
        ],
        ENRICH,
        ENRICH_LIGHT,
        title_size=15,
        body_size=12,
    )
    add_card(
        slide,
        0.55,
        3.95,
        6.0,
        2.45,
        "ReplayGain Analyzer",
        [
            Line(
                "Perceived loudness via FFmpeg's ebur128 filter (ITU-R BS.1770).",
                lead="Measures:",
            ),
            Line(
                "Four standard ReplayGain v2 tags - track gain and album gain.",
                lead="Writes:",
            ),
            Line(
                "Metadata-only and reversible by deleting tags.",
                marker="\u2022",
            ),
        ],
        ENRICH,
        ENRICH_LIGHT,
        title_size=15,
        body_size=12,
    )
    add_card(
        slide,
        6.75,
        3.95,
        6.0,
        2.45,
        "Audio Fingerprinter",
        [
            Line(
                "Chromaprint fingerprints via the external fpcalc utility.",
                lead="Creates:",
            ),
            Line(
                "Unknown tracks identified through the AcoustID database.",
                lead="Matches:",
            ),
            Line(
                "AcoustID metadata written to matched files on request.",
                lead="Tags:",
            ),
        ],
        ENRICH,
        ENRICH_LIGHT,
        title_size=15,
        body_size=12,
    )
    add_footer(slide, number)


def slide_tag_chain(prs: Presentation, number: int) -> None:
    """Build the BPM-to-Tempo tag-chain slide."""
    slide = new_slide(prs)
    add_title(
        slide,
        "The Tag Chain: BPM to Tempo",
        "Tempo Analyzer transforms each format's native BPM tag into a marking",
        ENRICH,
    )
    add_flow(
        slide,
        0.55,
        1.45,
        6.0,
        0.8,
        ["BPM Analyzer", "Tempo Analyzer"],
        ENRICH,
    )
    add_textbox(
        slide,
        6.85,
        1.45,
        5.9,
        0.8,
        [
            Line(
                "Tempo Analyzer must run after BPM Analyzer - it reads the "
                "BPM tag that BPM writes.",
                size=12,
                italic=True,
                color=GREY_TEXT,
                space_after=0,
            )
        ],
    )
    add_card(
        slide,
        0.55,
        2.6,
        12.2,
        2.65,
        "Tempo Analyzer",
        [
            Line(
                "Reads the BPM tag (written by BPM Analyzer) and converts the "
                "number into a human-readable marking - Allegro, House, "
                "Fast Run, and more",
                marker="\u2022",
            ),
            Line(
                "Seven selectable naming schemes - the marking lands in each "
                "format's native tag:",
                marker="\u2022",
            ),
            Line(
                "TXXX:TEMPO (ID3) - MP3",
                marker="-",
            ),
            Line(
                "tempo (Vorbis comment) - FLAC, OGG, Opus",
                marker="-",
            ),
            Line(
                "----:com.apple.iTunes:TEMPO (freeform) - M4A, MP4",
                marker="-",
            ),
            Line(
                "It will not detect BPM itself - if the BPM tag is missing, "
                "there is nothing to convert",
                marker="\u2022",
            ),
        ],
        ENRICH,
        ENRICH_LIGHT,
        title_size=15,
        body_size=12,
    )
    add_card(
        slide,
        0.55,
        5.4,
        12.2,
        1.35,
        "Tag transformers, not analysers",
        [
            Line(
                "Tempo Analyzer performs no audio analysis of its own - it "
                "consumes what another tool wrote. Key Detector writes TKEY "
                "independently, and mood tagging works straight from the "
                "audio signal.",
            )
        ],
        NAVY,
        CARD_GREY,
        title_size=13,
        body_size=12,
    )
    add_footer(slide, number)


def slide_mood_chain(prs: Presentation, number: int) -> None:
    """Build the signal-based mood tagging slide."""
    slide = new_slide(prs)
    add_title(
        slide,
        "The Mood Chain: Signal-Based Mood Tagging",
        "Mood is estimated from the audio itself, not from other tags",
        ENRICH,
    )
    add_card(
        slide,
        0.55,
        1.35,
        6.0,
        3.85,
        "Mood Analyzer",
        [
            Line(
                "Estimates mood directly from the audio signal - no "
                "pre-existing tags needed",
                marker="\u2022",
            ),
            Line(
                "Derives arousal and valence features and maps them to "
                "three mood words",
                marker="\u2022",
            ),
            Line(
                "Can write mood, confidence, and energy metadata",
                marker="\u2022",
            ),
            Line(
                "Processes one directory (no subfolders)",
                marker="\u2022",
            ),
        ],
        ENRICH,
        ENRICH_LIGHT,
        title_size=15,
        body_size=12,
    )
    add_card(
        slide,
        6.75,
        1.35,
        6.0,
        3.85,
        "Mood Analysis Batch Tagger",
        [
            Line(
                "The same signal mood engine - the same track produces "
                "the same values in both tools",
                marker="\u2022",
            ),
            Line(
                "Walks an entire directory tree recursively in one pass",
                marker="\u2022",
            ),
            Line(
                "Use for first-time tagging of a whole library, or a full re-tag",
                marker="\u2022",
            ),
            Line(
                "Leave Dry Run selected for the first pass",
                marker="\u2022",
            ),
        ],
        ENRICH,
        ENRICH_LIGHT,
        title_size=15,
        body_size=12,
    )
    add_card(
        slide,
        0.55,
        5.45,
        12.2,
        1.3,
        "Formats",
        [
            Line(
                "Both tools support all shared suite formats: MP3, FLAC, OGG, "
                "M4A, MP4, Opus, WAV, and AIFF variants.",
            )
        ],
        NAVY,
        CARD_GREY,
        title_size=13,
        body_size=12,
    )
    add_footer(slide, number)


def slide_genre_chain(prs: Presentation, number: int) -> None:
    """Build the genre-chain slide."""
    slide = new_slide(prs)
    add_title(
        slide,
        "The Genre Chain: Track to Standard Field",
        "Move curated genres into the field every player reads",
        ENRICH,
    )
    add_card(
        slide,
        0.55,
        1.3,
        3.9,
        5.3,
        "Album Genre Tagger",
        [
            Line(
                "Reads TITLEGENRE from every track in a folder, "
                "format-aware (TXXX / Vorbis / MP4 freeform)",
                marker="\u2022",
            ),
            Line(
                "De-duplicates and sorts, then writes a consolidated "
                "ALBUMGENRE (plus an ALBUMDERIVED flag)",
                marker="\u2022",
            ),
            Line(
                "Requires a minimum coverage - default 50% of tracks - "
                "before it will act",
                marker="\u2022",
            ),
        ],
        ENRICH,
        ENRICH_LIGHT,
        title_size=14,
        body_size=12,
    )
    add_card(
        slide,
        4.7,
        1.3,
        3.9,
        5.3,
        "Genre Sync",
        [
            Line(
                "Populates the standard TCON field using a priority "
                "system across title, artist, and album-level custom "
                "genre fields",
                marker="\u2022",
            ),
            Line(
                "Special handling for Various Artists compilations",
                marker="\u2022",
            ),
            Line(
                "Makes your curated taxonomy visible to players that only read TCON",
                marker="\u2022",
            ),
            Line(
                "All nine suite formats - MP3, FLAC, OGG, M4A, MP4, "
                "Opus, WAV, AIFF, AIF",
                marker="\u2022",
            ),
        ],
        ENRICH,
        ENRICH_LIGHT,
        title_size=14,
        body_size=12,
    )
    add_card(
        slide,
        8.85,
        1.3,
        3.9,
        5.3,
        "Tag Field Updater",
        [
            Line(
                "A standalone normalisation utility - not part of the ENRICH sequence",
                marker="\u2022",
            ),
            Line(
                "Rewrites separator characters (slash to semicolon) "
                "across the genre tag fields",
                marker="\u2022",
            ),
            Line(
                "Supports MP3, FLAC, MP4/M4A, OGG, Opus, WAV, AIFF/AIF, and WMA",
                marker="\u2022",
            ),
        ],
        ENRICH,
        ENRICH_LIGHT,
        title_size=14,
        body_size=12,
    )
    add_footer(slide, number)


def slide_cleaning(prs: Presentation, number: int) -> None:
    """Build the cleaning, artwork, and lyrics slide."""
    slide = new_slide(prs)
    add_title(
        slide,
        "Cleaning, Artwork, Lyrics & Identification",
        accent=ENRICH,
    )
    add_card(
        slide,
        0.55,
        1.3,
        3.9,
        5.3,
        "Metadata Scrubber",
        [
            Line(
                "Cleans tag clutter across all supported formats "
                "(except WMA) while always preserving Artist, "
                "Album, and Title",
                marker="\u2022",
            ),
            Line(
                "Selectively keep custom tags - lyrics, ratings - via an "
                "interactive checkbox interface",
                marker="\u2022",
            ),
            Line(
                "Selections persist between runs",
                marker="\u2022",
            ),
            Line(
                "Runs first in the ENRICH sequence",
                marker="\u2022",
            ),
        ],
        ENRICH,
        ENRICH_LIGHT,
        title_size=14,
        body_size=12,
    )
    add_card(
        slide,
        4.7,
        1.3,
        3.9,
        5.3,
        "Album Art Synchronizer",
        [
            Line(
                "Looks up artwork via MusicBrainz against Fanart.tv, "
                "Deezer, and iTunes Store",
                marker="\u2022",
            ),
            Line(
                "Prefers the Album Artist tag for accuracy on compilations",
                marker="\u2022",
            ),
            Line(
                "Embeds artwork into file tags and writes a folder.jpg",
                marker="\u2022",
            ),
            Line(
                "Runs last in the ENRICH sequence",
                marker="\u2022",
            ),
        ],
        ENRICH,
        ENRICH_LIGHT,
        title_size=14,
        body_size=12,
    )
    add_card(
        slide,
        8.85,
        1.3,
        3.9,
        5.3,
        "Lyrics Manager",
        [
            Line(
                "Fetches synced (timestamped) or plain lyrics from the "
                "LRCLIB online source",
                marker="\u2022",
            ),
            Line(
                "Embeds lyrics straight into each file's tags, so they "
                "travel with the file",
                marker="\u2022",
            ),
            Line(
                "Files are matched by artist and title tags; missing or "
                "Unknown tags are skipped",
                marker="\u2022",
            ),
        ],
        ENRICH,
        ENRICH_LIGHT,
        title_size=14,
        body_size=12,
    )
    add_footer(slide, number)


def slide_util_audio(prs: Presentation, number: int) -> None:
    """Build the audio-altering tools in UTIL slide."""
    slide = new_slide(prs)
    add_title(
        slide,
        "Audio-Altering Tools in UTIL",
        "Standalone tools that change the audio itself",
        UTIL,
    )
    add_card(
        slide,
        0.55,
        1.25,
        3.9,
        5.4,
        "Pop & Click Remover",
        [
            Line(
                "Repairs vinyl-rip pops and clicks using a windowed "
                "Median Absolute Deviation detector and cubic-spline "
                "interpolation",
                marker="\u2022",
            ),
            Line(
                "Local 20 ms detection window stays reliable across wide dynamic range",
                marker="\u2022",
            ),
            Line(
                "Idempotent: repeated runs converge to zero changes",
                marker="\u2022",
            ),
            Line(
                "16/24/32-bit PCM handled correctly",
                marker="\u2022",
            ),
        ],
        UTIL,
        UTIL_LIGHT,
        title_size=14,
        body_size=12,
    )
    add_card(
        slide,
        4.7,
        1.25,
        3.9,
        5.4,
        "Silence Trimmer & Fader",
        [
            Line(
                "Removes leading/trailing silence using a configurable dB threshold",
                marker="\u2022",
            ),
            Line(
                "Applies optional fade-in and fade-out",
                marker="\u2022",
            ),
            Line(
                "Processes through an isolated temporary copy - the "
                "original is untouched until the result is verified",
                marker="\u2022",
            ),
            Line(
                "Supports MP3, FLAC, OGG, M4A, Opus, WAV, and AIFF",
                marker="\u2022",
            ),
        ],
        UTIL,
        UTIL_LIGHT,
        title_size=14,
        body_size=12,
    )
    add_card(
        slide,
        8.85,
        1.25,
        3.9,
        5.4,
        "Audio Normalizer",
        [
            Line(
                "Loudness normalisation to a target LUFS using FFmpeg's "
                "two-pass loudnorm filter (EBU R128)",
                marker="\u2022",
            ),
            Line(
                "The simpler standalone tool - use the Normalise stage "
                "in Audio Refinery if you are running that pipeline "
                "anyway",
                marker="\u2022",
            ),
        ],
        UTIL,
        UTIL_LIGHT,
        title_size=14,
        body_size=12,
    )
    add_footer(slide, number)


def slide_conversion(prs: Presentation, number: int) -> None:
    """Build the conversion, ripping, and extraction slide."""
    slide = new_slide(prs)
    add_title(
        slide,
        "Conversion, Ripping & Extraction",
        accent=UTIL,
    )
    add_card(
        slide,
        0.55,
        1.25,
        3.9,
        5.4,
        "Music Format Converter",
        [
            Line(
                "Batch conversion across 14 formats: MP3, AAC, M4A, OGG, "
                "Opus, WMA, MP4, FLAC, WAV, ALAC, APE, AIFF, AIF, WavPack",
                marker="\u2022",
            ),
            Line(
                "Actively prevents invalid conversions: same-format "
                "re-encodes and lossy to lossless",
                marker="\u2022",
            ),
            Line(
                "Only valid output formats for the detected input are shown",
                marker="\u2022",
            ),
        ],
        UTIL,
        UTIL_LIGHT,
        title_size=14,
        body_size=12,
    )
    add_card(
        slide,
        4.7,
        1.25,
        3.9,
        5.4,
        "CD Ripper",
        [
            Line(
                "Rips physical audio CDs to FLAC, MP3, OGG, M4A, WAV, or Opus",
                marker="\u2022",
            ),
            Line(
                "MusicBrainz lookup with inline metadata correction before encoding",
                marker="\u2022",
            ),
            Line(
                "Windows-only; requires Administrator rights",
                marker="\u2022",
            ),
        ],
        UTIL,
        UTIL_LIGHT,
        title_size=14,
        body_size=12,
    )
    add_card(
        slide,
        8.85,
        1.25,
        3.9,
        5.4,
        "ASX Playlist Extractor",
        [
            Line(
                "Reads XML-based .asx playlist files, which point to "
                "audio elsewhere on disk",
                marker="\u2022",
            ),
            Line(
                "Copies the referenced files into a target directory",
                marker="\u2022",
            ),
            Line(
                "Fallback format detection across all nine supported "
                "audio extensions if the referenced file is not at "
                "the exact path",
                marker="\u2022",
            ),
        ],
        UTIL,
        UTIL_LIGHT,
        title_size=14,
        body_size=12,
    )
    add_footer(slide, number)


def slide_maintenance(prs: Presentation, number: int) -> None:
    """Build the library maintenance and safety-nets slide."""
    slide = new_slide(prs)
    add_title(
        slide,
        "Library Maintenance & Safety Nets",
        accent=UTIL,
    )
    add_card(
        slide,
        0.55,
        1.25,
        6.0,
        2.55,
        "Library Statistics Dashboard",
        [
            Line(
                "Scans a library and aggregates metadata already present "
                "in tags - read-only, no analysis and no tag writes",
                marker="\u2022",
            ),
            Line(
                "Summary counts, charts, missing-data lists, and tag "
                "completeness results",
                marker="\u2022",
            ),
        ],
        UTIL,
        UTIL_LIGHT,
        title_size=14,
        body_size=12,
    )
    add_card(
        slide,
        6.75,
        1.25,
        6.0,
        2.55,
        "File Reorganizer",
        [
            Line(
                "Moves/copies files into a user-defined tag-based folder hierarchy",
                marker="\u2022",
            ),
            Line(
                "Separate templates for named album artists and Various "
                "Artists releases - preview-first, Dry Run on by default",
                marker="\u2022",
            ),
        ],
        UTIL,
        UTIL_LIGHT,
        title_size=14,
        body_size=12,
    )
    add_card(
        slide,
        0.55,
        4.0,
        6.0,
        2.55,
        "Album Art Normalizer",
        [
            Line(
                "Standardises embedded artwork across all nine supported audio formats",
                marker="\u2022",
            ),
            Line(
                "Center-crops, resizes to a square resolution, re-encodes "
                "as an optimised JPEG; also normalises folder.jpg to "
                "1000 x 1000",
                marker="\u2022",
            ),
        ],
        UTIL,
        UTIL_LIGHT,
        title_size=14,
        body_size=12,
    )
    add_card(
        slide,
        6.75,
        4.0,
        6.0,
        2.55,
        "Undo Tag Edits",
        [
            Line(
                "Every tag-editing run records a snapshot of each file's "
                "tags before the run",
                marker="\u2022",
            ),
            Line(
                "Pick a saved run and restore your tags to exactly the "
                "way they were - a safety net for batch tagging",
                marker="\u2022",
            ),
        ],
        NAVY,
        CARD_GREY,
        title_size=14,
        body_size=12,
    )
    add_footer(slide, number)


def slide_formats(prs: Presentation, number: int) -> None:
    """Build the format-support matrix slide."""
    slide = new_slide(prs)
    add_title(
        slide,
        "Format Support at a Glance",
        "Source-and-output support per tool (see each tool's own guide)",
    )
    add_table(
        slide,
        0.4,
        1.2,
        12.5,
        5.8,
        FORMAT_HEADERS,
        FORMAT_ROWS,
        [3.0, 0.85, 0.85, 0.85, 0.85, 0.85, 5.25],
        font_size=8,
        accent=NAVY,
        center_cols=(1, 2, 3, 4, 5),
    )
    add_footer(slide, number)


def slide_chooser(prs: Presentation, number: int) -> None:
    """Build the task-to-tool chooser table."""
    slide = new_slide(prs)
    add_title(
        slide,
        "Choosing the Right Tool for a Task",
    )
    add_table(
        slide,
        0.55,
        1.25,
        12.2,
        5.6,
        CHOOSER_HEADERS,
        CHOOSER_ROWS,
        [5.2, 7.0],
        font_size=11,
        accent=ENRICH,
    )
    add_footer(slide, number)


def slide_getting_started(prs: Presentation, number: int) -> None:
    """Build the getting-started slide."""
    slide = new_slide(prs)
    add_title(
        slide,
        "Getting Started",
        "Three ways to run the suite",
    )
    add_card(
        slide,
        0.55,
        1.3,
        3.9,
        3.8,
        "1 - Master Driver",
        [
            Line(
                "Launch Master_Driver.pyw",
                marker="\u2022",
            ),
            Line(
                "Pick a tab, point it at a music folder, tick the tools you want",
                marker="\u2022",
            ),
            Line(
                "Click Run - Auto-Start/Auto-End make it hands-off",
                marker="\u2022",
            ),
            Line(
                "Recommended for your first full-library run",
                marker="\u2022",
            ),
        ],
        NAVY,
        CARD_GREY,
        title_size=15,
        body_size=12,
    )
    add_card(
        slide,
        4.7,
        1.3,
        3.9,
        3.8,
        "2 - Individual tools",
        [
            Line(
                "Every tool has its own launcher - Audio_Refinery.pyw, "
                "BPM_Analyzer.pyw, Library_Stats.pyw, and 23 more",
                marker="\u2022",
            ),
            Line(
                "Double-click to open just that tool",
                marker="\u2022",
            ),
            Line(
                "Best for focused, single-album work",
                marker="\u2022",
            ),
        ],
        ENRICH,
        ENRICH_LIGHT,
        title_size=15,
        body_size=12,
    )
    add_card(
        slide,
        8.85,
        1.3,
        3.9,
        3.8,
        "3 - Command line",
        [
            Line(
                r"audiosuite <command> <directory> [options]",
                marker="\u2022",
            ),
            Line(
                r'Example: audiosuite album-art "D:\Music\Beatles" --dry',
                marker="\u2022",
            ),
            Line(
                "Run audiosuite --help for the full command list",
                marker="\u2022",
            ),
        ],
        UTIL,
        UTIL_LIGHT,
        title_size=15,
        body_size=12,
    )
    add_card(
        slide,
        0.55,
        5.4,
        12.2,
        1.5,
        "Tips for your first run",
        [
            Line(
                "Start with Dry Run wherever a tool offers it - you see "
                "exactly what would happen before anything is written",
                marker="\u2022",
            ),
            Line(
                "FFmpeg on PATH is needed for conversion, ReplayGain "
                "analysis, and loudness normalisation",
                marker="\u2022",
            ),
            Line(
                "Every tool's Help button opens its own User Guide",
                marker="\u2022",
            ),
        ],
        NAVY,
        CARD_GREY,
        title_size=13,
        body_size=12,
    )
    add_footer(slide, number)


def slide_next_steps(prs: Presentation, number: int) -> None:
    """Build the where-to-go-next slide."""
    slide = new_slide(prs)
    add_title(
        slide,
        "Where to Go Next",
        "All documentation ships inside the suite, under user_guides/",
    )
    add_textbox(
        slide,
        0.55,
        1.35,
        12.2,
        5.4,
        [
            Line(
                "Each tool's own User Guide - every setting, default "
                "value, and step-by-step walkthrough "
                "(user_guides/individual_programs/)",
                size=15,
                space_after=10,
                marker="\u2022",
            ),
            Line(
                "The AudioSuite-Pro Overview Guide - how the 26 tools "
                "relate, and which one to reach for "
                "(user_guides/suite_overview/)",
                size=15,
                space_after=10,
                marker="\u2022",
            ),
            Line(
                "The Logging System Guide - log file locations, formats, "
                "and troubleshooting by message",
                size=15,
                space_after=10,
                marker="\u2022",
            ),
            Line(
                "The Technical User Guide - suite-wide error recovery and "
                "resource management",
                size=15,
                space_after=10,
                marker="\u2022",
            ),
            Line(
                "The Security Guide - API keys, credentials, and safe file handling",
                size=15,
                space_after=10,
                marker="\u2022",
            ),
            Line(
                "The CLI Commands Reference - every command and option "
                "(user_guides/reference/CLI_Commands_Reference.md)",
                size=15,
                space_after=10,
                marker="\u2022",
            ),
        ],
    )
    add_footer(slide, number)


def slide_closing(prs: Presentation) -> None:
    """Build the closing slide."""
    slide = new_slide(prs)
    bg = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), SLIDE_W, SLIDE_H
    )
    bg.fill.solid()
    bg.fill.fore_color.rgb = NAVY
    bg.line.fill.background()
    bg.shadow.inherit = False
    centered = PP_ALIGN.CENTER
    add_textbox(
        slide,
        0.9,
        2.6,
        11.53,
        1.2,
        [
            Line(
                "Your library, refined.",
                size=44,
                bold=True,
                color=WHITE,
                align=centered,
                space_after=0,
            )
        ],
    )
    add_textbox(
        slide,
        0.9,
        3.85,
        11.53,
        0.6,
        [
            Line(
                "Repair it. Tag it. Convert it. Maintain it.",
                size=19,
                color=LIGHT_BLUE,
                align=centered,
                space_after=0,
            )
        ],
    )
    add_textbox(
        slide,
        0.9,
        4.55,
        11.53,
        0.5,
        [
            Line(
                "Launch Master_Driver.pyw to get started.",
                size=14,
                color=WHITE,
                align=centered,
                space_after=0,
            )
        ],
    )


def build_deck() -> Presentation:
    """Build the complete presentation and return it."""
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H

    slide_title(prs)
    slide_what(prs, 2)
    slide_map(prs, 3)
    slide_master_driver(prs, 4)
    add_divider(
        prs,
        "Stage 1",
        "REFINE - Audio Repair & Processing",
        "Fix the audio itself - declick, trim silence, enhance tone, "
        "normalise loudness - before anything is tagged.",
        REFINE,
    )
    slide_refinery(prs, 6)
    slide_pipeline_steps(prs, 7)
    slide_workhorses(prs, 8)
    add_divider(
        prs,
        "Stage 2",
        "ENRICH - Analysis & Tagging",
        "Analyse and tag - BPM, tempo, key, mood, genre, artwork, lyrics.",
        ENRICH,
    )
    slide_enrich_order(prs, 10)
    slide_analysers(prs, 11)
    slide_tag_chain(prs, 12)
    slide_mood_chain(prs, 13)
    slide_genre_chain(prs, 14)
    slide_cleaning(prs, 15)
    add_divider(
        prs,
        "Stage 3",
        "UTIL - Conversion, Extraction & Maintenance",
        "Convert, extract, rip, and batch-process - day-to-day library maintenance.",
        UTIL,
    )
    slide_util_audio(prs, 17)
    slide_conversion(prs, 18)
    slide_maintenance(prs, 19)
    slide_formats(prs, 20)
    slide_chooser(prs, 21)
    slide_getting_started(prs, 22)
    slide_next_steps(prs, 23)
    slide_closing(prs)
    return prs


def main() -> None:
    """Generate the presentation file."""
    prs = build_deck()
    prs.save(OUTPUT)
    print(f"[DONE] wrote {OUTPUT} ({len(prs.slides)} slides)")


if __name__ == "__main__":
    main()
