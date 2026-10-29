"""Lock: worker counts resolve from ``default_max_workers()``, never a literal.

PLAN D56 made the suite default host-dependent.  A literal left behind is
invisible until a host with a different CPU count runs that path, which is
exactly how the CLI slot shims stayed at four (D65) and the batch tagger's
saved-config fallback stayed at four (D66).  This scan finds the remaining
shapes a fixed count can take — a ``max_workers=4`` keyword, a
``load_value("...workers", 4)`` default, a ``{"max_workers": 4}`` payload and
a ``"4"`` worker entry — and requires each to be either derived or one of the
documented single-worker call sites.

Changed in 1.4.0: adds the worker-count literal lock for the audit follow-up.

Changed in 2.1.7: ``documentation`` replaces ``user_guides`` in the scan's excluded
directories.

"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKIP_PARTS = frozenset(
    {".venv", "__pycache__", "build", "dist", "tests", "documentation"}
)
_WORKER_ARGUMENTS = frozenset({"max_workers", "num_workers", "workers"})
_WORKER_KEYS = frozenset({"max_workers", "num_workers", "workers"})

#: Sites that intentionally use one worker: the serial tag-write stage.  It is
#: about ordering, not parallelism, so deriving it from the host default would
#: change behaviour.
_ALLOWED_ONE_WORKER = frozenset(
    {
        ("replaygain_analyzer/core/file_processor.py", "max_workers"),
    }
)


def _first_party_files() -> list[Path]:
    return [
        path
        for path in sorted(_REPO_ROOT.rglob("*.py"))
        if not (_SKIP_PARTS & set(path.relative_to(_REPO_ROOT).parts))
    ]


def _worker_literal(value: ast.expr) -> int | None:
    """Return a fixed non-trivial worker literal in *value*, if present."""
    candidates = [value]
    if isinstance(value, ast.IfExp):
        candidates.extend([value.body, value.orelse])
    for candidate in candidates:
        if (
            isinstance(candidate, ast.Constant)
            and isinstance(candidate.value, int)
            and not isinstance(candidate.value, bool)
            and candidate.value > 1
        ):
            return candidate.value
    return None


def _literal_worker_counts() -> list[str]:
    """Return ``path:line — shape`` for every fixed worker count."""
    findings: list[str] = []
    for path in _first_party_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if (
                        keyword.arg in _WORKER_ARGUMENTS
                        and isinstance(keyword.value, ast.Constant)
                        and isinstance(keyword.value.value, int)
                        and keyword.value.value != 1
                    ):
                        findings.append(f"{rel}:{node.lineno} — {keyword.arg}=literal")
                if isinstance(node.func, ast.Attribute) and node.func.attr in {
                    "load_value",
                    "get",
                }:
                    has_worker_key = any(
                        isinstance(arg, ast.Constant)
                        and isinstance(arg.value, str)
                        and "worker" in arg.value
                        for arg in node.args[:1]
                    )
                    if has_worker_key and any(
                        isinstance(arg, ast.Constant) and isinstance(arg.value, int)
                        for arg in node.args[1:]
                    ):
                        findings.append(f"{rel}:{node.lineno} — worker config default")
            if isinstance(node, ast.Assign | ast.AnnAssign):
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                names = {
                    target.id
                    if isinstance(target, ast.Name)
                    else getattr(target, "attr", "")
                    for target in targets
                }
                worker_names = {
                    name
                    for name in names
                    if name in {"max_workers", "num_workers", "workers"}
                    or name.endswith("_workers")
                }
                if worker_names:
                    literal = _worker_literal(node.value)
                    if literal is not None:
                        findings.append(
                            f"{rel}:{node.lineno} — "
                            f"{sorted(worker_names)[0]} = {literal}"
                        )
            if (
                isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                and "worker" in node.name
            ):
                for inner in ast.walk(node):
                    if not isinstance(inner, ast.IfExp):
                        continue
                    literal = _worker_literal(inner)
                    if literal is not None:
                        findings.append(
                            f"{rel}:{inner.lineno} — {node.name} "
                            f"falls back to {literal}"
                        )
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values, strict=False):
                    if (
                        isinstance(key, ast.Constant)
                        and isinstance(key.value, str)
                        and key.value in _WORKER_KEYS
                        and isinstance(value, ast.Constant)
                        and isinstance(value.value, int)
                    ):
                        findings.append(f"{rel}:{node.lineno} — worker payload")
    return findings


class TestWorkerCountLiterals:
    """No fixed worker count outside the documented single-worker site."""

    def test_the_scan_finds_worker_call_sites(self) -> None:
        files = _first_party_files()
        texts = [path.read_text(encoding="utf-8") for path in files]
        assert sum("max_workers" in text for text in texts) >= 10, (
            "the worker-count scan collapsed"
        )

    def test_no_fixed_worker_count_outside_the_allowlist(self) -> None:
        findings = _literal_worker_counts()
        unexpected = [
            finding
            for finding in findings
            if not any(
                finding.startswith(f"{rel}:")
                and finding.endswith(f"{argument}=literal")
                for rel, argument in _ALLOWED_ONE_WORKER
            )
        ]
        assert not unexpected, (
            "Fixed worker counts must resolve through default_max_workers() "
            "(PLAN D56/D66); only the one-worker sites in "
            "_ALLOWED_ONE_WORKER may use a literal: " + "; ".join(unexpected)
        )

    def test_one_worker_sites_are_still_the_documented_ones(self) -> None:
        """The allowlist cannot rot: each entry must still pass 1."""
        present = {
            (rel, argument)
            for rel, argument in _ALLOWED_ONE_WORKER
            if "=1," in (_REPO_ROOT / rel).read_text(encoding="utf-8")
            or "=1)" in (_REPO_ROOT / rel).read_text(encoding="utf-8")
        }
        assert present == _ALLOWED_ONE_WORKER, (
            "an allowed single-worker site no longer passes 1: "
            f"{sorted(_ALLOWED_ONE_WORKER - present)}"
        )
