"""
secure_subprocess.py — Secure subprocess execution utilities.

Provides validated subprocess execution with security controls to prevent
command injection and ensure safe execution of external processes.
"""

import logging
import os
import re
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

from audio_suite_shared.exceptions import AudioSuiteError
from audio_suite_shared.subprocess_utils import creation_flags, get_startupinfo

logger = logging.getLogger(f"audio_suite.{__name__}")

# Allowed executable patterns for security
ALLOWED_EXECUTABLES = {
    # Python interpreter (for running suite modules)
    "python.exe",
    "python3.exe",
    "pythonw.exe",
    "python",
    "python3",
    "pythonw",
    # System utilities
    "ffmpeg",
    "ffmpeg.exe",
    "ffprobe",
    "ffprobe.exe",
    # OS file openers (platform_utils.open_path / ui_common._default_open_log)
    "open",
    "xdg-open",
    # Chromaprint fingerprinting (audio_fingerprinter/fpcalc)
    "fpcalc",
    "fpcalc.exe",
    # Windows ACL hardening (key_manager.py: Windows ACL restriction)
    # icacls.exe is always available at %SystemRoot%\System32 on Windows;
    # allow both bare and .exe forms matching the ffprobe/ffmpeg pairing.
    "icacls",
    "icacls.exe",
}

# Allowed file extensions for scripts
ALLOWED_SCRIPT_EXTENSIONS = {".py", ".pyw"}

# Dangerous characters to block in arguments
# Note: Removed ( ) as they are valid in Windows filenames like "(Greatest Hits)"
# Note: Apostrophe (') is allowed for valid file paths like "Sam's Town"
# Note: Removed $ as it's safe in subprocess arguments and valid in metadata
# Note: Double quote (") is blocked while single quote (') is allowed because
#   on Windows, cmd.exe treats " as a string delimiter (can break command-line
#   parsing) but treats ' as a literal character.  On Unix, neither is special
#   to subprocess.run when shell=False (the default), but blocking " only is
#   the conservative cross-platform choice — paths containing ' are common
#   (e.g. "Sam's Town.flac") while paths containing " are vanishingly rare.
DANGEROUS_CHARS = {";", "|", "`", "<", ">", '"'}


class SubprocessSecurityError(AudioSuiteError):
    """Raised when subprocess security validation fails."""


def validate_executable(executable: str) -> bool:
    """
    Validate that the executable is allowed to run.

    Args:
        executable: Path to the executable

    Returns:
        True if executable is allowed

    Raises:
        SubprocessSecurityError: If executable is not allowed
    """
    exe_name = Path(executable).name.lower()

    # Allow Python interpreter (for running suite modules)
    if exe_name in {
        "python",
        "python.exe",
        "pythonw",
        "pythonw.exe",
        "python3",
        "python3.exe",
    } or re.match(r"^python3\.\d+(?:\.exe)?$", exe_name):
        return True

    # Check against allowed executables
    if exe_name in ALLOWED_EXECUTABLES:
        return True

    # Allow absolute paths to Python scripts
    if (
        os.path.isabs(executable)
        and Path(executable).suffix in ALLOWED_SCRIPT_EXTENSIONS
    ):
        return validate_script_path(executable)

    raise SubprocessSecurityError(f"Executable not allowed: {executable}")


def validate_script_path(script_path: str) -> bool:
    """
    Validate that a script path is safe to execute.

    Args:
        script_path: Path to the script file

    Returns:
        True if path is safe

    Raises:
        SubprocessSecurityError: If path is dangerous
    """
    path = Path(script_path)

    # Check file extension
    if path.suffix.lower() not in ALLOWED_SCRIPT_EXTENSIONS:
        raise SubprocessSecurityError(f"Script extension not allowed: {path.suffix}")

    # Resolve path to prevent directory traversal
    try:
        resolved_path = path.resolve()
    except (OSError, RuntimeError) as e:
        raise SubprocessSecurityError(
            f"Cannot resolve script path: {script_path}"
        ) from e

    # Check for directory traversal attempts
    if ".." in path.parts or any(
        part.startswith(".") for part in path.parts if part != "."
    ):
        # Allow relative navigation within suite structure but warn
        logger.warning("Relative path detected in script: %s", script_path)

    # Ensure file exists and is readable
    if not resolved_path.exists():
        raise SubprocessSecurityError(f"Script file does not exist: {resolved_path}")

    if not os.access(resolved_path, os.R_OK):
        raise SubprocessSecurityError(f"Script file is not readable: {resolved_path}")

    return True


def validate_arguments(args: list[str]) -> list[str]:
    """
    Validate and sanitize subprocess arguments.

    Args:
        args: List of arguments to validate

    Returns:
        Sanitized arguments list

    Raises:
        SubprocessSecurityError: If arguments contain dangerous content
    """
    sanitized = []

    for arg in args:
        # Check for dangerous characters
        if any(char in arg for char in DANGEROUS_CHARS):
            raise SubprocessSecurityError(f"Dangerous character in argument: {arg}")

        # Check for shell injection patterns
        dangerous_patterns = [
            "&&",
            "||",
            ";",
            "|",
            "`",
            "$(",
            "${",
            ">",
            "<",
            ">>",
            "<<",
            "2>",
            "2>>",
        ]

        for pattern in dangerous_patterns:
            if pattern in arg:
                raise SubprocessSecurityError(
                    f"Shell injection pattern detected: {arg}"
                )

        # Validate absolute file paths in arguments
        if os.path.isabs(arg):
            try:
                path_obj = Path(arg)
                # Resolve to prevent traversal
                resolved = path_obj.resolve()
                # Use platform-appropriate maximum path length:
                # Windows MAX_PATH is 260; Linux/macOS PATH_MAX is 4096.
                max_path_len = 260 if sys.platform == "win32" else 4096
                if len(str(resolved)) > max_path_len:
                    raise SubprocessSecurityError(f"Path too long: {arg}")
            except (OSError, RuntimeError) as e:
                raise SubprocessSecurityError(f"Invalid path argument: {arg}") from e

        sanitized.append(arg)

    return sanitized


def run_secure_subprocess(
    executable: str,
    args: list[str],
    cwd: Optional[str] = None,
    timeout: Optional[int] = None,
    capture_output: bool = False,
    check: bool = True,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """
    Run a subprocess with security validation.

    Args:
        executable: The program to execute
        args: Arguments to pass to the program
        cwd: Working directory for the process
        timeout: Maximum execution time in seconds
        capture_output: Whether to capture stdout/stderr
        check: Whether to raise exception on non-zero exit
        **kwargs: Additional arguments passed to subprocess.run

    Returns:
        subprocess.CompletedProcess object

    Raises:
        SubprocessSecurityError: If security validation fails
        subprocess.TimeoutExpired: If process times out
        subprocess.CalledProcessError: If check=True and process fails
    """
    # Validate executable
    validate_executable(executable)

    # Validate arguments
    safe_args = validate_arguments(args)

    # Validate working directory
    if cwd:
        try:
            cwd_path = Path(cwd).resolve()
            if not cwd_path.exists():
                raise SubprocessSecurityError(
                    f"Working directory does not exist: {cwd}"
                )
            if not os.access(cwd_path, os.X_OK):
                raise SubprocessSecurityError(
                    f"Working directory not accessible: {cwd}"
                )
            safe_cwd = str(cwd_path)
        except (OSError, RuntimeError) as e:
            raise SubprocessSecurityError(f"Invalid working directory: {cwd}") from e
    else:
        safe_cwd = None

    # Build command
    cmd = [executable] + safe_args

    # Log execution for audit trail
    logger.info(
        "Executing secure subprocess: %s... (args: %d)",
        " ".join(cmd[:3]),
        len(safe_args),
    )

    try:
        # Use subprocess.run for better control
        result = subprocess.run(
            cmd,
            cwd=safe_cwd,
            timeout=timeout,
            capture_output=capture_output,
            check=check,
            text=True,
            startupinfo=get_startupinfo(),
            **kwargs,
        )

        logger.info("Subprocess completed with return code: %s", result.returncode)
        return result

    except subprocess.TimeoutExpired:
        logger.error(
            "Subprocess timed out after %s seconds: %s",
            timeout,
            executable,
            exc_info=True,
        )
        raise
    except subprocess.CalledProcessError as e:
        logger.error(
            "Subprocess failed with code %s: %s",
            e.returncode,
            executable,
            exc_info=True,
        )
        if capture_output:
            logger.error("stdout: %s", e.stdout)
            logger.error("stderr: %s", e.stderr)
        raise
    except Exception as e:
        logger.error("Unexpected error running subprocess: %s", e, exc_info=True)
        raise SubprocessSecurityError(f"Failed to run subprocess: {e}") from e


def run_secure_popen(
    executable: str, args: list[str], cwd: Optional[str] = None, **kwargs: Any
) -> subprocess.Popen[Any]:
    """
    Run a subprocess with Popen interface and security validation.

    Args:
        executable: The program to execute
        args: Arguments to pass to the program
        cwd: Working directory for the process
        **kwargs: Additional arguments passed to subprocess.Popen

    Returns:
        subprocess.Popen object

    Raises:
        SubprocessSecurityError: If security validation fails
    """
    # Validate executable
    validate_executable(executable)

    # Validate arguments
    safe_args = validate_arguments(args)

    # Validate working directory
    if cwd:
        try:
            cwd_path = Path(cwd).resolve()
            if not cwd_path.exists():
                raise SubprocessSecurityError(
                    f"Working directory does not exist: {cwd}"
                )
            safe_cwd = str(cwd_path)
        except (OSError, RuntimeError) as e:
            raise SubprocessSecurityError(f"Invalid working directory: {cwd}") from e
    else:
        safe_cwd = None

    # Build command
    cmd = [executable] + safe_args

    # Log execution for audit trail
    logger.info(
        "Starting secure subprocess: %s... (args: %d)",
        " ".join(cmd[:3]),
        len(safe_args),
    )

    try:
        process = subprocess.Popen(
            cmd,
            cwd=safe_cwd,
            text=True,
            creationflags=creation_flags(),
            startupinfo=get_startupinfo(),
            **kwargs,
        )
        logger.info("Subprocess started with PID: %s", process.pid)
        return process

    except Exception as e:
        logger.error("Failed to start subprocess: %s", e, exc_info=True)
        raise SubprocessSecurityError(f"Failed to start subprocess: {e}") from e


# Convenience functions for common Audio Suite patterns
def run_python_script(
    script_path: str,
    args: list[str],
    *,
    line_callback: Callable[[str], None] | None = None,
    timeout: int | None = None,
    env: dict[str, str] | None = None,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """
    Run a Python script securely.

    When *line_callback* is provided the subprocess stdout/stderr is captured
    line-by-line and each line is forwarded to the callback in real time
    (using Popen instead of run_secure_subprocess).  Without a callback the
    function delegates to ``run_secure_subprocess`` for simple blocking
    execution.

    Args:
        script_path: Path to the Python script
        args: Arguments to pass to the script
        line_callback: Optional callback invoked for each output line
        timeout: Optional timeout in seconds
        env: Optional extra environment variables.  Merged with the current
            process environment (caller's values take precedence).
        **kwargs: Additional arguments for run_secure_subprocess

    Returns:
        subprocess.CompletedProcess object.  Non-zero child exits are reported
        via ``returncode`` rather than raised, so callers can render per-module
        error dialogs; pass ``check=True`` explicitly to restore raising.
    """
    # Merge caller-provided env with the current process environment so that
    # secrets (e.g. the AcoustID API key) are not exposed on the command line.
    merged_env: dict[str, str] | None = None
    if env is not None:
        merged_env = {**os.environ, **env}

    if line_callback is None:
        kwargs.setdefault("check", False)
        if merged_env is not None:
            kwargs["env"] = merged_env
        return run_secure_subprocess(
            sys.executable, [script_path] + args, timeout=timeout, **kwargs
        )

    # Validate just like run_secure_subprocess would
    validate_executable(sys.executable)
    safe_args = validate_arguments([script_path] + args)
    cmd = [sys.executable] + safe_args

    logger.info("Executing (line callback): %s ... (args: %d)", script_path, len(args))

    stdout_lines: list[str] = []
    timed_out = False

    try:
        with subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=creation_flags(),
            env=merged_env,
        ) as proc:
            # Start a background timer that kills the process if the
            # timeout expires.  This is necessary because the line-by-line
            # read loop blocks on I/O — a silent child that never writes
            # would block the caller indefinitely without the timer.
            timer: threading.Timer | None = None
            if timeout is not None:

                def _kill() -> None:
                    nonlocal timed_out
                    timed_out = True
                    proc.kill()

                timer = threading.Timer(timeout, _kill)
                timer.daemon = True
                timer.start()

            try:
                if proc.stdout is not None:
                    for line in proc.stdout:
                        stripped = line.rstrip("\n\r")
                        stdout_lines.append(stripped)
                        if line_callback is not None:
                            line_callback(stripped)

                proc.wait(timeout=timeout)
            finally:
                if timer is not None:
                    timer.cancel()

            if timed_out:
                assert timeout is not None
                raise subprocess.TimeoutExpired(
                    cmd, timeout, output="\n".join(stdout_lines)
                )

        combined = "\n".join(stdout_lines)
        completed = subprocess.CompletedProcess(
            args=cmd,
            returncode=proc.returncode,
            stdout=combined,
            stderr="",
        )

        if proc.returncode != 0:
            logger.warning(
                "Script %s exited with code %d", script_path, proc.returncode
            )

        return completed

    except subprocess.TimeoutExpired:
        logger.error("Script %s timed out after %s seconds", script_path, timeout)
        raise


def start_python_script(
    script_path: str, args: list[str], **kwargs: Any
) -> subprocess.Popen[Any]:
    """
    Start a Python script securely using Popen.

    Args:
        script_path: Path to the Python script
        args: Arguments to pass to the script
        **kwargs: Additional arguments for run_secure_popen

    Returns:
        subprocess.Popen object
    """
    return run_secure_popen(sys.executable, [script_path] + args, **kwargs)
