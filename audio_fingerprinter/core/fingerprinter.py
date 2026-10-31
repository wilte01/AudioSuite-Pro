"""Fingerprint generation via the external ``fpcalc`` binary.

Resolution order for the binary:
    explicit `--fpcalc` path  >  ``FPCALC`` environment variable  >  PATH
    >  the ``fpcalc.exe`` committed at the checkout root.

The committed copy is the last resort, so an intentional PATH install still
wins, while a plain source checkout fingerprints out of the box without
``--fpcalc`` or a PATH edit.

The fingerprint inside ``FINGERPRINT=`` can be extremely long (one integer
per ~2.5ms of audio), so fpcalc output is captured as text and parsed
line-by-line rather than via mutagen or any Python fingerprint library.

Changed in 1.4.0: adds the committed ``fpcalc.exe`` as the final fallback, so
``audiosuite fingerprint`` works from a plain checkout without ``--fpcalc`` or
a PATH entry.  An explicit path, ``FPCALC`` and PATH still win.

Changed in 2.3.0: ``generate_fingerprint`` takes ``raw=True``, which passes
``-raw`` to fpcalc and yields the sub-fingerprints as comma-separated decimal
words.  The default is unchanged: fpcalc's own output is URL-safe base64 of
Chromaprint's *compressed* encoding, which is what the AcoustID API consumes but
is not directly comparable word by word.  The duplicate finder (functional
backlog F-02) needs the words to measure a distance, and it reuses this one
fpcalc resolution path rather than shelling out itself (D38).
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from audio_suite_shared.secure_subprocess import (
    SubprocessSecurityError,
    run_secure_subprocess,
)

from .exceptions import FingerprintToolError
from .models import Fingerprint

logger = logging.getLogger(__name__)

FPCALC_ENV_VAR = "FPCALC"
DEFAULT_MAX_LENGTH = 120
_FPCALC_TIMEOUT_SECS = 300

#: The ``fpcalc.exe`` committed at the checkout root.  ``fingerprinter.py`` is
#: ``<checkout>/audio_fingerprinter/core/fingerprinter.py``, so ``parents[2]``
#: is the checkout itself; an installed wheel simply will not have the file.
SHIPPED_FPCALC = Path(__file__).resolve().parents[2] / "fpcalc.exe"


@dataclass(frozen=True)
class FpcalcOutput:
    """Parsed stdout of ``fpcalc -length N <file>``.

    Attributes:
        duration: DURATION value in seconds (float).
        fingerprint: FINGERPRINT value as a Chromaprint string.
    """

    duration: float
    fingerprint: str


def resolve_fpcalc(explicit_path: str | None = None) -> str:
    """Locate the ``fpcalc`` executable.

    Resolution order is ``explicit_path``, then the ``FPCALC`` environment
    variable, then a ``shutil.which`` scan of PATH, then the copy of
    ``fpcalc.exe`` shipped at the checkout root (``SHIPPED_FPCALC``).

    Args:
        explicit_path: Optional user-supplied path to ``fpcalc``.

    Returns:
        Absolute path to the fpcalc executable.

    Raises:
        FingerprintToolError: If fpcalc cannot be located.
        SubprocessSecurityError: If ``validate_executable`` rejects the path
            (fpcalc not in the allowed executables allow-list).
    """
    candidates: list[str] = []
    if explicit_path:
        candidates.append(explicit_path)
    env_path = os.environ.get(FPCALC_ENV_VAR, "").strip()
    if env_path:
        candidates.append(env_path)

    for candidate in candidates:
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)

    found = shutil.which("fpcalc")
    if found:
        return os.path.abspath(found)

    if SHIPPED_FPCALC.is_file():
        return str(SHIPPED_FPCALC)

    raise FingerprintToolError(
        "fpcalc was not found. Pass --fpcalc, set the FPCALC environment "
        "variable, or add fpcalc to PATH.",
    )


def _parse_fpcalc_output(raw: str) -> FpcalcOutput:
    """Parse the ``DURATION=`` / ``FINGERPRINT=`` key-value lines of fpcalc.

    Args:
        raw: Captured fpcalc stdout.

    Returns:
        The parsed (duration, fingerprint) pair.

    Raises:
        FingerprintToolError: If the output is missing either key, or the
            duration string is not parseable as a float.
    """
    duration_str = ""
    fingerprint = ""
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("DURATION="):
            duration_str = line[len("DURATION=") :]
        elif line.startswith("FINGERPRINT="):
            fingerprint = line[len("FINGERPRINT=") :].strip()

    if not duration_str or not fingerprint:
        logger.error("fpcalc output missing DURATION/FINGERPRINT fields: %r", raw[:200])
        raise FingerprintToolError(
            "fpcalc produced no usable fingerprint for this file.",
            context={"raw_output": raw[:300]},
        )

    try:
        duration = float(duration_str)
    except ValueError as exc:
        raise FingerprintToolError(
            f"fpcalc returned a malformed DURATION value: {duration_str!r}",
            context={"duration_raw": duration_str},
        ) from exc

    return FpcalcOutput(duration=duration, fingerprint=fingerprint)


def generate_fingerprint(
    file_path: str,
    *,
    fpcalc_path: str | None = None,
    max_length: int = DEFAULT_MAX_LENGTH,
    raw: bool = False,
) -> Fingerprint:
    """Generate a Chromaprint fingerprint for a single audio file.

    Args:
        file_path: Path to the audio file.
        fpcalc_path: Optional explicit fpcalc binary path (see
            ``resolve_fpcalc`` for the fallback order).
        max_length: Maximum analysed duration in seconds passed to
            ``fpcalc -length``.
        raw: Pass ``-raw`` so the fingerprint is the sub-fingerprints as
            comma-separated decimal words instead of fpcalc's default URL-safe
            base64 of Chromaprint's compressed encoding.  The AcoustID lookup
            path must keep the default; a local comparison (the duplicate
            finder) needs the words.

    Returns:
        A ``Fingerprint`` carrying the file duration and fingerprint string.

    Raises:
        FingerprintToolError: On missing binary, non-zero fpcalc exit, or
            unparseable output.
    """
    executable = resolve_fpcalc(fpcalc_path)
    argv = ["-length", str(int(max_length))]
    if raw:
        argv.insert(0, "-raw")
    argv.append(file_path)

    try:
        completed = run_secure_subprocess(
            executable,
            argv,
            timeout=_FPCALC_TIMEOUT_SECS,
            capture_output=True,
            check=False,
        )
    except (OSError, SubprocessSecurityError) as exc:
        logger.error("fpcalc failed to start: %s", exc, exc_info=True)
        raise FingerprintToolError(
            f"fpcalc could not be run: {exc}",
            original=exc,
        ) from exc

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        logger.error(
            "fpcalc exited %s for %s: %s",
            completed.returncode,
            file_path,
            stderr,
        )
        raise FingerprintToolError(
            f"fpcalc failed with exit code {completed.returncode}.",
            context={"returncode": completed.returncode, "stderr": stderr[:300]},
        )

    parsed = _parse_fpcalc_output(completed.stdout or "")
    return Fingerprint(duration=parsed.duration, fingerprint=parsed.fingerprint)
