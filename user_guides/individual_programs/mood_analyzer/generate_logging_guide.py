"""Generate the Mood Analyzer Logging Guide .docx."""

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

doc = Document()

# ── Title ──
h = doc.add_heading("Mood Analyzer \u2014 Logging Guide", level=0)
h.alignment = WD_ALIGN_PARAGRAPH.CENTER
doc.add_paragraph(
    "Version 1.0 \u2014 September 2026"
).alignment = WD_ALIGN_PARAGRAPH.CENTER

# ── Overview ──
doc.add_heading("Overview", level=1)
doc.add_paragraph(
    "Mood Analyzer participates in the Audio Suite unified logging system "
    "that has replaced scattered per-tool log files. A single stdlib logging "
    "pipeline is configured once at startup and used by every tool, so all "
    "diagnostic messages \u2014 including Mood Analyzer\u2019s \u2014 land in "
    "one central, rotated log file."
)
doc.add_paragraph(
    "On top of that central log, Mood Analyzer still produces a per-run "
    "human-readable report of what it found. This guide explains both, where "
    "each lives, and how to read them when something goes wrong."
)

# ── Logging Features ──
doc.add_heading("Logging Features", level=1)

doc.add_heading("Unified Suite Logging", level=2)
p = doc.add_paragraph(style="List Bullet")
p.add_run("Program name: ").bold = True
p.add_run("mood_analyzer (logger id audio_suite.mood_analyzer)")
p = doc.add_paragraph(style="List Bullet")
p.add_run("Timestamps: ").bold = True
p.add_run("every record carries a full date and time")
p = doc.add_paragraph(style="List Bullet")
p.add_run("Levels: ").bold = True
p.add_run("info messages, warnings and errors are separated by level")
p = doc.add_paragraph(style="List Bullet")
p.add_run("Uncaught GUI exceptions: ").bold = True
p.add_run(
    "exceptions raised inside Tkinter callbacks are captured and logged instead "
    "of silently disappearing (especially under pythonw)."
)
p = doc.add_paragraph(style="List Bullet")
p.add_run("Rotation: ").bold = True
p.add_run("the central log is rotated automatically, so it never grows without bound.")

doc.add_heading("Per-Run Report", level=2)
doc.add_paragraph(
    "Each run also writes a plain-text report with a header (mode, analysis "
    "duration, parallel settings) followed by one line per file: the detected "
    "mood words, the confidence, and the energy band. Skipped and errored files "
    "are listed too."
)

# ── Log File Location ──
doc.add_heading("Log File Location", level=1)

doc.add_heading("Central Log", level=2)
doc.add_paragraph(
    "The central log lives at "
    "Audio Suite\\logs\\audio_suite.log (next to the application folder). "
    "When it rotates, older content is kept as audio_suite.log.1, "
    "audio_suite.log.2 and so on both next to the main file."
)
doc.add_paragraph(
    "If the logs folder cannot be created or written (for example on a "
    "read-only installation), the suite falls back to the system temporary "
    "directory under audio_suite_logs."
)

doc.add_heading("Per-Run Report", level=2)
doc.add_paragraph(
    "The report is written into the music folder you selected: "
    "mood_dry_run_log.txt for a dry run, mood_sync_log.txt for a live update. "
    "Re-running overwrites the previous report of the same mode."
)

# ── Viewing Mood Analyzer Logs ──
doc.add_heading("Viewing Mood Analyzer Logs", level=1)
doc.add_paragraph(
    "Search the central log for Mood Analyzer entries with a text search on "
    "the logger name:"
)
doc.add_paragraph(
    "# Search for all Mood Analyzer entries\n"
    'grep "audio_suite.mood_analyzer" Audio Suite\\logs\\audio_suite.log\n'
    "\n"
    "# Search for errors only\n"
    'grep "audio_suite.mood_analyzer" Audio Suite\\logs\\audio_suite.log '
    "| grep ERROR\n"
    "\n"
    "# Monitor current activity\n"
    "tail -f Audio Suite\\logs\\audio_suite.log"
)

# ── Common Entries ──
doc.add_heading("Common Entries", level=1)

doc.add_heading("Central Log \u2014 Normal Operation", level=2)
doc.add_paragraph(
    "2026-09-07 15:30:45  audio_suite.mood_analyzer         INFO     "
    "Starting mood analysis on 40 files"
)
doc.add_paragraph(
    "2026-09-07 15:35:22  audio_suite.mood_analyzer         INFO     "
    "Processed track.mp3 \u2192 Energetic;Bright;Confident (conf 0.87)"
)

doc.add_heading("Central Log \u2014 Error Condition", level=2)
doc.add_paragraph(
    "2026-09-07 15:32:10  audio_suite.mood_analyzer         ERROR    "
    "[AudioCodecError] Could not decode audio file 'song.mp3'."
)
doc.add_paragraph(
    "Errors are logged with a traceback so you can see exactly which call "
    "failed and why."
)

doc.add_heading("Per-Run Report", level=2)
doc.add_paragraph(
    "MOOD DETECTION REPORT\n"
    "Mode: DRY RUN\n"
    "Analysis Duration: 90 seconds\n"
    "Parallel: Yes\n"
    "Workers: 4\n"
    "============================================================\n"
    "[DETECTED] track.mp3 | Mood: Energetic;Bright;Confident | "
    "Confidence: 0.87 | Energy: 5\n"
    "[SKIP] broken.mp3: Could not decode audio file"
)

# ── Troubleshooting ──
doc.add_heading("Troubleshooting", level=1)

doc.add_heading("No Mood Analyzer entries in the central log?", level=2)
doc.add_paragraph(
    "1. Confirm Mood Analyzer was actually launched \u2014 entries are written "
    "as soon as the program starts.\n"
    "2. Check Audio Suite\\logs\\ exists and is writable.\n"
    "3. If the folder is read-only, the suite falls back to the temp "
    "directory \u2014 look under %TEMP%\\audio_suite_logs."
)

doc.add_heading("Per-run report missing or empty?", level=2)
doc.add_paragraph(
    "The report is written into the music folder you selected. Check that the "
    "folder is writable \u2014 the summary shows how many files were skipped "
    "before the report is written, so a report with many skips that you did "
    "not expect usually means the folder contains files the suite could not "
    "decode."
)

doc.add_heading("Report overwritten unexpectedly?", level=2)
doc.add_paragraph(
    "mood_dry_run_log.txt and mood_sync_log.txt are overwritten on each "
    "matching run (dry over dry, live over live). If you need to keep the "
    "history, copy the report before running again."
)

# ── Support ──
doc.add_heading("Support", level=1)
p = doc.add_paragraph(style="List Bullet")
p.add_run("Technical guide: ").bold = True
p.add_run("See TECHNICAL_USER_GUIDE.md")
p = doc.add_paragraph(style="List Bullet")
p.add_run("Logging system guide: ").bold = True
p.add_run("See LOGGING_SYSTEM_GUIDE.docx")
p = doc.add_paragraph(style="List Bullet")
p.add_run("Main user guide: ").bold = True
p.add_run("See Mood_Analyzer_User_Guide.docx")
p = doc.add_paragraph(style="List Bullet")
p.add_run("Central log location: ").bold = True
p.add_run("Audio Suite\\logs\\audio_suite.log")
p = doc.add_paragraph(style="List Bullet")
p.add_run("Per-run report: ").bold = True
p.add_run("mood_dry_run_log.txt / mood_sync_log.txt in your music folder")

# ── Save ──
output = (
    "D:\\Users\\wilte\\Desktop\\AudioSuite-Pro\\user_guides\\individual_programs\\"
    "mood_analyzer\\Mood_Analyzer_Logging_Guide.docx"
)
doc.save(output)
print(f"Saved to {output}")
