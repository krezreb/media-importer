from datetime import datetime
from pathlib import Path

from media_importer.models import DateSource, MediaItem, MediaType, ResolvedDate
from media_importer.pairing import find_pairs, suppressed_jpegs

DT = datetime(2025, 8, 27, 10, 53, 42)


def item(path: str, dated: bool = True) -> MediaItem:
    media = MediaItem(Path(path), MediaType.PHOTO)
    if dated:
        media.resolved = ResolvedDate(DT, DateSource.EXIF_DATE_TIME_ORIGINAL)
    return media


def test_matching_pair():
    pairs = find_pairs([item("/a/IMG_1.DNG"), item("/a/IMG_1.JPG")])
    assert len(pairs) == 1
    assert pairs[0].raw.filename == "IMG_1.DNG"
    assert pairs[0].jpeg.filename == "IMG_1.JPG"


def test_stem_matching_is_case_insensitive():
    assert len(find_pairs([item("/a/IMG_1.DNG"), item("/a/img_1.jpg")])) == 1


def test_different_directories_do_not_pair():
    """A JPEG must not be skipped because a RAW exists elsewhere in the tree."""
    assert find_pairs([item("/a/IMG_1.DNG"), item("/b/IMG_1.JPG")]) == []


def test_different_stems_do_not_pair():
    assert find_pairs([item("/a/IMG_1.DNG"), item("/a/IMG_2.JPG")]) == []


def test_raw_without_jpeg():
    assert find_pairs([item("/a/IMG_1.DNG")]) == []


def test_jpeg_without_raw():
    assert find_pairs([item("/a/IMG_1.JPG")]) == []


def test_tiff_is_not_a_raw_partner():
    assert find_pairs([item("/a/IMG_1.TIF"), item("/a/IMG_1.JPG")]) == []


def test_png_is_not_a_raw_partner():
    assert find_pairs([item("/a/IMG_1.PNG"), item("/a/IMG_1.JPG")]) == []


class TestAmbiguousGroups:
    """Anything ambiguous imports both files: disk space is cheaper than a lost photo."""

    def test_two_raws_sharing_a_stem(self):
        group = [item("/a/IMG_1.DNG"), item("/a/IMG_1.CR2"), item("/a/IMG_1.JPG")]
        assert find_pairs(group) == []

    def test_both_jpg_and_jpeg(self):
        group = [item("/a/IMG_1.DNG"), item("/a/IMG_1.JPG"), item("/a/IMG_1.JPEG")]
        assert find_pairs(group) == []

    def test_three_or_more_files(self):
        group = [item("/a/IMG_1.DNG"), item("/a/IMG_1.JPG"), item("/a/IMG_1.PNG")]
        assert find_pairs(group) == []


def test_undated_raw_does_not_suppress_its_jpeg():
    """Otherwise a bad RAW takes a perfectly good JPEG down with it."""
    group = [item("/a/IMG_1.DNG", dated=False), item("/a/IMG_1.JPG")]
    assert find_pairs(group) == []
    assert suppressed_jpegs(group) == {}


def test_suppressed_map_points_at_the_raw():
    jpeg = item("/a/IMG_1.JPG")
    raw = item("/a/IMG_1.DNG")
    mapping = suppressed_jpegs([raw, jpeg])
    assert mapping[id(jpeg)] is raw


def test_live_photo_is_not_a_pair():
    """HEIC + MOV split across the two libraries by design, not by accident."""
    heic = MediaItem(Path("/a/IMG_1.HEIC"), MediaType.PHOTO)
    heic.resolved = ResolvedDate(DT, DateSource.EXIF_DATE_TIME_ORIGINAL)
    mov = MediaItem(Path("/a/IMG_1.MOV"), MediaType.VIDEO)
    mov.resolved = ResolvedDate(DT, DateSource.VIDEO_METADATA)
    assert find_pairs([heic, mov]) == []
