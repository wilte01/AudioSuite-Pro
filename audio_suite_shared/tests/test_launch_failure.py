"""Tests for audio_suite_shared.launch_failure.

The record exists so the Master Driver's failure dialog can say *why* a tool
refused to start instead of only its exit code
(PLAN_2026-11-03_2.4.3_structure.md D-22).  These tests hold the properties the
dialog depends on: the key is the launcher name both processes hold, a record
is bounded and one-line, and a missing, unreadable or malformed record reads as
"no reason" instead of raising into the report.

Changed in 2.4.3: initial version (D-22).
"""

import json

from audio_suite_shared.launch_failure import (
    MAX_REASON_CHARS,
    clear_launch_failure,
    failure_path,
    read_launch_failure,
    record_launch_failure,
)


class TestRecordRoundTrip:
    def test_reason_is_read_back(self):
        record_launch_failure(
            "Library_Stats.pyw",
            "Library Statistics: Folder path does not exist: D:/gone",
        )
        assert (
            read_launch_failure("Library_Stats.pyw")
            == "Library Statistics: Folder path does not exist: D:/gone"
        )

    def test_key_is_the_script_name_not_its_folder(self):
        """The launcher holds ``sys.argv[0]``, the driver a full path.

        Both resolve to the same stem, which is what keeps the record findable
        without either side sharing a manifest id.
        """
        record_launch_failure(
            r"D:\Users\wilte\Desktop\AudioSuite-Pro\Library_Stats.pyw",
            "Folder path does not exist: D:/gone",
        )
        assert "D:/gone" in read_launch_failure("Library_Stats.pyw")

    def test_key_ignores_case(self):
        """A differently-cased invocation must still find its record."""
        record_launch_failure("Library_Stats.pyw", "Folder path does not exist")
        assert read_launch_failure("library_stats.pyw") == "Folder path does not exist"

    def test_separate_launchers_do_not_share_a_record(self):
        record_launch_failure("Library_Stats.pyw", "stats reason")
        record_launch_failure("BPM_Analyzer.pyw", "bpm reason")
        assert read_launch_failure("Library_Stats.pyw") == "stats reason"
        assert read_launch_failure("BPM_Analyzer.pyw") == "bpm reason"

    def test_clear_forgets_the_reason(self):
        record_launch_failure("Library_Stats.pyw", "Folder path does not exist")
        clear_launch_failure("Library_Stats.pyw")
        assert read_launch_failure("Library_Stats.pyw") == ""

    def test_clear_is_safe_without_a_record(self):
        clear_launch_failure("Never_Ran.pyw")
        assert read_launch_failure("Never_Ran.pyw") == ""


class TestReasonText:
    def test_reason_is_one_line(self):
        record_launch_failure("Library_Stats.pyw", "Folder path does\nnot exist: X")
        assert (
            read_launch_failure("Library_Stats.pyw") == "Folder path does not exist: X"
        )

    def test_reason_is_bounded(self):
        record_launch_failure("Library_Stats.pyw", "x" * (MAX_REASON_CHARS * 2))
        reason = read_launch_failure("Library_Stats.pyw")
        assert len(reason) == MAX_REASON_CHARS
        assert reason.endswith("...")

    def test_blank_reason_records_nothing(self):
        """A blank reason clears the record rather than leaving an older one."""
        record_launch_failure("Library_Stats.pyw", "an older reason")
        assert record_launch_failure("Library_Stats.pyw", "   \n\t") == ""
        assert not failure_path("Library_Stats.pyw").exists()


class TestDamagedRecord:
    def test_missing_record_reads_as_no_reason(self):
        assert read_launch_failure("Never_Ran.pyw") == ""

    def test_malformed_json_reads_as_no_reason(self):
        path = failure_path("Library_Stats.pyw")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        assert read_launch_failure("Library_Stats.pyw") == ""

    def test_payload_without_a_reason_reads_as_none(self):
        path = failure_path("Library_Stats.pyw")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"launcher": "Library_Stats.pyw"}), encoding="utf-8")
        assert read_launch_failure("Library_Stats.pyw") == ""
