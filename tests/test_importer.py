import os
from datetime import datetime

import pytest
from tests.conftest import make_file

from media_importer.importer import (
    TEMP_PREFIX,
    TEMP_SUFFIX,
    ImportCallbacks,
    execute,
    sweep_temp_files,
)
from media_importer.models import Action, CollisionPolicy
from media_importer.planner import build_plan

DT = datetime(2025, 8, 27, 10, 53, 42)


def plan_and_run(config, extractor):
    plan = build_plan(config, extractor)
    return plan, execute(plan)


class TestSuccessfulCopy:
    def test_file_is_copied_to_its_destination(self, config, extractor):
        make_file(config.source_path / "deep/IMG_1.JPG", b"pixels")
        extractor.dates["IMG_1.JPG"] = DT
        _, report = plan_and_run(config, extractor)
        target = config.photo_library / "2025/08/27/IMG_1.JPG"
        assert report.copied_count == 1
        assert target.read_bytes() == b"pixels"

    def test_destination_directories_are_created(self, config, extractor):
        make_file(config.source_path / "IMG_1.JPG")
        extractor.dates["IMG_1.JPG"] = DT
        plan_and_run(config, extractor)
        assert (config.photo_library / "2025/08/27").is_dir()

    def test_mtime_is_preserved(self, config, extractor):
        source = make_file(config.source_path / "IMG_1.JPG")
        stamp = DT.timestamp()
        os.utime(source, (stamp, stamp))
        extractor.dates["IMG_1.JPG"] = DT
        plan_and_run(config, extractor)
        target = config.photo_library / "2025/08/27/IMG_1.JPG"
        assert target.stat().st_mtime == pytest.approx(stamp)

    def test_no_temporary_files_are_left_behind(self, config, extractor):
        make_file(config.source_path / "IMG_1.JPG")
        extractor.dates["IMG_1.JPG"] = DT
        plan_and_run(config, extractor)
        leftovers = [p.name for p in config.photo_library.rglob("*") if TEMP_PREFIX in p.name]
        assert leftovers == []


class TestSourceImmutability:
    def test_source_files_survive_an_import(self, config, extractor):
        source = make_file(config.source_path / "IMG_1.JPG", b"pixels")
        extractor.dates["IMG_1.JPG"] = DT
        plan_and_run(config, extractor)
        assert source.exists() and source.read_bytes() == b"pixels"

    def test_skipped_jpeg_stays_in_the_source(self, config, extractor):
        make_file(config.source_path / "cam/IMG_1.DNG")
        jpeg = make_file(config.source_path / "cam/IMG_1.JPG")
        extractor.dates["IMG_1.DNG"] = DT
        extractor.dates["IMG_1.JPG"] = DT
        plan_and_run(config, extractor)
        assert jpeg.exists()
        assert not (config.photo_library / "2025/08/27/IMG_1.JPG").exists()
        assert (config.photo_library / "2025/08/27/IMG_1.DNG").exists()


class TestIdempotency:
    def test_second_run_copies_nothing(self, config, extractor):
        for n in range(5):
            make_file(config.source_path / f"IMG_{n}.JPG", f"pixels{n}".encode())
            extractor.dates[f"IMG_{n}.JPG"] = DT

        _, first = plan_and_run(config, extractor)
        assert first.copied_count == 5

        second_plan, second = plan_and_run(config, extractor)
        assert second.copied_count == 0
        assert len(second_plan.already_imported) == 5
        assert len(second_plan.collisions) == 0

    def test_repeated_runs_do_not_duplicate(self, config, extractor):
        make_file(config.source_path / "IMG_1.JPG")
        extractor.dates["IMG_1.JPG"] = DT
        for _ in range(3):
            plan_and_run(config, extractor)
        files = list((config.photo_library / "2025/08/27").iterdir())
        assert len(files) == 1


class TestExistingDestinations:
    def test_conflicting_file_is_not_overwritten(self, config, extractor):
        make_file(config.source_path / "IMG_1.JPG", b"incoming-and-longer")
        target = make_file(config.photo_library / "2025/08/27/IMG_1.JPG", b"original")
        extractor.dates["IMG_1.JPG"] = DT
        _, report = plan_and_run(config, extractor)
        assert report.copied_count == 0
        assert target.read_bytes() == b"original"

    def test_clobber_replaces_the_file(self, config, extractor):
        source = make_file(config.source_path / "IMG_1.JPG", b"incoming-longer")
        target = make_file(config.photo_library / "2025/08/27/IMG_1.JPG", b"old")
        os.utime(target, (0, source.stat().st_mtime - 3600))
        extractor.dates["IMG_1.JPG"] = DT
        config.on_collision = CollisionPolicy.CLOBBER
        _, report = plan_and_run(config, extractor)
        assert report.copied_count == 1
        assert target.read_bytes() == b"incoming-longer"

    def test_rename_keeps_both(self, config, extractor):
        make_file(config.source_path / "IMG_1.JPG", b"incoming-and-longer")
        target = make_file(config.photo_library / "2025/08/27/IMG_1.JPG", b"original")
        extractor.dates["IMG_1.JPG"] = DT
        config.on_collision = CollisionPolicy.RENAME
        _, report = plan_and_run(config, extractor)
        assert report.copied_count == 1
        assert target.read_bytes() == b"original"
        assert (
            config.photo_library / "2025/08/27/IMG_1-1.JPG"
        ).read_bytes() == b"incoming-and-longer"

    def test_destination_appearing_after_planning_is_not_clobbered(self, config, extractor):
        """Closes the window between the planner's stat and the executor's write."""
        make_file(config.source_path / "IMG_1.JPG", b"incoming")
        extractor.dates["IMG_1.JPG"] = DT
        plan = build_plan(config, extractor)
        assert plan.to_copy[0].action is Action.COPY

        sneaked = make_file(config.photo_library / "2025/08/27/IMG_1.JPG", b"appeared")
        report = execute(plan)

        assert report.copied_count == 0
        assert report.failed_count == 1
        assert sneaked.read_bytes() == b"appeared"


class TestPartialCopies:
    def test_stale_partial_files_are_swept(self, config, extractor):
        directory = config.photo_library / "2025/08/27"
        directory.mkdir(parents=True)
        stale = directory / f"{TEMP_PREFIX}999-IMG_1.JPG{TEMP_SUFFIX}"
        stale.write_bytes(b"half a file")

        make_file(config.source_path / "IMG_1.JPG")
        extractor.dates["IMG_1.JPG"] = DT
        plan_and_run(config, extractor)

        assert not stale.exists()

    def test_sweep_leaves_real_files_alone(self, tmp_path):
        keep = make_file(tmp_path / "IMG_1.JPG")
        stale = tmp_path / f"{TEMP_PREFIX}1-x{TEMP_SUFFIX}"
        stale.write_bytes(b"junk")
        assert sweep_temp_files(tmp_path) == 1
        assert keep.exists() and not stale.exists()

    def test_a_failed_copy_leaves_no_destination_file(self, config, extractor, monkeypatch):
        make_file(config.source_path / "IMG_1.JPG")
        extractor.dates["IMG_1.JPG"] = DT
        plan = build_plan(config, extractor)

        def boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr("media_importer.importer.shutil.copy2", boom)
        report = execute(plan)

        assert report.failed_count == 1
        assert not (config.photo_library / "2025/08/27/IMG_1.JPG").exists()


class TestErrorHandling:
    def test_one_failure_does_not_abort_the_rest(self, config, extractor, monkeypatch):
        for n in range(4):
            make_file(config.source_path / f"IMG_{n}.JPG", f"data{n}".encode())
            extractor.dates[f"IMG_{n}.JPG"] = DT
        plan = build_plan(config, extractor)

        real_copy = __import__("shutil").copy2
        calls = {"n": 0}

        def flaky(src, dst, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("transient failure")
            return real_copy(src, dst, *args, **kwargs)

        monkeypatch.setattr("media_importer.importer.shutil.copy2", flaky)
        report = execute(plan)

        assert report.copied_count == 3
        assert report.failed_count == 1
        assert "transient failure" in report.failed[0][1]

    def test_failures_identify_the_file(self, config, extractor, monkeypatch):
        make_file(config.source_path / "IMG_1.JPG")
        extractor.dates["IMG_1.JPG"] = DT
        plan = build_plan(config, extractor)
        monkeypatch.setattr(
            "media_importer.importer.shutil.copy2",
            lambda *a, **k: (_ for _ in ()).throw(OSError("nope")),
        )
        report = execute(plan)
        assert report.failed[0][0].source_path.name == "IMG_1.JPG"


class TestCallbacks:
    def test_progress_callbacks_fire(self, config, extractor):
        for n in range(3):
            make_file(config.source_path / f"IMG_{n}.JPG", f"d{n}".encode())
            extractor.dates[f"IMG_{n}.JPG"] = DT
        plan = build_plan(config, extractor)

        started, completed = [], []
        callbacks = ImportCallbacks(
            on_file_started=lambda item, i, total: started.append((item.filename, i, total)),
            on_file_completed=lambda item, i, total: completed.append(item.filename),
        )
        execute(plan, callbacks)

        assert len(started) == 3 and len(completed) == 3
        assert started[0][2] == 3

    def test_cancellation_stops_early(self, config, extractor):
        for n in range(5):
            make_file(config.source_path / f"IMG_{n}.JPG", f"d{n}".encode())
            extractor.dates[f"IMG_{n}.JPG"] = DT
        plan = build_plan(config, extractor)

        seen = {"n": 0}

        def should_stop():
            seen["n"] += 1
            return seen["n"] > 2

        report = execute(plan, should_stop=should_stop)
        assert report.copied_count == 2


def test_end_to_end_matches_the_specification_example(config, extractor):
    """The worked example from SPEC section 25."""
    make_file(config.source_path / "camera/random/IMG_001.DNG", b"raw")
    make_file(config.source_path / "camera/random/IMG_001.JPG", b"jpg")
    make_file(config.source_path / "camera/videos/20250827_105030.mp4", b"vid")
    make_file(config.source_path / "phone/DCIM/IMG_002.JPG", b"photo2")
    extractor.dates["IMG_001.DNG"] = DT
    extractor.dates["IMG_001.JPG"] = DT
    extractor.dates["IMG_002.JPG"] = datetime(2025, 8, 28, 9, 0, 0)

    _plan, report = plan_and_run(config, extractor)

    assert report.copied_count == 3
    assert (config.photo_library / "2025/08/27/IMG_001.DNG").exists()
    assert (config.photo_library / "2025/08/28/IMG_002.JPG").exists()
    assert (config.video_library / "2025/08/27/20250827_105030.mp4").exists()
    assert not (config.photo_library / "2025/08/27/IMG_001.JPG").exists()
    assert (config.source_path / "camera/random/IMG_001.JPG").exists()


def test_same_name_size_and_date_counts_as_already_imported(config, extractor):
    """A documented consequence of comparing by size + date instead of hashing.

    Two genuinely different files that share a destination name, a byte count
    and a capture date are treated as one already-imported file and the second
    is skipped rather than flagged. That is the deliberate trade for never
    reading file contents; the alternative is hashing the whole library on
    every run.
    """
    make_file(config.source_path / "IMG_1.JPG", b"aaaaaaaa")
    target = make_file(config.photo_library / "2025/08/27/IMG_1.JPG", b"bbbbbbbb")
    extractor.dates["IMG_1.JPG"] = DT

    plan, report = plan_and_run(config, extractor)

    assert len(plan.already_imported) == 1
    assert report.copied_count == 0
    assert target.read_bytes() == b"bbbbbbbb"
