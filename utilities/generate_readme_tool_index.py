#!/usr/bin/env python3
"""
generate_readme_tool_index.py

Regenerates the tool-index table block in the repository README.md from the
tool manifest, so the 27-row table cannot drift from the registry the Master
Driver and CLI actually consult (plan iteration 5, item E1, audit #10).

Source-of-truth chain (reused, not duplicated):

* Tool name, description, launcher and category come from
  ``audio_suite_shared.tool_plugin`` (the manifest table).
* The user-guide filename is derived as ``"<pyw stem>_User_Guide.docx"``,
  with any deviation listed in ``_GUIDE_FILENAME_OVERRIDES`` below.  Every
  derived (or overridden) name must be present in the ``guide_to_program``
  registry inside ``audio_suite_shared/platform_utils.py`` — the existing
  index of guides, reused on purpose so no third list can be created.
* The ``Platform`` column comes from ``audio_suite_shared/platform_support.py``
  (plan G1), the declared platform support matrix, so a tool's tier is
  rendered from the same declaration the branch enumeration and README
  platform section are built from.
* The guide folder from that registry must actually contain the ``.docx``
  file, and the launcher ``.pyw`` must exist at the suite root, before the
  row is emitted; a dead row aborts the run with [ERROR].

Usage:
    python utilities/generate_readme_tool_index.py

Run this after adding a tool to ``_DEFAULT_MANIFESTS``.  The table block
between the TOOL INDEX markers is the only part of README.md this script
touches.

Conventions (AGENTS.md "Utility Script Markers"): ASCII-only [START] /
[OK] / [ERROR] / [DONE] status markers on stdout/stderr.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"
PLATFORM_UTILS = REPO_ROOT / "audio_suite_shared" / "platform_utils.py"

BEGIN_MARK = "<!-- TOOL INDEX: BEGIN"
END_MARK = "<!-- TOOL INDEX: END"
END_SUFFIX = " -->"

_GUIDE_FILENAME_OVERRIDES: dict[str, str] = {
    # The launcher is named Album_Art_Synch.pyw; the guide (and its
    # guide_to_program key) spell the word out: Synchronizer.
    "art": "Album_Art_Synchronizer_User_Guide.docx",
}


def extract_guide_registry() -> dict[str, str]:
    """Return the ``guide_to_program`` registry from platform_utils.py.

    The registry is a function-local literal dict inside ``open_help``;
    it is extracted with ``ast`` rather than re-declared, so the README
    cannot disagree with the code the Help buttons actually use.

    Raises:
        RuntimeError: If the registry literal is not found (the shared
            helper's shape changed — fix the extraction, never the copy).
    """
    tree = ast.parse(
        PLATFORM_UTILS.read_text(encoding="utf-8"), filename=str(PLATFORM_UTILS)
    )
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Name)
                and target.id == "guide_to_program"
                and isinstance(node.value, ast.Dict)
            ):
                extracted: dict[str, str] = ast.literal_eval(node.value)
                return extracted
    raise RuntimeError("guide_to_program dict literal not found in platform_utils.py")


def guide_filename_for(manifest_id: str, pyw_filename: str) -> str:
    """Derive the guide document filename for a tool.

    Args:
        manifest_id: The tool's manifest id.
        pyw_filename: The tool's launcher basename (``BPM_Analyzer.pyw``).

    Returns:
        The documented guide filename (``<stem>_User_Guide.docx`` by
        derivation, or the registered override).
    """
    stem = Path(pyw_filename).stem
    derived = f"{stem}_User_Guide.docx"
    return _GUIDE_FILENAME_OVERRIDES.get(manifest_id, derived)


def render_tool_index() -> str:
    """Build the complete marker-enclosed README table block.

    Every row is validated before it is emitted: the derived guide name
    must be registered in ``guide_to_program``, its ``.docx`` must exist
    under ``user_guides/individual_programs/``, and the launcher ``.pyw``
    must exist at the suite root.  Any dead row aborts the build.

    Returns:
        The replacement block including both markers, or an empty string
        if validation failed (the failure is printed to stderr).
    """
    from audio_suite_shared.platform_support import TIER_TITLES, tool_tier
    from audio_suite_shared.tool_plugin import get_registry

    guides = extract_guide_registry()
    rows: list[str] = []
    for manifest in get_registry().all:
        guide_name = guide_filename_for(manifest.id, manifest.pyw_filename)
        folder = guides.get(guide_name)
        if not folder:
            print(
                f"[ERROR] {manifest.id}: guide {guide_name!r} is not registered"
                f" in guide_to_program (platform_utils.py)",
                file=sys.stderr,
            )
            return ""
        guide_path = f"user_guides/individual_programs/{folder}/{guide_name}"
        if not (REPO_ROOT / guide_path).exists():
            print(
                f"[ERROR] {manifest.id}: guide artifact missing: {guide_path}",
                file=sys.stderr,
            )
            return ""
        if not (REPO_ROOT / manifest.pyw_filename).exists():
            print(
                f"[ERROR] {manifest.id}: launcher missing: {manifest.pyw_filename}",
                file=sys.stderr,
            )
            return ""
        description = manifest.description.replace("|", "\\|")
        # The tier comes from the declared matrix (plan G1), not from a second
        # list here: a tool is Windows-only iff one of its own branches is.
        platform = TIER_TITLES[tool_tier(manifest.id)]
        rows.append(
            f"| {manifest.name} | {description} | `{manifest.pyw_filename}` "
            f"| `{guide_path}` | {platform} |"
        )
    lines = [
        f"{BEGIN_MARK} — generated by utilities/generate_readme_tool_index.py;"
        " edit the manifest in audio_suite_shared/tool_plugin.py and re-run"
        " the script; do not edit the table by hand. -->",
        "",
        "| Tool | What it does | Launcher | User guide | Platform |",
        "|---|---|---|---|---|",
        *rows,
        "",
        f"{END_MARK} -->",
    ]
    return "\n".join(lines)


def main() -> int:
    """Regenerate the README tool-index block in place."""
    print("[START] Regenerating the README.md tool index from the manifest")
    try:
        guides = extract_guide_registry()
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        return 1
    block = render_tool_index()
    if not block:
        return 1

    text = README.read_text(encoding="utf-8")
    begin = text.find(BEGIN_MARK)
    end = text.find(END_MARK)
    if begin == -1 or end == -1 or end < begin:
        print("[ERROR] TOOL INDEX markers not found in README.md")
        return 1
    end = end + len(END_MARK) + len(END_SUFFIX)

    # Keep the file's existing line terminator (AGENTS.md line-ending rule):
    # the generated block may use \n, so normalise it to the host file's
    # terminator before splicing.
    terminator = "\r\n" if "\r\n" in text else "\n"
    block = block.replace("\n", terminator)
    new_text = text[:begin] + block + text[end:]
    README.write_text(new_text, encoding="utf-8", newline="")

    row_count = sum(
        1
        for line in block.splitlines()
        if line.startswith("| ") and not line.startswith("| Tool")
    )
    print(
        f"[OK] Tool index regenerated: {row_count} tool rows; "
        f"{len(guides)} guides registered in platform_utils.py"
    )
    print("[DONE]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
