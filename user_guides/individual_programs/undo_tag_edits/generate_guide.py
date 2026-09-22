"""Generate the Undo Tag Edits User Guide .docx."""

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

doc = Document()

# ── Title ──
h = doc.add_heading("Undo Tag Edits \u2014 User Guide", level=0)
h.alignment = WD_ALIGN_PARAGRAPH.CENTER
doc.add_paragraph(
    "Version 1.0 \u2014 September 2026"
).alignment = WD_ALIGN_PARAGRAPH.CENTER

# ── Overview ──
doc.add_heading("Overview", level=1)
doc.add_paragraph(
    "Undo Tag Edits is a safety net for anyone using the Audio Suite tagging "
    "tools. Every time a tag-editing tool runs \u2014 for example BPM Analyzer, "
    "Tempo Analyzer, Mood Analysis Batch Tagger, Tag Field Updater, or File "
    "Reorganizer \u2014 Audio Suite automatically records a snapshot of each file's "
    "tags "
    "exactly as they were before that run. Undo Tag Edits lets you pick one of "
    "those saved runs and restore your file tags to the way they were before it "
    "happened."
)

# ── Quick Start ──
doc.add_heading("Quick Start", level=1)
doc.add_paragraph(
    "1. Open the Master Driver.\n"
    "2. Click the UTIL button on the left.\n"
    "3. Scroll to the bottom of the Utilities list to the Undo Tag Edits card.\n"
    "4. Click Open Undo.\n"
    "5. In the window that opens, select a run from the Recent runs list.\n"
    "6. Read the preview to confirm it is the run you want to undo.\n"
    "7. Click Undo Selected Run and confirm when asked.\n"
    "8. Done \u2014 your files' tags are restored to how they were before that run."
)

doc.add_paragraph(
    "You can also launch Undo Tag Edits directly by double-clicking "
    "Undo_Tag_Edits.pyw in the Audio Suite folder."
)

# ── What Can Be Undone ──
doc.add_heading("What Can Be Undone", level=1)
doc.add_paragraph(
    "Undo history is recorded automatically by the tools that change tag "
    "metadata and by the Tag-Based File Reorganizer. Typical examples:"
)
p = doc.add_paragraph(style="List Bullet")
p.add_run("Tag edits: ").bold = True
p.add_run(
    "anything written by a batch tag run, such as BPM, tempo, key, mood, genre, "
    "ReplayGain tags or embedded album artwork \u2014 the original tags (or "
    "cover image) are restored."
)
p = doc.add_paragraph(style="List Bullet")
p.add_run("File moves: ").bold = True
p.add_run("files that a reorganiser run moved are moved back to their original folder.")
p = doc.add_paragraph(style="List Bullet")
p.add_run("File copies: ").bold = True
p.add_run(
    "copies created by a reorganiser run are removed from the destination folder."
)

doc.add_paragraph(
    "No extra setup is needed. The snapshots are created automatically in the "
    "background while a tool runs \u2014 you never have to remember to turn "
    "anything on."
)

# ── The Window, Explained ──
doc.add_heading("The Undo Tag Edits Window", level=1)
doc.add_paragraph("The window is deliberately simple. There are four parts:")

doc.add_heading("Recent runs", level=2)
doc.add_paragraph(
    "A list of your saved runs, newest first. Each line shows the date and time, "
    "the tool that made the changes, and how many files were involved. You don't "
    "need to understand any technical identifiers \u2014 the description is all "
    "you need."
)

doc.add_heading("What this will do", level=2)
doc.add_paragraph(
    "When you select a run, this panel explains exactly what undoing it will do, "
    "for example 'Restore tags: C:\\Music\\song.mp3' or 'Move back: ...'. This "
    "lets you double-check that you picked the right run before doing anything."
)

doc.add_heading("Buttons", level=2)
p = doc.add_paragraph()
p.add_run("Undo Selected Run: ").bold = True
p.add_run(
    "Restores the selected run. This is the main action and is disabled until "
    "you select a run."
)
p = doc.add_paragraph()
p.add_run("Refresh: ").bold = True
p.add_run(
    "Re-reads the undo history. Use it after running another tag tool so the new "
    "run appears in the list."
)
p = doc.add_paragraph()
p.add_run("Help: ").bold = True
p.add_run("Opens this guide.")

# ── The Confirmation Step ──
doc.add_heading("The Confirmation Step", level=1)
doc.add_paragraph(
    "Undoing a run permanently overwrites the current tags of the files in that "
    "run with the saved pre-run versions. Because this cannot be undone, the "
    "tool asks you to confirm before it makes any changes. Read the message "
    "carefully and click Yes only if you are sure."
)

doc.add_heading("What You See After Undoing", level=2)
doc.add_paragraph(
    "When the undo finishes, a summary tells you how many files were restored, "
    "how many could not be restored, and how many were skipped. If any file "
    "could not be restored, a warning explains that you should check the "
    "processing log for details."
)

# ── Safety and Limits ──
doc.add_heading("Safety and Limits", level=1)

doc.add_heading("Snapshots Come First", level=2)
doc.add_paragraph(
    "Undo works because every file is snapshotted before it is changed. If a "
    "tool was run before undo history was available, there is nothing to restore "
    "for that run \u2014 it simply will not appear in the list."
)

doc.add_heading("How Much History Is Kept", level=2)
doc.add_paragraph(
    "Audio Suite keeps the most recent runs (50 by default). Older runs are "
    "removed automatically to save space. If a run has disappeared from the "
    "list, it has fallen off the end of the saved history and can no longer be "
    "undone."
)

doc.add_heading("Empty Runs Are Not Saved", level=2)
doc.add_paragraph(
    "If a tool run ended up changing nothing (for example a dry run, or nothing "
    "needed updating), it is not recorded, so it will not appear in the list."
)

doc.add_heading("Files Changed By Another Tool", level=2)
doc.add_paragraph(
    "If you edit the same files again after a saved run, undoing the older run "
    "will replace the tags with the version saved before that older run \u2014 "
    "any changes you made since then will be overwritten. Check the preview "
    "before confirming."
)

# ── Troubleshooting ──
doc.add_heading("Troubleshooting", level=1)

doc.add_paragraph(
    "The list says 'You have no saved undo history yet': "
    "This is expected if you have not run a tag-editing tool yet, or if your "
    "saved history was pruned. Run a tag tool first, then reopen the window."
)
doc.add_paragraph(
    "A run I expected is missing: "
    "The run may have been a dry run (nothing changed), or it may have been "
    "pruned because more than the maximum number of runs have been saved since."
)
doc.add_paragraph(
    "A file could not be restored: "
    "The file may be locked, read-only, or the original tags may be "
    "unavailable. Check the processing log for the exact error."
)
doc.add_paragraph(
    "I accidentally undid the wrong run: "
    "Undoing a run is itself not recorded. Your best next step is to re-run the "
    "original tool to re-apply the tags you wanted."
)

# ── Note ──
doc.add_heading("A Note For Technical Users", level=1)
doc.add_paragraph(
    "The command-line equivalent (python utilities/undo.py) still works and "
    "offers list, show, and undo subcommands for scripting and power use. The "
    "graphical window provides exactly the same undo engine behind a friendlier "
    "interface."
)

# ── Save ──
output = (
    "D:\\Users\\wilte\\Desktop\\AudioSuite-Pro\\user_guides\\individual_programs\\"
    "undo_tag_edits\\Undo_Tag_Edits_User_Guide.docx"
)
doc.save(output)
print(f"Saved to {output}")
