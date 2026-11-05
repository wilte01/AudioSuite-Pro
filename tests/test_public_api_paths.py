"""The pre-split import paths still resolve (WP-9).

`audio_suite_shared.ui_common` was split into `ui_tabs`, `ui_rows`,
`ui_dialogs` and `ui_presets`, and every existing importer
(`from audio_suite_shared.ui_common import X`) must keep working.  The list is
frozen rather than derived, so a name that silently stops being re-exported
fails here instead of in a tool at launch.  It also asserts the facade points
at the *same object*: a copied definition would drift from the real one.

Changed in 2.4.3: initial version (WP-9).
"""

import pytest

from audio_suite_shared import ui_common

#: name -> module that now owns the implementation.
MOVED_NAMES: dict[str, str] = {
    "_default_open_log": "ui_tabs",
    "build_processing_tab": "ui_tabs",
    "build_results_tab": "ui_tabs",
    "delete_preset_action": "ui_presets",
    "discrete_slider_row": "ui_rows",
    "load_preset_names": "ui_presets",
    "path_row": "ui_rows",
    "save_preset_dialog": "ui_presets",
    "slider_row": "ui_rows",
    "show_message": "ui_dialogs",
}


def test_the_frozen_list_is_not_empty() -> None:
    assert MOVED_NAMES


@pytest.mark.parametrize("name", sorted(MOVED_NAMES))
def test_moved_name_still_resolves_from_ui_common(name: str) -> None:
    assert hasattr(ui_common, name), f"{name} is no longer re-exported"


@pytest.mark.parametrize(("name", "module"), sorted(MOVED_NAMES.items()))
def test_moved_name_is_the_new_modules_object(name: str, module: str) -> None:
    home = __import__(f"audio_suite_shared.{module}", fromlist=[name])
    assert getattr(ui_common, name) is getattr(home, name)
