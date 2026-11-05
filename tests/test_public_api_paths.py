"""The pre-split import paths still resolve (WP-9).

`audio_suite_shared.ui_common` was split into `ui_tabs`, `ui_rows`,
`ui_dialogs` and `ui_presets`, and `audio_suite_shared.file_processor_base`
was split into `file_discovery`, `parallel_pool`, `inplace_workflow` and
`reporting`.  Every existing importer must keep working, so each facade must
still expose every moved name.  The lists are frozen rather than derived, so a
name that silently stops being re-exported fails here instead of in a tool at
launch.  Each test also asserts the facade points at the *same object*: a
copied definition would drift from the real one.

Changed in 2.4.3: initial version (WP-9 #1); extended for the
`file_processor_base` split (WP-9 #2).
"""

import pytest

from audio_fingerprinter.core import file_processor as fingerprint_module
from audio_suite_shared import batch_undo, file_processor_base, ui_common

#: name -> module that now owns the implementation, behind `ui_common`.
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

#: name -> module that now owns the implementation, behind `file_processor_base`.
PROCESSOR_BASE_NAMES: dict[str, str] = {
    "CompleteCallback": "reporting",
    "ErrorCallback": "reporting",
    "InplaceDspFn": "inplace_workflow",
    "InplaceDspResult": "inplace_workflow",
    "InplaceWorkerFactory": "inplace_workflow",
    "ProgressCallback": "reporting",
    "_emit_completion": "reporting",
    "_preflight_discover": "reporting",
}


#: name -> module that now owns the implementation, behind `batch_undo`.
UNDO_NAMES: dict[str, str] = {
    "BatchInfo": "undo_records",
    "RevertResult": "undo_records",
    "UndoRecord": "undo_records",
    "UndoRecordsMixin": "undo_records",
    "UndoRevertMixin": "undo_revert",
    "_AUTO_VACUUM_FULL": "undo_schema",
    "_DEFAULT_MAX_BYTES": "undo_records",
    "_DEFAULT_MAX_ENTRIES": "undo_records",
    "_SCHEMA_SQL": "undo_schema",
    "_load_max_bytes": "undo_records",
    "_load_max_entries": "undo_records",
}


#: name -> module that now owns it, behind the fingerprinter's file_processor.
FINGERPRINT_NAMES: dict[str, str] = {
    "_MESSAGE_STATUSES": "fingerprint_messages",
    "_apply_album_decision": "fingerprint_phases",
    "_commit_match_tags": "fingerprint_tags",
    "_finalize_album_file": "fingerprint_phases",
    "_match_message": "fingerprint_messages",
    "_release_facts_for": "fingerprint_tags",
    "_result_display": "fingerprint_messages",
    "_run_album_phase": "fingerprint_phases",
    "_run_isrc_submission": "fingerprint_phases",
    "_write_isrc_for": "fingerprint_tags",
    "_write_mbids_for": "fingerprint_tags",
    "collect_isrc_submissions": "fingerprint_phases",
}


def test_the_frozen_lists_are_not_empty() -> None:
    assert MOVED_NAMES
    assert PROCESSOR_BASE_NAMES
    assert UNDO_NAMES
    assert FINGERPRINT_NAMES


@pytest.mark.parametrize("name", sorted(MOVED_NAMES))
def test_moved_name_still_resolves_from_ui_common(name: str) -> None:
    assert hasattr(ui_common, name), f"{name} is no longer re-exported"


@pytest.mark.parametrize(("name", "module"), sorted(MOVED_NAMES.items()))
def test_moved_name_is_the_new_modules_object(name: str, module: str) -> None:
    home = __import__(f"audio_suite_shared.{module}", fromlist=[name])
    assert getattr(ui_common, name) is getattr(home, name)


@pytest.mark.parametrize("name", sorted(PROCESSOR_BASE_NAMES))
def test_moved_name_still_resolves_from_file_processor_base(name: str) -> None:
    assert hasattr(file_processor_base, name), f"{name} is no longer re-exported"


@pytest.mark.parametrize(("name", "module"), sorted(PROCESSOR_BASE_NAMES.items()))
def test_moved_name_is_the_new_pipeline_modules_object(name: str, module: str) -> None:
    home = __import__(f"audio_suite_shared.{module}", fromlist=[name])
    assert getattr(file_processor_base, name) is getattr(home, name)


@pytest.mark.parametrize("name", sorted(UNDO_NAMES))
def test_moved_name_still_resolves_from_batch_undo(name: str) -> None:
    assert hasattr(batch_undo, name), f"{name} is no longer re-exported"


@pytest.mark.parametrize(("name", "module"), sorted(UNDO_NAMES.items()))
def test_moved_name_is_the_new_undo_modules_object(name: str, module: str) -> None:
    home = __import__(f"audio_suite_shared.{module}", fromlist=[name])
    assert getattr(batch_undo, name) is getattr(home, name)


@pytest.mark.parametrize("name", sorted(FINGERPRINT_NAMES))
def test_moved_name_still_resolves_from_the_fingerprint_processor(name: str) -> None:
    assert hasattr(fingerprint_module, name), f"{name} is no longer re-exported"


@pytest.mark.parametrize(("name", "module"), sorted(FINGERPRINT_NAMES.items()))
def test_moved_name_is_the_new_fingerprint_modules_object(
    name: str, module: str
) -> None:
    home = __import__(f"audio_fingerprinter.core.{module}", fromlist=[name])
    assert getattr(fingerprint_module, name) is getattr(home, name)
