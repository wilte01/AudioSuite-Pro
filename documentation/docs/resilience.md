# Retries, failure handling and resource cleanup

This page describes what the suite actually does when a file, a step or a
batch fails. It exists because an earlier *Technical User Guide* described a
checkpoint/recovery subsystem that was never built — `ErrorRecoveryManager`,
`CheckpointData`, a recovery folder and a background cleanup thread. None of
those exist. What does exist is smaller, and this page is written from it:
`audio_suite_shared/error_recovery.py`, `audio_suite_shared/resource_manager.py`
and the Master Driver's `batch_orchestrator.py`.

## Retrying one operation

`retry_with_backoff(func, config, operation_id)` runs `func` and retries it,
with `RetryConfig` fields (defaults in brackets):

| Field | Meaning |
| --- | --- |
| `max_retries` `[3]` | Extra attempts after the first, so at most `max_retries + 1` calls. |
| `retry_delay` `[1.0]` | Seconds before the second attempt. |
| `backoff_factor` `[2.0]` | Multiplier applied per attempt: 1 s, 2 s, 4 s … |
| `max_delay` `[60.0]` | Ceiling for one delay, so backoff cannot grow without bound. |
| `retry_on_exceptions` `[IOError, OSError, PermissionError]` | The only types retried. Anything else is re-raised on the first failure. |

The logging contract matters as much as the timing: each failed attempt writes
the mapped exception and its traceback at **DEBUG**, each scheduled retry writes
one **WARNING** naming the attempt and the delay, and exhausted retries write a
single **ERROR** with `failure_reason`. The caller is the reporting boundary —
it knows the filename and shows the per-file outcome — so a failure is never
reported three times at ERROR for one file.

Retries are used by the shared file-processor base for per-file work, and by
the Master Driver's batch loop for a whole step (below).

## Choosing skip, retry or abort

`get_recovery_action(error, operation_type, user_callback=None)` classifies an
exception:

| Exception | Action |
| --- | --- |
| `MemoryError`, `KeyboardInterrupt` | `ABORT` — retrying cannot help. |
| `FileNotFoundError` | `SKIP` — the file is gone; other files are unaffected. |
| `PermissionError`, `OSError` | `RETRY`, or `user_callback` when one is supplied. |
| anything else | `RETRY`, or `user_callback` when one is supplied. |

`RecoveryAction` also carries `USER_CHOICE`, for a caller whose callback wants
to ask rather than decide.

## A failed batch step

The Master Driver runs each selected step through the same helper with a
stricter configuration: `max_retries=2`, `retry_delay=2.0` (so 2 s then 4 s),
retrying only `OSError`/`PermissionError`. A step that exhausts them is marked
**FAILED**, the batch carries on with the next step, and the run's summary
counts it. A step that never completed carries no caveat note: there is no
finished work to annotate.

Steps run in the order the driver decides — the manifest's `order` for each
category, with hard dependencies declared in `DEPENDENCY_GRAPH` (today: Tempo
Analyser after BPM Analyser). A tool that needs a tag another tool writes
reports the file as skipped rather than failing it, so a partial pipeline
still produces a usable library.

A step whose dependency did **not** succeed is not started at all: it is marked
**SKIPPED** and carries the reason — `skipped: dependency 'bpm' failed`, or
`did not run` when that dependency was itself skipped. This holds in
sequential and Parallel mode alike. Starting Tempo against files BPM never
tagged would write a tempo marking derived from nothing and then report the
step as completed, which is worse than not running it.

## Resource cleanup

`ResourceManager` is a process-wide registry of things that must not leak:
temporary files and directories, threads, subprocess handles. It registers an
`atexit` handler, so normal exit and an unhandled exception both reach
`cleanup_all_resources()`.

- `register_resource(..., auto_cleanup=True)` records an id, a type, an
  optional path and a cleanup callback.
- `temporary_file()` / `temporary_directory()` are context managers: the
  resource unregisters and is removed even when the body raises.
- `track_thread(thread, name=None)` keeps a weak reference and warns at
  cleanup if the thread is still alive — the tool cannot kill it, but the log
  says which one survived.
- `cleanup_expired_resources(max_age_hours=24)` is the sweep for a long-running
  process; it is explicit, not a background thread.

There is no checkpoint file to inspect and no recovery folder to clean up. If
a run is interrupted, the next run starts from the files as they are: the
Refinery's completion registry is what makes a re-run cheap, not a journal.

## Where a failure surfaces

Three places, deliberately:

1. the per-file status line in the tool window, for the person watching;
2. `logs/<program>.log` for detail and `logs/audio_suite.log` for WARNING and
   above, described in {doc}`user/messages`;
3. `--json` output, where `success` / `error` / `skipped_files` / `error_files`
   are built from the exceptions themselves so a wording change cannot break a
   script.
