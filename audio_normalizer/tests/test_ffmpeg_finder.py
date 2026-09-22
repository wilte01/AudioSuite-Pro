# -*- coding: utf-8 -*-
"""Startupinfo helper behavior (canonical: audio_suite_shared.subprocess_utils)."""

from unittest.mock import patch

from audio_suite_shared.subprocess_utils import get_startupinfo


class TestGetStartupinfo:
    def test_returns_startupinfo_on_windows(self) -> None:
        si = get_startupinfo()
        assert si is not None

    def test_returns_none_on_non_windows(self) -> None:
        with patch(
            "audio_suite_shared.subprocess_utils.os.name",
            "posix",
        ):
            result = get_startupinfo()
        assert result is None
