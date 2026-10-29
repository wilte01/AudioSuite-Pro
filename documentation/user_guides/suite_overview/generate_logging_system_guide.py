"""Generate the suite-wide Logging System Guide from the current implementation.

The source of truth for everything described here is
``audio_suite_shared/logging_setup.py`` (file locations, rotation parameters,
formatter, package attachment, the administrator filter) and
``audio_suite_shared/cli_base.py`` (``--log-level``).  Edit those modules
first, then re-run this script.

Output is written next to this file, relative to ``__file__`` - no
machine-specific path is baked into the generator.
"""

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

OUTPUT = Path(__file__).resolve().parent / "LOGGING_SYSTEM_GUIDE.docx"


def bullet(doc: Document, title: str, text: str) -> None:
    paragraph = doc.add_paragraph(style="List Bullet")
    paragraph.add_run(title).bold = True
    paragraph.add_run(text)


def example_line(stamp: str, name: str, level: str, message: str) -> str:
    """Render one example record exactly as the configured formatter would.

    Mirrors the format string documented below (two-space separators, the
    name field padded to 40, the level field padded to 8), so the samples
    cannot drift away from the real output when the format changes.
    """
    return f"{stamp}  {name:<40}  {level:<8}  {message}"


doc = Document()
title = doc.add_heading("AudioSuite-Pro - Logging System Guide", level=0)
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
subtitle = doc.add_paragraph(
    "Based on audio_suite_shared.logging_setup and audio_suite_shared.cli_base"
)
subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER

doc.add_heading("Overview", level=1)
doc.add_paragraph(
    "Every program in the suite writes to two rotating log files. "
    "A single call to configure_logging(program_name), made at startup by "
    "each .pyw launcher, the Master Driver, the lyrics_manager entry "
    "point and the command-line interface, creates both handlers, attaches "
    "them to the loggers listed in this guide, and records the program's "
    "start line."
)
bullet(
    doc,
    "The suite log (logs/audio_suite.log) is the administrator's record. ",
    "It carries the startup lifecycle line plus every WARNING, ERROR and "
    "CRITICAL record from any first-party logger. DEBUG and normal-running "
    "INFO are deliberately excluded, so the file stays small enough to spot "
    "failures at a glance.",
)
bullet(
    doc,
    "The per-program log (logs/<program_name>.log) is the diagnostic record. ",
    "It preserves the per-file processing detail (tag fallbacks, subprocess "
    "audit trail, per-file successes) that the suite log filters out. One "
    "process runs one program, so a session writes exactly one per-program "
    "file.",
)

doc.add_heading("Where the Log Files Live", level=1)
bullet(
    doc,
    "Suite log: ",
    "logs/audio_suite.log inside the AudioSuite-Pro folder.",
)
bullet(
    doc,
    "Per-program log: ",
    "logs/<program_name>.log - for example logs/bpm_analyzer.log, "
    "logs/master_driver.log, or logs/audiosuite_cli.log for a command-line "
    "run. The name matches the program identifier passed to "
    "configure_logging.",
)
bullet(
    doc,
    "Fallback: ",
    "if logs/ cannot be created (typically a permissions problem), the "
    "files are written to the system temporary folder under audio_suite_logs "
    "instead. Check both locations when a log seems missing - the switch "
    "happens silently.",
)
bullet(
    doc,
    "Encoding: ",
    "UTF-8.",
)
bullet(
    doc,
    "Not in the repository: ",
    "logs/ and all *.log files are git-ignored, so a fresh clone has no "
    "log folder until the first program creates it.",
)

doc.add_heading("Rotation", level=1)
bullet(
    doc,
    "Suite log: ",
    "the active file reaches 2 MB (2,097,152 bytes) and then rolls over "
    "into audio_suite.log.1 through audio_suite.log.5 - up to six files, "
    "about 12 MB.",
)
bullet(
    doc,
    "Per-program logs: ",
    "the active file reaches 1 MB and then rolls over into "
    "<program>.log.1 through <program>.log.3 - up to four files, about "
    "4 MB per program.",
)
bullet(
    doc,
    "Automatic: ",
    "rotation is performed by Python's RotatingFileHandler; nothing has "
    "to trigger or supervise it.",
)
doc.add_paragraph(
    "AudioSuite-Pro/logs/\n"
    "|-- audio_suite.log        suite log, newest records\n"
    "|-- audio_suite.log.1      most recent suite-log backup\n"
    "|-- audio_suite.log.2 ... audio_suite.log.5\n"
    "|-- bpm_analyzer.log       per-program log for bpm_analyzer\n"
    "|-- bpm_analyzer.log.1 ... bpm_analyzer.log.3\n"
    "`-- <other programs>.log   one set per program that has run"
)

doc.add_heading("Which Records Reach Which File", level=1)
bullet(
    doc,
    "Suite log - lifecycle and failures: ",
    'the INFO startup line "=== <program_name> started ===" written by the '
    "audio_suite logger, plus every WARNING, ERROR and CRITICAL record from "
    "any first-party logger (shared infrastructure and tool packages "
    "alike). This is the file to read when checking whether a run failed.",
)
bullet(
    doc,
    "Suite log - excluded: ",
    "DEBUG records and normal-running INFO records (per-file progress, tag "
    "fallbacks, subprocess commands that succeeded) are filtered out by the "
    "administrator filter. They are not lost - they go to the per-program "
    "log instead.",
)
bullet(
    doc,
    "Per-program log - full detail: ",
    "every record the running program and its shared infrastructure emit at "
    "or above the program's level. A GUI launch uses DEBUG, so every detail "
    "is preserved; a CLI run uses its --log-level, so the file matches the "
    "console verbosity you asked for.",
)
bullet(
    doc,
    "First-party tool packages: ",
    "every logging.getLogger(__name__) call in a first-party module, "
    "because configure_logging attaches both file handlers to each tool "
    "package logger (bpm_analyzer, noise_reduction, tempo_analyzer and the "
    "rest). This holds for GUI launches and CLI runs alike.",
)
bullet(
    doc,
    "Uncaught exceptions: ",
    "main-thread and worker-thread crashes are recorded at CRITICAL with "
    "a full traceback, including runs under pythonw where no console "
    "exists. KeyboardInterrupt is passed to the default handler.",
)
bullet(
    doc,
    "Deliberately excluded: ",
    "third-party library loggers (urllib3 and friends) are never handed "
    "the suite handlers, and the root logger is left untouched so console "
    "output is written exactly once.",
)

doc.add_heading("Log Entry Format", level=1)
doc.add_paragraph(
    "Each record is one line: timestamp, logger name (padded to 40 "
    "characters), level, message."
)
doc.add_paragraph(
    "Format: %(asctime)s  %(name)-40s  %(levelname)-8s  %(message)s\n"
    "Timestamp: %Y-%m-%d %H:%M:%S"
)
doc.add_paragraph(
    "\n".join(
        (
            example_line(
                "2026-10-09 09:15:04",
                "audio_suite",
                "INFO",
                "=== bpm_analyzer started ===",
            ),
            example_line(
                "2026-10-09 09:15:06",
                "bpm_analyzer.core.file_processor",
                "WARNING",
                "Skipping unreadable file: track9.mp3",
            ),
        )
    )
)
doc.add_paragraph(
    "The first example appears in both files; the second appears only in "
    "the suite log and logs/bpm_analyzer.log, because a WARNING is "
    "administrator-relevant. A per-file INFO record appears only in "
    "logs/bpm_analyzer.log."
)

doc.add_heading("Log Levels", level=1)
bullet(doc, "DEBUG: ", "verbose detail used when diagnosing a problem.")
bullet(doc, "INFO: ", "normal lifecycle and progress events.")
bullet(doc, "WARNING: ", "something unexpected that was worked around.")
bullet(doc, "ERROR: ", "an operation failed; the program usually continues.")
bullet(doc, "CRITICAL: ", "an uncaught exception ended the operation.")
doc.add_paragraph(
    "A GUI launch pins every first-party package logger to DEBUG, so every "
    "first-party record reaches the per-program file. The CLI passes its "
    "own --log-level instead, so its verbosity choice governs the console "
    "and the per-program file together. In both cases the suite log shows "
    "only the lifecycle line and WARNING-and-above records."
)

doc.add_heading("Command Line", level=1)
doc.add_paragraph(
    "The CLI accepts --log-level (DEBUG, INFO, WARNING, ERROR - default "
    "WARNING) before the command name. An unrecognised value falls back "
    "to WARNING. Examples:"
)
doc.add_paragraph(
    "python -m audio_suite_shared.cli_app --log-level INFO stats <folder>\n"
    "python -m audio_suite_shared.cli_app --log-level DEBUG convert "
    "<folder> --dry"
)
doc.add_paragraph(
    "The CLI also writes to the terminal via logging.basicConfig, in the "
    "form 'LEVEL [logger.name] message'. That console path exists only "
    "for CLI runs; a GUI program has no console, which is why the files "
    "are the record of a GUI session."
)

doc.add_heading("Reading the Logs", level=1)
bullet(
    doc,
    "Did a run fail? ",
    "open logs/audio_suite.log and search for ERROR or WARNING. The suite "
    "log is scoped to exactly this question.",
)
bullet(
    doc,
    "Why did one file fail? ",
    "open logs/<program_name>.log (for example logs/music_format_converter"
    ".log) - the per-file DEBUG/INFO detail lives there.",
)
bullet(
    doc,
    "By program or module: ",
    'findstr /C:"bpm_analyzer" logs\\bpm_analyzer.log  (Windows) or  '
    'grep "bpm_analyzer" logs/bpm_analyzer.log',
)
bullet(
    doc,
    "By level: ",
    'findstr "ERROR" logs\\audio_suite.log  or  grep " ERROR " logs/audio_suite.log',
)
bullet(
    doc,
    "By date: ",
    'findstr /C:"2026-10-09" logs\\audio_suite.log  or  grep '
    '"2026-10-09" logs/audio_suite.log',
)
bullet(
    doc,
    "Across generations: ",
    "search the numbered .1 files as well when the record you need is "
    "older than the current file.",
)

doc.add_heading("Cleaning Up", level=1)
bullet(
    doc,
    "When it is safe: ",
    "only while every suite program is closed - an open log file cannot "
    "be deleted on Windows, and deleting it would discard records still "
    "being written.",
)
bullet(
    doc,
    "What to delete: ",
    "any or all of logs\\audio_suite.log, its .1 through .5 backups, and "
    "the per-program <program>.log files with their .1 through .3 backups.",
)
bullet(
    doc,
    "Afterwards: ",
    "the folder and the active files are recreated on the next start and "
    "rotation resumes from an empty file. The directory is never "
    "required to exist in advance.",
)
bullet(
    doc,
    "No automatic pruning: ",
    "retention is bounded by rotation, not by age, so trim the files "
    "yourself if you want them gone sooner.",
)

doc.add_heading("Compatibility API", level=1)
doc.add_paragraph("Older call sites keep working unchanged:")
bullet(
    doc,
    "get_logger(program_name): ",
    "returns the ErrorLogger wrapper; its records are written under the "
    "audio_suite.<program_name> logger.",
)
bullet(
    doc,
    "cleanup_logs(): ",
    "retained no-op - rotation belongs to RotatingFileHandler, so there "
    "is no per-program cleanup to perform.",
)
bullet(
    doc,
    "get_log_stats(): ",
    "retained, returns an empty structure; the log is no longer parsed to produce it.",
)
bullet(
    doc,
    "GUI dialogs: ",
    "showing an error messagebox is the caller's responsibility; the "
    "corresponding record still reaches the suite log.",
)

doc.add_heading("Troubleshooting", level=1)
bullet(
    doc,
    "No logs folder: ",
    "check that the AudioSuite-Pro folder is writable, then look in the "
    "temporary fallback folder audio_suite_logs.",
)
bullet(
    doc,
    "Expected detail missing from the suite log: ",
    "by design - the suite log keeps only the lifecycle line and "
    "WARNING-and-above. Look in logs/<program_name>.log for DEBUG/INFO "
    "processing detail.",
)
bullet(
    doc,
    "Per-program log missing for a CLI run: ",
    "raise --log-level; a WARNING run drops DEBUG/INFO detail from the "
    "per-program file as well as the console.",
)
bullet(
    doc,
    "File never grows: ",
    "confirm the program logged its '=== <program> started ===' line. "
    "If that line is absent, configure_logging never ran for the "
    "session.",
)
bullet(
    doc,
    "Records from a third-party library are absent: ",
    "that is by design - only first-party loggers and the audio_suite "
    "tree are routed to these files.",
)
bullet(
    doc,
    "Rotation seems to have stopped: ",
    "the active file is simply under its size limit; rollover happens at "
    "the limit, not on a schedule (2 MB for the suite log, 1 MB for each "
    "per-program log).",
)

doc.add_heading("Quick Reference", level=1)
bullet(
    doc,
    "Suite log: ",
    "logs/audio_suite.log - lifecycle + WARNING and above; 2 MB, five backups.",
)
bullet(
    doc,
    "Per-program log: ",
    "logs/<program_name>.log - full diagnostic detail; 1 MB, three backups.",
)
bullet(
    doc,
    "Fallback: ",
    "temp audio_suite_logs when logs/ is not writable.",
)
bullet(
    doc,
    "Scope: ",
    "audio_suite.* plus every first-party tool package, GUI and CLI; "
    "third-party loggers excluded.",
)
bullet(
    doc,
    "Writer: ",
    "audio_suite_shared.logging_setup.configure_logging, called once at startup.",
)
bullet(
    doc,
    "CLI flag: ",
    "--log-level DEBUG|INFO|WARNING|ERROR (default WARNING).",
)

doc.add_paragraph(
    "Generated by user_guides/suite_overview/generate_logging_system_guide.py "
    "- edit the generator (or the modules it documents), not this file."
)

doc.save(OUTPUT)
print(f"Saved to {OUTPUT}")
