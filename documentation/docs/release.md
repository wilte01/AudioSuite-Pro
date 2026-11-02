# Cutting a release

Every version here is cut by one command. What it writes is what ships:
`[project] version` in `pyproject.toml`, `uv.lock`, both change-history files,
every guide whose subtitle names a version, the annotated tag and the GitHub
release page. Nothing is done by hand, because the 1.2.0 and 1.3.0 cuts each did
the same six steps manually and each step is easy to do half-way — a bumped
version with a stale lock, a promoted changelog with a blank `[Unreleased]`, or
a regenerated `.docx` that an external editor silently re-saved.

The script is `utilities/release.py`. The rules it enforces are the repository's
own `AGENTS.md`; this page describes how to drive it, not what the rules are.

## Before you start

* A clean working tree on `main`, with this release's entries already written —
  see [Writing the entries](#writing-the-entries).
* `uv` on `PATH`. It re-locks the dependency graph and refreshes the editable
  install's metadata so the gate reads the new version.
* GitHub's CLI, `gh`, authenticated, so the release page can be created. When
  `gh` is installed but missing from `PATH` (common on Windows), the script also
  probes `Program Files\GitHub CLI\gh.exe` before giving up.
* The dev extras in the interpreter you pass: re-rendering a guide needs
  `python-docx`, and the gate needs ruff, mypy and bandit.

## Writing the entries

Two files hold the change history, and a bullet's subject decides which one it
belongs to:

* [CHANGELOG.md](../../CHANGELOG.md) — what a user can run or observe. The
  in-app *What's New* panel renders this file.
* [TECHNICAL_CHANGELOG.md](../../TECHNICAL_CHANGELOG.md) — the gate, CI, tests,
  tooling and behaviour-neutral refactors.

Both are written under `## [Unreleased]` before the cut. The user-facing file
must hold at least one bullet; the technical one may legally hold nothing, and a
release with no developer-facing change adds no heading there rather than an
empty section.

## The two runs

A cut is the same command twice, and that is deliberate: a tag has to point at a
commit that already contains the cut, while the cut's own run has its changes
uncommitted by definition.

```bash
# 1. write the artefacts, then run the gate
python utilities/release.py 2.4.0

# 2. review and commit what it wrote, then tag and publish
git add -A
git commit -m "Cut 2.4.0"
python utilities/release.py 2.4.0
```

The first run bumps the version, re-locks, promotes both changelogs, re-renders
the version-labelled guides, refreshes the editable install and runs the full
gate. The second run finds every file step already done and prints `[SKIP]` for
each, then creates the annotated tag `v2.4.0`, pushes it, and creates the GitHub
release `AudioSuite-Pro 2.4.0` whose notes are the `## [2.4.0]` section of
`CHANGELOG.md` verbatim — so a release page and the changelog cannot describe
the same release differently.

If you commit the cut and forget the second run, the release exists only as
untagged code. Re-running the command is the fix; so is the backfill below.

## What each step checks

* **Version** — read from `[project] version`, never a second constant, and
  validated as `X.Y.Z` before anything is written.
* **Lock** — `uv lock --check` decides whether a re-lock is needed at all, and
  the new version is then read back out of `uv.lock` rather than assumed.
* **Changelogs** — the promotion is driven by the real `[Unreleased]` body and
  refuses to release an empty one in `CHANGELOG.md`.
* **Guides** — a guide is re-rendered only when its subtitle does not already
  name the new version, and the result is compared zip entry by zip entry. A
  change to anything but `word/document.xml` is external-tool drift, not this
  release, and fails the cut.
* **Gate** — compile over the tracked file list, ruff check and format, mypy,
  bandit parsed for 0 High / 0 Medium, then the bare test suite.
* **Publishing** — only on a clean tree whose `HEAD` declares the version.

Every step is idempotent: a second run of the same version reports `[SKIP]` and
leaves every byte where it was, so a cut can be retried after a transient
failure without producing a second commit's worth of noise.

## Flags

| Flag | Effect |
| --- | --- |
| `--date YYYY-MM-DD` | The changelog heading's date; defaults to today. |
| `--dry-run` | Report every planned change, write nothing, run no gate. |
| `--skip-gate` | Stop after the file changes instead of running the gate. |
| `--offline` | Pass `--offline` to `uv`, and stop before pushing or publishing. |
| `--no-publish` | Cut the files without tagging or creating a release page. |
| `--backfill-releases` | Create the release page for every version tag that lacks one, then exit. |
| `--root PATH` | Operate on another checkout. |
| `--python PATH` | The interpreter carrying the dev extras. |

## When something refuses

* **`the [Unreleased] section holds no entries`** — write the user-facing bullet
  first. This is the one refusal that means the release itself is not ready.
* **`entries other than word/document.xml changed`** — a guide was re-saved by
  an external editor. Re-render it from its Markdown source before retrying.
* **`[TODO] ... has uncommitted changes`** — the publishing pass ran on a cut
  that has not been committed yet. Commit it and run the command again.
  Untracked files such as a log or a scratch folder do not block it.
* **`[TODO] HEAD declares X, not Y`** — the commit does not contain the cut.
* **`gh is not on PATH`** — install GitHub's CLI or pass `--no-publish`. The
  step fails loudly rather than silently skipping: a tagless, releaseless
  version is exactly what this step exists to prevent.
* **`no version tags found; refusing a vacuous release backfill`** — the
  backfill is pointed at a checkout with no tags.

## Backfilling older releases

A version that was tagged before the release page existed can be published
without touching its code:

```bash
python utilities/release.py --backfill-releases
```

It walks the tags in version order, skips the ones that already have a page, and
skips any tag the changelog cannot describe rather than inventing notes for it.
`--dry-run` shows the plan first.

## After the cut

* Confirm the release page and the tag name in the repository's Releases tab,
  and that the new version is the one marked *Latest*.
* Push the cut's commit if you have not already — the tag and the commit are
  what CI and the docs locks read.
* User guides are part of the cut, so there is nothing left to render by hand.
  If a guide's prose changed for this release, edit its Markdown source and
  re-render it *before* the cut: the release step only rewrites the version
  subtitle.
