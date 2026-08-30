"""Move-mode import.

MOVE deliberately breaks the source-immutability rule that governs COPY, so
these tests pin exactly how far that goes: a source file is removed only when
its copy is verifiably in place, and only for files that are actually imported.
"""

from __future__ import annotations

from datetime import datetime

from tests.conftest import make_file

from media_importer.importer import execute
from media_importer.models import CollisionPolicy, ImportAction
from media_importer.planner import build_plan

DT = datetime(2025, 8, 27, 10, 53, 42)


def run_move(config, extractor):
    plan = build_plan(config, extractor)
    return plan, execute(plan, action=ImportAction.MOVE)


class TestMoveRemovesTheSource:
    def test_imported_file_leaves_the_source(self, config, extractor):
        source = make_file(config.source_path / "IMG_1.JPG", b"pixels")
        extractor.dates["IMG_1.JPG"] = DT
        _, report = run_move(config, extractor)
        assert report.copied_count == 1
        assert (config.photo_library / "2025/08/27/IMG_1.JPG").read_bytes() == b"pixels"
        assert not source.exists()

    def test_content_and_mtime_survive_the_move(self, config, extractor):
        import os

        source = make_file(config.source_path / "IMG_1.JPG", b"pixels")
        stamp = DT.timestamp()
        os.utime(source, (stamp, stamp))
        extractor.dates["IMG_1.JPG"] = DT
        run_move(config, extractor)
        target = config.photo_library / "2025/08/27/IMG_1.JPG"
        assert target.read_bytes() == b"pixels"
        assert target.stat().st_mtime == int(stamp) or abs(target.stat().st_mtime - stamp) < 1

    def test_video_moves_to_the_video_library(self, config, extractor):
        source = make_file(config.source_path / "20250827_105030.mp4", b"vid")
        run_move(config, extractor)
        assert (config.video_library / "2025/08/27/20250827_105030.mp4").exists()
        assert not source.exists()


class TestMoveLeavesEverythingElseAlone:
    """Only files that are genuinely imported may be removed."""

    def test_undated_file_stays_put(self, config, extractor):
        source = make_file(config.source_path / "IMG_1.JPG")
        _, report = run_move(config, extractor)
        assert report.copied_count == 0
        assert source.exists()

    def test_paired_jpeg_stays_put(self, config, extractor):
        raw = make_file(config.source_path / "cam/IMG_1.DNG", b"raw")
        jpeg = make_file(config.source_path / "cam/IMG_1.JPG", b"jpg")
        extractor.dates["IMG_1.DNG"] = DT
        extractor.dates["IMG_1.JPG"] = DT
        run_move(config, extractor)
        assert not raw.exists(), "the RAW was imported, so it should have moved"
        assert jpeg.exists(), "the skipped JPEG must never be deleted"

    def test_collision_leaves_the_source(self, config, extractor):
        source = make_file(config.source_path / "IMG_1.JPG", b"incoming-and-longer")
        make_file(config.photo_library / "2025/08/27/IMG_1.JPG", b"original")
        extractor.dates["IMG_1.JPG"] = DT
        _, report = run_move(config, extractor)
        assert report.copied_count == 0
        assert source.exists()

    def test_already_imported_leaves_the_source(self, config, extractor):
        import os

        source = make_file(config.source_path / "IMG_1.JPG", b"same")
        target = make_file(config.photo_library / "2025/08/27/IMG_1.JPG", b"same")
        os.utime(target, (source.stat().st_atime, source.stat().st_mtime))
        extractor.dates["IMG_1.JPG"] = DT
        plan, _report = run_move(config, extractor)
        assert len(plan.already_imported) == 1
        assert source.exists(), "an existing copy is not a reason to delete the original"

    def test_unsupported_files_stay_put(self, config, extractor):
        notes = make_file(config.source_path / "notes.txt")
        run_move(config, extractor)
        assert notes.exists()

    def test_failed_import_keeps_the_source(self, config, extractor, monkeypatch):
        """The source must survive if the destination never landed."""
        source = make_file(config.source_path / "IMG_1.JPG")
        extractor.dates["IMG_1.JPG"] = DT
        plan = build_plan(config, extractor)

        monkeypatch.setattr(
            "media_importer.importer.os.link", lambda *a: (_ for _ in ()).throw(OSError())
        )
        monkeypatch.setattr(
            "media_importer.importer.shutil.copy2",
            lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
        )
        report = execute(plan, action=ImportAction.MOVE)

        assert report.failed_count == 1
        assert source.exists()


class TestMoveMechanics:
    def test_same_filesystem_uses_the_fast_path(self, config, extractor, monkeypatch):
        """A multi-gigabyte same-disk move must not rewrite the bytes."""
        make_file(config.source_path / "IMG_1.JPG", b"pixels")
        extractor.dates["IMG_1.JPG"] = DT

        copied = {"n": 0}
        real = __import__("shutil").copy2

        def counting(*a, **k):
            copied["n"] += 1
            return real(*a, **k)

        monkeypatch.setattr("media_importer.importer.shutil.copy2", counting)
        run_move(config, extractor)

        assert copied["n"] == 0, "same-filesystem move should not have copied"
        assert (config.photo_library / "2025/08/27/IMG_1.JPG").exists()

    def test_cross_device_falls_back_to_copying(self, config, extractor, monkeypatch):
        source = make_file(config.source_path / "IMG_1.JPG", b"pixels")
        extractor.dates["IMG_1.JPG"] = DT

        def no_links(*args):
            raise OSError(18, "Invalid cross-device link")

        monkeypatch.setattr("media_importer.importer.os.link", no_links)
        _, report = run_move(config, extractor)

        assert report.copied_count == 1
        assert (config.photo_library / "2025/08/27/IMG_1.JPG").read_bytes() == b"pixels"
        assert not source.exists()

    def test_clobbering_move_replaces_and_removes_source(self, config, extractor):
        import os

        source = make_file(config.source_path / "IMG_1.JPG", b"incoming-longer")
        target = make_file(config.photo_library / "2025/08/27/IMG_1.JPG", b"old")
        os.utime(target, (0, source.stat().st_mtime - 3600))
        extractor.dates["IMG_1.JPG"] = DT
        config.on_collision = CollisionPolicy.CLOBBER

        _, report = run_move(config, extractor)

        assert report.copied_count == 1
        assert target.read_bytes() == b"incoming-longer"
        assert not source.exists()

    def test_destination_appearing_after_planning_keeps_the_source(self, config, extractor):
        make_file(config.source_path / "IMG_1.JPG", b"incoming")
        extractor.dates["IMG_1.JPG"] = DT
        plan = build_plan(config, extractor)

        sneaked = make_file(config.photo_library / "2025/08/27/IMG_1.JPG", b"appeared")
        report = execute(plan, action=ImportAction.MOVE)

        assert report.failed_count == 1
        assert sneaked.read_bytes() == b"appeared"
        assert (config.source_path / "IMG_1.JPG").exists()

    def test_copy_mode_is_still_the_default(self, config, extractor):
        source = make_file(config.source_path / "IMG_1.JPG")
        extractor.dates["IMG_1.JPG"] = DT
        plan = build_plan(config, extractor)
        execute(plan)
        assert source.exists()


def test_move_then_rerun_finds_nothing(config, extractor):
    for n in range(3):
        make_file(config.source_path / f"IMG_{n}.JPG", f"pixels{n}".encode())
        extractor.dates[f"IMG_{n}.JPG"] = DT

    _, first = run_move(config, extractor)
    assert first.copied_count == 3

    second_plan, second = run_move(config, extractor)
    assert second.copied_count == 0
    assert second_plan.items == []
