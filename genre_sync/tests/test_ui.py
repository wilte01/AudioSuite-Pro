"""
Tests for genre_sync.ui modules — setup_tab, results_tab, processing_tab.

These are thin wrappers around shared widgets. Tests verify the correct
shared builder is called with the right tool-specific arguments.
"""

from unittest.mock import MagicMock, patch


class TestSetupTab:
    @staticmethod
    def _build_kwargs():
        return dict(
            folder_path=MagicMock(),
            run_mode=MagicMock(),
            auto_start_var=MagicMock(),
            auto_end_var=MagicMock(),
            clear_logs_var=MagicMock(),
            parallel_var=MagicMock(),
            on_browse=MagicMock(),
            on_start=MagicMock(),
        )

    def test_build_returns_widgets_dict(self):
        from genre_sync.ui.setup_tab import build

        parent = MagicMock()
        parent.pack = MagicMock()
        widgets = build(parent=parent, **self._build_kwargs())
        assert isinstance(widgets, dict)
        assert set(widgets) == {
            "start_btn",
            "refresh_preset_list",
            "preset_combo",
            "controls_panel",
        }

    def test_build_accepts_required_parameters(self):
        from genre_sync.ui.setup_tab import build

        parent = MagicMock()
        parent.pack = MagicMock()
        widgets = build(parent=parent, **self._build_kwargs())
        assert widgets["start_btn"] is not None
        assert callable(widgets["refresh_preset_list"])


class TestResultsTab:
    def test_build_returns_dict_with_correct_text(self):
        with patch("genre_sync.ui.results_tab.build_results_tab") as mock_builder:
            mock_builder.return_value = {"completion_label": MagicMock()}

            from genre_sync.ui.results_tab import build

            parent = MagicMock()
            on_open_log = MagicMock()
            on_open_folder = MagicMock()
            build(
                parent=parent,
                on_open_log=on_open_log,
                on_open_folder=on_open_folder,
            )
            mock_builder.assert_called_once()
            assert (
                mock_builder.call_args[1]["completion_text"] == "Processing Complete!"
            )
            assert mock_builder.call_args[1]["on_open_log"] is on_open_log
            assert mock_builder.call_args[1]["on_open_folder"] is on_open_folder


class TestProcessingTab:
    def test_build_calls_build_processing_tab(self):
        with patch("genre_sync.ui.processing_tab.build_processing_tab") as mock_builder:
            mock_builder.return_value = {"overall_status": MagicMock()}

            from genre_sync.ui.processing_tab import build

            parent = MagicMock()
            slot_vars = [MagicMock() for _ in range(4)]
            build(parent=parent, slot_vars=slot_vars)
            mock_builder.assert_called_once_with(
                parent,
                slot_vars,
                stats_text="Processed: 0 | Updated: 0 | Skipped: 0 | Errors: 0",
            )

    def test_build_default_slot_vars(self):
        with patch("genre_sync.ui.processing_tab.build_processing_tab") as mock_builder:
            mock_builder.return_value = {"overall_status": MagicMock()}

            from genre_sync.ui.processing_tab import build

            parent = MagicMock()
            build(parent=parent, slot_vars=None)
            mock_builder.assert_called_once()
            # Should pass None for slot_vars
            assert mock_builder.call_args[0][1] is None
