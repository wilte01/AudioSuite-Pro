# Security Policy for AudioSuite-Pro

This page is the policy and threat model: what the suite treats as untrusted,
where the subprocess boundary is, and what is out of scope. User-facing
practice — encrypted API keys and how to recover them, safe file selection,
and what each security message means — is documented in
[documentation/docs/user/security.md](documentation/docs/user/security.md).

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

Every subprocess invocation in the shipped runtime — the tool packages,
`audio_suite_shared` and `master_driver` — goes through
`audio_suite_shared/secure_subprocess.py`, which enforces an executable
allowlist (notably `ffmpeg` / `ffprobe`, treated as a pair, `fpcalc` for
fingerprinting, and `explorer` / `eject` for CD-drive control), refuses
`shell=True`, and rejects partial paths outside the allowlist. Arguments are
validated too: shell metacharacters and redirection patterns are refused
before anything is spawned. The wrapper always supplies `startupinfo` itself,
and `text=False` is available for a **binary** stream — the Audio Enhancer
reads raw float32 PCM off ffmpeg's stdout, which decoding as text would
corrupt.

New subprocess call sites must use this wrapper. That is no longer a
review-only convention: `tests/test_subprocess_boundary.py` parses every
shipped module and fails on a direct `subprocess.run` / `Popen` /
`check_output` outside the wrapper, so the invariant cannot drift back.
`utilities/` is deliberately outside that boundary — those scripts drive the
development checkout (`uv`, `git`, `pytest`) and never process user audio, so
adding their tools to the product allowlist would be the wrong fix.

One action deliberately runs no process at all: the CD Ripper opens a Windows
tray through MCI (`mciSendStringW`) with a command built from a validated
single drive letter, which replaced an interpolated PowerShell command string
(audit R-08). `os.startfile(path)` calls in the UI layer open user-picked
local files via the OS shell association; they are never fed tag-derived or
network-derived strings.

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
