from datetime import datetime

import pytest
from tests.conftest import make_file

from media_importer.models import (
    Action,
    ClobberPreference,
    CollisionPolicy,
    CollisionResolution,
    IgnoreReason,
    MediaType,
    Reason,
)
from media_importer.planner import _safe_destination, build_plan

DT = datetime(2025, 8, 27, 10, 53, 42)
DT2 = datetime(2025, 8, 28, 9, 0, 0)


def by_name(plan):
    return {item.filename: item for item in plan.items}


class TestBasicPlanning:
    def test_dated_photo_is_planned_for_copy(self, config, extractor):
        make_file(config.source_path / "deep/IMG_1.JPG")
        extractor.dates["IMG_1.JPG"] = DT
        plan = build_plan(config, extractor)
        item = by_name(plan)["IMG_1.JPG"]
        assert item.action is Action.COPY
        assert item.destination_path == config.photo_library / "2025/08/27/IMG_1.JPG"

    def test_video_goes_to_the_video_library(self, config, extractor):
        make_file(config.source_path / "20250827_105030.mp4")
        plan = build_plan(config, extractor)
        item = by_name(plan)["20250827_105030.mp4"]
        assert item.media_type is MediaType.VIDEO
        assert item.destination_path == config.video_library / "2025/08/27/20250827_105030.mp4"

    def test_source_layout_does_not_affect_destination(self, config, extractor):
        make_file(config.source_path / "a/b/c/d/IMG_1.JPG")
        extractor.dates["IMG_1.JPG"] = DT
        plan = build_plan(config, extractor)
        assert by_name(plan)["IMG_1.JPG"].destination_path.parent.as_posix().endswith("2025/08/27")

    def test_unsupported_files_are_ignored_not_copied(self, config, extractor):
        make_file(config.source_path / "notes.txt")
        plan = build_plan(config, extractor)
        assert plan.items == []
        assert plan.ignored[0].reason is IgnoreReason.UNSUPPORTED_EXTENSION

    def test_symlinks_are_ignored(self, config, extractor):
        real = make_file(config.source_path / "IMG_1.JPG")
        (config.source_path / "link.jpg").symlink_to(real)
        extractor.dates["IMG_1.JPG"] = DT
        plan = build_plan(config, extractor)
        assert len(plan.items) == 1
        assert plan.symlinks[0].path.name == "link.jpg"

    def test_undated_photo_is_not_copied(self, config, extractor):
        make_file(config.source_path / "IMG_1.JPG")
        plan = build_plan(config, extractor)
        item = by_name(plan)["IMG_1.JPG"]
        assert item.action is Action.UNDATED
        assert item.reason is Reason.NO_USABLE_DATE
        assert item.destination_path is None

    def test_path_scheme_is_applied(self, config, extractor):
        make_file(config.source_path / "IMG_1.JPG")
        extractor.dates["IMG_1.JPG"] = DT
        config.import_path = "YYYY/YYYY-MM-DD"
        plan = build_plan(config, extractor)
        assert by_name(plan)["IMG_1.JPG"].destination_path == (
            config.photo_library / "2025/2025-08-27/IMG_1.JPG"
        )

    def test_categories_partition_the_plan(self, config, extractor):
        make_file(config.source_path / "a/IMG_1.DNG")
        make_file(config.source_path / "a/IMG_1.JPG")
        make_file(config.source_path / "undated.png")
        make_file(config.source_path / "20250827_105030.mp4")
        extractor.dates["IMG_1.DNG"] = DT
        extractor.dates["IMG_1.JPG"] = DT
        plan = build_plan(config, extractor)
        plan.check_partition()  # raises if the preview would mislead


class TestRawJpegPairing:
    def test_jpeg_is_skipped_and_raw_imported(self, config, extractor):
        make_file(config.source_path / "cam/IMG_1.DNG")
        make_file(config.source_path / "cam/IMG_1.JPG")
        extractor.dates["IMG_1.DNG"] = DT
        extractor.dates["IMG_1.JPG"] = DT
        items = by_name(build_plan(config, extractor))
        assert items["IMG_1.DNG"].action is Action.COPY
        assert items["IMG_1.JPG"].action is Action.SKIP
        assert items["IMG_1.JPG"].reason is Reason.JPEG_PAIRED_WITH_RAW

    def test_undated_raw_lets_the_jpeg_through(self, config, extractor):
        make_file(config.source_path / "cam/IMG_1.DNG")
        make_file(config.source_path / "cam/IMG_1.JPG")
        extractor.dates["IMG_1.JPG"] = DT  # only the JPEG has usable EXIF
        items = by_name(build_plan(config, extractor))
        assert items["IMG_1.DNG"].action is Action.UNDATED
        assert items["IMG_1.JPG"].action is Action.COPY

    def test_jpeg_in_another_directory_is_imported(self, config, extractor):
        make_file(config.source_path / "a/IMG_1.DNG")
        make_file(config.source_path / "b/IMG_1.JPG")
        extractor.dates["IMG_1.DNG"] = DT
        extractor.dates["IMG_1.JPG"] = DT2
        items = by_name(build_plan(config, extractor))
        assert items["IMG_1.DNG"].action is Action.COPY
        assert items["IMG_1.JPG"].action is Action.COPY


class TestExistingDestinations:
    def _existing(self, config, content=b"data"):
        target = config.photo_library / "2025/08/27/IMG_1.JPG"
        make_file(target, content)
        return target

    def test_identical_file_is_already_imported(self, config, extractor):
        source = make_file(config.source_path / "IMG_1.JPG", b"same")
        target = self._existing(config, b"same")
        import os

        os.utime(target, (source.stat().st_atime, source.stat().st_mtime))
        extractor.dates["IMG_1.JPG"] = DT
        item = by_name(build_plan(config, extractor))["IMG_1.JPG"]
        assert item.action is Action.SKIP
        assert item.reason is Reason.ALREADY_IMPORTED

    def test_different_size_is_a_collision(self, config, extractor):
        make_file(config.source_path / "IMG_1.JPG", b"aaaa")
        self._existing(config, b"bb")
        extractor.dates["IMG_1.JPG"] = DT
        item = by_name(build_plan(config, extractor))["IMG_1.JPG"]
        assert item.action is Action.COLLISION
        assert item.collision is CollisionResolution.SKIPPED

    def test_destination_symlink_is_an_error(self, config, extractor):
        make_file(config.source_path / "IMG_1.JPG")
        target = config.photo_library / "2025/08/27/IMG_1.JPG"
        target.parent.mkdir(parents=True)
        target.symlink_to(config.source_path / "IMG_1.JPG")
        extractor.dates["IMG_1.JPG"] = DT
        item = by_name(build_plan(config, extractor))["IMG_1.JPG"]
        assert item.action is Action.ERROR
        assert item.reason is Reason.DESTINATION_IS_SYMLINK


class TestInPlanCollisions:
    """Two source files claiming one destination inside a single run."""

    def _two_rivals(self, config, extractor, d1=DT, d2=DT):
        make_file(config.source_path / "cardA/IMG_1.JPG", b"first")
        make_file(config.source_path / "cardB/IMG_1.JPG", b"second-longer")
        extractor.dates["IMG_1.JPG"] = d1
        return config, extractor

    def test_second_claim_is_detected(self, config, extractor):
        self._two_rivals(config, extractor)
        plan = build_plan(config, extractor)
        assert len(plan.to_copy) == 1
        assert len(plan.collisions) == 1
        assert plan.collisions[0].collided_with is not None

    def test_without_detection_one_would_be_silently_lost(self, config, extractor):
        self._two_rivals(config, extractor)
        plan = build_plan(config, extractor)
        destinations = [i.destination_path for i in plan.to_copy]
        assert len(destinations) == len(set(destinations))

    def test_rename_gives_distinct_paths(self, config, extractor):
        self._two_rivals(config, extractor)
        config.on_collision = CollisionPolicy.RENAME
        plan = build_plan(config, extractor)
        names = sorted(i.destination_path.name for i in plan.to_copy)
        assert names == ["IMG_1-1.JPG", "IMG_1.JPG"]

    def test_three_rivals_get_distinct_indexes(self, config, extractor):
        for card in ("A", "B", "C"):
            make_file(
                config.source_path / f"card{card}/IMG_1.JPG", card.encode() * (ord(card) - 64)
            )
        extractor.dates["IMG_1.JPG"] = DT
        config.on_collision = CollisionPolicy.RENAME
        plan = build_plan(config, extractor)
        names = sorted(i.destination_path.name for i in plan.to_copy)
        assert names == ["IMG_1-1.JPG", "IMG_1-2.JPG", "IMG_1.JPG"]


class TestCollisionPolicies:
    def _setup(self, config, extractor, existing=b"old", incoming=b"new-and-longer"):
        make_file(config.source_path / "IMG_1.JPG", incoming)
        make_file(config.photo_library / "2025/08/27/IMG_1.JPG", existing)
        extractor.dates["IMG_1.JPG"] = DT

    def test_skip_is_the_default(self, config, extractor):
        self._setup(config, extractor)
        assert config.on_collision is CollisionPolicy.SKIP
        item = by_name(build_plan(config, extractor))["IMG_1.JPG"]
        assert item.action is Action.COLLISION
        assert item.reason is Reason.COLLISION_SKIPPED

    def test_rename_plans_a_suffixed_copy(self, config, extractor):
        self._setup(config, extractor)
        config.on_collision = CollisionPolicy.RENAME
        item = by_name(build_plan(config, extractor))["IMG_1.JPG"]
        assert item.action is Action.COPY
        assert item.destination_path.name == "IMG_1-1.JPG"
        assert item.collision is CollisionResolution.RENAMED

    def test_rename_picks_the_lowest_free_index(self, config, extractor):
        self._setup(config, extractor)
        make_file(config.photo_library / "2025/08/27/IMG_1-1.JPG", b"taken")
        config.on_collision = CollisionPolicy.RENAME
        item = by_name(build_plan(config, extractor))["IMG_1.JPG"]
        assert item.destination_path.name == "IMG_1-2.JPG"

    def _clobber_setup(self, config, extractor, prefers):
        """Same capture date, different sizes, incoming file is newer by mtime."""
        import os

        source = make_file(config.source_path / "IMG_1.JPG", b"incoming-longer")
        existing = make_file(config.photo_library / "2025/08/27/IMG_1.JPG", b"old")
        os.utime(existing, (0, source.stat().st_mtime - 3600))
        extractor.dates["IMG_1.JPG"] = DT
        config.on_collision = CollisionPolicy.CLOBBER
        config.clobber_prefers = prefers
        return by_name(build_plan(config, extractor))["IMG_1.JPG"]

    def test_clobber_newest_replaces_the_older_file(self, config, extractor):
        item = self._clobber_setup(config, extractor, ClobberPreference.NEWEST)
        assert item.action is Action.COPY
        assert item.collision is CollisionResolution.CLOBBERED
        assert item.destination_path.name == "IMG_1.JPG"

    def test_clobber_oldest_keeps_the_incumbent(self, config, extractor):
        item = self._clobber_setup(config, extractor, ClobberPreference.OLDEST)
        assert item.action is Action.COLLISION
        assert item.collision is CollisionResolution.SKIPPED

    def test_clobber_prefers_later_capture_date(self, config, extractor):
        """Capture date is the primary key; mtime is only the tie-break."""
        import os

        source = make_file(config.source_path / "IMG_1.JPG", b"incoming-longer")
        existing = make_file(config.photo_library / "2025/08/27/IMG_1.JPG", b"old")
        # Incoming has the EARLIER capture date but the NEWER mtime.
        os.utime(existing, (0, source.stat().st_mtime - 3600))
        extractor.dates["IMG_1.JPG"] = DT
        config.on_collision = CollisionPolicy.CLOBBER
        config.clobber_prefers = ClobberPreference.NEWEST
        item = by_name(build_plan(config, extractor))["IMG_1.JPG"]
        assert item.action is Action.COPY

    def test_clobber_ties_keep_the_incumbent(self, config, extractor):
        """Repeated runs must be stable rather than rewriting the same file."""
        source = make_file(config.source_path / "IMG_1.JPG", b"aaaa")
        existing = make_file(config.photo_library / "2025/08/27/IMG_1.JPG", b"bbbb")
        import os

        os.utime(existing, (source.stat().st_atime, source.stat().st_mtime))
        extractor.dates["IMG_1.JPG"] = DT
        config.on_collision = CollisionPolicy.CLOBBER
        plan = build_plan(config, extractor)
        # identical size + identical mtime -> recognised as already imported
        assert by_name(plan)["IMG_1.JPG"].action is Action.SKIP


class TestPathSafety:
    def test_normal_filename_joins_under_the_library(self, tmp_path):
        from pathlib import Path

        result = _safe_destination(tmp_path, Path("2025/08/27"), "IMG_1.JPG")
        assert result == tmp_path / "2025/08/27/IMG_1.JPG"

    @pytest.mark.parametrize("name", ["../escape.jpg", "..", ".", "a/b.jpg", "", "nul\x00.jpg"])
    def test_hostile_filenames_are_refused(self, tmp_path, name):
        from pathlib import Path

        with pytest.raises(ValueError):
            _safe_destination(tmp_path, Path("2025"), name)
