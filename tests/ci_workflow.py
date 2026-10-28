"""Slice the CI workflow into jobs and steps for structure locks.

A text lock that reads the whole workflow cannot tell "the *security* job has
the audit step" from "some job does", and a slice that silently comes back
empty passes every assertion built on it. These helpers return the block and
assert it is non-empty, so a renamed job or step fails loudly at the call site
instead of turning a lock vacuous.

Both the dependency-audit lock (D96) and the payload-artifact lock (D103) read
the workflow this way; sharing the slicer keeps them agreeing about where one
job ends and the next begins.

Changed in 1.4.1: initial version, extracted from the D96 workflow lock when
the D103 artifact lock needed the same slicing.
Changed in 1.4.1: ``action()`` slices a step by its ``uses:`` value, because
the artifact upload step has no ``name:`` to key on.
Changed in 2.1.6: ``job_names()`` enumerates the jobs, so the cost ledger
(R-17) can assert it prices every one of them instead of only the ones it
remembered to name.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The workflow the structure locks inspect.
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def workflow_text(path: Path | None = None) -> str:
    """Return the workflow file's text."""
    source = WORKFLOW if path is None else path
    return source.read_text(encoding="utf-8")


def job_names(path: Path | None = None) -> tuple[str, ...]:
    """Return every job id in the workflow, in file order.

    The search starts at the ``jobs:`` key, because the trigger block's members
    (``push``, ``pull_request``) are also two-space-indented keys and would
    otherwise be read as jobs.

    Raises:
        AssertionError: if the workflow has no ``jobs:`` block or declares no
            job - an empty tuple would let a lock over "every job" pass
            vacuously.
    """
    text = workflow_text(path)
    block = re.search(r"^jobs:\s*$", text, re.MULTILINE)
    assert block is not None, "the workflow has no jobs: block"
    names = tuple(
        re.findall(r"^  ([A-Za-z0-9_-]+):\s*$", text[block.end() :], re.MULTILINE)
    )
    assert names, "the workflow declares no jobs"
    return names


def job(name: str, path: Path | None = None) -> str:
    """Return the YAML block for job *name* (a 2-space-indented key).

    Raises:
        AssertionError: if the job is missing or the block is empty - a lock
            reading ``""`` would pass every assertion below.
    """
    text = workflow_text(path)
    match = re.search(rf"^  {re.escape(name)}:\s*$", text, re.MULTILINE)
    assert match is not None, f"ci.yml has no {name!r} job"
    start = match.start()
    following = re.search(r"^  [A-Za-z0-9_-]+:\s*$", text[match.end() :], re.MULTILINE)
    end = match.end() + following.start() if following else len(text)
    block = text[start:end]
    assert block.strip(), f"ci.yml's {name!r} job parsed as empty"
    return block


def step(job_block: str, name: str) -> str:
    """Return the YAML block for the named step inside *job_block*."""
    match = re.search(rf"^      - name: {re.escape(name)}\s*$", job_block, re.MULTILINE)
    assert match is not None, f"the job has no step named {name!r}"
    start = match.start()
    following = re.search(r"^      - ", job_block[match.end() :], re.MULTILINE)
    end = match.end() + following.start() if following else len(job_block)
    block = job_block[start:end]
    assert block.strip(), f"step {name!r} parsed as empty"
    return block


def action(job_block: str, name: str) -> str:
    """Return the YAML block for the step that uses action *name*.

    Args:
        job_block: A job's text, as :func:`job` returns.
        name: The ``uses:`` value, e.g. ``actions/upload-artifact@v4``.

    Returns:
        The step's block, from ``- uses:`` to the next step.

    Raises:
        AssertionError: if the action is absent or the block is empty.
    """
    match = re.search(rf"^      - uses: {re.escape(name)}\s*$", job_block, re.MULTILINE)
    assert match is not None, f"the job has no step using {name!r}"
    start = match.start()
    following = re.search(r"^      - ", job_block[match.end() :], re.MULTILINE)
    end = match.end() + following.start() if following else len(job_block)
    block = job_block[start:end]
    assert block.strip(), f"the step using {name!r} parsed as empty"
    return block
