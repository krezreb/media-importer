"""Recursive source discovery.

The scanner only finds files.  It does not classify them, date them, decide
anything about them, or touch them.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigurationError
from .models import IgnoreReason

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScanEvent:
    path: Path
    ignore_reason: IgnoreReason | None = None

    @property
    def is_ignored(self) -> bool:
        return self.ignore_reason is not None


def scan(root: Path) -> Iterator[ScanEvent]:
    """Yield every regular file under *root*, lazily, without following symlinks.

    Not descending into symlinked directories also means a symlink loop cannot
    hang the scan, so no visited-inode bookkeeping is needed.
    """
    root = Path(root)
    if not root.exists():
        raise ConfigurationError(f"Source directory does not exist: {root}")
    if not root.is_dir():
        raise ConfigurationError(f"Source path is not a directory: {root}")

    yield from _walk(root)


def _walk(directory: Path) -> Iterator[ScanEvent]:
    try:
        entries = sorted(os.scandir(directory), key=lambda e: e.name)
    except PermissionError:
        log.warning("Permission denied, skipping directory: %s", directory)
        return
    except OSError as exc:
        log.warning("Could not read directory %s: %s", directory, exc)
        return

    for entry in entries:
        path = Path(entry.path)

        # Checked first, and without following: is_dir()/is_file() would
        # resolve the link and report on its target instead.
        if entry.is_symlink():
            log.debug("Ignoring symlink: %s", path)
            yield ScanEvent(path, IgnoreReason.SYMLINK)
            continue

        try:
            if entry.is_dir(follow_symlinks=False):
                yield from _walk(path)
            elif entry.is_file(follow_symlinks=False):
                yield ScanEvent(path)
        except OSError as exc:  # pragma: no cover - transient fs errors
            log.warning("Could not stat %s: %s", path, exc)
