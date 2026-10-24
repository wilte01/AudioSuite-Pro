---
title: Undo Tag Edits — User Guide
version: auto
---

## Overview

Undo Tag Edits is a safety net for anyone using the Audio Suite tagging tools. Every time a tag-editing tool runs — for example BPM Analyzer, Tempo Analyzer, Mood Analysis Batch Tagger, Tag Field Updater, or File Reorganizer — Audio Suite automatically records a snapshot of each file's tags exactly as they were before that run. Undo Tag Edits lets you pick one of those saved runs and restore your file tags to the way they were before it happened.

## Quick Start

\1. Open the Master Driver.\
2. Click the UTIL button on the left.\
3. Scroll to the bottom of the Utilities list to the Undo Tag Edits card.\
4. Click Open Undo.\
5. In the window that opens, select a run from the Recent runs list.\
6. Read the preview to confirm it is the run you want to undo.\
7. Click Undo Selected Run and confirm when asked.\
8. Done — your files are restored to how they were before that run.

You can also launch Undo Tag Edits directly by double-clicking Undo_Tag_Edits.pyw in the Audio Suite folder.

## What Can Be Undone

Undo history is recorded automatically by the tools that change tag metadata, by the tools that repair audio in place, and by the Tag-Based File Reorganizer. Typical examples:

- **Tag edits: **anything written by a batch tag run, such as BPM, tempo, key, mood, genre, ReplayGain tags or embedded album artwork — the original tags (or cover image) are restored.
- **In-place audio repairs: **files repaired by Noise Reduction or Pop & Click Remover are put back exactly as they were before the run — the original audio, byte for byte, along with the tags that were in the file at the time. The preview line for these runs reads 'Restore original audio' rather than 'Restore tags'.
- **File moves: **files that a reorganiser run moved are moved back to their original folder.
- **File copies: **copies created by a reorganiser run are removed from the destination folder.
- **Deletions: **files deleted by a Metadata Scrubber restore run are brought back with their original content.

No extra setup is needed. The snapshots are created automatically in the background while a tool runs — you never have to remember to turn anything on.

### How Much History Is Kept

Undo history is capped so it cannot fill your disk: the most recent 50 runs are kept, and the total stored size is limited as well. Because an in-place audio repair stores a complete copy of every file it changes, one very large run can use up a large part of that space, and older runs are dropped from the list when the limit is reached.

In practice this means: undo a run soon after you make it, and keep your own backups of masters you care about. Audio Suite never promises to hold an unlimited history.

## The Undo Tag Edits Window

The window is deliberately simple. There are four parts:

### Recent runs

A list of your saved runs, newest first. Each line shows the date and time, the tool that made the changes, and how many files were involved. You don't need to understand any technical identifiers — the description is all you need.

### What this will do

When you select a run, this panel explains exactly what undoing it will do, for example 'Restore tags: C:\Music\song.mp3', 'Restore original audio: C:\Music\hum.wav' or 'Move back: ...'. This lets you double-check that you picked the right run before doing anything.

### Buttons

**Undo Selected Run: **Restores the selected run. This is the main action and is disabled until you select a run.

**Refresh: **Re-reads the undo history. Use it after running another tag tool so the new run appears in the list.

**Help: **Opens this guide.

## The Confirmation Step

Undoing a run permanently overwrites the current contents of the files in that run with the saved pre-run versions. For a tag run that means the tags; for an in-place audio repair it means the whole file, audio included. Because this cannot be undone, the tool asks you to confirm before it makes any changes. Read the message carefully and click Yes only if you are sure.

### What You See After Undoing

When the undo finishes, a summary tells you how many files were restored, how many could not be restored, and how many were skipped. If any file could not be restored, a warning explains that you should check the processing log for details.

## Safety and Limits

### Snapshots Come First

Undo works because every file is snapshotted before it is changed. If a tool was run before undo history was available, there is nothing to restore for that run — it simply will not appear in the list.

### How Much History Is Kept

Audio Suite keeps the most recent runs (50 by default). Older runs are removed automatically to save space. If a run has disappeared from the list, it has fallen off the end of the saved history and can no longer be undone.

### Empty Runs Are Not Saved

If a tool run ended up changing nothing (for example a dry run, or nothing needed updating), it is not recorded, so it will not appear in the list.

### Files Changed By Another Tool

If you edit the same files again after a saved run, undoing the older run will put the files back the way they were before that older run — the saved tags, or for an in-place audio repair the saved file itself. Anything that happened to them since will be overwritten. Check the preview before confirming.

## Troubleshooting

The list says 'You have no saved undo history yet': This is expected if you have not run a tool that records history, or if your saved history was pruned. Run a tag tool or an in-place repair first, then reopen the window.

A run I expected is missing: The run may have been a dry run (nothing changed), or it may have been pruned because more than the maximum number of runs have been saved since.

A file could not be restored: The file may be locked, read-only, or the saved copy may be unavailable. Check the processing log for the exact error.

I accidentally undid the wrong run: Undoing a run is itself not recorded. Your best next step is to re-run the original tool to re-apply the tags you wanted.

## A Note For Technical Users

The command-line equivalent (python utilities/undo.py) still works and offers list, show, and undo subcommands for scripting and power use. The graphical window provides exactly the same undo engine behind a friendlier interface.
