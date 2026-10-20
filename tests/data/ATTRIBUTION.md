# Audio test fixtures — provenance and attribution

The audio files in this directory are small binary containers used as test
fixtures for the Sprint 1 format support (`.wv`, `.ape`, `.mpc`, `.spx`,
`.dsf`). They were fetched from the **mutagen** project's test data:

- Source: <https://github.com/quodlibet/mutagen> (`tests/data/`)
- License: **GPL-2.0-or-later**

| File | Format |
|------|--------|
| `silence-44-s.wv` | WavPack |
| `mac-396.ape`, `mac-399.ape`, `mac-390-hdr.ape` | Monkey's Audio |
| `click.mpc` | Musepack |
| `empty.spx` | Ogg Speex |
| `with-id3.dsf`, `without-id3.dsf` | DSD Stream File |

`mac-390-hdr.ape` is a header-only negative fixture (no decodable audio).

AudioSuite-Pro is licensed under GPL-3.0-or-later. GPL-2.0-or-later is
compatible with, and re-licensable under, GPL-3.0 (the "or later" option in
the source license permits the upgrade), so these fixtures may be
redistributed here.

These files are declared as an exception format in
`tests/test_release_notes.py` (no comment syntax to carry a change note).

## BPM regression corpus

`tests/data/bpm_corpus/` holds seven CC0 excerpts of real recordings used to
calibrate and regress the BPM onset-periodicity gate. Their provenance,
licences, trim offsets and measured calibration live in
[`bpm_corpus/ATTRIBUTION.md`](bpm_corpus/ATTRIBUTION.md).
