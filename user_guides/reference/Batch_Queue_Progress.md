# Batch Queue & Progress — User Guide

## Overview

The Master Driver's ENRICH and UTIL tabs now include a real-time batch queue
progress display. When you launch a multi-tool batch, the control strip expands
to show:

- A **step indicator**: "Step 2 of 6: Mood Analyzer"
- An **ETA label**: "Elapsed: 0:45  ETA: 2:15"
- A **progress bar**: fills as each tool completes

## How it works

1. Select the tools you want to run (checkboxes in the ENRICH or UTIL tab).
2. Configure tool-specific options.
3. Click **LAUNCH ENRICH PROCESS** or **LAUNCH UTILITY PROCESS**.
4. The progress bar, step indicator, and ETA appear below the control strip.
5. Each tool runs in sequence (sequential mode by default).
6. After the batch completes, the progress widgets hide automatically.

## Parallel mode

The `BatchOrchestrator` supports dependency-aware parallel execution.
Tools that do not depend on each other can run concurrently when
`parallel=True` is passed. The dependency graph is:

| Tool       | Depends on              |
|------------|-------------------------|
| mood       | bpm, key, tempo         |
| tempo      | bpm                     |
| genre_sync | (none)                  |
| replaygain | (none)                  |
| scrubber   | (none)                  |
| art        | (none)                  |
| album_genre| (none)                  |

## Per-step retry

If a tool fails due to a transient error (e.g., `PermissionError`, `OSError`),
the orchestrator retries it up to 2 times with exponential backoff
(2 s, then 4 s). After exhaustion the step is marked `FAILED` and the batch
continues with the next tool.

## ETA estimation

After at least one tool completes, the ETA is calculated as:

    (average duration of completed tools) × (remaining steps)

After the first batch run, per-tool average durations are stored in
`audio_suite_config.json` under `tool_durations`, allowing the ETA to
be estimated before any tool finishes on subsequent runs.

## Architecture

- `master_driver/batch_orchestrator.py` — `BatchOrchestrator`, `BatchStep`,
  `BatchProgress`, `BatchReport`, dependency graph, retry logic.
- `master_driver/runner/module_runner.py` — delegates to `BatchOrchestrator`
  when a `progress_callback` is provided.
- `master_driver/app.py` — `_update_batch_progress()` callback updates the
  progress bar/step/ETA widgets on the UI thread.
- `audio_suite_shared/secure_subprocess.py` — `run_python_script()` now
  accepts a `line_callback` parameter for real-time output streaming.
- `audio_suite_shared/suite_config.py` — `save_tool_duration()` / `load_tool_durations()` / `load_average_tool_duration()` persist run history.
