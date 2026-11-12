# Provenance — bundled binaries and their licence texts

This folder ships **inside the installer payload** at `licenses\`. It exists
because `fpcalc.exe` and `discid.dll` are third-party LGPL binaries committed to
this repository, and LGPL requires the licence text to travel with the binary it
covers.

Every claim below was verified by download and hash on **2026-11-11**. Each row
names the archive, the archive's SHA-256, and the SHA-256 of the file as
committed, so a buyer's reviewer can reproduce the comparison rather than trust
this page.

---

## 1. The two binaries

| | `fpcalc.exe` | `discid.dll` |
|---|---|---|
| Component | Chromaprint `fpcalc` (Audio Fingerprinter) | libdiscid (CD Ripper, loaded via `ctypes`) |
| Version | **1.6.1** | **0.6.5** |
| Bytes as committed | 4,146,176 | 40,456 |
| SHA-256 as committed | `00dcc56d911f2dea84737aa9dc8e2d118c9eb7a037d815d1ed001d8593e8fbee` | `e3bba899467d6e19f1b8e35e5cdffb803cbdc1fd4aff0729b9141dd6283d8dba` |
| Upstream release | acoustid/chromaprint `v1.6.1` | metabrainz/libdiscid `v0.6.5` |
| Archive | `chromaprint-fpcalc-1.6.1-windows-x86_64.zip` | `libdiscid-0.6.5-win.zip` |
| Archive URL | `https://github.com/acoustid/chromaprint/releases/download/v1.6.1/chromaprint-fpcalc-1.6.1-windows-x86_64.zip` | `https://github.com/metabrainz/libdiscid/releases/download/v0.6.5/libdiscid-0.6.5-win.zip` |
| Archive bytes | 1,816,911 | 127,032 |
| Archive SHA-256 | `735d6182b38e9f364b84ce6f4ccd682c75e2851de89735711d6b762d12b92a4e` | `a1198731d417a04b3d8499bcc10b6a8ddcab06476c855ebff0fb4134888b1be5` |
| Path inside the archive | `chromaprint-fpcalc-1.6.1-windows-x86_64/fpcalc.exe` | `libdiscid-0.6.5-win/x64/discid.dll` |
| Match | **byte-identical** — same length and SHA-256 | **byte-identical** — same length and SHA-256 |
| Licence | LGPL-2.1 as distributed (Chromaprint's own source is MIT) | LGPL-2.1-or-later |
| Licence texts shipped here | `Chromaprint-LICENSE.md` + `LGPL-2.1.md` | `LGPL-2.1.md` |

**Why the discid row says `x64`.** The archive carries both a `Win32\` and an
`x64\` build; their DLLs are 36,504 and 40,456 bytes and hash differently. The
committed file is the **64-bit** build, which is the one an
`ArchitecturesInstallIn64BitMode=x64compatible` installer should load.

**Why the archive hashes matter as much as the file hashes.** Chromaprint
publishes no checksum file, so the archive hash is recorded to pin *which*
release asset was used. libdiscid publishes `SHA256SUMS` alongside the release,
and the archive hash above matches the line it lists for `libdiscid-0.6.5-win.zip`
— so that row is anchored in the project's own published digest, not only in
our measurement.

---

## 2. The licence texts in this folder

| File | Bytes | SHA-256 | Where it came from |
|---|---|---|---|
| `Chromaprint-LICENSE.md` | 1,801 | `562cfe59627e0c4e8e3b066f3ff2e9736f83811ffe4c6c2c7796595aa7595ebd` | `https://raw.githubusercontent.com/acoustid/chromaprint/v1.6.1/LICENSE.md` — unmodified |
| `LGPL-2.1.md` | 26,940 | `319daefe38ebeead3df178e5937898a52d67c0c795f54f1c0bb10ac3b9cffb63` | Extracted from inside `libdiscid-0.6.5-win.zip` (`libdiscid-0.6.5-win/COPYING`) — unmodified |

Both are verbatim. Do not reflow or convert their line endings: the hashes above
are the record, and an edited licence text is no longer the licence.

`LGPL-2.1.md` serves both binaries. The Chromaprint archive carries only
`fpcalc.exe` — no licence file — so the text comes from libdiscid's archive,
which distributes the same GNU LGPL version 2.1. `Chromaprint-LICENSE.md` is the
notice that explains why an MIT-licensed project's *binary* is LGPL-2.1: it
includes parts of FFmpeg and must be considered as a whole under LGPL 2.1.

**The LGPL-2.1-ness is a property of the build, not of the source.** The
committed `fpcalc.exe` reports FFmpeg `Lavc 62.11.100`. A build linked against a
GPL-licensed FFT library instead would be GPL, which is why the binary's own
version output is part of the record.

---

## 3. Corresponding source (LGPL-2.1 §6)

Both projects' complete corresponding source is public, and the versions are
named above:

- Chromaprint 1.6.1 — `https://github.com/acoustid/chromaprint/tree/v1.6.1`
  (release tarball: `https://github.com/acoustid/chromaprint/releases/download/v1.6.1/chromaprint-1.6.1.tar.gz`)
- libdiscid 0.6.5 — `https://github.com/metabrainz/libdiscid/tree/v0.6.5`
  (release tarball: `https://github.com/metabrainz/libdiscid/releases/download/v0.6.5/libdiscid-0.6.5.tar.gz`)

The suite loads them as separate processes/libraries (`fpcalc.exe` is executed;
`discid.dll` is loaded with `ctypes`), which is the arrangement LGPL anticipates.
A recipient who wants to substitute their own build of either can replace the
file at the installed location; nothing in the suite links statically against
them.

---

## 4. Re-verifying this record

```bash
# fpcalc
curl -sSLO https://github.com/acoustid/chromaprint/releases/download/v1.6.1/chromaprint-fpcalc-1.6.1-windows-x86_64.zip
sha256sum chromaprint-fpcalc-1.6.1-windows-x86_64.zip   # expect 735d6182...
unzip -p chromaprint-fpcalc-1.6.1-windows-x86_64.zip \
  chromaprint-fpcalc-1.6.1-windows-x86_64/fpcalc.exe | sha256sum   # expect 00dcc56d...

# libdiscid (hash also cross-checkable against the project's SHA256SUMS)
curl -sSL https://github.com/metabrainz/libdiscid/releases/download/v0.6.5/SHA256SUMS
curl -sSLO https://github.com/metabrainz/libdiscid/releases/download/v0.6.5/libdiscid-0.6.5-win.zip
sha256sum libdiscid-0.6.5-win.zip                       # expect a1198731...
unzip -p libdiscid-0.6.5-win.zip libdiscid-0.6.5-win/x64/discid.dll | sha256sum  # expect e3bba899...

# the committed files themselves
sha256sum fpcalc.exe discid.dll
```

If a future rebuild replaces either binary, update this file **and**
`THIRD_PARTY_NOTICES.md` §5 in the same change. A provenance record that has
drifted from the bytes it describes is worse than no record, because it is
believed.
