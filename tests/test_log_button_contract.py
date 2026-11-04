"""The "no run report yet" message has exactly one implementation.

``audio_suite_shared.ui_helpers.open_log_file`` is the handler every GUI tool's
View Log binds, and it owns both the open and the not-yet-written branch — which
is why the *Run Reports vs Program Logs* rule can promise one behaviour across
the suite. A tool that keeps its own copy satisfies today's wording while
silently ignoring tomorrow's change, and the copy is invisible to every other
lock: the callback-payload contract reads call signatures, and a tool's own
tests assert its copy.

``mood_analysis_batch_tagger`` was that copy (its own title, its own branch) until
the View Log defect review found it; this scan is what refuses the next one.

Changed in 2.4.3: initial version, from the View Log defect review
(PLAN_2026-11-03_2.4.3_structure.md D-16, D-19).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The user-facing sentence the shared helper emits before a run has written its
#: report.
NO_LOG_YET = "No log file available yet."

#: Where the message is allowed to live.
OWNER = "audio_suite_shared/ui_helpers.py"

#: Directory names never scanned: a test may quote the sentence, prose may
#: describe it, and the rest is not first-party source.
_EXCLUDED_DIRS = frozenset(
    {".venv", ".git", "tests", "documentation", "build", "dist", "__pycache__"}
)


def _first_party_modules() -> list[Path]:
    """Every first-party Python module, sorted for a stable report."""
    modules: list[Path] = []
    for path in REPO_ROOT.rglob("*.py"):
        parts = path.relative_to(REPO_ROOT).parts
        if _EXCLUDED_DIRS.intersection(parts[:-1]) or parts[-1] in {"setup.py"}:
            continue
        modules.append(path)
    return sorted(modules)


def test_the_no_log_message_has_a_single_source() -> None:
    """A second copy of the sentence fails here, naming the file that holds it."""
    modules = _first_party_modules()
    assert len(modules) > 100, f"scan reached only {len(modules)} modules"

    holders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in modules
        if NO_LOG_YET in path.read_text(encoding="utf-8", errors="replace")
    ]

    assert holders == [OWNER], (
        f"{NO_LOG_YET!r} must live once, in {OWNER}; also found in: {holders}"
    )
