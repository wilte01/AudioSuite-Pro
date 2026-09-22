"""
log_builder.py
Assembles the categorised Genre Sync log from four result buckets.

Pure function — no tkinter, no file I/O.
"""


def build_log_lines(
    is_dry_run: bool,
    total: int,
    updated_count: int,
    skipped_count: int,
    no_genre_count: int,
    error_count: int,
    duration_secs: float,
    log_updated: list[str],
    log_skipped: list[str],
    log_no_genre: list[str],
    log_errors: list[str],
) -> list[str]:
    """
    Build the full log as a list of strings ready for writelines().

    Returns the assembled lines; caller is responsible for writing to disk.
    """
    minutes = int(duration_secs // 60)
    seconds = int(duration_secs % 60)

    lines: list[str] = [
        "GENRE SYNC REPORT\n",
        f"Mode: {'DRY RUN' if is_dry_run else 'LIVE UPDATE'}\n",
        "=" * 60 + "\n\n",
    ]

    if log_updated:
        label = "WOULD UPDATE" if is_dry_run else "UPDATED"
        lines.append(f"{label} ({len(log_updated)} files):\n")
        lines.append("-" * 60 + "\n")
        lines.extend(log_updated)
        lines.append("\n")

    if log_skipped:
        lines.append(f"SKIPPED - Already Correct ({len(log_skipped)} files):\n")
        lines.append("-" * 60 + "\n")
        lines.extend(log_skipped)
        lines.append("\n")

    if log_no_genre:
        lines.append(f"NO GENRE FIELDS AVAILABLE ({len(log_no_genre)} files):\n")
        lines.append("-" * 60 + "\n")
        lines.extend(log_no_genre)
        lines.append("\n")

    if log_errors:
        lines.append(f"ERRORS ({len(log_errors)} files):\n")
        lines.append("-" * 60 + "\n")
        lines.extend(log_errors)
        lines.append("\n")

    lines += [
        "=" * 60 + "\n",
        "SUMMARY:\n",
        f"Total files: {total}\n",
        f"{'Would update' if is_dry_run else 'Updated'}: {updated_count}\n",
        f"Skipped (already correct): {skipped_count}\n",
        f"No genre fields: {no_genre_count}\n",
        f"Errors: {error_count}\n",
        f"Time: {minutes:02d}:{seconds:02d}\n",
    ]

    return lines
