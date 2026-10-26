"""
Tests for audio_suite_shared.secure_subprocess
Gap G-18: validate_executable, validate_script_path, validate_arguments,
          run_secure_subprocess, run_secure_popen

Security-critical: injection attempts, allowlist bypass, happy paths.

Changed in 2.1.4: covers the ``text`` parameter, which lets a binary stream
(the enhancer's raw PCM decode) use the wrapper (audit R-08, plan C3).
"""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import audio_suite_shared.secure_subprocess as ss
from audio_suite_shared.secure_subprocess import (
    SubprocessSecurityError,
    run_python_script,
    run_secure_popen,
    run_secure_subprocess,
    start_python_script,
    validate_arguments,
    validate_executable,
    validate_script_path,
)

# ── validate_executable ───────────────────────────────────────────────────────


class TestValidateExecutable:
    def test_python_is_allowed(self):
        assert validate_executable("python") is True

    def test_python3_is_allowed(self):
        assert validate_executable("python3") is True

    def test_python_exe_is_allowed(self):
        assert validate_executable("python.exe") is True

    def test_python3_exe_is_allowed(self):
        assert validate_executable("python3.exe") is True

    def test_ffmpeg_is_allowed(self):
        assert validate_executable("ffmpeg") is True

    def test_ffmpeg_exe_is_allowed(self):
        assert validate_executable("ffmpeg.exe") is True

    def test_ffprobe_is_allowed(self):
        assert validate_executable("ffprobe") is True

    def test_icacls_is_allowed(self):
        assert validate_executable("icacls") is True

    def test_icacls_exe_is_allowed(self):
        assert validate_executable("icacls.exe") is True

    def test_open_is_allowed(self):
        assert validate_executable("open") is True

    def test_xdg_open_is_allowed(self):
        assert validate_executable("xdg-open") is True

    def test_python_prefix_variants_allowed(self):
        # e.g. python3.12
        assert validate_executable("python3.12") is True

    @pytest.mark.parametrize(
        "exe",
        [
            "bash",
            "sh",
            "cmd.exe",
            "powershell.exe",
            "rm",
            "del",
            "curl",
            "wget",
            "nc",
            "netcat",
            "sudo",
            "su",
        ],
    )
    def test_disallowed_executables_raise(self, exe):
        with pytest.raises(SubprocessSecurityError):
            validate_executable(exe)

    def test_absolute_path_to_python_script_allowed(self, tmp_path):
        script = tmp_path / "tool.py"
        script.write_text("pass")
        assert validate_executable(str(script)) is True

    def test_absolute_path_to_pyw_script_allowed(self, tmp_path):
        script = tmp_path / "tool.pyw"
        script.write_text("pass")
        assert validate_executable(str(script)) is True

    def test_absolute_path_nonexistent_script_raises(self, tmp_path):
        missing = tmp_path / "ghost.py"
        with pytest.raises(SubprocessSecurityError):
            validate_executable(str(missing))

    def test_absolute_path_disallowed_extension_raises(self, tmp_path):
        script = tmp_path / "tool.sh"
        script.write_text("#!/bin/sh")
        with pytest.raises(SubprocessSecurityError):
            validate_executable(str(script))

    def test_case_insensitive_for_exe_names(self):
        # exe_name is lowercased before checking: both spellings must agree,
        # whatever the platform-dependent allowlist says for the base name.
        assert validate_executable("FFMPEG") is validate_executable("ffmpeg")

    def test_error_message_contains_executable_name(self):
        with pytest.raises(SubprocessSecurityError, match="bash"):
            validate_executable("bash")


# ── validate_script_path ──────────────────────────────────────────────────────


class TestValidateScriptPath:
    def test_existing_py_file_is_valid(self, tmp_path):
        script = tmp_path / "run.py"
        script.write_text("pass")
        assert validate_script_path(str(script)) is True

    def test_existing_pyw_file_is_valid(self, tmp_path):
        script = tmp_path / "run.pyw"
        script.write_text("pass")
        assert validate_script_path(str(script)) is True

    def test_nonexistent_file_raises(self, tmp_path):
        with pytest.raises(SubprocessSecurityError, match="does not exist"):
            validate_script_path(str(tmp_path / "ghost.py"))

    def test_disallowed_extension_raises(self, tmp_path):
        script = tmp_path / "script.sh"
        script.write_text("#!/bin/sh")
        with pytest.raises(SubprocessSecurityError, match="not allowed"):
            validate_script_path(str(script))

    def test_txt_extension_raises(self, tmp_path):
        f = tmp_path / "script.txt"
        f.write_text("x")
        with pytest.raises(SubprocessSecurityError):
            validate_script_path(str(f))

    def test_returns_true_for_valid_path(self, tmp_path):
        script = tmp_path / "valid.py"
        script.write_text("pass")
        assert validate_script_path(str(script)) is True


# ── validate_arguments ────────────────────────────────────────────────────────


class TestValidateArguments:
    def test_clean_args_return_unchanged(self):
        args = ["--source", "/music/folder", "--output", "/out"]
        result = validate_arguments(args)
        assert result == args

    def test_empty_list_returns_empty(self):
        assert validate_arguments([]) == []

    @pytest.mark.parametrize("bad_char", [";", "|", "`", "<", ">", '"'])
    def test_dangerous_chars_raise(self, bad_char):
        with pytest.raises(SubprocessSecurityError, match="[Dd]angerous"):
            validate_arguments([f"--arg=value{bad_char}extra"])

    @pytest.mark.parametrize("pattern", ["&&", "||", "$(", "${", ">>", "2>", "<<"])
    def test_shell_injection_patterns_raise(self, pattern):
        with pytest.raises(SubprocessSecurityError):
            validate_arguments([f"--source={pattern}/etc/passwd"])

    def test_pipe_in_arg_raises(self):
        with pytest.raises(SubprocessSecurityError):
            validate_arguments(["ffmpeg", "|", "cat"])

    def test_apostrophe_is_allowed(self):
        """Apostrophe is valid in file names like "Sam's Town"."""
        result = validate_arguments(["Sam's Town.mp3"])
        assert "Sam's Town.mp3" in result

    def test_parentheses_are_allowed(self):
        """Parentheses are valid in Windows filenames like "(Greatest Hits)"."""
        result = validate_arguments(["Album (Greatest Hits).flac"])
        assert result == ["Album (Greatest Hits).flac"]

    def test_numeric_args_are_allowed(self):
        result = validate_arguments(["--bitrate", "320", "--sample-rate", "44100"])
        assert result == ["--bitrate", "320", "--sample-rate", "44100"]

    def test_long_but_valid_path_is_allowed(self, tmp_path):
        # A real path under 260 chars should pass
        result = validate_arguments([str(tmp_path)])
        assert str(tmp_path) in result

    def test_multiple_clean_args_all_returned(self):
        args = ["a", "b", "c", "d"]
        assert validate_arguments(args) == args

    def test_error_message_contains_offending_arg(self):
        with pytest.raises(SubprocessSecurityError) as exc_info:
            validate_arguments(["--source=/evil|command"])
        assert (
            "/evil|command" in str(exc_info.value)
            or "injection" in str(exc_info.value).lower()
        )


# ── run_secure_subprocess ─────────────────────────────────────────────────────


class TestRunSecureSubprocess:
    def test_runs_allowed_executable(self, tmp_path):
        """Run python -c 'pass' — minimal safe execution."""
        result = run_secure_subprocess(
            sys.executable, ["-c", "pass"], capture_output=True, check=True
        )
        assert result.returncode == 0

    def test_invalid_executable_raises_before_spawn(self):
        with pytest.raises(SubprocessSecurityError):
            run_secure_subprocess("bash", ["-c", "echo hi"])

    def test_dangerous_argument_raises_before_spawn(self):
        with pytest.raises(SubprocessSecurityError):
            run_secure_subprocess(sys.executable, ["-c", "pass; rm -rf /"])

    def test_nonexistent_cwd_raises(self, tmp_path):
        missing_dir = str(tmp_path / "no_such_dir")
        with pytest.raises(
            SubprocessSecurityError, match="[Dd]oes not exist|[Ww]orking"
        ):
            run_secure_subprocess(sys.executable, ["-c", "pass"], cwd=missing_dir)

    def test_valid_cwd_is_accepted(self, tmp_path):
        result = run_secure_subprocess(
            sys.executable,
            ["-c", "import os\nprint(os.getcwd())"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        assert result.returncode == 0

    def test_capture_output_populates_stdout(self):
        result = run_secure_subprocess(
            sys.executable, ["-c", "print('hello')"], capture_output=True, check=True
        )
        assert "hello" in result.stdout

    def test_failing_process_raises_with_check_true(self):
        with pytest.raises(subprocess.CalledProcessError):
            run_secure_subprocess(
                sys.executable,
                ["-c", "import sys\nsys.exit(1)"],
                capture_output=True,
                check=True,
            )

    def test_failing_process_no_raise_with_check_false(self):
        result = run_secure_subprocess(
            sys.executable,
            ["-c", "import sys\nsys.exit(1)"],
            capture_output=True,
            check=False,
        )
        assert result.returncode == 1

    def test_timeout_raises_timeout_expired(self):
        with pytest.raises(subprocess.TimeoutExpired):
            run_secure_subprocess(
                sys.executable,
                ["-c", "import time\ntime.sleep(10)"],
                timeout=1,
                capture_output=True,
            )


# ── run_secure_popen ──────────────────────────────────────────────────────────


class TestRunSecurePopen:
    def test_returns_popen_object(self):
        proc = run_secure_popen(
            sys.executable,
            ["-c", "pass"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        proc.wait()
        assert proc.returncode == 0

    def test_invalid_executable_raises(self):
        with pytest.raises(SubprocessSecurityError):
            run_secure_popen("bash", ["-c", "echo hi"])

    def test_dangerous_arg_raises_before_spawn(self):
        with pytest.raises(SubprocessSecurityError):
            run_secure_popen(sys.executable, ["--evil|arg"])

    def test_nonexistent_cwd_raises(self, tmp_path):
        with pytest.raises(SubprocessSecurityError):
            run_secure_popen(
                sys.executable, ["-c", "pass"], cwd=str(tmp_path / "missing")
            )

    def test_output_can_be_read(self):
        proc = run_secure_popen(
            sys.executable,
            ["-c", "print('popen_output')"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, _ = proc.communicate()
        assert "popen_output" in stdout


# ── convenience wrappers ──────────────────────────────────────────────────────


class TestConvenienceWrappers:
    def test_run_python_script_executes_script(self, tmp_path):
        script = tmp_path / "hello.py"
        script.write_text("print('wrapper_ok')")
        result = run_python_script(str(script), [], capture_output=True, check=True)
        assert "wrapper_ok" in result.stdout

    def test_run_python_script_returns_result_on_nonzero_exit(self, tmp_path):
        """Regression: a non-zero child exit must come back as CompletedProcess
        (so callers can show a per-module error dialog) instead of raising
        CalledProcessError and crashing the batch worker thread."""
        script = tmp_path / "fail.py"
        script.write_text("import sys; sys.exit(3)")
        result = run_python_script(str(script), [], capture_output=True)
        assert result.returncode == 3

    def test_run_python_script_explicit_check_true_still_raises(self, tmp_path):
        script = tmp_path / "fail.py"
        script.write_text("import sys; sys.exit(3)")
        with pytest.raises(subprocess.CalledProcessError):
            run_python_script(str(script), [], capture_output=True, check=True)

    def test_start_python_script_returns_popen(self, tmp_path):
        script = tmp_path / "noop.py"
        script.write_text("pass")
        proc = start_python_script(
            str(script), [], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        proc.wait()
        assert proc.returncode == 0


# ── gap completion: error branches & the line-callback path ───────────────────


class TestValidateScriptPathErrorBranches:
    def test_resolve_failure_raises(self, tmp_path):
        script = tmp_path / "run.py"
        script.write_text("pass")
        with patch.object(Path, "resolve", side_effect=OSError("bad")):
            with pytest.raises(SubprocessSecurityError, match="Cannot resolve"):
                validate_script_path(str(script))

    def test_current_directory_traversal_warns_but_passes(self, tmp_path):
        real = tmp_path / "real.py"
        real.write_text("pass")
        candidate = str(tmp_path / "sub" / ".." / "real.py")
        assert validate_script_path(candidate) is True

    def test_unreadable_file_raises(self, tmp_path):
        script = tmp_path / "locked.py"
        script.write_text("pass")
        with patch.object(ss.os, "access", return_value=False):
            with pytest.raises(SubprocessSecurityError, match="not readable"):
                validate_script_path(str(script))


class TestValidateArgumentsErrorBranches:
    def test_overlong_absolute_path_raises(self, tmp_path):
        long_arg = str(tmp_path / ("a" * 300))
        with patch.object(ss.sys, "platform", "win32"):
            with pytest.raises(SubprocessSecurityError, match="too long"):
                validate_arguments([long_arg])

    def test_invalid_absolute_path_raises(self):
        with patch.object(Path, "resolve", side_effect=OSError("bad")):
            with pytest.raises(SubprocessSecurityError, match="Invalid path"):
                validate_arguments(["C:/evil"])


class TestRunSecureSubprocessErrorBranches:
    def test_cwd_not_executable_raises(self, tmp_path):
        with patch.object(
            ss.os, "access", side_effect=lambda _p, mode: mode != os.X_OK
        ):
            with pytest.raises(SubprocessSecurityError, match="not accessible"):
                run_secure_subprocess(sys.executable, ["-c", "pass"], cwd=str(tmp_path))

    def test_cwd_resolve_failure_raises(self):
        with patch.object(Path, "resolve", side_effect=OSError("bad")):
            with pytest.raises(SubprocessSecurityError, match="Invalid working"):
                run_secure_subprocess(sys.executable, ["-c", "pass"], cwd="C:/any")

    def test_unexpected_subprocess_error_wrapped(self):
        fake_run = MagicMock(side_effect=RuntimeError("boom"))
        with patch("audio_suite_shared.secure_subprocess.subprocess.run", fake_run):
            with pytest.raises(SubprocessSecurityError, match="Failed to run"):
                run_secure_subprocess(sys.executable, ["-c", "pass"])


class TestRunSecurePopenErrorBranches:
    def test_valid_cwd_is_used(self, tmp_path):
        proc = run_secure_popen(
            sys.executable,
            ["-c", "pass"],
            cwd=str(tmp_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        proc.wait()
        assert proc.returncode == 0

    def test_cwd_resolve_failure_raises(self):
        with patch.object(Path, "resolve", side_effect=OSError("bad")):
            with pytest.raises(SubprocessSecurityError, match="Invalid working"):
                run_secure_popen(sys.executable, ["-c", "pass"], cwd="C:/any")

    def test_start_failure_wrapped(self):
        fake_popen = MagicMock(side_effect=RuntimeError("boom"))
        with patch("audio_suite_shared.secure_subprocess.subprocess.Popen", fake_popen):
            with pytest.raises(SubprocessSecurityError, match="Failed to start"):
                run_secure_popen(sys.executable, ["-c", "pass"])


class _FakePopen:
    """Context-manager fake for subprocess.Popen (line-callback path)."""

    def __init__(self, lines, returncode=0, wait_raises=None):
        self._lines = lines
        self.returncode = returncode
        self.wait_raises = wait_raises
        self.stdout = iter([f"{ln}\n" for ln in lines])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def wait(self, timeout=None):
        if self.wait_raises is not None:
            raise self.wait_raises
        return self.returncode


class TestRunPythonScriptLineCallback:
    def _run(self, fake):
        captured = []
        with patch(
            "audio_suite_shared.secure_subprocess.subprocess.Popen",
            return_value=fake,
        ):
            result = run_python_script(
                "C:/app/run.py", ["--x"], line_callback=captured.append
            )
        return result, captured

    def test_forwards_each_line_to_callback(self):
        fake = _FakePopen(["first", "second"])
        result, captured = self._run(fake)
        assert captured == ["first", "second"]
        assert result.returncode == 0
        assert result.stdout == "first\nsecond"

    def test_nonzero_exit_logs_warning(self):
        fake = _FakePopen(["oops"], returncode=3)
        result, _ = self._run(fake)
        assert result.returncode == 3

    def test_timeout_expired_is_relayed(self):
        fake = _FakePopen(["slow"], wait_raises=subprocess.TimeoutExpired("x", 1))
        with pytest.raises(subprocess.TimeoutExpired):
            self._run(fake)


# ── text parameter (plan C3, audit R-08) ─────────────────────────────────────


class TestTextParameter:
    """``text`` lets a binary stream use the wrapper.

    The Audio Enhancer reads raw float32 PCM off ffmpeg's stdout; decoding that
    as text corrupts it, and the wrapper used to hardcode ``text=True``.  The
    default must stay ``True`` so no existing caller changes behaviour.
    """

    def test_default_still_returns_str(self):
        result = run_secure_subprocess(
            sys.executable, ["-c", "print('hello')"], capture_output=True, check=True
        )
        assert isinstance(result.stdout, str)
        assert result.stdout.strip() == "hello"

    def test_text_false_returns_bytes(self):
        result = run_secure_subprocess(
            sys.executable,
            ["-c", "print(chr(0))"],
            capture_output=True,
            check=True,
            text=False,
        )
        assert isinstance(result.stdout, bytes)
        # Trailing newline differs by platform (\r\n on Windows).
        assert result.stdout.strip() == b"\x00"

    def test_text_false_carries_raw_binary_intact(self):
        """This is the enhancer's case: PCM bytes, not text.

        ``text=True`` hands the child's stdout to a text decoder; raw float32
        samples have no text reading, so the bytes must arrive untouched.
        (Subprocess's own reader thread swallows the decode error on some
        versions and leaves ``stdout`` as ``None``, which is why the caller
        cannot rely on an exception being raised.)
        """
        program = "import sys\nsys.stdout.buffer.write(bytes([0, 129, 255]))"
        result = run_secure_subprocess(
            sys.executable,
            ["-c", program],
            capture_output=True,
            check=True,
            text=False,
        )
        assert result.stdout == b"\x00\x81\xff"
