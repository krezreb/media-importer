"""Filesystem timestamp access, with real birth-time support where it exists.

Linux exposes no birth time through the Python standard library: ``os.stat``
grows an ``st_birthtime`` only on macOS/BSD and (since 3.12) Windows, and there
is no ``os.statx`` binding.  Reaching it requires calling ``statx(2)`` and then
checking the returned mask, because even a successful call frequently declines
to supply the field:

    FAT32 / exFAT     no btime   <- the format of most camera SD cards
    WSL DrvFs / 9p    usually no btime
    NFS               generally no btime
    ext4              absent on inodes created before ~2011

So birth time is treated as normally-absent rather than exceptional, and the
caller falls back to mtime.  That fallback is sanctioned, but it is never
silent: the two are reported through distinct `DateSource` values so the user
can always see which timestamp dated a file.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_AT_FDCWD = -100
_AT_STATX_SYNC_AS_STAT = 0x0000
_STATX_BTIME = 0x0000_0800


class _StatxTimestamp(ctypes.Structure):
    _fields_ = [
        ("tv_sec", ctypes.c_int64),
        ("tv_nsec", ctypes.c_uint32),
        ("__reserved", ctypes.c_int32),
    ]


class _Statx(ctypes.Structure):
    _fields_ = [
        ("stx_mask", ctypes.c_uint32),
        ("stx_blksize", ctypes.c_uint32),
        ("stx_attributes", ctypes.c_uint64),
        ("stx_nlink", ctypes.c_uint32),
        ("stx_uid", ctypes.c_uint32),
        ("stx_gid", ctypes.c_uint32),
        ("stx_mode", ctypes.c_uint16),
        ("__spare0", ctypes.c_uint16 * 1),
        ("stx_ino", ctypes.c_uint64),
        ("stx_size", ctypes.c_uint64),
        ("stx_blocks", ctypes.c_uint64),
        ("stx_attributes_mask", ctypes.c_uint64),
        ("stx_atime", _StatxTimestamp),
        ("stx_btime", _StatxTimestamp),
        ("stx_ctime", _StatxTimestamp),
        ("stx_mtime", _StatxTimestamp),
        ("stx_rdev_major", ctypes.c_uint32),
        ("stx_rdev_minor", ctypes.c_uint32),
        ("stx_dev_major", ctypes.c_uint32),
        ("stx_dev_minor", ctypes.c_uint32),
        ("__spare2", ctypes.c_uint64 * 14),
    ]


def _load_statx():
    """Return a callable statx(), or None when this platform has no usable one."""
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
    except OSError:  # pragma: no cover - no libc to load
        return None
    fn = getattr(libc, "statx", None)  # glibc >= 2.28
    if fn is None:  # pragma: no cover - older glibc / musl
        return None
    fn.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.POINTER(_Statx),
    ]
    fn.restype = ctypes.c_int
    return fn


_statx = _load_statx()


@dataclass(frozen=True)
class BirthTime:
    """Explicitly three-state: present, or absent with a stated reason."""

    value: datetime | None
    available: bool
    unavailable_reason: str | None = None

    @classmethod
    def missing(cls, reason: str) -> BirthTime:
        return cls(value=None, available=False, unavailable_reason=reason)


def birth_time(path: Path) -> BirthTime:
    """Best-effort true creation time for *path*."""
    if _statx is None:
        return BirthTime.missing("statx() unavailable on this platform")

    buf = _Statx()
    rc = _statx(
        _AT_FDCWD,
        os.fsencode(str(path)),
        _AT_STATX_SYNC_AS_STAT,
        _STATX_BTIME,
        ctypes.byref(buf),
    )
    if rc != 0:
        err = ctypes.get_errno()
        return BirthTime.missing(f"statx() failed: {os.strerror(err)}")

    # A successful call still has to be asked whether it actually filled the
    # field in; most filesystems here will not have.
    if not buf.stx_mask & _STATX_BTIME:
        return BirthTime.missing("filesystem does not record a birth time")

    if buf.stx_btime.tv_sec <= 0:
        return BirthTime.missing("filesystem reported a null birth time")

    try:
        value = datetime.fromtimestamp(buf.stx_btime.tv_sec + buf.stx_btime.tv_nsec / 1e9)
    except (OverflowError, OSError, ValueError):
        return BirthTime.missing("filesystem reported an out-of-range birth time")

    return BirthTime(value=value, available=True)


def mtime(path: Path) -> datetime:
    """Modification time as a naive local datetime."""
    return datetime.fromtimestamp(path.stat().st_mtime)
