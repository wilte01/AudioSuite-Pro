# Suite overview

AudioSuite-Pro is 30 first-party tools behind one Click CLI and one Master
Driver GUI, for processing, repairing, analysing and tagging a music library.
Every tool also runs on its own; the driver exists so a library can be handled
as a pipeline instead of one window at a time.

This page is the map. Each tool's own guide is the manual — the
{doc}`../index` links all of them.

## How the tools are grouped

The grouping is the suite's own, and it is what the Master Driver's tabs show:

| Tab | Category | Tools | What belongs here |
| --- | --- | --- | --- |
| REFINE | `refinery` | Audio Refinery | The multi-stage audio pipeline: declick, trim, reduce noise, enhance, normalise in one decode/encode pass. Settings are shared with the standalone Audio Refinery window. |
| ENRICH | `enrich` | 11 | Reading and writing metadata — scrubbing, fingerprinting, ReplayGain, genre, BPM, tempo, key, mood, artwork, lyrics. |
| UTIL | `utility` | 18 | Everything else: conversion, extraction, ripping, editing, and the batch tools that do not fit either pipeline stage. |

The counts come from the tool registry, which also generates the table on
{doc}`../index`. A tool's category decides which card it gets; a new
tool appears in the right tab without any UI code being edited.

## Running a batch

- **Order is declared, not learned.** The driver runs a category's selected
  tools in the manifest's `order` value, and `DEPENDENCY_GRAPH` adds hard
  edges on top (today: Tempo Analyser after BPM Analyser). A tool that needs a
  tag an earlier tool writes reports the file as *skipped* rather than failing
  it, so the rest of the batch still produces a usable library.
- **A failed step does not stop the run.** Transient file-system errors are
  retried twice (2 s, then 4 s); a step that still fails is marked FAILED and
  the batch continues. The policy is described in
  {doc}`../resilience`.
- **Two ways to run the same work.** The CLI does it headlessly
  (`audiosuite <command>`), the Master Driver does it with progress, retries and
  a summary. The [CLI reference](../../user_guides/reference/CLI_Commands_Reference.md)
  lists every command and its `--json` payload. A command's exit status matches
  its summary: `0` clean (skipped files included), `1` finished with per-file
  errors or stopped fatally, `2` a usage error.

## Where to go next

| You want | Read |
| --- | --- |
| What one tool does, setting by setting | that tool's user guide, linked from the {doc}`../index` |
| Every command and flag, or scripting the suite | [CLI commands reference](../../user_guides/reference/CLI_Commands_Reference.md) |
| What an error message means and where the logs are | {doc}`messages` |
| How retries, failure handling and cleanup work | {doc}`../resilience` |
| API keys, file handling, what the suite treats as untrusted | {doc}`security` |
| Building the suite's own code | [contributing](../../CONTRIBUTING.md), {doc}`../api`, {doc}`../plugins` |
