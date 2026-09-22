"""
cd_ripper/core/rip_log.py — Plain-text log file writer for log_cb output.

Distinct from audio_suite_shared's centralized RotatingFileHandler logging
(see audio_suite_shared/error_logger.py): this module writes CD-Ripper-
specific extraction and diagnostic messages passed to log_cb throughout
core/ripper.py to a small file in the cd_ripper package folder, so
they're easy to find without digging through the suite-wide log.
"""

import logging
import threading
from datetime import datetime

from cd_ripper.core.cd_ripper_config import get_log_path

logger = logging.getLogger(__name__)

_write_lock = threading.Lock()


def write_log_line(message: str) -> None:
    """
    Append a single timestamped line to the CD Ripper log file.

    Best-effort by design: a failure to write the log must never interrupt
    a rip in progress (this mirrors cd_ripper_config.save()'s existing
    best-effort-write pattern for the same reason), so I/O errors here are
    caught and silently discarded rather than raised.

    Args:
        message: The log_cb message to record.
    """
    line = f"{datetime.now().isoformat(timespec='seconds')}  {message}\n"
    try:
        with _write_lock, open(get_log_path(), "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        # Best-effort by design (see docstring): never raise during a rip.
        logger.debug("Could not write CD Ripper log line", exc_info=True)
