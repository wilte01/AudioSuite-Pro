# Security in AudioSuite-Pro

This page describes what the suite does to protect your files and your API
keys, and what to do when a security message appears. The reporting policy and
the threat model live in [SECURITY.md](../../../SECURITY.md); this page is the
user-facing half.

## What the suite blocks

Every program that runs another process goes through one wrapper
(`audio_suite_shared/secure_subprocess.py`), so the rules are the same
everywhere and there is nothing to configure.

- **Executables are allow-listed.** Only the Python interpreters the suite
  understands and the audio tools it ships against (`ffmpeg`, `ffprobe`) may be
  launched. Anything else is refused before it starts.
- **Scripts must be first-party.** Script paths must end in `.py` or `.pyw` and
  must exist; the path is resolved first, so a symlink or `..` segment cannot
  redirect the suite to another file.
- **Arguments are screened.** The shell metacharacters `;`, `|`, `` ` ``,
  `<`, `>` and `"` are refused inside an argument, because the suite never runs
  a shell: a character that would only mean something to `cmd.exe` or `sh` is
  a sign that the value did not come from where it should have.
- **Paths are length-checked** against the platform limit (260 characters on
  Windows, 4096 on Linux and macOS), and directory traversal is refused.

**Your music library's names keep working.** The screen is for shell syntax,
not for punctuation: apostrophes (`Sam's Town`), parentheses
(`Greatest Hits (Deluxe Edition)`), brackets (`Artist - Album [2004]`),
ampersands and accented or non-Latin characters are all valid.

## API keys are encrypted

Keys you enter for an online service (Fanart.tv is the one that needs them) are
encrypted with Fernet symmetric encryption before they are written to disk.

- On first use the module creates a key file (`album_art_config.key`) next to
  the configuration file. API keys are stored encrypted in
  `album_art_config.json`. Both live in one place,
  `album_art_sync/config/`, and every entry point — the window and the
  command-line or batch runs — reads that same file. An installation from an
  earlier version may still hold a copy beside the module or in its `core/`
  folder; the first load copies it and its `.key` into `config/` and leaves the
  originals in place.
- Both files are git-ignored and must never be committed or shared. A backup
  copy of a replaced key file (`*.key.bak`) is secret-class too.
- If the key file is ever replaced, values encrypted under the old key stop
  decrypting and must be re-entered; the module logs a WARNING saying so at
  launch. Before overwriting a key file it copies the old one to
  `<key file>.bak`.
- To recover the old values: stop the module, put the `.bak` file back in place
  of the `.key` file, delete the new `.key`, and restart. If the key file was
  already corrupt when it was replaced, the `.bak` is a diagnostic copy only and
  the values cannot be recovered.

Keys are decrypted only in memory, when a request needs them. The suite never
writes a decrypted key to a log, a report or a screenshot-visible field.

## Safe file selection

Use the built-in folder browser. It validates what you picked before any tool
touches it.

| Input | Result |
|---|---|
| `D:\Audio Files\Collection` | valid |
| `/home/user/music` | valid |
| `C:\..\Windows\System32` | refused: directory traversal |
| `C:\My<Files>Music` | refused: characters the shell would read as syntax |
| `CON` | refused: reserved Windows device name |

A refused path shows a dialog naming the reason; nothing is written.

## Network connections

All HTTPS requests verify certificates against the bundled certificate
authorities. A certificate that does not validate fails the request instead of
being ignored, so a proxy that intercepts traffic produces an error rather than
silently accepting a substituted certificate.

## Error messages

Two modes decide how much a message says:

- **Normal operation** shows a short, non-technical message. It names what
  failed and what to do next, without internal paths or stack detail.
- **Debug mode** shows the full detail and is what a bug report should include.
  Set `AUDIOSUITE_DEBUG=1` before launching:

  ```bat
  set AUDIOSUITE_DEBUG=1
  python Master_Driver.pyw
  ```

  ```bash
  export AUDIOSUITE_DEBUG=1
  python Master_Driver.py
  ```

Every error is written to the log either way, so a problem you saw once can
still be diagnosed later. See the
[logging system guide](../../user_guides/suite_overview/LOGGING_SYSTEM_GUIDE.docx)
for where the files live.

## Common messages

| Message | Cause | Fix |
|---|---|---|
| `Executable not allowed` | something tried to launch a program outside the allow-list | run the suite's own programs; if a first-party tool triggers this, report it |
| `Dangerous character in argument` | a value contained a shell character (semicolon, pipe, backtick, angle bracket or double quote) | rename the file or album so the name has no shell syntax |
| `Path too long` | the full path exceeds the platform limit | shorten the folder name or move the library closer to the drive root |
| `Directory traversal detected` | a path contained `..` | pick the folder with the browser instead of typing it |
| `Script file does not exist` | a program file is missing or was moved | reinstall or repair the suite |
| `Invalid path selected` | the folder no longer exists or is unreadable | re-select it in the browser |
| SSL certificate error | wrong system clock, or a proxy intercepting HTTPS | correct the date/time, then check the network |
| API keys stopped working | the key file was replaced | restore the `.bak` key file (see above) and re-enter the keys |

## What is your responsibility

The suite runs with your user account's privileges and cannot defend you
against someone who already has that account. It also does not manage your
backups. Practically:

1. **Back up the config directory.** Copy `audio_suite_config.json`,
   `album_art_config.json` and `album_art_config.key` together; a key without
   its config is useless and vice versa.
2. **Keep the key files private.** Restrict who can read them, and never paste
   one into a ticket or a chat.
3. **Rotate keys you have exposed.** Replace a key at the provider, then
   re-enter it.
4. **Keep the suite and Python current.** Dependency changes go through the
   locked environment (`uv sync`), and the project's gate screens dependencies
   for known advisories.

## For developers

The rules above are enforced by code, not convention: the allow-list and the
argument screen are in `audio_suite_shared/secure_subprocess.py`, and new
subprocess call sites must use it — a raw `subprocess.run` in a tool package is
a review finding. Its public functions are documented in the API reference.
Threat-model details, the reporting route and what is intentionally out of scope
are in [SECURITY.md](../../../SECURITY.md).
