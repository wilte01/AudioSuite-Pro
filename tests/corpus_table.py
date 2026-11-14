"""The one parser for a corpus declaration table.

`tests/data/bpm_corpus/ATTRIBUTION.md` and `tests/data/key_corpus/ATTRIBUTION.md`
are the source of truth for their corpora: the expectations live in the
`## Clips` table, not in a Python dict, so a recording cannot be deleted while
its annotation stays behind and a recording the gate refuses keeps an honest
row (BPM D99; key D147).

One parser, because two copies of a table reader is the same defect class the
suite forbids elsewhere: the second copy drifts in separator handling, and only
one of them gets the "malformed row must fail loudly" rule. The caller supplies
the heading and a file name for the failure messages.

Changed in 2.7.0: extracted from `bpm_analyzer/tests/test_bpm_detector.py` when
the key corpus needed the same parser (D147).
"""

from __future__ import annotations


def pipe_rows(
    markdown: str, heading: str, *, name: str = "ATTRIBUTION.md"
) -> list[dict[str, str]]:
    """Return the first pipe table under *heading*, keyed by its header cells.

    Args:
        markdown: The ATTRIBUTION.md text.
        heading:  The heading line the table sits under, e.g. ``"## Clips"``.
        name:     File name used in failure messages.

    Returns:
        One dict per data row, mapping header cell to cell text.  The
        ``|---|---|`` separator is skipped.

    Raises:
        AssertionError: If the heading or a table under it is missing, or a row
            does not have the header's column count - a malformed table must
            fail loudly rather than parse into a shorter corpus.
    """
    lines = markdown.splitlines()
    assert heading in lines, (
        f"{heading!r} heading missing from {name} - the table "
        "is the suite's source of truth"
    )
    start = lines.index(heading)
    table: list[list[str]] = []
    for line in lines[start + 1 :]:
        if line.startswith("|"):
            table.append([cell.strip() for cell in line.strip().strip("|").split("|")])
        elif table:
            break
    assert len(table) >= 2, f"no pipe table under {heading!r}"

    header = table[0]
    rows: list[dict[str, str]] = []
    for row in table[1:]:
        if all(cell and set(cell) <= set("-: ") for cell in row):
            continue
        assert len(row) == len(header), (
            f"malformed row under {heading!r}: {len(row)} cells for "
            f"{len(header)} columns: {row}"
        )
        rows.append(dict(zip(header, row, strict=True)))
    return rows
