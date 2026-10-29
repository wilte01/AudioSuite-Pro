# Messages, dialogs and log files

AudioSuite-Pro tells you what happened in three places: a dialog or CLI line,
a per-file status line in the window you are watching, and a log file. This
page explains where each one lives, what the severity words mean, and what to
do about each error message the suite can show.

The wording itself is not written here first. Every user-facing error sentence
comes from one table in `audio_suite_shared/exceptions.py`
(`USER_MESSAGES`), and `audio_suite_shared/tests/test_exceptions.py` fails if
this page and that table disagree — so a message cannot quietly change meaning.
Run with `AUDIOSUITE_DEBUG=1` to see the raw exception instead of the sentence.

## Where the log files are

Each program writes two rotating files under `logs/`:

| File | What it holds | Rotation |
| --- | --- | --- |
| `logs/audio_suite.log` | The administrator's record: the `=== <program> started ===` lifecycle line, plus every **WARNING or worse** from any module. Normal per-file progress is deliberately absent, so a failure is findable. | 2 MiB, 5 backups |
| `logs/<program>.log` | That program's full detail, every file it touched, at the level the run used. | 1 MiB, 3 backups |

Both files are UTF-8 and share one line format — timestamp, logger name padded
to 40 characters, level padded to 8, message:

```text
2026-10-24 11:42:07,512  audio_suite.bpm_analyzer   INFO      [OK] song.flac
```

- **The folder** is `logs/` inside the suite folder. If that is not writable
  (a read-only install, for example) the suite falls back to a temporary
  directory instead of failing, so check `logs/` first and then the temp
  folder.
- **`AUDIOSUITE_LOG_DIR`** overrides the location entirely, which is what the
  test suite uses so it never writes to the shipped log. Set it if your
  install folder is read-only and you want the files somewhere predictable.
- **`--log-level`** sets the threshold for the per-program file on a CLI run;
  the suite log stays at WARNING and above by design.
- **`logs/` is git-ignored**, so a fresh checkout has no log folder until a
  program runs.

## What the severity words mean

| Level | What it means | What you do |
| --- | --- | --- |
| `INFO` | A milestone: the run started, a file was handled, a batch finished. | Nothing. It is the record of what ran. |
| `WARNING` | Something was skipped or degraded, but the run continued — a missing optional tag, artwork not found online, a retried file-system error. | Read the line; fix it only if the outcome matters to you. |
| `ERROR` | One file failed. The rest of the batch continues and the summary counts it. | Find the file in `logs/<program>.log`, act on the message below. |
| `CRITICAL` | The run itself could not continue — a missing external tool, an unwritable destination, a lost network drive. | Fix the system problem, then re-run. |

## What each error message means

The class names are the internal types; you only ever see the sentence.

| Message you see | Internal type | What to do |
| --- | --- | --- |
| The file could not be found. It may have been moved or deleted. | `AudioFileNotFoundError` | Re-scan the folder; if the file moved during the run, run it again on the new location. |
| Permission denied. Check that AudioSuite has read/write access. | `AudioPermissionError` | Close anything holding the file (players, tag editors, sync clients), then check the file is not read-only. |
| The disk is full. Free up space and try again. | `AudioDiskFullError` | Free space and re-run. The affected file was not modified. |
| Could not access the folder. Check that it exists and is accessible. | `AudioDirectoryError` | Check the path, the drive letter and the account's access to it. |
| This file uses an unsupported or unreadable codec. | `AudioCodecError` | Convert the file to a supported format, or install the codec the file needs. |
| The file format is invalid or corrupted. | `AudioFormatError` | The file is not a valid container of its extension — re-copy it from the source, or repair it. |
| An external tool (e.g. ffmpeg) failed. Check that it is installed and up to date. | `AudioExternalToolError` | Run `audiosuite doctor`; install or update FFmpeg and re-run. |
| Could not read or write the file's metadata tags. | `AudioTagError` | The tag block is unreadable or locked. Open the file in a tag editor, re-save it, and re-run. |
| Audio analysis failed. The file may be corrupted or too short. | `AudioAnalysisError` | Analysis needs decodable, non-silent audio of at least the documented minimum length; check the file plays. |
| The configuration file is missing or corrupted. Default settings will be used. | `AudioConfigFileError` | Nothing to do for this run; the tool used defaults. Recreate your settings if you need them. |
| An invalid configuration value was detected. Please check your settings. | `AudioConfigValueError` | Open the tool's settings and correct the value named in the per-program log. |
| A required tool or library is not installed. | `AudioMissingDependencyError` | Install the optional extra the tool needs (`uv sync --extra ml` for the ML engines) and restart the tool. |
| A file system error occurred. | `AudioIOError` | Usually a transient lock or a disconnected drive; re-run once the path is available. |
| An error occurred during processing. | `AudioProcessingError` | The per-file line in `logs/<program>.log` names the file and the reason. |
| A configuration error occurred. | `AudioConfigurationError` | Check the tool's settings file; `audiosuite doctor` names a missing or unreadable one. |
| An unexpected error occurred. Please check the log for details. | `AudioSuiteError` | Search `logs/audio_suite.log` for the same timestamp; the traceback is in `logs/<program>.log`. |

## Reading a failing run

- **A per-file skip is not an error.** A file that has no beat, is silent, is
  too short to analyse, or is missing a tag another tool writes is reported as
  skipped with a reason, and the batch carries on. The summary counts it.
- **Don't parse the prose.** `audiosuite <command> --json` publishes the same
  outcome structurally — `success`, `error`, `skipped_files`, `error_files` —
  built from the exceptions themselves, so a wording change cannot break a
  script. The CLI reference documents each command's payload.
- **Retries are logged, not hidden.** A transient file-system error is retried
  with backoff; you see a `WARNING` per attempt and one `ERROR` line if the
  attempts are exhausted. The resilience page explains the policy.
