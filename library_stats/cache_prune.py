"""
cache_prune.py - whole-cache clearing and the completeness trend (2.4.3).

WP-9 #5 moved these methods off ``LibraryCache`` into ``CachePruneMixin``;
bodies are unchanged and ``library_cache`` still re-exports every name.

Changed in 2.4.3: split out of ``library_stats.library_cache``
(PLAN_2026-11-03_2.4.3_structure.md WP-9).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

from .cache_schema import _path_fold

logger = logging.getLogger(f"audio_suite.{__name__}")

_HISTORY_SNAPSHOTS = 100


class CachePruneMixin:
    """Whole-cache clearing and the completeness trend half of ``LibraryCache``."""

    _conn: sqlite3.Connection | None
    _path: Path
    _scope_plans: dict[str, str]

    def invalidate_scope_plans(self) -> None:
        """Provided by ``CacheStoreMixin``, composed ahead of this one."""
        raise NotImplementedError

    def _path_prefix(self, dir_path: str) -> str:
        """Provided by ``CacheStoreMixin``, composed ahead of this one."""
        raise NotImplementedError

    def _connect(self) -> sqlite3.Connection:
        """Provided by ``LibraryCache`` itself; composed ahead of this mixin."""
        raise NotImplementedError

    def _commit(self) -> None:
        """Provided by ``LibraryCache`` itself; composed ahead of this mixin."""
        raise NotImplementedError

    def clear_all(self) -> None:
        """Delete every row in the cache."""
        conn = self._connect()
        conn.execute("DELETE FROM files")
        self._commit()
        # Every scope is now empty, so every remembered ratio is meaningless.
        self.invalidate_scope_plans()

    def record_completeness_snapshot(self, report: Any) -> bool:
        """Store one completeness snapshot for its directory.

        Consecutive duplicates are suppressed: opening the dashboard (or
        re-running ``--completeness``) without touching a file must not pad the
        trend series with identical points.  Only the newest
        ``_HISTORY_SNAPSHOTS`` rows per directory are kept.

        Args:
            report: A ``CompletenessReport`` (anything exposing ``directory``,
                ``total_files``, ``overall_pct`` and ``tag_results``).

        Returns:
            True when a row was written, False when it was a duplicate.
        """
        conn = self._connect()
        scope = _path_fold(self._path_prefix(report.directory))
        tag_pcts = {name: tc.pct_complete for name, tc in report.tag_results.items()}
        payload = json.dumps(tag_pcts, sort_keys=True)

        last = conn.execute(
            "SELECT total_files, tag_pcts FROM completeness_history "
            "WHERE path_fold = ? ORDER BY id DESC LIMIT 1",
            [scope],
        ).fetchone()
        if (
            last is not None
            and int(last[0]) == int(report.total_files)
            and last[1] == payload
        ):
            return False

        conn.execute(
            "INSERT INTO completeness_history "
            "(path_fold, path, total_files, overall_pct, tag_pcts) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                scope,
                os.path.normpath(str(report.directory)),
                int(report.total_files),
                float(report.overall_pct),
                payload,
            ],
        )
        conn.execute(
            "DELETE FROM completeness_history "
            "WHERE path_fold = ? AND id NOT IN ("
            "    SELECT id FROM completeness_history WHERE path_fold = ? "
            "    ORDER BY id DESC LIMIT ?"
            ")",
            [scope, scope, _HISTORY_SNAPSHOTS],
        )
        self._commit()
        return True

    def completeness_history(
        self, dir_path: str, limit: int = 12
    ) -> list[dict[str, Any]]:
        """Return up to *limit* snapshots for *dir_path*, oldest first.

        Oldest-first is the order a time-series chart needs; the newest
        *limit* rows are selected, then reversed so a chart's x-axis runs
        left to right in time.
        """
        conn = self._connect()
        scope = _path_fold(self._path_prefix(dir_path))
        rows = conn.execute(
            "SELECT recorded_at, total_files, overall_pct, tag_pcts "
            "FROM completeness_history WHERE path_fold = ? "
            "ORDER BY id DESC LIMIT ?",
            [scope, max(1, int(limit))],
        ).fetchall()
        history: list[dict[str, Any]] = []
        for recorded_at, total_files, overall_pct, tag_pcts in reversed(rows):
            try:
                parsed = json.loads(tag_pcts)
            except (TypeError, ValueError):
                parsed = {}
            history.append(
                {
                    "recorded_at": recorded_at,
                    "total_files": int(total_files),
                    "overall_pct": float(overall_pct),
                    "tag_pcts": parsed if isinstance(parsed, dict) else {},
                }
            )
        return history

    def clear_completeness_history(self, dir_path: str | None = None) -> int:
        """Delete stored snapshots (all of them, or one directory's)."""
        conn = self._connect()
        if dir_path is None:
            cur = conn.execute("DELETE FROM completeness_history")
        else:
            scope = _path_fold(self._path_prefix(dir_path))
            cur = conn.execute(
                "DELETE FROM completeness_history WHERE path_fold = ?", [scope]
            )
        self._commit()
        return int(cur.rowcount or 0)
