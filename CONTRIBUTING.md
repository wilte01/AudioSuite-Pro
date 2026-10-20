# Contributing to AudioSuite-Pro

Thanks for looking at the codebase. Contributing is deliberately mechanical:
the suite defends its gates, so this file describes the gates and the
registration points you must satisfy — not taste.

## Setup

```pwsh
git clone <this-repository> AudioSuite-Pro
cd AudioSuite-Pro
uv sync --extra dev --extra analysis --extra cd-ripping
```

This gives you the runtime deps, the test stack (`pytest`/`pytest-cov`),
`ruff`, `mypy` and `bandit`. `ffmpeg` and `ffprobe` must also be on `PATH`
(see README "Prerequisites"); the launchers warn — they do not block — when
they are missing.

## The mandatory Phase Gate

**Every change is gated before it is marked complete.** Run all six (from the
suite root, Windows/pwsh). The suite floor is Python 3.11, and `tomllib` is
standard library on every supported version, so the TOML-dependent config locks
run everywhere:

```pwsh
# 0. compile / import gate — mandatory first step after any edit
python -m compileall -q -f . -x '(^|/)(\.venv|\.git)/'

# 1. lint + formatting
python -m ruff check .
python -m ruff format --check .

# 2. static typing (strict is set in pyproject.toml)
python -m mypy .

# 3. security screening (UTF-8 enabled on Windows; -c loads pyproject skips)
$env:PYTHONUTF8='1'; python -X utf8 -m bandit -r . -x ./.venv -c pyproject.toml

# 4. the full test suite — a package-scoped run is NOT a substitute
python -m pytest -q

# 5. secrets staged for commit (primary + supplemental patterns)
git grep --cached -n -i -E -I -e "api[_-]?key|secret|passwd|password|token"
git grep --cached -n -i -E -I -e "[-_](key|secret|token|password|passwd|client)[^ ]*[=:][^A-Za-z0-9_][A-Za-z0-9+/=_-]{10,}"
git grep --cached -n -E -I -e '"[a-f0-9]{32}"'
git grep --cached -n -E -I -e '"[A-Za-z0-9+/]{44,}={0,2}"'
git grep --cached -n -E -I -e "-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"
```

Run all six in one shot with `utilities\run_gate.ps1`.

Zero failures, zero "fix later". A failing test is never deleted, skipped,
or `xfail`ed to make a gate green — resolve the cause. The coverage gate
(`fail_under = 75`) is enforced on the bare full-suite run only.

### Test selection (markers)

- `integration` tests (require ffmpeg and real audio files) **run by
  default** wherever ffmpeg/ffprobe are found; where a binary is missing the
  root `conftest.py` auto-skips each one with a reason naming the missing
  executable.
- `hardware` tests (physical CD drive + Win32 drive API) are **deselected by
  default** and never run in CI. Run them locally with the documented
  opt-in:

  ```pwsh
  python -m pytest -m hardware
  ```

  Run this before considering any `cd_ripper` work complete — the 30
  hardware tests exist so release testing covers them.

- `gui`-marked tests need a real Tk display; on a headless host they skip
  with an attributable reason, and the session summary states explicitly
  that GUI behaviour was not verified.

## Test file naming

One test file per source module, in `<package>/tests/`, named
`test_<module>.py` — `core/scrubber.py` → `tests/test_scrubber.py`. Do not
add descriptive suffixes (`test_app_audio_detection.py` is wrong;
`test_app.py` with a test class inside is right). Composite files testing
tightly-coupled modules (`test_tag_io.py` for `tag_reader.py` +
`tag_writer.py`) are the accepted exception. New or modified functions ship
with their tests in the same change — coverage targets 85%+ on modified
logic, and audio/correctness-relevant fixes are verified by decoding and
measuring the result, never by reading back internal state.

## Registering a new tool (checklist)

Every new tool must be wired into ALL of the following; missing one is a
silent runtime degradation:

1. **Tool manifest** — `audio_suite_shared/tool_plugin.py`
   (`_DEFAULT_MANIFESTS`; the `id` is the single source of truth used
   everywhere below).
2. **Master Driver card** — `master_driver/ui/cards/{tool_id}_card.py`;
   the filename must be exactly `{tool_id}_card.py`.
3. **CLI command** — the tool's `click` command + import in
   `audio_suite_shared/cli_app.py` (verify flag names against the CLI).
4. **Arg builder** — `master_driver/runner/arg_builder.py`; enrich tools
   emit `[path, mode_flag, start_flag, end_flag]`.
5. **Batch orchestration** — `master_driver/batch_orchestrator.py`
   `DEPENDENCY_GRAPH`.
6. **Driver state** — `master_driver/state/app_state.py` toggle key.
7. **Pyw launcher** — top-level `<Tool_Name>.pyw` with the
   `guard_or_exit()` pre-flight call.
8. **User guide** — generator in
   `user_guides/individual_programs/<module_dir>/generate_guide.py` (run it;
   the `.docx` is an artifact), and the filename registered in
   `audio_suite_shared/platform_utils.py` `guide_to_program`.
9. **Test registration** — `<module>/tests` in `pyproject.toml` `testpaths`
   + coverage `source`.
10. **Tests** — a new `<module>/tests/` suite, and the expected-set tests
    updated in lockstep.

When you are done, regenerate the README tool index — the table is produced
from the manifest and the full-suite lock tests fail if it drifts:

```pwsh
.venv\Scripts\python.exe utilities\generate_readme_tool_index.py
[OK] Tool index regenerated: ... rows
```

## CLI JSON schema conformance

Every CLI command publishes a JSON payload through
`audio_suite_shared/cli_schema.py`. Two artifacts are committed: the schema
document (`audio_suite_shared/cli_schema.json`, generated from that table) and
one recorded payload per command (`tests/data/cli_payloads.json`). The CI job
"CLI schema conformance" validates the recordings against the document with the
real draft 2020-12 validator a consumer uses, and
`tests/test_cli_schema_conformance.py` makes the same check in the suite - plus
the mutations that prove it can fail. A new command fails the gate until it has
a recording.

After a deliberate schema change, re-record the corpus from the real commands:

```pwsh
python -m tests.cli_schema_conformance --record
```

Never let CI record: a gate that rewrites the artifact it judges reports no
drift.

CI also publishes the recordings for people who consume the CLI rather than
change it: the test job exports them as one file per command and uploads the
`cli-payloads` artifact, so a script author can download real payloads without
a checkout. Reproduce that directory locally with:

```pwsh
python -m tests.cli_schema_conformance --export-dir cli-payloads
```

`cue generate` becomes `cue-generate.json` for the recorded payload and
`cue-generate-error.json` for its fatal-error document — the file a run prints
when it dies before doing any work. The export refuses a corpus the gate
rejects, so a published document is always one the contract validates.
`cli-payloads/` is gitignored — it is a build artifact, not a second copy of
the corpus.

`audiosuite --json-schema` prints the committed document, and every command's
variant carries an `examples` array with the recorded payload for that command
followed by its fatal-error document, so a script author can see the shape of
both a successful and a failed run from an install without running anything.
`--record` rewrites the corpus **and** the document's examples from the same
run, and the conformance gate checks every promise: each example is present, it
validates against its own variant, it is the recorded document, and a failure
example really is the failure shape — zero counters, `errors: 1`, the reason in
`error`, and no tool-specific keys, so a failed run is readable with the code
that reads a successful one. The document ships as package data
(`[tool.setuptools.package-data]`), because the flag reads the installed file
rather than regenerating it.

## Dependency security scanning

CI's security job audits the graph the suite actually ships. It exports the
locked graph (`uv.lock`, all extras, project excluded) and runs `pip-audit`
against that file rather than against `.venv`, because the virtualenv also
carries environment-only packages such as `pip`, whose advisories are not this
project's to fix.

Run the same scan locally:

```pwsh
uv export --frozen --all-extras --no-emit-project --format requirements-txt --no-hashes -o requirements-audit.txt
uvx pip-audit -r requirements-audit.txt --no-deps --desc
```

`--no-deps` is deliberate: the export is already resolved, and letting
pip-audit resolve again could audit versions the lock never installs.

- CI runs the step **on probation for two sprints**
  (`continue-on-error: true`), so a newly published advisory is visible without
  blocking unrelated work. Do not delete the step to silence it, and do not
  move the audit onto `.venv`.
- A finding that can be upgraded away is fixed in the change that found it,
  with the scan re-run to prove it: `urllib3>=2.8.0` landed with the step that
  reported the three advisories against 2.7.0.
- A finding that cannot be upgraded yet is recorded in the governing plan's
  decision log with its advisory id and the reason, not suppressed.

## Audio correctness

This suite writes audio and tag data. A defect that could corrupt,
mis-normalize, or mis-tag user audio is the highest-priority fix class:
validate such changes by decoding the output and measuring it (RMS, frames,
tag payload), not by asserting the function returned a value. Dry-run flags
must be traced end-to-end to the write site.

## Security

See `SECURITY.md` for reporting vulnerabilities and for what the suite
treats as untrusted input. API keys and runtime config files
(`audio_suite_config.json`, `album_art_config.json`) are gitignored on
purpose — never stage them.

## Licence

Contributions are licensed under the GPL-3.0-or-later, like the rest of the
project — see `LICENSE`.
