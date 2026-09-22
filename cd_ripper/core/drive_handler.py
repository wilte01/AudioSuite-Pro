"""
drive_handler.py  –  Low-level CD/DVD drive control via SCSI Pass-Through.

Provides device opening, TOC reading, raw sector reading through
IOCTL_SCSI_PASS_THROUGH_DIRECT with the MMC "READ CD" command (0xBE),
and spin-down control.  Windows-only at runtime; macOS/Linux support is
not yet implemented.
"""

import ctypes
import logging as _logging
import sys
from collections.abc import Callable

from audio_suite_shared.exceptions import AudioExternalToolError, AudioIOError

# ctypes.wintypes is only available on Windows
if sys.platform == "win32":
    import ctypes.wintypes


# ── Physical constants ────────────────────────────────────────────────────

SECTOR_SIZE = 2352
SECTORS_PER_SEC = 75
SAMPLE_RATE = 44100
CHANNELS = 2
BITS_PER_SAMPLE = 16

# READ CD (0xBE) C2 error-pointer block: 1 bit per byte of the 2352-byte
# audio block returned when CDB byte 9 bits 2-1 request C2 error flags.
# Per MMC, drives that don't actually support C2 are permitted to zero-fill
# this field rather than reject the request -- see diagnose_c2_reliability().
C2_FLAG_BYTES_PER_SECTOR = 294

# ── Win32 constants ───────────────────────────────────────────────────────

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_FLAG_NO_BUFFERING = 0x20000000

# INVALID_HANDLE_VALUE is a Win32 sentinel; defined conditionally so the
# module can be imported on non-Windows (e.g. for testing or inspection).
if sys.platform == "win32":
    INVALID_HANDLE_VALUE = ctypes.wintypes.HANDLE(-1).value
    # ctypes.windll.kernel32 does NOT reliably preserve the true Win32
    # last-error code for later retrieval via ctypes.GetLastError() --
    # any intervening OS-level operation (including internal CPython/ctypes
    # bookkeeping calls) can clobber it before it's read.  Loading kernel32
    # explicitly with use_last_error=True captures the error into a
    # ctypes-private, thread-local copy immediately after each call,
    # which callers must then read with ctypes.get_last_error() (lowercase),
    # never the bare ctypes.GetLastError().  See:
    # https://docs.python.org/3/library/ctypes.html#ctypes.get_last_error
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
else:
    INVALID_HANDLE_VALUE = -1  # Placeholder; ripper is Windows-only at runtime
    _kernel32 = None  # Unused; every call site requiring it is Windows-only at runtime

IOCTL_SCSI_PASS_THROUGH_DIRECT = 0x4D014
IOCTL_CDROM_READ_TOC = 0x24000
IOCTL_STORAGE_MEDIA_REMOVAL = 0x2D4804
IOCTL_CDROM_STOP_AUDIO = 0x2404E
SCSI_IOCTL_DATA_IN = 1
SCSI_IOCTL_DATA_OUT = 0


# ── TOC structures ────────────────────────────────────────────────────────


class _TOC_TRACK(ctypes.Structure):
    _fields_ = [
        ("Reserved", ctypes.c_uint8),
        ("Control", ctypes.c_uint8),
        ("TrackNumber", ctypes.c_uint8),
        ("Reserved1", ctypes.c_uint8),
        ("Address", ctypes.c_uint8 * 4),
    ]


class _CDROM_TOC(ctypes.Structure):
    _fields_ = [
        ("Length", ctypes.c_uint8 * 2),
        ("FirstTrack", ctypes.c_uint8),
        ("LastTrack", ctypes.c_uint8),
        ("TrackData", _TOC_TRACK * 100),
    ]


# ── SCSI Pass-Through structure ───────────────────────────────────────────


class SCSI_PASS_THROUGH_DIRECT(ctypes.Structure):
    """SCSI pass-through direct structure for CD ripping."""

    _fields_ = [
        ("Length", ctypes.c_uint16),
        ("ScsiStatus", ctypes.c_uint8),
        ("PathId", ctypes.c_uint8),
        ("TargetId", ctypes.c_uint8),
        ("Lun", ctypes.c_uint8),
        ("CdbLength", ctypes.c_uint8),
        ("SenseInfoLength", ctypes.c_uint8),
        ("DataIn", ctypes.c_uint8),
        ("Padding", ctypes.c_uint8 * 3),  # alignment
        ("DataTransferLength", ctypes.c_uint32),
        ("TimeOutValue", ctypes.c_uint32),
        ("DataBuffer", ctypes.c_void_p),
        ("SenseInfoOffset", ctypes.c_uint32),
        ("Cdb", ctypes.c_uint8 * 16),
    ]


# ── Device helpers ────────────────────────────────────────────────────────


def _require_windows() -> None:
    """Fail fast with a clear error if not running on Windows.

    SCSI pass-through CD extraction relies on ctypes.windll, which only
    exists on Windows. macOS/Linux support is a possible future
    enhancement and is not implemented today; this stops the code from
    reaching an opaque AttributeError deep inside ctypes.
    """
    if sys.platform != "win32":
        raise AudioExternalToolError(
            "CD ripping is only supported on Windows (requires "
            f"ctypes.windll, unavailable on {sys.platform!r}). "
            "macOS/Linux support is not yet implemented.",
            tool="cd_drive",
        )


def _open_device(drive_letter: str) -> int:
    """Open the CD device handle. Returns handle or raises RuntimeError."""
    _require_windows()
    device_path = f"\\\\.\\{drive_letter}:"
    kernel32 = _kernel32
    handle = kernel32.CreateFileW(
        device_path,
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        # Try read-only
        handle = kernel32.CreateFileW(
            device_path,
            GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
    if handle == INVALID_HANDLE_VALUE:
        err = ctypes.get_last_error()
        raise AudioIOError(
            f"Cannot open CD device {device_path} (Win32 error {err}). "
            f"Try running as Administrator."
        )
    return int(handle)


def _msf_to_lba(m: int, s: int, f: int) -> int:
    return (m * 60 + s) * SECTORS_PER_SEC + f - 150


# ── TOC reading ───────────────────────────────────────────────────────────


def read_toc(drive_letter: str, log_cb: Callable[[str], None]) -> list[dict[str, int]]:
    _require_windows()
    kernel32 = _kernel32
    handle = _open_device(drive_letter)
    try:
        toc = _CDROM_TOC()
        bytes_ret = ctypes.wintypes.DWORD(0)
        ok = kernel32.DeviceIoControl(
            handle,
            IOCTL_CDROM_READ_TOC,
            None,
            0,
            ctypes.byref(toc),
            ctypes.sizeof(toc),
            ctypes.byref(bytes_ret),
            None,
        )
        if not ok:
            err = ctypes.get_last_error()
            raise AudioIOError(f"IOCTL_CDROM_READ_TOC failed: Win32 error {err}")

        first, last = toc.FirstTrack, toc.LastTrack
        log_cb(f"[TOC] Tracks {first}\u2013{last}")
        tracks = []
        for i in range(last - first + 1):
            t = toc.TrackData[i]
            a = t.Address
            lba = _msf_to_lba(a[1], a[2], a[3])
            t_next = toc.TrackData[i + 1]
            a_next = t_next.Address
            lba_next = _msf_to_lba(a_next[1], a_next[2], a_next[3])
            sectors = lba_next - lba
            tracks.append(
                {
                    "number": t.TrackNumber,
                    "start_lba": lba,
                    "end_lba": lba_next - 1,
                    "sectors": sectors,
                }
            )
            log_cb(
                f"[TOC] Track {t.TrackNumber:02d}: LBA {lba}\u2013{lba_next - 1} "
                f"({sectors} sectors)"
            )
        return tracks
    finally:
        kernel32.CloseHandle(handle)


# ── SCSI read functions ───────────────────────────────────────────────────


def _bytes_per_sector(request_c2: bool) -> int:
    """Total bytes returned per sector by _read_cd_scsi for the given C2 setting."""
    return SECTOR_SIZE + (C2_FLAG_BYTES_PER_SECTOR if request_c2 else 0)


def _read_cd_scsi(
    handle: int,
    lba: int,
    count: int,
    buf: ctypes.Array[ctypes.c_char],
    log_cb: Callable[[str], None],
    request_c2: bool = False,
) -> int:
    """
    Issue MMC READ CD (0xBE) command via SCSI pass-through.

    Args:
        request_c2: If True, sets CDB byte 9 bits 2-1 to request the 294
            C2 error-pointer bytes per sector in addition to user data,
            so each sector occupies SECTOR_SIZE + C2_FLAG_BYTES_PER_SECTOR
            bytes in the output buffer. Defaults to False, which preserves
            the exact prior behaviour (audio-only, 0xF8 flags byte).

    Returns bytes transferred, raises RuntimeError on failure.
    """
    kernel32 = _kernel32
    sptd = SCSI_PASS_THROUGH_DIRECT()
    sptd.Length = ctypes.sizeof(SCSI_PASS_THROUGH_DIRECT)
    sptd.CdbLength = 12
    sptd.DataIn = SCSI_IOCTL_DATA_IN
    sptd.DataTransferLength = count * _bytes_per_sector(request_c2)
    sptd.TimeOutValue = 60
    sptd.DataBuffer = ctypes.cast(buf, ctypes.c_void_p)
    sptd.SenseInfoOffset = 0
    sptd.SenseInfoLength = 0

    # READ CD CDB (12 bytes):
    # Op=0xBE, Type=0, LBA(4), Len(3),
    # Flags=0xF8 (sync+header+subheader+user+edc), or 0xFA to additionally
    # request C2 error flags (bits 2-1 = 01), SubCh=0
    cdb = sptd.Cdb
    cdb[0] = 0xBE  # READ CD
    cdb[1] = 0x00  # sector type: any
    cdb[2] = (lba >> 24) & 0xFF
    cdb[3] = (lba >> 16) & 0xFF
    cdb[4] = (lba >> 8) & 0xFF
    cdb[5] = lba & 0xFF
    cdb[6] = (count >> 16) & 0xFF
    cdb[7] = (count >> 8) & 0xFF
    cdb[8] = count & 0xFF
    cdb[9] = 0xFA if request_c2 else 0xF8
    cdb[10] = 0x00
    cdb[11] = 0x00

    bytes_ret = ctypes.wintypes.DWORD(0)
    ok = kernel32.DeviceIoControl(
        handle,
        IOCTL_SCSI_PASS_THROUGH_DIRECT,
        ctypes.byref(sptd),
        ctypes.sizeof(sptd),
        ctypes.byref(sptd),
        ctypes.sizeof(sptd),
        ctypes.byref(bytes_ret),
        None,
    )
    if not ok:
        err = ctypes.get_last_error()
        raise AudioIOError(
            f"SCSI pass-through DeviceIoControl failed: Win32 error {err}"
        )
    if sptd.ScsiStatus != 0:
        raise AudioIOError(f"SCSI command failed: SCSI status {sptd.ScsiStatus}")
    return int(sptd.DataTransferLength)


# ── Spin-down ─────────────────────────────────────────────────────────────


def spin_down_drive(drive_letter: str, log_cb: Callable[[str], None]) -> None:
    """
    Spin down the CD drive after ripping is complete.
    Sends a SCSI STOP UNIT command via pass-through.
    """
    try:
        handle = _open_device(drive_letter)
        kernel32 = _kernel32
        try:
            sptd = SCSI_PASS_THROUGH_DIRECT()
            sptd.Length = ctypes.sizeof(SCSI_PASS_THROUGH_DIRECT)
            sptd.CdbLength = 6
            sptd.DataIn = SCSI_IOCTL_DATA_OUT
            sptd.DataTransferLength = 0
            sptd.TimeOutValue = 15
            sptd.DataBuffer = None
            sptd.SenseInfoOffset = 0
            sptd.SenseInfoLength = 0

            # STOP UNIT CDB (6 bytes): Op=0x1B, Immed=0, LoEj=0, Start=0
            cdb = sptd.Cdb
            cdb[0] = 0x1B  # START STOP UNIT
            cdb[1] = 0x00  # Immed=0
            cdb[2] = 0x00
            cdb[3] = 0x00
            cdb[4] = 0x00  # LoEj=0, Start=0 \u2192 stop spindle
            cdb[5] = 0x00

            bytes_ret = ctypes.wintypes.DWORD(0)
            kernel32.DeviceIoControl(
                handle,
                IOCTL_SCSI_PASS_THROUGH_DIRECT,
                ctypes.byref(sptd),
                ctypes.sizeof(sptd),
                ctypes.byref(sptd),
                ctypes.sizeof(sptd),
                ctypes.byref(bytes_ret),
                None,
            )
            log_cb("[Drive] Spin-down command sent.")
        finally:
            kernel32.CloseHandle(handle)
    except (OSError, RuntimeError) as e:
        _logging.getLogger(__name__).warning(
            "Drive spin-down failed: %s", e, exc_info=True
        )
        log_cb(f"[Drive] Spin-down skipped: {e}")
