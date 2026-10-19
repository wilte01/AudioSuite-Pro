"""Cross-tool lock: a GUI slot grid must match its processor's worker count.

PLAN D56 replaced the fixed four-worker default with
``default_max_workers()`` (one per logical CPU, capped at
``MAX_WORKERS_CEILING``).  A GUI sizes its slot grid **once**, when the widget
is built, while the processor hands each worker an index from
``range(max_workers)``.  If those two numbers drift the failure is silent or
mysterious: a grid smaller than the pool raises ``IndexError`` inside the
worker (the file is reported as an unexplained error), and a grid larger than
the pool leaves "IDLE" slots that never update.

Nothing is registered by hand here.  The tool list comes from the tool
manifest (:mod:`audio_suite_shared.tool_plugin`); each tool's entry module
comes from its own ``.pyw`` launcher; and the grid sites come from an AST
scan of every ``app.py`` in the tree.  Registering a tool therefore adds it to
this lock automatically: its entry either builds a grid (which must be sized
from the shared default and must match its processors) or inherits a
grid-owning base (which must resolve the default at construction).  A grid
built in a file no manifest tool owns fails the ownership assertion.

Layers:

* the source lock requires every ``slot_vars`` grid to be sized from a
  canonical symbol and to live in a manifest tool's entry module or in one of
  the shared bases;
* the runtime lock resolves every grid's size and asserts it equals
  ``default_max_workers()``, and that every ``BaseFileProcessor`` subclass in
  the owning package resolves the same count;
* the typed-count lock requires every GUI that builds a worker-named Tk
  variable to call ``cap_typed_workers`` on the main thread *before* it
  persists the workers setting, passing an ``unattended=`` argument so a
  driver or ``--start`` launch logs the clamp instead of waiting on a modal
  dialog — D66's guard cannot be omitted by a newly registered tool, and it
  cannot reintroduce the blocking dialog either.

Changed in 1.4.0: adds the typed worker-count cap lock (D66 follow-up) and
requires its ``unattended=`` argument so unattended launches never block (D70).
"""

from __future__ import annotations

import ast
import importlib
import inspect
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

from audio_suite_shared.constants import default_max_workers

_REPO_ROOT = Path(__file__).resolve().parent.parent

#: Size expressions a slot grid may use.  Each resolves to the shared worker
#: default; a literal (``range(4)``) or an ad-hoc expression is the D56 drift
#: this test exists to stop.
_CANONICAL_SIZES = frozenset(
    {"DEFAULT_MAX_WORKERS", "WORKER_SLOT_COUNT", "self.num_workers", "num_workers"}
)

#: Shared bases that own a slot grid for their subclasses: model name ->
#: (module, grid size expression).
_SHARED_BASES: dict[str, tuple[str, str]] = {
    "BaseSuiteApp": ("audio_suite_shared/app_bootstrap.py", "self.num_workers"),
    "AnalysisAppBase": (
        "audio_suite_shared/analysis_app_base.py",
        "WORKER_SLOT_COUNT",
    ),
    "AnalysisTagToolApp": (
        "audio_suite_shared/tool_app_base.py",
        "DEFAULT_MAX_WORKERS",
    ),
    # Inherits its grid from AnalysisTagToolApp; listed so the two in-place
    # repair tools' entry modules resolve to a grid-owning base.
    "NoisePopToolApp": (
        "audio_suite_shared/tool_app_base.py",
        "DEFAULT_MAX_WORKERS",
    ),
}

_SKIP_PARTS = frozenset({".venv", "__pycache__", "build", "dist", "tests"})


# ── Discovery ─────────────────────────────────────────────────────────────────


def _module_file(module: str) -> Path | None:
    """Return the file backing a dotted module, if it exists."""
    path = _REPO_ROOT / Path(*module.split("."))
    if path.with_suffix(".py").is_file():
        return path.with_suffix(".py")
    if (path / "app.py").is_file():
        return path / "app.py"
    return None


def _launcher_imports(launcher: Path) -> list[tuple[str, str]]:
    """Return ``(module, imported name)`` pairs from a launcher's imports."""
    tree = ast.parse(launcher.read_text(encoding="utf-8"), filename=str(launcher))
    return [
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    ]


def _looks_like_tool_module(module: str, name: str) -> int:
    """Score how likely *module* is the launcher's own tool entry point."""
    score = 0
    if module.endswith(".app"):
        score += 4
    if name == "main" or name.endswith("App") or name.endswith("Tool"):
        score += 2
    if "app" in module.split("."):
        score += 1
    return score


def _tool_entry(tool_id: str, pyw_filename: str) -> Path:
    """Resolve the tool's GUI entry module from its ``.pyw`` launcher.

    The launcher is the only file that knows a manifest id's package, so the
    manifest plus the launcher together replace the old hand-written table.
    """
    launcher = _REPO_ROOT / pyw_filename
    assert launcher.is_file(), f"{tool_id}: launcher {pyw_filename} is missing"

    scored: list[tuple[int, str]] = []
    for module, name in _launcher_imports(launcher):
        top = module.split(".")[0]
        if (
            not (_REPO_ROOT / top).is_dir()
            or not (_REPO_ROOT / top / "__init__.py").is_file()
        ):
            continue
        if _module_file(module) is None:
            continue
        shared = top == "audio_suite_shared"
        scored.append(
            (_looks_like_tool_module(module, name) - (2 if shared else 0), module)
        )

    assert scored, (
        f"{tool_id}: {pyw_filename} does not import a first-party tool module"
    )
    best = max(score for score, _ in scored)
    module = next(module for score, module in scored if score == best)
    entry = _module_file(module)
    assert entry is not None, f"{tool_id}: cannot resolve {module} to a file"
    return entry


@lru_cache(maxsize=None)
def _manifest_tools() -> dict[str, Path]:
    """``tool_id -> entry module file`` for every tool in the manifest."""
    from audio_suite_shared.tool_plugin import get_registry

    manifests = get_registry().all
    assert manifests, "the tool manifest is empty — the lock cannot check anything"
    return {
        manifest.id: _tool_entry(manifest.id, manifest.pyw_filename)
        for manifest in manifests
    }


def _grid_site(path: Path) -> tuple[int, str] | None:
    """Return ``(line, size expression)`` for a ``slot_vars`` grid in *path*."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        value = node.value
        if not isinstance(value, ast.ListComp) or len(value.generators) != 1:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names = [
            t.id if isinstance(t, ast.Name) else getattr(t, "attr", "") for t in targets
        ]
        if "slot_vars" not in names:
            continue
        iterator = value.generators[0].iter
        if not (
            isinstance(iterator, ast.Call)
            and isinstance(iterator.func, ast.Name)
            and iterator.func.id == "range"
            and len(iterator.args) == 1
        ):
            continue
        found.append((node.lineno, ast.unparse(iterator.args[0])))
    assert len(found) <= 1, f"{path} builds slot_vars more than once: {found}"
    return found[0] if found else None


#: Tk variable factories that can hold a user-typed worker count.
_WORKER_VAR_FACTORIES = frozenset({"IntVar", "StringVar", "DoubleVar"})

#: The one GUI helper allowed to clamp a typed count.
_CAP_HELPER = "cap_typed_workers"


def _last_name(expr: ast.expr) -> str:
    """Return the final component of a call target (``tk.IntVar`` -> ``IntVar``)."""
    return ast.unparse(expr).split(".")[-1]


def _worker_var_lines(path: Path) -> list[int]:
    """Line numbers where *path* builds a worker-named Tk variable."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        if _last_name(node.value.func) not in _WORKER_VAR_FACTORIES:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any("worker" in ast.unparse(target).lower() for target in targets):
            lines.append(node.lineno)
    return sorted(lines)


def _enclosing_function(
    tree: ast.Module, lineno: int
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Return the innermost function containing *lineno*, if any."""
    best: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        end = node.end_lineno or node.lineno
        if node.lineno <= lineno <= end and (best is None or node.lineno > best.lineno):
            best = node
    return best


def _typed_worker_problems(path: Path) -> list[str]:
    """Reasons *path*'s typed worker count is not capped safely (empty = OK)."""
    relative = path.relative_to(_REPO_ROOT).as_posix()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    imported = any(
        isinstance(node, ast.ImportFrom)
        and (node.module or "").endswith("ui_common")
        and any(alias.name == _CAP_HELPER for alias in node.names)
        for node in ast.walk(tree)
    )
    caps = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _last_name(node.func) == _CAP_HELPER
    ]
    if not caps:
        return [
            f"{relative}: builds a typed worker count but never calls "
            f"{_CAP_HELPER}() — a count above the slot grid would silently run "
            "at the grid size with no warning and be saved uncapped (D66)"
        ]

    problems: list[str] = []
    if not imported:
        problems.append(
            f"{relative}: calls {_CAP_HELPER}() without importing it from "
            "audio_suite_shared.ui_common — import the shared guard instead of "
            "reimplementing the clamp"
        )

    saves = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and _last_name(node.func) == "save_value"
        and "worker" in ast.unparse(node).lower()
    ]
    for cap in caps:
        if not any(keyword.arg == "unattended" for keyword in cap.keywords):
            problems.append(
                f"{relative}:{cap.lineno}: {_CAP_HELPER}() must pass an "
                "unattended= argument so a Master Driver or --start launch logs "
                "the clamp instead of waiting on a modal dialog"
            )
        function = _enclosing_function(tree, cap.lineno)
        if function is None:
            problems.append(
                f"{relative}:{cap.lineno}: {_CAP_HELPER}() runs at module scope, "
                "not in the method that starts the run"
            )
            continue
        if function.name.lstrip("_") in {"run", "run_worker", "worker_run"}:
            problems.append(
                f"{relative}:{cap.lineno}: {_CAP_HELPER}() is inside "
                f"{function.name}(), a background worker — it shows a message "
                "box and writes the variable, so it must run on the main thread"
            )
            continue
        function_saves = [
            line
            for line in saves
            if function.lineno <= line <= (function.end_lineno or function.lineno)
        ]
        if not function_saves:
            problems.append(
                f"{relative}:{cap.lineno}: {_CAP_HELPER}() is not in the method "
                "that persists the workers setting, so the saved value can "
                "diverge from what runs"
            )
        elif cap.lineno > min(function_saves):
            problems.append(
                f"{relative}:{min(function_saves)}: the workers setting is "
                f"persisted before {_CAP_HELPER}() at line {cap.lineno} — the "
                "uncapped value would be saved"
            )
    return problems


def _app_files() -> list[Path]:
    """Every non-test ``app.py`` plus every shared base module."""
    files = [
        path
        for path in sorted(_REPO_ROOT.rglob("app.py"))
        if not (_SKIP_PARTS & set(path.relative_to(_REPO_ROOT).parts))
    ]
    files.extend(sorted((_REPO_ROOT / "audio_suite_shared").glob("*.py")))
    return files


@lru_cache(maxsize=None)
def _grid_sites() -> dict[Path, tuple[int, str]]:
    """Every slot-grid construction site, keyed by absolute path."""
    sites: dict[Path, tuple[int, str]] = {}
    for path in _app_files():
        site = _grid_site(path)
        if site is not None:
            sites[path.resolve()] = site
    return sites


@lru_cache(maxsize=None)
def _app_bases(path: Path) -> list[str]:
    """Bare base-class names of the classes defined in *path*."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        ast.unparse(base).split(".")[-1]
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        for base in node.bases
    ]


def _own_grid_tools() -> dict[str, Path]:
    """Manifest tools whose own entry module builds the slot grid."""
    sites = _grid_sites()
    return {
        tool_id: entry
        for tool_id, entry in _manifest_tools().items()
        if entry.resolve() in sites
    }


def _base_grid_tools() -> dict[str, str]:
    """Manifest tools backed by a shared grid: ``tool_id -> base class name``."""
    result: dict[str, str] = {}
    for tool_id, entry in _manifest_tools().items():
        if entry.resolve() in _grid_sites():
            continue
        for base in _app_bases(entry):
            if base in _SHARED_BASES:
                result[tool_id] = base
                break
    return result


#: The one legitimate worker-named Tk variable outside a tool's GUI: the
#: Master Driver's per-tool *launch arguments*, not a slot-grid field.
_DRIVER_WORKER_VARS = "master_driver/state/app_state.py"


@lru_cache(maxsize=None)
def _stray_worker_vars() -> dict[Path, tuple[int, ...]]:
    """Worker-named Tk variables created outside the entry modules this lock scans.

    A typed worker field built in a UI submodule would otherwise be invisible to
    the cap lock, so it is rejected here rather than silently uncovered.
    """
    scanned = set(_app_files())
    stray: dict[Path, tuple[int, ...]] = {}
    for path in sorted(_REPO_ROOT.rglob("*.py")):
        relative = path.relative_to(_REPO_ROOT)
        if _SKIP_PARTS & set(relative.parts):
            continue
        if path in scanned or relative.as_posix() == _DRIVER_WORKER_VARS:
            continue
        lines = _worker_var_lines(path)
        if lines:
            stray[path] = tuple(lines)
    return stray


@lru_cache(maxsize=None)
def _typed_worker_sites() -> dict[Path, tuple[int, ...]]:
    """Every GUI that builds a worker-named Tk variable, keyed by absolute path."""
    sites: dict[Path, tuple[int, ...]] = {}
    for path in _app_files():
        lines = _worker_var_lines(path)
        if lines:
            sites[path.resolve()] = tuple(lines)
    return sites


@lru_cache(maxsize=None)
def _processor_specs(package: Path) -> list[tuple[str, str]]:
    """``(module, class)`` for every ``BaseFileProcessor`` subclass in *package*."""
    specs: list[tuple[str, str]] = []
    for path in sorted(package.rglob("*.py")):
        relative = path.relative_to(package)
        if _SKIP_PARTS & set(relative.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(
                (isinstance(base, ast.Name) and base.id == "BaseFileProcessor")
                or (
                    isinstance(base, ast.Attribute) and base.attr == "BaseFileProcessor"
                )
                for base in node.bases
            ):
                continue
            module = ".".join(path.relative_to(_REPO_ROOT).with_suffix("").parts)
            specs.append((module, node.name))
    return specs


# ── Source lock ──────────────────────────────────────────────────────────────


class TestSlotGridSourceLock:
    """Every grid is canonical, and every grid belongs to a manifested tool."""

    def test_the_scan_finds_every_grid(self) -> None:
        """An empty or truncated scan must fail loudly, not pass vacuously."""
        tools = _manifest_tools()
        assert len(tools) >= 20, f"manifest discovery collapsed: {sorted(tools)}"
        own = _own_grid_tools()
        assert len(own) >= 10, f"tool-owned grid scan collapsed: {sorted(own)}"
        shared = {
            (_REPO_ROOT / module_path).resolve()
            for module_path, _ in _SHARED_BASES.values()
        }
        assert shared <= set(_grid_sites()), "a shared base no longer builds a grid"

    def test_every_grid_is_sized_from_a_canonical_symbol(self) -> None:
        offenders = [
            f"{path.relative_to(_REPO_ROOT).as_posix()}:{line} uses range({size})"
            for path, (line, size) in _grid_sites().items()
            if size not in _CANONICAL_SIZES
        ]
        assert not offenders, (
            "Slot grids must be sized from DEFAULT_MAX_WORKERS / "
            "WORKER_SLOT_COUNT / num_workers so they track the worker default "
            "(PLAN D56): " + "; ".join(offenders)
        )

    def test_every_grid_is_owned_by_a_manifest_tool_or_a_shared_base(self) -> None:
        owned = {entry.resolve() for entry in _manifest_tools().values()}
        shared = {
            (_REPO_ROOT / module_path).resolve()
            for module_path, _ in _SHARED_BASES.values()
        }
        for path in _grid_sites():
            assert path in owned or path in shared, (
                f"{path.relative_to(_REPO_ROOT).as_posix()} builds a slot grid but "
                "is neither a manifest tool's entry module nor a shared base — "
                "register the tool (tool_plugin.py) or move the grid into a base"
            )

    def test_every_manifest_tool_is_accounted_for(self) -> None:
        """Each tool either owns a grid, inherits one, or has no slot grid."""
        missing: list[str] = []
        for tool_id, entry in sorted(_manifest_tools().items()):
            if entry.resolve() in _grid_sites():
                continue
            if set(_app_bases(entry)) & set(_SHARED_BASES):
                continue
            if "slot_vars" in entry.read_text(encoding="utf-8"):
                missing.append(f"{tool_id} ({entry.name})")
        assert not missing, (
            "tools referencing slot_vars without an owned or inherited grid: "
            + ", ".join(missing)
        )


class TestTypedWorkerCountIsCapped:
    """A GUI that takes a typed worker count must clamp it before persisting."""

    def test_the_scan_finds_typed_worker_inputs(self) -> None:
        """An empty scan fails loudly; every site is owned like a grid."""
        sites = _typed_worker_sites()
        assert len(sites) >= 5, "typed worker-input discovery collapsed: " + ", ".join(
            path.name for path in sites
        )
        names = {path.relative_to(_REPO_ROOT).as_posix() for path in sites}
        assert "audio_suite_shared/analysis_app_base.py" in names, names

        owned = {entry.resolve() for entry in _manifest_tools().values()}
        shared = {
            (_REPO_ROOT / module_path).resolve()
            for module_path, _ in _SHARED_BASES.values()
        }
        for path in sites:
            assert path in owned or path in shared, (
                f"{path.relative_to(_REPO_ROOT).as_posix()} builds a typed worker "
                "count but is neither a manifest tool's entry module nor a shared "
                "base — register the tool (tool_plugin.py) so the cap lock covers "
                "it, or move the input into a shared base"
            )

    def test_worker_inputs_outside_the_entry_modules_are_rejected(self) -> None:
        """A worker field hidden in a UI submodule must not escape the lock."""
        stray = _stray_worker_vars()
        assert not stray, (
            "a typed worker input must live in the tool's entry module (``app.py``) "
            "or a shared base so the cap lock can see it; found: "
            + ", ".join(
                f"{path.relative_to(_REPO_ROOT).as_posix()}:{lines[0]}"
                for path, lines in stray.items()
            )
        )

    def test_every_typed_worker_count_is_capped_before_persistence(self) -> None:
        problems = [
            problem
            for path in _typed_worker_sites()
            for problem in _typed_worker_problems(path)
        ]
        assert not problems, (
            "typed worker counts must be capped with the shared helper on the "
            "main thread before the setting is saved (PLAN D66):\n  "
            + "\n  ".join(problems)
        )


# ── Runtime lock ─────────────────────────────────────────────────────────────


class TestGridMatchesProcessorDefault:
    """The GUI's grid and its processors must resolve the same worker count."""

    @pytest.mark.parametrize("tool_id", sorted(_own_grid_tools()))
    def test_grid_matches_processor_workers(self, tool_id: str) -> None:
        entry = _own_grid_tools()[tool_id]
        size_symbol = _grid_sites()[entry.resolve()][1]
        assert size_symbol == "DEFAULT_MAX_WORKERS", (
            f"{tool_id}: a tool-owned grid must use DEFAULT_MAX_WORKERS, "
            f"not {size_symbol}"
        )

        module = ".".join(entry.relative_to(_REPO_ROOT).with_suffix("").parts)
        app_module = importlib.import_module(module)
        grid_size = getattr(app_module, size_symbol)
        assert grid_size == default_max_workers(), (
            f"{tool_id}: grid {size_symbol}={grid_size} does not track "
            f"default_max_workers()={default_max_workers()}"
        )

        package = _REPO_ROOT / entry.relative_to(_REPO_ROOT).parts[0]
        specs = _processor_specs(package)
        assert specs, (
            f"{tool_id}: no BaseFileProcessor subclass found in {package.name}"
        )

        for module_name, class_name in specs:
            processor_cls: Any = getattr(
                importlib.import_module(module_name), class_name
            )
            signature = inspect.signature(processor_cls)
            assert all(
                parameter.default is not inspect.Parameter.empty
                for parameter in signature.parameters.values()
            ), f"{tool_id}: {class_name} needs constructor arguments"
            processor = processor_cls()
            assert processor.max_workers == grid_size, (
                f"{tool_id}: {class_name} resolves {processor.max_workers} workers "
                f"for {grid_size} display slots"
            )

    @pytest.mark.parametrize("tool_id", sorted(_base_grid_tools()))
    def test_base_provided_grid_resolves_the_default(self, tool_id: str) -> None:
        base_name = _base_grid_tools()[tool_id]
        module_path, symbol = _SHARED_BASES[base_name]

        if base_name == "BaseSuiteApp":
            from audio_suite_shared.app_bootstrap import BaseSuiteApp

            parameters = inspect.signature(BaseSuiteApp.__init__).parameters
            assert parameters["num_workers"].default is None, (
                f"{tool_id}: {base_name} must resolve num_workers at construction "
                "so its grid is not frozen at an earlier CPU count"
            )
            return

        module_name = module_path.removesuffix(".py").replace("/", ".")
        module = importlib.import_module(module_name)
        grid_size = getattr(module, symbol)
        assert grid_size == default_max_workers(), (
            f"{tool_id}: {base_name}.{symbol}={grid_size} does not track "
            f"default_max_workers()={default_max_workers()}"
        )

    def test_shared_analysis_grid_tracks_the_default(self) -> None:
        import audio_suite_shared.analysis_app_base as base

        assert base.WORKER_SLOT_COUNT == base.DEFAULT_MAX_WORKERS
        assert base.WORKER_SLOT_COUNT == default_max_workers()

    def test_shared_tag_tool_grid_tracks_the_default(self) -> None:
        import audio_suite_shared.tool_app_base as base

        assert base.DEFAULT_MAX_WORKERS == default_max_workers()
