"""Stage the documentation site: one build, one copy list, one publish root.

The rendered pages link repository files with a checkout-relative prefix -
``documentation/docs/index.md`` names ``../../README.md`` and
``documentation/docs/user/security.md`` names ``../../../SECURITY.md`` - and
Sphinx keeps a page's depth in the output, so those hrefs only resolve when the
publish root has the same shape as the checkout. This module builds the site and
stages that shape:

```text
documentation/docs/_build/
    index.html              redirect to documentation/docs/ (front door of a zip)
    documentation/docs/     the Sphinx output
    documentation/user_guides/  copied, because every tool row links
                            ../user_guides/... from a page one level down
    packaging/              copied, because the index links ../../packaging/...
    README.md  CHANGELOG.md  CONTRIBUTING.md  SECURITY.md
```

Two callers share it, and that is the point: CI runs
``python utilities/build_docs_site.py`` and publishes the result, and
``tests/test_docs_build.py::TestPublishedTreeIsSelfContained`` runs the same
function and walks every emitted link. A copy list written twice would drift,
and the lock would then certify a tree nobody publishes (PLAN_feature_expansion
D7).

The doctrees directory is deliberately **outside** the publish root: a plain
``sphinx-build`` with no ``-d`` writes ``.doctrees`` *inside* the output
directory (1.9 MB of pickles at 2.1.0), which would otherwise ship in the
artifact and, under a static host, be served at ``/html/.doctrees/`` (D8).

This module does not judge Sphinx warnings. ``tests/test_docs_build.py`` is the
gate that turns a parser warning into a failure, and it runs before this step in
CI; a second verdict here could disagree with it.

Build it with the interpreter that carries the ``dev`` extra::

    python utilities/build_docs_site.py
    python utilities/build_docs_site.py --out /tmp/site   # elsewhere

Changed in 2.1.1: new module - the staging step shared by CI and the
self-containment lock (PLAN_feature_expansion.md D7, D8). ``AGENTS.md`` is not
staged: it is the repository's instruction file for people working in the
checkout, not an end-user document, and the artifact is handed to whoever opens
the zip (D13).

Changed in 2.1.7: the publish root mirrors the checkout: pages at
``documentation/docs/``, guides at ``documentation/user_guides/``.

"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

#: The checkout root; this module lives in ``utilities/``.
REPO_ROOT = Path(__file__).resolve().parents[1]

#: Repository files the rendered pages link to, copied to the publish root.
#: ``AGENTS.md`` is deliberately absent: ``docs/index.md`` no longer cites it,
#: and the repository's instruction file is not an end-user document (D13).
STAGED_FILES: tuple[str, ...] = (
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
)

#: Directories copied wholesale into the publish root, keyed by their
#: repository-relative path so the published tree keeps the checkout's shape.
#: ``documentation/user_guides`` is what a page at
#: ``documentation/docs/<page>.html`` reaches with ``../user_guides/...``.
STAGED_DIRS: tuple[str, ...] = ("documentation/user_guides", "packaging")

#: Written at the publish root so the artifact opens at its front door. A bare
#: project URL has no index page of its own and the pages live in ``html/``.
ROOT_REDIRECT = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AudioSuite-Pro documentation</title>
<meta http-equiv="refresh" content="0; url=documentation/docs/">
<link rel="canonical" href="documentation/docs/">
</head>
<body>
<p>The documentation is at <a href="documentation/docs/">documentation/docs/</a>.</p>
</body>
</html>
"""


def build_site(root: Path, out: Path) -> int:
    """Build the Sphinx source into ``<out>/documentation/docs``.

    The output keeps the checkout's depth below the publish root, so a page's
    ``../../README.md`` reaches the staged copy at ``<out>/README.md``.

    Args:
        root: The repository root.
        out: The publish root; the HTML lands in its ``html`` subdirectory.

    Returns:
        The number of rendered ``.html`` pages.

    Raises:
        RuntimeError: If Sphinx is missing or the build fails.
    """
    html = out / "documentation" / "docs"
    if html.exists():
        shutil.rmtree(html)
    doctrees = Path(tempfile.mkdtemp(prefix="audiosuite-doctrees-"))
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "sphinx",
                "-b",
                "html",
                "-q",
                "-d",
                str(doctrees),
                str(root / "documentation" / "docs"),
                str(html),
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    finally:
        shutil.rmtree(doctrees, ignore_errors=True)
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip()
        raise RuntimeError(
            f"sphinx exited {result.returncode}; is the dev extra installed?\n{detail}"
        )
    # Warnings are the gate's business, but printing them here keeps a manual
    # run honest: a warning-free build is silence.
    warnings = result.stderr.strip()
    if warnings:
        print(f"[INFO] sphinx reported:\n{warnings}")
    pages = sorted(html.rglob("*.html"))
    if not pages:
        raise RuntimeError(f"the build wrote no pages under {html}")
    return len(pages)


def stage(root: Path, out: Path) -> Path:
    """Build the site and stage every target its pages link to.

    Args:
        root: The repository root.
        out: The publish root, created if needed.

    Returns:
        The publish root, for the caller's own assertions.

    Raises:
        RuntimeError: If the build fails or a staged target is missing.
        OSError: If a copy fails.
    """
    out.mkdir(parents=True, exist_ok=True)
    pages = build_site(root, out)
    print(f"[OK] built {pages} pages into {out / 'documentation' / 'docs'}")

    for name in STAGED_FILES:
        source = root / name
        if not source.is_file():
            raise RuntimeError(f"cannot stage {name}: {source} does not exist")
        shutil.copy2(source, out / name)
        print(f"[OK] staged {name}")

    for name in STAGED_DIRS:
        source = root / name
        if not source.is_dir():
            raise RuntimeError(f"cannot stage {name}/: {source} does not exist")
        target = out / name
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
        print(f"[OK] staged {name}/")

    (out / "index.html").write_text(ROOT_REDIRECT, encoding="utf-8", newline="\n")
    print("[OK] wrote index.html (redirect to documentation/docs/)")
    return out


def main(argv: list[str] | None = None) -> int:
    """Run the staging step.

    Args:
        argv: Command-line arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        ``0`` on success, ``1`` when the build or a copy fails.
    """
    parser = argparse.ArgumentParser(
        description="Build the documentation site and stage its publish tree."
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Publish root (default: <root>/documentation/docs/_build)",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: this checkout)",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else REPO_ROOT
    out = (
        Path(args.out).resolve()
        if args.out
        else root / "documentation" / "docs" / "_build"
    )

    print(f"[START] staging the documentation site into {out}")
    try:
        stage(root, out)
    except (OSError, RuntimeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    print("[DONE]")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
