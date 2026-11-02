# PLAN — Duplicate Finder duplicate disposition (quarantine / delete / ASX stub)

**Status:** `[x]` **COMPLETE (2026-11-02), shipped as 2.4.0.** The disposition
writer, the ASX stub reader/restorer, the CLI/GUI/driver wiring, the guides and
the release notes are implemented and verified by the full gate. D20 and D21
record the two corrections found during implementation and review.

**Base state:** `main` at `a9afe78` ("Record the spectral repair deferral and
close the restoration plan"), working tree clean. The last cut is **2.3.1**
(`pyproject.toml`), whose Duplicate Finder ships quarantine only. The next free
minor is **2.4.0** (the restoration plan released its 2.4.0 slot when F-08b was
deferred).

**Governing scope:** the Duplicate Finder's disposition of a duplicate (keep the
current quarantine move, delete, or replace with an ASX stub), the stub's
metadata contract, and the ASX Playlist Extractor's ability to consume that stub
and recreate the file. Nothing else: no new tool, no change to detection,
clustering, the keeper rule, the fingerprint cache, the theme, or any other
tool's behaviour.

**Source:** maintainer brief, 2026-11-02:

> I am looking at extending the options available when running the Duplicate
> Finder. Currently duplicates are kept, i.e. moved to a default library or to a
> user named library. The options I would like to consider are: 1) Delete
> duplicates, 2) Replace duplicates with an .ASX stub that points to the kept
> file. This would give the user 3 options. If the user selects to have a .ASX
> stub, then, at a later stage, they should be able to recreate the original
> file by running the ASX Extractor, this means that the creation of the .ASX
> file must contain all required tags. At this stage, review the idea and
> develop a plan for introducing the suggested changes. Do not go beyond
> creating the plan.

**Versioning:** one **minor, 2.4.0**, for the whole capability, even though it
touches two tools. The Duplicate Finder must not be able to write a stub that
the shipped extractor cannot restore, so the writer (DD-1 … DD-3) and the
reader/restorer (DD-4) ship in the same cut. Splitting them would ship a
documented promise the installed suite cannot keep. The alternative (2.4.0
writer, 2.5.0 reader) is recorded in D14 and rejected.

**Anti-creep:** implement only the items below. No new audio DSP, no change to
fingerprinting, clustering, keeper selection or the cache, no change to the
default disposition, no new tool, no new CLI command, no plugin point, and no
restyle of either window. A defect found while implementing an item is fixed in
the same change with a regression test and recorded in §6 (`AGENTS.md`,
*Defects and failing checks*).

---

## 1. What is true today (measured at `a9afe78`)

Every statement below is read from the committed source, not assumed.

| Area | State now | Evidence |
|---|---|---|
| Disposition | **One behaviour: quarantine.** A live run moves every non-keeper into the quarantine folder and records each move in the undo journal. A dry run moves nothing. | `duplicate_finder/core/file_processor.py::run_duplicate_scan`, `quarantine_file`. The package docstring states "Nothing here deletes audio". |
| Settings | `ScanSettings` is a frozen dataclass with threshold, three comparison bounds and `quarantine_dir`; there is no notion of what to do with a duplicate. | `duplicate_finder/core/models.py`. |
| Report and payload | Per-file tokens are `[KEEP]`, `[DUPLICATE]`, `[MOVED]`, `[CACHED]`, `[FINGERPRINT]`, `[SKIP]`, `[ERROR]`; the completion payload adds `groups`, `duplicates`, `quarantined`. | `duplicate_finder/core/file_processor.py`; locked by `tests/test_completion_seam.py` and `tests/test_completion_payload_published.py` (19 GUI tools). |
| GUI | Setup has a similarity slider and a quarantine folder entry. The shared Mode combobox is Dry Run / Live Update. Presets store threshold, quarantine folder and run mode. | `duplicate_finder/ui/setup_tab.py`, `ui/app.py::_collect_settings`. |
| Driver | The card exposes threshold and quarantine folder. The arg builder emits `[path, mode, start, end, --threshold, value, --quarantine-dir, value]`; `utils/cli_args.py` reads exactly those slots. | `master_driver/ui/cards/duplicate_finder_card.py`, `master_driver/runner/arg_builder.py::_build_duplicate_finder_args`, `duplicate_finder/utils/cli_args.py`. |
| CLI | The registered command is `duplicates`; options are `--threshold`, `--quarantine-dir`, `--cache`, the shared `--dry/--live` and `--json`. | `duplicate_finder/cli.py`; `tests/data/cli_payloads.json` and `audio_suite_shared/cli_schema.json` carry its payload. |
| ASX reading | The parser reads the first `<ref href>` only. It ignores every other element, including title/author/params. It resolves an absolute or ASX-relative path, tries a same-stem sibling in a supported audio extension when the target is missing, and rejects DTD/entity payloads. | `asx_extractor/core/asx_parser.py::process_asx_file`. |
| ASX writing | The extractor writes no ASX files. Extraction copies the referenced audio into the selected directory with `copy2`, then moves the playlist to the Trash (or unlinks it when `send2trash` is unavailable). | `asx_extractor/core/file_ops.py`, `asx_extractor/cli.py::run_cli_extraction`. |
| ASX discovery | Top-level `.asx` files in the selected directory only; sub-folders are not scanned. | `asx_extractor/cli.py`, `asx_extractor/app.py`. |
| Tag surface | Read: nine canonical editor fields (`title`, `artist`, `album`, `album_artist`, `track`, `disc`, `year`, `genre`, `comment`), MusicBrainz IDs, ISRCs, synced/plain lyrics, embedded artwork, raw tags. Write: one canonical field at a time, raw tags, synced/plain lyrics, and **JPEG-only** `embed_artwork`. | `audio_suite_shared/tag_helper_base.py::EDITABLE_FIELDS`, `tag_helper_reader.py`, `tag_helper_writer.py`. |
| Trash | `send2trash` is a declared runtime dependency and is installed on first use into the interpreter running the tool. The extractor still imports it optionally and falls back to permanent `unlink()` for playlists. | `pyproject.toml`, `uv.lock`, `duplicate_finder/core/trash.py`, `asx_extractor/core/file_ops.py`. |
| Case sensitivity | **Defect confirmed while planning:** the parser matches the literal element name `ref`, so a well-formed ASX that uses the format's usual uppercase `<REF HREF="…">` is reported `NO REF LINK IN ASX`. Reproduced at `a9afe78` with a real temporary playlist and audio file. | `asx_parser.py` (`root.iter("ref")`); the existing tests only use lowercase `<ref>`. |
| Locks that will move | Completion seam (19 tools), completion publisher table, callback payload contract, CLI usage-error table, CLI schema corpus, AppState/runner/card expectations, guide-claim tokens, user-guide hygiene, release-note window. | `tests/test_completion_seam.py`, `tests/test_completion_payload_published.py`, `tests/test_callback_payload_contract.py`, `tests/test_cli_usage_errors.py`, `tests/cli_schema_conformance.py`, `master_driver/tests/test_app_state.py`, `master_driver/tests/test_runner.py`, `master_driver/tests/test_ui_cards.py`, `tests/test_guide_claims.py`, `tests/test_user_guide_hygiene.py`, `tests/test_release_notes.py`. |

### 1.1 The three outcomes, as they would stand

| Disposition | Duplicate file | Kept file | Reversible by | Today |
|---|---|---|---|---|
| Move to quarantine (default) | moved intact into the quarantine folder, undo snapshot recorded | untouched, read only | Undo Tag Edits (move snapshot) | ships |
| Delete | moved to the OS Recycle Bin | untouched, read only | the operating system's Trash | **does not exist** |
| Replace with ASX stub | removed to the OS Recycle Bin after a verified stub is written in its place | untouched, read only | ASX Playlist Extractor (recreates from the keeper and the stub's tags) | **does not exist** |

### 1.2 What the stub has to be

The stub is a normal ASX 3.0 playlist whose `<ref>` points at the keeper, so
any ASX-aware player can still play it and the existing extractor already
recovers the *content*. What the stub adds is the metadata of the file it
replaced, under a versioned, machine-readable schema, so the extractor can
recreate the original file rather than just copy the keeper under the stub's
name.

### 1.3 The tag inventory the plan will promise

The suite has a canonical, cross-format tag surface, so the promise is defined
against that surface rather than against format-specific frames:

- **Required (always written, even when empty):** the nine `EDITABLE_FIELDS`.
  Absence is recorded explicitly (an empty value), so restoring a duplicate
  that had no album clears the keeper's album instead of silently keeping it.
- **Carried when present:** MusicBrainz track/album/artist IDs, every ISRC,
  synced lyrics, plain lyrics, and embedded cover artwork.
- **Deliberately not carried:** ReplayGain values (they measure the removed
  encoding, not the keeper's audio), non-canonical TXXX/custom frames,
  chapters/cue data, technical stream properties, and file timestamps. §2.5
  records why, and the guides will say it.

---

## 2. The proposed contract

### 2.1 Dispositions

One enum, `quarantine | delete | asx-stub`, stored in `ScanSettings` and
defaulting to `quarantine`. Existing runs, presets and driver cards that do not
name a disposition keep behaving exactly as they do today.

- **Quarantine** — unchanged: move to the chosen/default quarantine folder,
  record the move for Undo Tag Edits.
- **Delete** — move each duplicate to the operating system's Recycle Bin. The
  run never calls `unlink()` on audio and never falls back to permanent
  deletion: when the Trash backend is unavailable the run refuses before it
  fingerprints anything and says so.
- **ASX stub** — write `<duplicate stem>.asx` beside the duplicate (with a
  ` (2)` suffix on collision), verify it parses and its `<ref>` resolves to the
  keeper, then move the duplicate to the Recycle Bin. A failure at any point
  leaves the audio file in place.

### 2.2 Safety invariants (not open for a later item to weaken)

1. **The keeper is never opened for writing.** Its SHA-256 and mtime are
   unchanged after every disposition; the tests assert the hash.
2. **A dry run performs no file operation** — no quarantine folder, no stub, no
   Trash call — and reports exactly what a live run would do.
3. **Stub before Trash.** A stub is parsed back and its `<ref>` is resolved
   before the duplicate is moved to the Trash. A stub-write failure is an error,
   not a deletion.
4. **Delete means Trash.** No permanent-delete path exists for audio. The
   first delete or stub run installs `send2trash` into the interpreter running
   the tool; if that install fails, `delete` and `asx-stub` are refused with a
   user-facing message before any file is touched.
5. **No overwrite anywhere.** Stub names and quarantine names gain a numeric
   suffix; the extractor's recreated file does the same.
6. **The stub is untrusted input.** The existing DTD/entity rejection stays;
   base64 fields are decoded with validation and size caps; a malformed stub is
   a per-file failure, never a crash or a partial replacement.
7. **Partial restoration is impossible.** The extractor builds the recreated
   file at a temporary path in the destination folder, writes its tags there,
   and only then atomically renames it into place. On failure the temporary file
   is removed and the stub is retained.

### 2.3 The ASX stub format, version 1

Writer output (the exact element order is fixed by the writer and asserted by a
test):

```xml
<?xml version="1.0" encoding="utf-8"?>
<ASX Version="3.0">
  <ENTRY>
    <TITLE>Artist - Title</TITLE>
    <AUTHOR>Artist</AUTHOR>
    <COPYRIGHT>2026 Label</COPYRIGHT>
    <ABSTRACT>Suite-generated stub; metadata for the file this replaced.</ABSTRACT>
    <REF HREF="../../Masters/song.flac"/>
    <PARAM NAME="AudioSuite:stub-version" VALUE="1"/>
    <PARAM NAME="AudioSuite:original-name" VALUE="song_128.mp3"/>
    <PARAM NAME="AudioSuite:keeper-name" VALUE="song.flac"/>
    <PARAM NAME="AudioSuite:field:title" VALUE="Title"/>
    <PARAM NAME="AudioSuite:field:artist" VALUE="Artist"/>
    <PARAM NAME="AudioSuite:field:album" VALUE="Album"/>
    <PARAM NAME="AudioSuite:field:album_artist" VALUE=""/>
    <PARAM NAME="AudioSuite:field:track" VALUE="3"/>
    <PARAM NAME="AudioSuite:field:disc" VALUE="1"/>
    <PARAM NAME="AudioSuite:field:year" VALUE="2026"/>
    <PARAM NAME="AudioSuite:field:genre" VALUE="Jazz"/>
    <PARAM NAME="AudioSuite:field:comment" VALUE=""/>
    <PARAM NAME="AudioSuite:mbid:MUSICBRAINZ_TRACKID" VALUE="…"/>
    <PARAM NAME="AudioSuite:isrc" VALUE="GBAYE…"/>
    <PARAM NAME="AudioSuite:isrc" VALUE="GBAYE…"/>
    <PARAM NAME="AudioSuite:lyrics:plain-base64" VALUE="…"/>
    <PARAM NAME="AudioSuite:lyrics:synced-base64" VALUE="…"/>
    <PARAM NAME="AudioSuite:artwork:mime" VALUE="image/jpeg"/>
    <PARAM NAME="AudioSuite:artwork:base64" VALUE="…"/>
  </ENTRY>
</ASX>
```

Rules:

- **`<REF>` is relative when the keeper is on the same volume** (`os.path.relpath`,
  written with `/` separators), otherwise absolute. It is resolved against the
  stub's own folder, which is where a user will run the extractor.
- **The conventional uppercase element and attribute names are written**
  (`<ASX>`, `<ENTRY>`, `<REF HREF>`, `<PARAM NAME VALUE>`), because that is what
  Windows Media-era writers produce and what ASX-aware players expect. The
  reader matches names case-insensitively, which is also the confirmed defect in
  §1.
- **`AudioSuite:stub-version` is the discriminator.** A playlist without it is a
  plain ASX and is handled by today's code path, unchanged; an unknown version
  is refused with a typed error rather than guessed.
- **The nine `field:` params are always present.** An empty `VALUE` means the
  source file had no value, and restoration clears that field on the copy. A
  value containing a line break or tab is written as
  `AudioSuite:field:<name>:base64` instead, because XML attribute-value
  normalisation turns literal newlines into spaces; the reader accepts either
  form.
- **Multi-line or binary values are base64** (`lyrics:*`, `artwork:*`) for the
  same reason.
- **`<TITLE>`/`<AUTHOR>`/`<COPYRIGHT>`/`<ABSTRACT>` are display copies** for
  players and humans. They are not read back for restoration; the `PARAM`
  payload is authoritative.
- **Artwork is carried only when it is JPEG**, the only form the shared
  `embed_artwork` writes. When the source art is PNG, the stub records
  `AudioSuite:artwork:omitted` with a reason and the guide says the cover is not
  recreated. This is a v1 boundary, not a silent drop.

### 2.4 What "recreate the original file" means

The duplicate's audio was a different encoding of the same recording (a 128
kbit/s MP3 beside a FLAC master). The keeper's audio is the one worth keeping,
so restoration produces:

- **content:** a copy of the keeper's bytes (`copy2`), verified by the SHA-256
  of its *decoded audio* (a tag write necessarily changes the container bytes,
  so a whole-file hash can never match the keeper);
- **name:** `<stub stem>.<keeper extension>` in the stub's folder — the
  duplicate's stem, the keeper's extension, so a FLAC never carries an `.mp3`
  name;
- **tags:** the duplicate's tag snapshot, applied after deleting the copy's
  inherited keeper tags, so absent fields stay absent and ReplayGain, MBIDs,
  ISRCs, lyrics or art the duplicate did not have are not inherited from the
  keeper;
- **cleanup:** the stub moves to the Trash only after the final file exists and
  its tags have been written.

The recreated file is therefore **not byte-identical to the removed duplicate**
— it is the better copy with the duplicate's name and metadata. The guide must
state that in one sentence, and the plan's tests assert content, name and tags
separately rather than pretending one hash proves all three.

### 2.5 What is deliberately not carried, and why

| Not carried | Reason |
|---|---|
| ReplayGain values | They describe the loudness of the removed encoding; copying them onto the keeper's different audio would be a false measurement. |
| Non-canonical TXXX/custom frames | They are format-specific and often tool noise; the canonical nine fields plus MBIDs/ISRC/lyrics/art are the suite's readable, writable surface. |
| Chapters, cue sheets, embedded cues | No suite reader/writer exists for them; a promise here would be untested. |
| Bitrate, sample rate, duration, size | Recorded for the report only; restoration takes the keeper's real properties. |
| File timestamps | The copy gets `copy2`'s source timestamps; the duplicate's timestamps are not part of its identity. |
| PNG cover art (v1) | The shared artwork writer supports JPEG; see §2.3. |

### 2.6 Surfaces

| Surface | Change |
|---|---|
| `ScanSettings` | `disposition: str = "quarantine"`, validated in `__post_init__`. |
| CLI `duplicates` | New `--on-duplicate [quarantine\|delete\|asx-stub]`, default `quarantine`. `--quarantine-dir` remains, used only by quarantine mode. Text summary and JSON gain `deleted`, `stubbed`, `disposition`. |
| GUI Setup | New **Duplicate handling** combobox with the three options. The quarantine entry/Browse are enabled only for quarantine; the explanatory caption and the live-run confirmation follow the same update function, so presets and driver argv cannot leave the window disagreeing with the run. |
| Presets | Store the disposition value; an old preset without it loads as quarantine. |
| Driver card | New disposition combobox; the quarantine row keeps its current meaning. `AppState.duplicate_disposition` (default `quarantine`). |
| ASX Extractor card | New **Include subfolders** checkbox; `AppState.asx_recursive` (default `False`). |
| Driver argv | `arg_builder` always emits `--on-duplicate <value>` and, for the extractor, the checkbox's `--recursive/--no-recursive`; each tool's `utils/cli_args.py` parses and validates it. A driven run therefore does exactly what the card shows. |
| ASX Extractor CLI | `--recursive/--no-recursive` (default off, preserving today's top-level behaviour). |
| ASX Extractor GUI | **Include subfolders** checkbox, same default. |
| Report tokens | `[DELETED] <path> -> Recycle Bin`, `[STUBBED] <path> -> <stub> (keeper: <keeper>)`, plus the existing tokens. |
| Completion payload | Adds `deleted` and `stubbed`; `quarantined` stays (0 for the other modes). |

---

## 3. How acceptance is measured

### 3.1 Shared rules

- Every acceptance is checked **on disk**, not on a returned counter: file
  existence, SHA-256 of the keeper, the bytes and tags read back with
  `mutagen` from the written file, and the XML parsed from the stub.
- The Trash is injected at one seam (`duplicate_finder/core/trash.py`,
  `move_to_trash(path) -> None`) so a test can assert the exact paths passed
  without sending a developer's fixture to the real Recycle Bin. One test
  monkeypatches the backend to raise and asserts the audio survives.
- The existing fixture library (7 files, 1 group, 3 duplicates, keeper
  `song.flac`) is the base. Tag values are written to the duplicate copies
  **before** the run with `mutagen`, so the expected snapshot comes from the
  fixture, not from the code under test.

### 3.2 Delete

| Check | Bar |
|---|---|
| Files | The three duplicates are absent from the library; the four non-duplicates and the keeper remain. |
| Trash seam | Called exactly three times, once per duplicate path, and never with the keeper. |
| Keeper | SHA-256 unchanged. |
| Quarantine | The quarantine folder is not created. |
| Report | Three `[DELETED]` lines; `deleted=3`, `quarantined=0`, `duplicates=3`, `errors=0`. |
| Dry run | No Trash call, no file change, `deleted=0`, report says "would delete". |
| Backend unavailable | Run reports a fatal error before fingerprinting; library is byte-identical. |

### 3.3 Stub creation

| Check | Bar |
|---|---|
| Stub files | Three `.asx` files exist beside the removed duplicates; each parses as XML and carries `AudioSuite:stub-version = 1`. |
| Reference | Each `<ref>` resolves to the keeper from the stub's folder. |
| Tags | The nine `field:` params equal the values read independently from the source duplicate before the run; MBIDs/ISRC/lyrics/art appear when the source had them. |
| Removal | The duplicate's audio path no longer exists; the Trash seam received it; the keeper is untouched. |
| Collision | A pre-existing `<stem>.asx` yields `<stem> (2).asx` and neither file is overwritten. |
| Ordering | With stub writing forced to fail, the duplicate still exists and the Trash seam was not called. |
| Dry run | No stub, no Trash call, no change. |
| Repeat scan | A second scan finds no duplicates (stubs are not audio and are ignored by `discover_files`). |

### 3.4 Stub restoration (ASX Extractor)

| Check | Bar |
|---|---|
| Content | The recreated file's decoded audio SHA-256 equals the keeper's, and the tag snapshot is present. |
| Name | `<stub stem>.<keeper extension>` in the stub's folder; collision gains a suffix. |
| Tags | `mutagen` reads back the nine fields equal to the stub's source values; absent fields are absent, not inherited from the keeper; MBIDs/ISRC/lyrics/art match; ReplayGain is not invented. |
| Atomicity | With the tag writer forced to fail, no final file exists, the temporary file is gone, and the stub is still present. |
| Cleanup | The stub is moved to the Trash only after the final file exists; a Trash failure leaves the final file and the stub and is counted as an error. |
| Missing keeper | Reported `FILE NOT FOUND`; the stub remains; no copy is created. |
| Plain ASX | Existing playlists copy/remove exactly as before, with no tag write. |
| Recursive | A stub in a sub-folder is found only when `--recursive`/the checkbox is on; the default result is unchanged. |
| Uppercase ASX | A playlist using `<REF HREF="…">` now resolves (regression test for the §1 defect). |

---

## 4. Items

Status legend: `[ ]` pending · `[~]` in progress · `[x]` done.

### DD-1 — Shared ASX stub schema and tag snapshot (M)

**Status:** `[x]` complete. **Work order 1.**

*Change.* New `audio_suite_shared/asx_stub.py`, with no Tk and no tool imports:

- constants for the schema version, the `AudioSuite:` prefix, the nine field
  names, and the size caps;
- `StubMetadata` (frozen dataclass) holding the original/keeper names, the nine
  fields, MBIDs, ISRCs, lyrics and optional artwork;
- `build_stub(metadata) -> bytes` (deterministic ElementTree serialisation) and
  `write_stub(path, metadata) -> None` (temp file + `os.replace`, UTF-8,
  newline-stable);
- `read_stub(path) -> StubMetadata | None` — `None` for a plain ASX, a typed
  failure for a malformed/oversized stub; keeps the existing DTD/entity
  rejection;
- `snapshot_tags(path) -> StubMetadata` reading through
  `TagHandlerFactory` (`read_editable_tags`, `read_musicbrainz_ids`,
  `read_isrcs`, `read_lyrics_tags`, `extract_artwork`);
- `apply_tags(path, metadata) -> None` — delete the copy's tags, write the nine
  fields (clearing absent ones), MBIDs, ISRCs, lyrics, and JPEG artwork;
- `derive_restore_name(stub_path, keeper_path) -> Path` (§2.4).

*Why shared.* Both tools need the same schema and neither may import the other;
one implementation is what keeps the writer and reader from drifting.

*Acceptance.* Round-trip `StubMetadata` through bytes and back; the serialised
XML has the fixed element order; an empty field survives as empty; base64
lyrics/art survive newlines and binary; a field with a line break survives in
its `:base64` form; a DTD-bearing, oversized, truncated, non-base64 or
unknown-version stub is refused; `snapshot_tags`/`apply_tags` are exercised on
real MP3 and FLAC files (write, read back with `mutagen`, compare to the
source).

*Files:* `audio_suite_shared/asx_stub.py` (new),
`audio_suite_shared/tests/test_asx_stub.py` (new).

*Risk.* The schema is the contract for a file users may keep for years; a
field naming mistake is expensive to undo. Pin the writer output in one literal
XML fixture and read it back, rather than only round-tripping objects.

### DD-2 — Disposition model, Trash seam and the two new outcomes (M)

**Status:** `[x]` complete. **Work order 2.**

*Change.* Add `duplicate_finder/core/trash.py` with `move_to_trash(path)` and an
`available()` probe around `send2trash`; never fall back to `unlink`. Add the
disposition enum/default to `ScanSettings` and dispatch in
`run_duplicate_scan`: quarantine keeps `quarantine_file`; delete calls the Trash
seam; stub calls `snapshot_tags`, `write_stub` beside the duplicate, re-reads
and resolves the stub, then calls the Trash seam. Add `deleted` and `stubbed`
to `ScanOutcome`, the report lines, and the completion payload. A run that
needs the Trash backend and cannot import it reports one fatal `on_error`
before discovery.

*Acceptance.* §3.2 and §3.3 in full, including failure ordering and the
byte-identical keeper.

*Files:* `duplicate_finder/core/file_processor.py`, `duplicate_finder/core/models.py`,
`duplicate_finder/core/disposition.py` (new: the enum, labels and validator),
`duplicate_finder/core/trash.py` (new), `duplicate_finder/__init__.py` (the
"nothing is deleted" statement now needs its three dispositions),
`duplicate_finder/tests/test_file_processor.py`,
`duplicate_finder/tests/test_disposition.py` (new),
`duplicate_finder/tests/test_trash.py` (new), `pyproject.toml` + `uv.lock` (the
`send2trash` dependency).

*Risk.* This is the item that can lose a file. The Trash-only rule, the
stub-before-Trash order and the hash assertions are the controls; none may be
relaxed to make a test pass.

### DD-3 — CLI, GUI, presets, driver and payload wiring (M)

**Status:** `[x]` complete. **Work order 3.**

*Change.* Wire the disposition through every entry point:

- `cli.py`: `--on-duplicate` with `click.Choice`, text/JSON summary additions;
- `ui/setup_tab.py` + `ui/app.py`: the combobox, one `_set_disposition(value)`
  that both the widget event and every pre-fill route call, dependent-control
  enablement, the caption, and the live-run confirmation (interactive runs
  only, so a driven Auto Start cannot block on a dialog);
- `_collect_settings`/`_apply_preset` and the completion rows (`deleted`,
  `stubbed`, and the action verb);
- `master_driver/state/app_state.py` (`duplicate_disposition`),
  `master_driver/ui/cards/duplicate_finder_card.py` (combobox),
  `master_driver/runner/arg_builder.py` (always emit the option),
  `duplicate_finder/utils/cli_args.py` (parse/validate it);
- update the frozen locks: `master_driver/tests/test_app_state.py`,
  `master_driver/tests/test_runner.py`, `master_driver/tests/test_ui_cards.py`,
  `tests/test_completion_seam.py`, `tests/test_completion_payload_published.py`,
  `tests/test_cli_usage_errors.py`, and re-record
  `tests/data/cli_payloads.json` plus `audio_suite_shared/cli_schema.json` with
  `python -m tests.cli_schema_conformance --record`.

*Acceptance.* Every pre-fill route (driver argv, preset restore, combobox edit)
reaches the same narrowed widget state, asserted in `TestDispositionPrefill`;
an invalid `--on-duplicate` is Click's exit 2 with the value named; the driver's
argv and the window's controls agree; the completion handler's required-field
set in `test_completion_seam.py` matches the publisher's payload.

*Files:* as listed above, plus `duplicate_finder/tests/test_cli.py`,
`duplicate_finder/tests/test_cli_args.py`, `duplicate_finder/tests/test_app.py`.

*Risk.* The GUI pre-fill class in `AGENTS.md` is exactly this shape: a value
written in Python bypasses the widget event that would have updated dependent
controls. One update function, called by every route, plus a test per route.

### DD-4 — ASX Extractor restore and recursive discovery (L)

**Status:** `[x]` complete. **Work order 4.**

*Change.*

- `asx_parser.py`: match element and attribute names case-insensitively (fixes
  the §1 defect); require the resolved href to be an existing **regular file**
  with a supported audio extension; return the parsed `StubMetadata` when the
  playlist carries `AudioSuite:stub-version`.
- `file_ops.py`: `recreate_from_stub(stub, destination_dir)` — copy the keeper
  to a temporary path with the keeper's extension, apply the snapshot, atomically
  replace into the derived name, record the copy in the undo journal, and only
  then trash the stub. Plain playlists keep today's copy/remove path.
- `cli.py` and `app.py`: `--recursive` / **Include subfolders**; stubs are
  reported separately (`recreated`) in the log and summary; a stub failure names
  why and leaves both files.
- `_run_tool` payload gains `recreated`; the CLI JSON and the text summary carry
  it.
- driver wiring: `asx_extractor/utils/cli_args.py` parses `--recursive`;
  `master_driver/state/app_state.py` gains `asx_recursive` (default `False`),
  `asx_card.py` gains the checkbox, and `arg_builder.py` emits the option from
  it, so a driven extraction matches the card.

*Acceptance.* §3.4 in full, including the atomicity, missing-keeper, plain-ASX
and uppercase-ASX cases; the driver passes the checkbox value and the window
opens showing it; an unknown `stub-version` is refused with the reason in the
log.

*Files:* `asx_extractor/core/asx_parser.py`, `asx_extractor/core/file_ops.py`,
`asx_extractor/cli.py`, `asx_extractor/app.py`, `asx_extractor/ui/setup_tab.py`,
`asx_extractor/utils/cli_args.py`, `master_driver/state/app_state.py`,
`master_driver/ui/cards/asx_card.py`, `master_driver/runner/arg_builder.py`,
`asx_extractor/tests/test_asx_core.py`, `test_cli.py`, `test_cli_args.py`,
`test_app.py`, `test_setup_tab.py`, `master_driver/tests/test_app_state.py`,
`test_runner.py`, `test_ui_cards.py`.

*Risk.* The extractor has never written tags, and it is the only recovery path
for a stubbed library. The temporary-file + atomic-rename rule and the
stub-retained-on-failure rule are the controls; a test must force both failure
points.

### DD-5 — Guides, changelog and the release cut (S)

**Status:** `[x]` complete. **Work order 5, after every code item is green.**

*Change.*

- Rewrite the affected sections of `Duplicate_Finder_User_Guide.md` (the three
  dispositions, the Recycle Bin, the stub's meaning, what is and is not
  restored, the dry-run-first workflow, the confirmation) and
  `ASX_Playlist_Extractor_User_Guide.md` (stub detection, restore naming and
  tags, recursive option, failure semantics).
- Sweep `documentation/` for the old "nothing is ever deleted" claim and the
  old option lists: `git grep -l -i "quarantin\|asx-extract\|nothing is ever
  deleted" -- documentation/`
- Update `CLI_Commands_Reference.md` (the new options and payload keys) and
  re-render every touched guide and the reference:
  `python utilities/build_user_guides.py duplicate_finder`,
  `... asx_extractor`, `... reference`, then `--check`.
- Add the 2.4.0 user-facing entry to `CHANGELOG.md`; add the test/lock work to
  `TECHNICAL_CHANGELOG.md` only if it is not user-observable. Move the
  release-note window (`tests/test_release_notes.py`) to 2.4.0 at the cut, and
  ensure every new code file carries `Changed in 2.4.0`.
- Update the README/docs tool descriptions only where they claim the old
  behaviour; the tool count does not change.

*Acceptance.* `python utilities/build_user_guides.py --check` reports every
artefact current; `tests/test_user_guide_hygiene.py`,
`tests/test_cli_reference_hygiene.py`, `tests/test_docs_build.py` and
`tests/test_guide_claims.py` pass; the guides name every new option and status
token the code emits.

*Risk.* A stale "nothing is deleted" sentence is now false in a way that can
lose a user's file. The sweep is a directory walk, not a list of remembered
files.

---

## 5. Work order and release map

| Order | Item | Depends on | Release |
|---|---|---|---|
| 1 | DD-1 shared stub schema | — | 2.4.0 |
| 2 | DD-2 disposition + Trash + stub writing | DD-1 | 2.4.0 |
| 3 | DD-3 CLI/GUI/driver/payload | DD-2 | 2.4.0 |
| 4 | DD-4 extractor restore | DD-1, DD-2 | 2.4.0 |
| 5 | DD-5 guides, changelog, cut | DD-3, DD-4 | 2.4.0 |

DD-1 is first because it is the contract both tools share; DD-4 follows DD-2
because its fixture is a real stub produced by the writer, not a hand-written
one. Nothing ships between DD-2 and DD-4: the capability is one release.

---

## 6. Decision log

| D | Decision | Status | Rationale / evidence |
|---|---|---|---|
| D1 | **Quarantine stays the default; delete and stub are opt-in per run.** | PROPOSED | The tool's current guarantee is "nothing is deleted"; changing the default would silently change every existing preset and driven card. An opt-in keeps 2.3.1 behaviour for anyone who does not touch the new control. |
| D2 | **One disposition enum (`quarantine`, `delete`, `asx-stub`) in `ScanSettings`, surfaced as `--on-duplicate` and one GUI combobox.** | PROPOSED | Three mutually exclusive outcomes should not be three booleans; one value is validated once and cannot be "delete and stub" at the same time. `asx-stub` matches the file extension and reads as one token in a CLI. |
| D3 | **Delete uses the OS Trash through `send2trash`, added as a runtime dependency; there is no permanent-delete fallback for audio.** | PROPOSED | A permanent delete is unrecoverable and would make the tool's safety story false. `send2trash` is the cross-platform Recycle Bin API, is already the extractor's preferred path, and adding it also removes that optional-import gap. If it cannot be imported at runtime, the run refuses before touching anything. |
| D4 | **Stub first, verify, then Trash.** | PROPOSED | The failure this prevents is the one that cannot be undone: audio removed with no usable pointer. The stub is re-parsed and its `<ref>` resolved before the audio is moved. |
| D5 | **The stub sits beside the duplicate, named `<stem>.asx`, with a numeric suffix on collision; `<ref>` is relative when possible.** | PROPOSED | The stub replaces the file where the user expects it, so a folder view still shows one entry per recording. A relative href keeps a library portable within a volume; an absolute href is the only correct answer across volumes. |
| D6 | **The format is versioned ASX 3.0 with a fixed writer order, `AudioSuite:` params, conventional uppercase elements and a case-insensitive reader.** | PROPOSED | ASX is the user's chosen interchange format and already playable. A version marker lets the extractor distinguish a suite stub from a plain playlist without guessing, and lets v2 change the schema without breaking v1. The case-insensitive reader also fixes the confirmed `<REF>` defect (D13). |
| D7 | **The nine canonical fields are always written; MBIDs, ISRCs, lyrics and JPEG artwork are carried when present; everything else is out of scope.** | PROPOSED | This is the suite's cross-format readable/writable surface, so the promise is testable on every supported container. Writing all nine, including empty ones, is what makes restoration clear rather than inherit the keeper's values. §2.5 records the exclusions with reasons. |
| D8 | **ReplayGain is not carried or restored.** | PROPOSED | Its values measure the removed encoding's loudness; applying them to the keeper's different audio would fabricate a measurement — the class `AGENTS.md` treats as release-blocking. |
| D9 | **The recreated file takes the duplicate's stem and the keeper's extension.** | PROPOSED | A FLAC payload named `.mp3` is a lie that breaks players and downstream tools. The original name is stored for the report and the guide explains the rename. |
| D10 | **Plain ASX playlists keep today's path; only a versioned suite stub is restored with tags.** | PROPOSED | Existing users' playlists must not start receiving tag writes or different names. The version marker is the switch, and a regression test pins the plain path. |
| D11 | **Recursive discovery is an explicit option, default off.** | PROPOSED | Stubs live in album sub-folders, so a library-wide restore needs recursion; changing the default would surprise a user who selected one folder. The duplicate guide tells the user to tick it. |
| D12 | **Trash actions are not recorded in the suite's undo journal; recovery is the Recycle Bin (delete/stub) and the extractor (stub).** | PROPOSED | The journal's model is move/copy and cannot represent a Trash operation; faking a "move" would make Undo restore a file the user deliberately deleted and leave the stub behind. The guides state the recovery path instead of promising an undo that does not exist. |
| D13 | **The uppercase-`<REF>` defect is fixed in DD-4 with a regression test.** | PROPOSED | Confirmed at `a9afe78`: a well-formed `<ASX><ENTRY><REF HREF="…"/></ENTRY></ASX>` returns `NO REF LINK IN ASX`. ASX files in the wild, including Windows Media's own, commonly use uppercase element names, so the reader cannot rely on the writer's spelling. Fixed in the change that touches the parser, per *Defects and failing checks*. |
| D14 | **One minor, 2.4.0, ships the writer and the restorer together.** | PROPOSED | A 2.4.0 that writes stubs no installed extractor can fully restore would publish a promise the suite cannot keep. Both tools change, but one capability is being added; a single minor is the honest cut. The alternative (2.4.0 writer, 2.5.0 reader) is rejected for that reason, not for effort. |
| D15 | **No new tool, manifest entry, CLI command or plugin point.** | PROPOSED | Both changes extend existing tools and existing entry points. The eleven-step registration checklist therefore does not apply; the locks that do move are the completion seam, the payload publisher, the CLI schema corpus and the app-state/runner expectations. |
| D16 | **Artwork is carried only as JPEG in v1; PNG art is recorded as omitted, not silently dropped.** | PROPOSED | `embed_artwork` accepts JPEG only across the handlers. Extending the shared artwork writer to PNG is a cross-format API change with its own test burden and is not needed to prove the stub contract; the omission is explicit in the stub and the guide. |
| D17 | **The driver always emits `--on-duplicate`, even when it is the default.** | PROPOSED | A driven run must do what the card shows. Emitting it always also exercises the parser on every driven run rather than only when the user changes the card, which is how a shifted argv is caught early. |
| D18 | **Interactive live runs using delete or stub ask for confirmation; driven Auto Start runs honour the card without a dialog.** | PROPOSED | A dialog in an unattended run blocks the driver until someone clicks it — the same failure class as a modal in a worker. The card selection is the user's explicit choice for a driven run; an interactive user gets one clear warning with the recovery path. |
| D19 | **Restoration writes through a temporary file and an atomic replace.** | PROPOSED | A crash mid-tag-write must not leave a half-tagged file under the final name with the stub already gone. The temp file is in the destination folder (same volume), removed on failure, and the stub is trashed only after the replace succeeds. |
| D20 | **The content check hashes decoded audio, not the whole file.** | ACCEPTED during implementation | Writing the duplicate's tags into the copy changes the container bytes, so the planned whole-file SHA-256 equality is unachievable while restoring tags. The invariant that matters is that the audio samples are unchanged; `recreate_from_stub` decodes both files and compares the PCM digest. The temp file also keeps the real audio extension, because the tag handler is chosen by suffix. |
| D21 | **A missing Recycle Bin backend is installed automatically into `sys.executable`, never delegated to the user.** | ACCEPTED during review | The launcher re-executes into `.venv`, so a copy in the system Python is invisible to the run and a pip instruction would install into the wrong interpreter. `duplicate_finder.core.trash.ensure_available()` reuses `optional_deps.ensure` before the first file is touched, re-imports the package, and refuses with a plain-language message only when the install itself fails. |

### 6.1 Decisions for the reviewer to confirm before DD-2

These are the choices that change what a user can lose; the rest can be
adjusted during implementation.

1. **D3** — add `send2trash` as a runtime dependency (recommended) rather than
   implementing platform-specific Trash calls or allowing permanent deletion.
2. **D14** — ship writer and restorer in one 2.4.0 minor (recommended) rather
   than a 2.4.0/2.5.0 split.
3. **D7/D8** — the tag inventory: nine fields + MBIDs/ISRC/lyrics/JPEG art, with
   ReplayGain and custom frames excluded. If the reviewer wants ReplayGain
   retained for reference, it can be stored in the stub as informational data
   but must not be written onto the restored audio.
4. **D16** — JPEG-only artwork in v1, or approve extending the shared artwork
   writer to PNG as part of DD-1.

---

## 7. Verification plan

Run in this order after the last code change; a per-package run is not proof.

1. `python -m compileall -q -f .`
2. `ruff check .` and `ruff format --check .`
3. `python -m mypy .` (bare, never per-file)
4. `PYTHONUTF8=1 python -X utf8 -m bandit -r . -x ./.venv -c pyproject.toml`
   — expect 0 High / 0 Medium.
5. `pytest` (bare, so `testpaths` includes every package suite).
6. `python -m tests.cli_schema_conformance --record` after the CLI surface is
   final, then re-run the CLI contract tests; inspect the diff for incidental
   churn and restore anything unrelated.
7. `python utilities/build_user_guides.py --check` after every guide render.
8. **End-to-end on a temporary copy of the fixture library**, in one script:
   tag the duplicates, run delete, assert the library and the Trash seam; copy
   the library again, run stub, parse each stub, run the extractor, decode the
   recreated file and compare SHA-256 to the keeper and tags with `mutagen`.
   Delete the script afterwards; evidence belongs in this plan's record, not in
   the tree.

The focused tests that must be green before the full suite: `test_asx_stub.py`,
`test_file_processor.py`, `test_disposition.py`, `test_trash.py`,
`test_cli.py`, `test_app.py`, `test_asx_core.py`, the ASX extractor CLI/app
suite, and the five lock modules named in DD-3.

---

## 8. Out of scope / recorded limitations

- **No undo-journal entry for Trash or stub actions** (D12). The guide says so.
- **No ReplayGain/custom-frame/chapter carry** (D7, D8). The stub records only
  the documented surface.
- **No PNG artwork in v1** (D16).
- **A stub breaks if the keeper is moved or deleted.** The extractor reports
  `FILE NOT FOUND`; the same-stem fallback can find a sibling encoding. The
  guide warns that the keeper is the stub's only content source.
- **No cross-volume relative href.** `os.path.relpath` raises across Windows
  drives, so the writer emits an absolute path there; moving the library to
  another machine then requires editing the stub. Recorded, not solved.
- **No change to detection, clustering, keeper selection, cache, or the
  quarantine default.** A separate plan would own any of those.
- **No new plugin extension point** for dispositions. The enum is first-party
  only.

---

## 9. Risks and their controls

| Risk | Control |
|---|---|
| A wrong keeper choice plus delete removes the only copy. | Dry run reports the keeper and every distance; delete is opt-in, confirmed interactively, and goes to the Recycle Bin, not oblivion. |
| A stub is written but the audio is trashed before the stub is usable. | Stub is written to a temp file, atomically replaced, re-parsed and resolved, and only then is the audio trashed (D4). |
| A tag field is lost because the snapshot omitted it or restoration inherited the keeper's value. | All nine fields are always written; restoration deletes the copy's tags first; tests compare to the source duplicate's independently read tags. |
| The extractor writes tags onto the wrong file or leaves a half-restored one. | Temp file + atomic replace, stub retained on failure, SHA-256 content check, and a forced tag-write failure test (D19). |
| `send2trash` is missing in a frozen build. | Run-start availability check with a clear message; no permanent fallback for audio; declared dependency and a packaging check. |
| Existing presets/driven runs silently change behaviour. | Default stays quarantine; old presets without the key load as quarantine; the driver always emits the option so the card and run agree. |
| Documentation still says "nothing is ever deleted". | DD-5's directory-wide grep and the guide-claims lock; the guides are read against the final code, not the plan. |
| The ASX schema is treated as a stable API but drifts. | Version marker, fixed writer order, literal XML fixture, and a reader that rejects an unknown version rather than guessing. |

---

## 10. Change history

| Date | Change |
|---|---|
| 2026-11-02 | Plan created from the maintainer's brief. No code, test, guide or configuration changed. The uppercase-`<REF>` defect was reproduced at `a9afe78` and recorded as D13 for DD-4. |
| 2026-11-02 | Implemented DD-1 to DD-5. D20 records the decoded-audio correction found by the first restore test; `send2trash` 2.1.0 joins the runtime dependencies. |
| 2026-11-02 | Review fix: a stub run under `.venv` reported `send2trash` missing even though the system Python had it. D21 adds the automatic install into the running interpreter and removes the pip instruction from the user-facing error. |

---

## 11. Close-out

**Closed:** 2026-11-02, version 2.4.0.

- Full gate: `ruff check .`, `ruff format --check .`, `mypy .` (556 files),
  `compileall`, and `bandit` (0 High / 0 Medium, 46 Low) are clean.
- Tests: bare `pytest` passed 11,197 with 3 platform/display skips and 90.97%
  coverage; the focused duplicate-finder and release/guide locks passed 264.
- Guides: Duplicate Finder, ASX Extractor and the CLI reference were updated,
  rendered and checked (`build_user_guides.py --check`, 29 current); Sphinx
  docs tests passed 16.
- Review fix: D21 records the automatic `send2trash` install into the running
  `.venv`, which removed the pip instruction from the user-facing error.
- Release cut: 2.4.0, with both change histories and the generated guides in
  the same change set; the close-out commit is pushed to `origin/main`.
