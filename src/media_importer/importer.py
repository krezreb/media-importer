"""Import execution.

Carries out an already-built plan.  It never re-derives dates, pairing, or
collision decisions -- if the plan says COPY to a path, that is what happens.

Progress is emitted through callbacks rather than printed, so the importer
stays independent of the presentation layer.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .models import (
    Action,
    CollisionResolution,
    ImportAction,
    ImportPlan,
    ImportReport,
    PlanItem,
)

log = logging.getLogger(__name__)

TEMP_PREFIX = ".mediaimport-"
TEMP_SUFFIX = ".partial"


@dataclass
class ImportCallbacks:
    """Subscribe to progress without coupling the importer to a UI."""

    on_file_started: object = None
    on_file_completed: object = None
    on_file_failed: object = None

    def started(self, item: PlanItem, index: int, total: int) -> None:
        if callable(self.on_file_started):
            self.on_file_started(item, index, total)

    def completed(self, item: PlanItem, index: int, total: int) -> None:
        if callable(self.on_file_completed):
            self.on_file_completed(item, index, total)

    def failed(self, item: PlanItem, error: str, index: int, total: int) -> None:
        if callable(self.on_file_failed):
            self.on_file_failed(item, error, index, total)


def execute(
    plan: ImportPlan,
    callbacks: ImportCallbacks | None = None,
    should_stop: object = None,
    action: ImportAction = ImportAction.COPY,
) -> ImportReport:
    """Run every planned import in *plan*. One file's failure never aborts the rest.

    With `ImportAction.MOVE` a source file is deleted only after its copy is
    verifiably in place, and only for files that are actually imported.
    Anything skipped, undated, colliding or already present keeps its source.
    """
    cb = callbacks or ImportCallbacks()
    report = ImportReport(plan=plan)

    work = plan.to_copy
    total = len(work)
    swept: set[Path] = set()

    for index, item in enumerate(work, start=1):
        if callable(should_stop) and should_stop():
            log.info("Import cancelled after %d/%d files", index - 1, total)
            break

        cb.started(item, index, total)
        try:
            _import_one(item, swept, action)
        except Exception as exc:
            log.exception("Failed to import %s", item.source_path)
            report.failed.append((item, str(exc)))
            cb.failed(item, str(exc), index, total)
        else:
            report.copied.append(item)
            cb.completed(item, index, total)

    return report


def _import_one(item: PlanItem, swept: set[Path], action: ImportAction) -> None:
    assert item.action is Action.COPY
    destination = item.destination_path
    assert destination is not None

    directory = destination.parent
    directory.mkdir(parents=True, exist_ok=True)

    # Debris from a killed run would otherwise sit in the library forever, and
    # would be seen as a real file by anything later scanning that tree.
    if directory not in swept:
        sweep_temp_files(directory)
        swept.add(directory)

    clobbering = item.collision is CollisionResolution.CLOBBERED

    if action is ImportAction.MOVE and not clobbering and _fast_move(item.source_path, destination):
        return

    # The temporary lives in the destination directory, not /tmp: rename is
    # only atomic within one filesystem, and the library is very often on a
    # different mount than the system temp directory.
    tmp = directory / f"{TEMP_PREFIX}{os.getpid()}-{destination.name}{TEMP_SUFFIX}"
    try:
        # copy2 preserves mtime. Downstream tools read library timestamps, and
        # it is also what lets a repeat import recognise its own earlier copies
        # without reading any metadata.
        shutil.copy2(item.source_path, tmp)
        _finalize(tmp, destination, clobbering=clobbering)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:  # pragma: no cover
                log.warning("Could not remove temporary file %s", tmp)

    if action is ImportAction.MOVE:
        # Reached only when _finalize did not raise, so the destination is
        # complete and verified before the original is given up.
        _remove_source(item.source_path)


def _fast_move(source: Path, destination: Path) -> bool:
    """Try to move within one filesystem without rewriting the bytes.

    os.link is atomic, fails if the destination exists (so it keeps the same
    exclusive-create guarantee as an ordinary copy), preserves the timestamps
    for free, and is instant regardless of file size -- which matters a great
    deal when moving multi-gigabyte video.

    Returns False for a cross-device move (EXDEV), where the caller falls back
    to copying.
    """
    try:
        os.link(source, destination)
    except FileExistsError:
        raise FileExistsError(
            f"Destination appeared after planning and was not overwritten: {destination}"
        ) from None
    except OSError:
        return False  # different filesystem, or links unsupported

    _remove_source(source)
    return True


def _remove_source(source: Path) -> None:
    try:
        source.unlink()
    except OSError as exc:
        # The import itself succeeded; failing to tidy up must not undo it or
        # be reported as a failed import.
        log.warning("Imported but could not remove source %s: %s", source, exc)


def _finalize(tmp: Path, destination: Path, *, clobbering: bool) -> None:
    """Move *tmp* into place atomically.

    For an ordinary copy the destination is expected to be free, and it must
    stay that way: os.rename would happily overwrite a file that appeared
    between planning and now.  os.link fails if the target exists, giving an
    atomic exclusive create, so that window is closed rather than merely
    narrowed.
    """
    if clobbering:
        os.replace(tmp, destination)
        return

    try:
        os.link(tmp, destination)
    except FileExistsError:
        raise FileExistsError(
            f"Destination appeared after planning and was not overwritten: {destination}"
        ) from None
    except OSError:
        # Some filesystems refuse hard links; fall back to a checked rename.
        if destination.exists():
            raise FileExistsError(
                f"Destination appeared after planning and was not overwritten: {destination}"
            ) from None
        os.replace(tmp, destination)
        return
    tmp.unlink()


def sweep_temp_files(directory: Path) -> int:
    """Delete stale partial files left by an interrupted run. Returns the count."""
    removed = 0
    try:
        entries = list(directory.iterdir())
    except OSError:  # pragma: no cover
        return 0
    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            continue
        if entry.name.startswith(TEMP_PREFIX) and entry.name.endswith(TEMP_SUFFIX):
            try:
                entry.unlink()
                removed += 1
                log.info("Removed stale partial file: %s", entry)
            except OSError:  # pragma: no cover
                log.warning("Could not remove stale partial file: %s", entry)
    return removed
