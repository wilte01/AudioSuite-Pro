# Third-Party Notices — AudioSuite-Pro

AudioSuite-Pro is distributed under the **GNU General Public License,
version 3.0 or later** (see [`LICENSE`](LICENSE)).

This file records every third-party component the suite depends on, is built
with, or ships, the licence each is under, and what that means for
redistribution. It exists so the position is stated once, plainly, instead of
being discovered by a buyer's counsel.

**Not legal advice.** It summarises licences; it is not a legal opinion. Obtain
advice before selling or shipping a binary.

---

## 1. The short version

| Category | Position |
|---|---|
| The suite itself | GPL-3.0-or-later |
| Runtime dependencies | 17 declared; **2 copyleft** (`mutagen` GPL-2.0-or-later, `pedalboard` GPL-3.0), 1 file-level copyleft (`certifi`, MPL-2.0), 14 permissive |
| Optional extras | `cd-ripping` adds LGPL-3.0-or-later and BSD-2-Clause; `ml` adds MIT, Apache-2.0 and PyTorch's BSD-3-Clause; `analysis` adds nothing new |
| Bundled binaries | `fpcalc.exe` (Chromaprint, **LGPL-2.1** as distributed) and `discid.dll` (libdiscid 0.6.5, **LGPL-2.1-or-later**) |
| Bundled runtime (installer) | CPython, PSF-2.0 |
| Not bundled | FFmpeg and FFprobe — an external requirement on `PATH` |
| Committed test fixtures | Provenance and licence recorded in `tests/data/ATTRIBUTION.md` and `tests/data/bpm_corpus/ATTRIBUTION.md` |

**The consequence:** because `pedalboard` is GPL-3.0 and `mutagen` is
GPL-2.0-or-later, any *distributed* build of this suite must be GPL-3-compatible.
A closed-source desktop product requires replacing both libraries first.

---

## 2. Why the suite is GPL-3.0-or-later

The licence was not chosen arbitrarily, and it cannot be changed by preference:

- **`pedalboard`** (Spotify's audio-effects library, used by the enhancement
  stage) is **GPL-3.0**. Linking it into a distributed binary makes that binary
  subject to GPL-3.
- **`mutagen`** (the tag read/write engine behind every tag tool) is
  **GPL-2.0-or-later**, which is compatible with GPL-3 through its "or later"
  clause.
- The heaviest *rejected* analysis engines were no better: Essentia is AGPL and
  madmom's models are CC BY-NC-SA, both of which constrain a permissive grant
  further than GPL does.

Versions are deliberately not repeated in this file: **[`uv.lock`](uv.lock) is
the authoritative dependency graph** (166 packages at this revision). Licences
below were read from each distribution's own metadata and `LICENSE` file.

---

## 3. Runtime dependencies

Declared in `[project] dependencies` in [`pyproject.toml`](pyproject.toml).

| Component | Licence | Role in the suite |
|---|---|---|
| `certifi` | MPL-2.0 | CA bundle for HTTPS. File-level copyleft only; used unmodified |
| `click` | BSD-3-Clause | The `audiosuite` command-line framework |
| `cryptography` | Apache-2.0 OR BSD-3-Clause | Encryption of stored API-key files |
| `librosa` | ISC | Analysis: BPM, key, mood features |
| `matplotlib` | PSF-based matplotlib licence | Charts in the Library Statistics dashboard |
| `mutagen` | **GPL-2.0-or-later** | Every tag read and write, across every container |
| `numpy` | BSD-3-Clause | Audio arrays and DSP numerics |
| `pedalboard` | **GPL-3.0** | Enhancement DSP (the Refinery's Enhance stage) |
| `Pillow` | MIT-CMU | Album-artwork resizing and normalisation |
| `pydub` | MIT | Audio segment handling |
| `scipy` | BSD-3-Clause | Signal processing primitives |
| `sounddevice` | MIT | Preview playback |
| `requests` | Apache-2.0 | HTTP for the optional metadata lookups |
| `send2trash` | BSD-3-Clause | Duplicate dispositions moved to the OS Recycle Bin |
| `urllib3` | MIT | HTTP transport under `requests` |
| `winaccent` | MIT | Windows accent-colour integration (Windows only) |
| `audioop-lts` | PSF-2.0 | `audioop` backport on Python 3.13 and later |

---

## 4. Optional extras

Installed only when asked for; a missing extra is reported, never fatal.

| Extra | Component | Licence | Role |
|---|---|---|---|
| `analysis` | `librosa` | ISC | Already a runtime dependency; the extra exists for install ergonomics |
| `cd-ripping` | `discid` (python-discid 1.3.0) | **LGPL-3.0-or-later** | MusicBrainz disc IDs (CD Ripper) |
| `cd-ripping` | `musicbrainzngs` | BSD-2-Clause | MusicBrainz metadata lookup |
| `ml` | `demucs` 4.1.0 | MIT | Stem Separator's separation engine |
| `ml` | `pyrnnoise` 0.4.5 | Apache-2.0 | ML Denoiser's RNNoise model |
| `ml` | `torch` (≥ 2.9, pinned by the extra) | BSD-3-Clause (PyTorch itself) | Demucs' tensor backend. The wheel bundles third-party components under their own terms (Apache-2.0, MIT, BSD, ISC, Zlib, BSL-1.0, LLVM exception); the wheel's own `LICENSE` files govern |

---

## 5. Bundled binaries (committed to this repository)

Two third-party executables are committed so the related tools work out of the
box. Both are unmodified upstream builds.

| File | Component | Version | Licence |
|---|---|---|---|
| `fpcalc.exe` (4,146,176 bytes) | Chromaprint `fpcalc` — the Audio Fingerprinter shells out to it | 1.6.1, built against FFmpeg Lavc 62.11.100 / Lavf 62.3.100 / SwR 6.1.100 | **LGPL-2.1** as distributed |
| `discid.dll` (40,456 bytes) | libdiscid, MetaBrainz Foundation — loaded by `ctypes` for the CD Ripper | 0.6.5 | **LGPL-2.1-or-later** |

**Chromaprint, precisely.** Chromaprint's own source is MIT, but its published
`LICENSE.md` states that because it includes parts of FFmpeg, "as a whole,
Chromaprint should be therefore considered to be licensed under the LGPL 2.1",
and that a binary distributor must also consider the licence of the external
FFT library it was compiled against. The committed build reports FFmpeg
`Lavc 62.11.100`, so LGPL-2.1 obligations apply to redistributing it.

### Provenance — verified 2026-11-11

Both files are **byte-identical** to their official upstream release assets, so
this is a measured match rather than a recollection. The full record, including
the digests needed to re-verify it, is
[`packaging/licenses/PROVENANCE.md`](packaging/licenses/PROVENANCE.md) — and that
record ships inside the installer in its `licenses` folder.

| | `fpcalc.exe` | `discid.dll` |
|---|---|---|
| Upstream release | acoustid/chromaprint **v1.6.1** | metabrainz/libdiscid **v0.6.5** |
| Archive | `chromaprint-fpcalc-1.6.1-windows-x86_64.zip` | `libdiscid-0.6.5-win.zip` |
| Archive SHA-256 | `735d6182b38e9f364b84ce6f4ccd682c75e2851de89735711d6b762d12b92a4e` | `a1198731d417a04b3d8499bcc10b6a8ddcab06476c855ebff0fb4134888b1be5` |
| File inside the archive | `chromaprint-fpcalc-1.6.1-windows-x86_64/fpcalc.exe` | `libdiscid-0.6.5-win/x64/discid.dll` |
| SHA-256 as committed | `00dcc56d911f2dea84737aa9dc8e2d118c9eb7a037d815d1ed001d8593e8fbee` | `e3bba899467d6e19f1b8e35e5cdffb803cbdc1fd4aff0729b9141dd6283d8dba` |
| Match | byte-identical (4,146,176 bytes) | byte-identical (40,456 bytes) |

The libdiscid row is additionally anchored in the project's own published
`SHA256SUMS`: the archive digest above is the line it lists. The committed
`discid.dll` is the **x64** build; the archive's 32-bit DLL is a different file
(36,504 bytes), which matters because the installer is `x64compatible`.

**The licence texts now travel with the binaries.** `build_installer.ps1` stages
`packaging/licenses/` into the payload as a `licenses` folder, and refuses a
build whose texts are missing, so a recipient of the installer gets them without
asking:

- `licenses/LGPL-2.1.md` — the GNU LGPL version 2.1 text, verbatim, extracted
  from the `COPYING` inside `libdiscid-0.6.5-win.zip`. It covers both binaries.
- `licenses/Chromaprint-LICENSE.md` — verbatim from the `v1.6.1` tag; it is the
  notice explaining why an MIT-licensed project's binary is LGPL-2.1.
- `licenses/PROVENANCE.md` — the record above, with re-verification commands.

Both texts are unmodified. A recorded digest and an edited licence text cannot
both be true, so neither file is ever touched in place.

---

## 6. The runtime bundled by the installer

`packaging/build_installer.ps1` stages a **CPython runtime** inside the
installer payload, so the installer redistributes CPython. Its licence
(**PSF-2.0**) must accompany a shipped build. CPython's licence text is not
duplicated here; take it from the runtime being staged.

---

## 7. External system requirements (not bundled by default)

**FFmpeg and FFprobe** must be on `PATH`; the suite shells out to both for
decoding, encoding, loudness measurement and silence detection.

- FFmpeg is licensed **LGPL-2.1-or-later**, or **GPL-2.0-or-later** when built
  with GPL-only components. Which applies depends entirely on the build.
- The suite does **not** bundle them by default — it is the user's install.
- `packaging/build_installer.ps1 -BundleFFmpeg <dir>` *can* bundle a local
  build. If that option is used for a distributed installer, FFmpeg's licence
  text and (for a GPL build) the corresponding-source offer must ship with it.

---

## 8. Test fixtures and sample audio

Committed audio fixtures come from upstream projects' own test corpora and from
CC0 sources. Their provenance and licence are recorded beside them:

- `tests/data/ATTRIBUTION.md`
- `tests/data/bpm_corpus/ATTRIBUTION.md`

They are not duplicated here, deliberately: one record per fixture set, kept
next to the files it describes.

---

## 9. What GPL-3.0-or-later requires of anyone distributing a build

1. **Offer the complete corresponding source** to every recipient of a binary.
2. **No additional restrictions** may be imposed on recipients' exercise of the
   rights the GPL grants.
3. **The work cannot be relicensed as proprietary** while `mutagen` and
   `pedalboard` remain linked in.
4. **Notices must be retained**, and modified versions must be marked as
   changed.
5. **Network use is not distribution.** GPL-3 has no network-use clause (unlike
   the AGPL), so *operating* the suite as a hosted service does not, by itself,
   trigger a source-disclosure obligation.

Point 5 is the commercial opening a buyer has; points 1–3 are the constraint
that shapes what they can sell.

---

## 10. How this file was produced, and how to re-verify it

Licences were read on **2026-11-11** from each installed distribution's
metadata and licence file, and the binaries' versions from the binaries
themselves. To reproduce or refresh:

```bash
uv sync --frozen --all-extras
python -m pip list --format=json        # the graph actually installed
python -m pip_audit                     # the security side of the same graph
./fpcalc.exe -version                   # the bundled fingerprint calculator
powershell -NoProfile -Command "(Get-Item discid.dll).VersionInfo"
git ls-files | grep -iE '\.(exe|dll)$'  # every committed binary
```

A licence *scan* (for example `pip-licenses` or an SBOM tool) should be run once
more against the exported lock at handover, and its output filed with this
document. This file is a statement of the position, not a substitute for that
scan.
