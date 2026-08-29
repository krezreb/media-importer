"""Extension-based media classification.

Classification is purely by extension and always case-insensitive.  The RAW and
JPEG sets are *subsets* of the photo set rather than separate categories: a RAW
file classifies as a photo, and the RAW subset is consulted only by the pairing
stage.
"""

from __future__ import annotations

from pathlib import Path

from .models import MediaType

# Camera manufacturer raw capture formats.  This set exists only to drive
# RAW/JPEG pairing.  TIFF is deliberately absent -- it is an ordinary photo
# format, not a manufacturer raw, so a .tif beside a .jpg is not a pair.
RAW_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".dng",
        ".cr2",
        ".cr3",
        ".nef",
        ".nrw",
        ".arw",
        ".orf",
        ".rw2",
        ".raf",
        ".pef",
        ".srw",
        ".rwl",
        ".erf",
        ".3fr",
        ".iiq",
        ".x3f",
        ".mef",
        ".mos",
        ".kdc",
        ".dcr",
    }
)

JPEG_EXTENSIONS: frozenset[str] = frozenset({".jpg", ".jpeg"})

_OTHER_PHOTO_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".png",
        ".tif",
        ".tiff",
        # HEIC/HEIF has been the iPhone default since 2017 and is the single
        # most likely extension to meet when importing from a phone.
        ".heic",
        ".heif",
        ".webp",
    }
)

PHOTO_EXTENSIONS: frozenset[str] = _OTHER_PHOTO_EXTENSIONS | JPEG_EXTENSIONS | RAW_EXTENSIONS

VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".mp4",
        ".mov",
        ".m4v",
        ".avi",
        ".mpg",
        ".mpeg",
        ".mts",
        ".3gp",
        ".mkv",
        ".webm",
        ".insv",
    }
)


def classify(path: Path) -> MediaType:
    ext = path.suffix.lower()
    if ext in PHOTO_EXTENSIONS:
        return MediaType.PHOTO
    if ext in VIDEO_EXTENSIONS:
        return MediaType.VIDEO
    return MediaType.UNKNOWN


def is_raw(path: Path) -> bool:
    return path.suffix.lower() in RAW_EXTENSIONS


def is_jpeg(path: Path) -> bool:
    return path.suffix.lower() in JPEG_EXTENSIONS
