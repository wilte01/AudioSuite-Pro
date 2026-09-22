"""
asx_parser.py
Parse a single ASX playlist file and resolve its referenced audio path.

Uses xml.etree.ElementTree for robust XML parsing instead of regex,
which handles attribute ordering, quoting, and whitespace correctly.

Pure functions — no tkinter, no file copying; the only I/O is reading the
ASX text content and probing candidate audio files for existence.
"""

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional

from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.exceptions import map_to_audio_error

logger = logging.getLogger(__name__)

# Legacy regex kept for backward compatibility; prefer XML parsing via
# process_asx_file() which handles all attribute formats correctly.
ASX_REF_PATTERN = re.compile(r'<ref\s+href="([^"]+)"', re.IGNORECASE)


def get_fallback_audio_path(audio_path: Path) -> Optional[Path]:
    """
    Return the first existing sibling of audio_path (same parent, same
    stem) whose extension is in SUPPORTED_EXTENSIONS, or None.

    The audio_path extension itself is excluded, so this helper only
    ever returns an *alternate* file — the primary href is still
    preferred by process_asx_file.

    Args:
        audio_path: Original resolved audio Path (need not exist).

    Returns:
        The first existing same-stem sibling in SUPPORTED_EXTENSIONS
        order, or None if no candidate exists.
    """
    parent = audio_path.parent
    stem = audio_path.stem
    original_ext = audio_path.suffix.lower()
    for ext in SUPPORTED_EXTENSIONS:
        if ext == original_ext:
            continue
        candidate = parent / f"{stem}{ext}"
        if candidate.exists():
            return candidate
    return None


def process_asx_file(asx_file: Path, source_dir: Path) -> dict[str, Any]:
    """
    Read and parse one ASX file, resolving the referenced audio path.

    Tries the primary path first; falls back to the first existing
    same-stem sibling in any suite supported extension if the primary
    is missing.

    Args:
        asx_file:   Path to the .asx playlist file.
        source_dir: Directory being processed (used for context only).

    Returns:
        On success::

            {
                'success':    True,
                'asx_fn':     str,   # filename only
                'asx_path':   Path,  # full path to the .asx file
                'audio_path': Path,  # resolved audio file that exists
            }

        On failure::

            {
                'success':    False,
                'asx_fn':     str,
                'audio_path': str,   # path attempted, or "N/A"
                'reason':     str,   # human-readable failure reason
            }
    """
    asx_filename = asx_file.name

    try:
        content = asx_file.read_text(encoding="utf-8", errors="ignore")

        # Strip XML declaration if present (some ASX files have encoding
        # declarations that don't match the actual encoding)
        if content.lstrip().startswith("<?"):
            end = content.find("?>")
            if end != -1:
                content = content[end + 2 :]

        # ElementTree expands internal entities (billion-laughs DoS), and
        # defusedxml is not a suite dependency by policy.  ASX playlists
        # never legitimately carry a DTD, so reject any payload that declares
        # one before handing it to the parser.
        upper_content = content.upper()
        if "<!DOCTYPE" in upper_content or "<!ENTITY" in upper_content:
            return {
                "success": False,
                "asx_fn": asx_filename,
                "audio_path": "N/A",
                "reason": "DTD-BEARING ASX REJECTED",
            }

        try:
            # The DTD/entity guard above neutralises the XXE / billion-laughs
            # exposure; bandit's B314 cannot see flow and is silenced here.
            root = ET.fromstring(content)  # nosec B314
        except ET.ParseError:
            return {
                "success": False,
                "asx_fn": asx_filename,
                "audio_path": "N/A",
                "reason": "INVALID XML IN ASX",
            }

        # Find the first <ref> element with an href attribute
        href: str | None = None
        for ref in root.iter("ref"):
            href = ref.get("href")
            if href:
                break

        if not href:
            return {
                "success": False,
                "asx_fn": asx_filename,
                "audio_path": "N/A",
                "reason": "NO REF LINK IN ASX",
            }

        href_path = Path(href)
        if href_path.is_absolute():
            audio_path = href_path.resolve()
        else:
            audio_path = (asx_file.parent / href_path).resolve()

        # Primary path found
        if audio_path.exists():
            return {
                "success": True,
                "asx_fn": asx_filename,
                "asx_path": asx_file,
                "audio_path": audio_path,
            }

        # Try an alternate same-stem sibling in any supported extension
        fallback = get_fallback_audio_path(audio_path)
        if fallback is not None:
            return {
                "success": True,
                "asx_fn": asx_filename,
                "asx_path": asx_file,
                "audio_path": fallback,
            }

        # Determine the most useful failure reason
        reason = (
            "DIRECTORY NOT FOUND"
            if not audio_path.parent.exists()
            else "FILE NOT FOUND"
        )

        return {
            "success": False,
            "asx_fn": asx_filename,
            "audio_path": str(audio_path),
            "reason": reason,
        }

    except (ET.ParseError, OSError, ValueError) as exc:
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        return {
            "success": False,
            "asx_fn": asx_filename,
            "audio_path": "N/A",
            "reason": f"READ ERROR: {exc}",
        }
