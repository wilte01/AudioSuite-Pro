# Security Policy for AudioSuite-Pro

## Reporting a vulnerability

There is currently **no dedicated private vulnerability-reporting channel
and no promised response time**. Report a suspected vulnerability by opening
a repository issue with a title prefixed `[security]` and the minimal
reproduction. Before the maintainer confirms, avoid publishing exploit
detail that would help someone weaponise the finding.

If a confirmed vulnerability has been fixed, it is announced in
`CHANGELOG.md`.

## What this suite treats as untrusted input

- **Raw audio and tag files are untrusted input.** Tools read
  third-party-authored containers (MP3/FLAC/OGG/MP4/WAV and the tag payloads
  they carry) with `mutagen` and `librosa`/`pydub`; a hostile file is a
  supported scenario, not an edge case.
- **Playlist files** (`.asx`, `.cue`) are parsed XML/structured input from
  anywhere on the library path.
- **API responses** (AcoustID/MusicBrainz, Lyrics providers, image sources)
  are untrusted metadata feeding tag writes.

Treat anything a tool reads before writing as attacker-controllable, and
prefer new parsing code that fails closed (typed exceptions out of
`audio_suite_shared/exceptions.py`) over lenient fallbacks.

## Subprocess execution surface

All first-party subprocess invocations go through
`audio_suite_shared/secure_subprocess.py`, which enforces an executable
allowlist (notably `ffmpeg` / `ffprobe`, treated as a pair), refuses
`shell=True`, and rejects partial paths outside the allowlist. New
subprocess call sites must use this wrapper — a raw `subprocess.run` in a
tool package is a review finding, not a pattern. `os.startfile(path)` calls
in the UI layer open user-picked local files via the OS shell association;
they are never fed tag-derived or network-derived strings.

## What is intentionally out of scope

- Local attacks from someone with the same user account on your machine
  (the suite runs with the privileges of that user).
- Issues in bundled third-party binaries (`fpcalc.exe`, `discid.dll`) that
  upstream projects would need to fix. Please still report interactions
  between those binaries and the suite's own code.

## Dependencies

Dependency changes go through `uv sync` against `uv.lock`, and the gate
includes a bandit screening pass (`0 High / 0 Medium` required) plus the
staged-secret grep patterns documented in `CONTRIBUTING.md`. API keys are
stored only in gitignored local config files and are never committed.
