from pathlib import Path

import pytest

from media_importer.classifier import (
    JPEG_EXTENSIONS,
    PHOTO_EXTENSIONS,
    RAW_EXTENSIONS,
    VIDEO_EXTENSIONS,
    classify,
    is_jpeg,
    is_raw,
)
from media_importer.models import MediaType


@pytest.mark.parametrize("name", ["a.jpg", "a.JPG", "a.jpeg", "a.png", "a.tif", "a.heic", "a.webp"])
def test_photo_extensions(name):
    assert classify(Path(name)) is MediaType.PHOTO


@pytest.mark.parametrize("name", ["a.dng", "a.CR2", "a.nef", "a.arw", "a.rw2"])
def test_raw_classifies_as_photo(name):
    assert classify(Path(name)) is MediaType.PHOTO
    assert is_raw(Path(name))


@pytest.mark.parametrize("name", ["a.mp4", "a.MOV", "a.mkv", "a.webm", "a.insv", "a.3gp"])
def test_video_extensions(name):
    assert classify(Path(name)) is MediaType.VIDEO


@pytest.mark.parametrize("name", ["a.txt", "a.xmp", "a", "a.doc"])
def test_unknown_extensions(name):
    assert classify(Path(name)) is MediaType.UNKNOWN


def test_classification_is_case_insensitive():
    assert classify(Path("a.JpEg")) is MediaType.PHOTO
    assert classify(Path("a.MpG")) is MediaType.VIDEO


def test_heic_is_supported():
    """iPhone default since 2017; the most likely extension when importing a phone."""
    assert ".heic" in PHOTO_EXTENSIONS
    assert ".heif" in PHOTO_EXTENSIONS


def test_tiff_is_not_raw():
    """A TIFF beside a JPEG must not be treated as a pair."""
    assert not is_raw(Path("a.tif"))
    assert not is_raw(Path("a.tiff"))
    assert ".tif" not in RAW_EXTENSIONS


def test_raw_and_jpeg_are_subsets_of_photos():
    assert RAW_EXTENSIONS < PHOTO_EXTENSIONS
    assert JPEG_EXTENSIONS < PHOTO_EXTENSIONS
    assert not (RAW_EXTENSIONS & VIDEO_EXTENSIONS)


def test_jpeg_detection():
    assert is_jpeg(Path("a.JPG")) and is_jpeg(Path("a.jpeg"))
    assert not is_jpeg(Path("a.png"))
