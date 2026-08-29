from datetime import datetime, timedelta

from tests.conftest import FakeExtractor, make_file

from media_importer.date_resolver import FLOOR, DateResolver, is_plausible
from media_importer.metadata import MetadataCandidate
from media_importer.models import DateSource, MediaType

MTIME = datetime(2025, 8, 29, 12, 0, 0)


class TestSanityCheck:
    def test_quicktime_epoch_rejected(self):
        assert not is_plausible(datetime(1904, 1, 1), MTIME)

    def test_unix_epoch_rejected(self):
        assert not is_plausible(datetime(1970, 1, 1), MTIME)

    def test_floor_is_inclusive(self):
        assert is_plausible(FLOOR, MTIME)
        assert not is_plausible(FLOOR - timedelta(days=1), MTIME)

    def test_old_capture_with_recent_mtime_accepted(self):
        """A file copied to a new disk keeps its real capture date."""
        assert is_plausible(datetime(2015, 6, 2), datetime(2024, 1, 10))

    def test_future_capture_rejected(self):
        """A file cannot have been recorded after it was last written."""
        assert not is_plausible(datetime(2031, 1, 1), MTIME)

    def test_slack_allows_small_clock_skew(self):
        assert is_plausible(MTIME + timedelta(days=365), MTIME)
        assert not is_plausible(MTIME + timedelta(days=731), MTIME)


class TestPhotoResolution:
    def test_prefers_date_time_original(self, tmp_path):
        photo = make_file(tmp_path / "a.jpg")
        extractor = FakeExtractor(
            {
                "a.jpg": [
                    MetadataCandidate(
                        datetime(2025, 8, 27), DateSource.EXIF_DATE_TIME_ORIGINAL, "x"
                    ),
                    MetadataCandidate(datetime(2020, 1, 1), DateSource.EXIF_CREATE_DATE, "y"),
                ]
            }
        )
        resolved = DateResolver(extractor).resolve_photo(photo)
        assert resolved.value == datetime(2025, 8, 27)
        assert resolved.source is DateSource.EXIF_DATE_TIME_ORIGINAL

    def test_falls_back_through_the_exif_chain(self, tmp_path):
        photo = make_file(tmp_path / "a.jpg")
        extractor = FakeExtractor(
            {"a.jpg": [MetadataCandidate(datetime(2025, 8, 27), DateSource.EXIF_DATE_TIME, "z")]}
        )
        assert DateResolver(extractor).resolve_photo(photo).source is DateSource.EXIF_DATE_TIME

    def test_missing_metadata_is_undated(self, tmp_path):
        photo = make_file(tmp_path / "a.jpg")
        assert DateResolver(FakeExtractor()).resolve_photo(photo) is None

    def test_garbage_metadata_is_undated(self, tmp_path):
        """A rejected date must not silently become a 1904 directory."""
        photo = make_file(tmp_path / "a.jpg")
        extractor = FakeExtractor(
            {
                "a.jpg": [
                    MetadataCandidate(datetime(1904, 1, 1), DateSource.EXIF_DATE_TIME_ORIGINAL, "x")
                ]
            }
        )
        assert DateResolver(extractor).resolve_photo(photo) is None

    def test_never_uses_filename(self, tmp_path):
        """Photos do not fall back to the filename, however tempting it looks."""
        photo = make_file(tmp_path / "20250827_105030.jpg")
        assert DateResolver(FakeExtractor()).resolve_photo(photo) is None

    def test_never_uses_filesystem_time(self, tmp_path):
        photo = make_file(tmp_path / "a.jpg")
        assert DateResolver(FakeExtractor()).resolve_photo(photo) is None


class TestVideoResolution:
    def test_metadata_wins(self, tmp_path):
        video = make_file(tmp_path / "20250101_000000.mp4")
        extractor = FakeExtractor({"20250101_000000.mp4": datetime(2025, 8, 27, 10, 50, 30)})
        resolved = DateResolver(extractor).resolve_video(video)
        assert resolved.source is DateSource.VIDEO_METADATA
        assert resolved.value == datetime(2025, 8, 27, 10, 50, 30)

    def test_filename_used_when_metadata_absent(self, tmp_path):
        video = make_file(tmp_path / "20250827_105030.mp4")
        resolved = DateResolver(FakeExtractor()).resolve_video(video)
        assert resolved.source is DateSource.FILENAME
        assert resolved.value == datetime(2025, 8, 27, 10, 50, 30)

    def test_garbage_metadata_falls_through_to_filename(self, tmp_path):
        """A rejected metadata date behaves exactly as if the field were absent."""
        video = make_file(tmp_path / "20250827_105030.mp4")
        extractor = FakeExtractor({"20250827_105030.mp4": datetime(1904, 1, 1)})
        resolved = DateResolver(extractor).resolve_video(video)
        assert resolved.source is DateSource.FILENAME

    def test_filesystem_time_is_the_last_resort(self, tmp_path):
        video = make_file(tmp_path / "clip.mp4")
        resolved = DateResolver(FakeExtractor()).resolve_video(video)
        assert resolved.source in (DateSource.FS_BIRTH_TIME, DateSource.FS_MTIME)

    def test_priority_order(self, tmp_path):
        """metadata > filename > filesystem, checked by removing one tier at a time."""
        named = make_file(tmp_path / "20250827_105030.mp4")

        with_meta = DateResolver(
            FakeExtractor({"20250827_105030.mp4": datetime(2020, 1, 1, 8, 0, 0)})
        ).resolve_video(named)
        assert with_meta.source is DateSource.VIDEO_METADATA

        without_meta = DateResolver(FakeExtractor()).resolve_video(named)
        assert without_meta.source is DateSource.FILENAME

        unnamed = make_file(tmp_path / "clip.mp4")
        assert DateResolver(FakeExtractor()).resolve_video(unnamed).source in (
            DateSource.FS_BIRTH_TIME,
            DateSource.FS_MTIME,
        )


def test_prefetch_only_batches_photos(tmp_path):
    from media_importer.models import MediaItem

    extractor = FakeExtractor()
    items = [
        MediaItem(make_file(tmp_path / "a.jpg"), MediaType.PHOTO),
        MediaItem(make_file(tmp_path / "b.mp4"), MediaType.VIDEO),
    ]
    DateResolver(extractor).prefetch(items)
    assert [p.name for p in extractor.prefetched] == ["a.jpg"]
