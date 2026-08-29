# Photo & Video Import CLI — Technical Specification

## 1. Overview

Build an interactive Python CLI application with a terminal user interface (TUI) for importing photos and videos from an arbitrary source directory into two separate media libraries:

- A **photo library**
- A **video library**

The source directory is **not expected to have any particular directory structure**.

The application must recursively scan the source tree, identify media files, determine their capture date using metadata and fallback mechanisms, and copy them into the appropriate destination library.

The default destination organization is:

```text
YYYY/MM/DD/<filename>
```

However, the destination path scheme must be configurable by the user.

For example:

```text
PHOTO_LIBRARY/
└── 2025/
    └── 08/
        └── 27/
            └── IMG_1234.DNG

VIDEO_LIBRARY/
└── 2025/
    └── 08/
        └── 27/
            └── 20250827_105030.mp4
```

The source files must never be modified, moved, renamed, or deleted.

---

# 2. User Interface

The application must provide an interactive TUI rather than requiring command-line arguments for normal operation.

The main interface should allow the user to:

- Select/configure the source/import directory
- Select/configure the photo library destination
- Select/configure the video library destination
- Configure the destination path scheme
- Start an import
- Exit

The currently configured values should be clearly displayed.

The TUI should be designed for normal repeated use rather than requiring the user to specify all options every time.

---

# 3. Persistent Configuration

Application settings must be persisted in the user's home directory.

For example:

```text
~/.<application-name>/
└── config.toml
```

The exact configuration format and location may be chosen during implementation.

At minimum, the configuration must contain:

```toml
source_path = "/path/to/import"
photo_library = "/path/to/photos"
video_library = "/path/to/videos"
import_path = "YYYY/MM/DD"
```

Previously configured values must automatically be loaded when the application starts.

The default destination path scheme must be:

```text
YYYY/MM/DD
```

---

# 4. Source Scanning

The configured source directory must be scanned **recursively**.

The source directory structure has no significance and must not be reproduced in the destination.

For example:

```text
IMPORT/
├── camera/
│   ├── random/
│   │   ├── IMG_001.DNG
│   │   └── IMG_001.JPG
│   └── stuff/
│       └── video.mp4
├── phone/
│   └── DCIM/
│       └── 100APPLE/
│           └── IMG_2345.JPG
└── backup/
    └── old/
        └── 20250827_105030.mp4
```

All supported media files must be discovered regardless of where they occur in the source tree.

The destination location is determined from the media's resolved capture date and the configured destination path scheme.

---

# 5. Media Classification

The importer must classify discovered files into:

- Photos
- Videos
- Unsupported/unknown files

Supported extensions should be explicitly defined by the application and ideally be configurable.

At minimum, the application should recognize common formats.

### Photos

Examples include:

- JPG / JPEG
- PNG
- TIFF
- DNG
- CR2
- CR3
- NEF
- ORF
- RW2
- ARW
- Other common RAW formats

### Videos

Examples include:

- MP4
- MOV
- M4V
- AVI
- MPG / MPEG
- MTS
- 3GP

Unsupported files must be ignored and must not be copied.

---

# 6. Capture Date Resolution

Each media file must have a resolved date before an import destination can be determined.

The application must record not only the resolved date but also **where that date came from**.

For example:

```text
Date: 2025-08-27 10:53:42
Source: EXIF DateTimeOriginal
```

or:

```text
Date: 2025-08-27 10:50:30
Source: filename
```

The date resolution process differs between photos and videos.

---

# 7. Photo Date Resolution

For photos, the application should primarily use EXIF metadata to determine the original capture date.

The preferred field is:

```text
DateTimeOriginal
```

Other appropriate EXIF date fields may be used as fallbacks when `DateTimeOriginal` is unavailable.

A valid camera capture date from EXIF must take precedence over filesystem timestamps.

The source directory structure must never be used to determine the date.

## Example

A photo containing:

```text
DateTimeOriginal = 2025:08:27 10:53:42
```

must be assigned the date:

```text
2025-08-27
```

and, with the default path scheme, copied to:

```text
PHOTO_LIBRARY/2025/08/27/<filename>
```

If no reliable capture date can be obtained from photo metadata, the file must be reported as undated rather than silently using an arbitrary filesystem timestamp.

---

# 8. Video Date Resolution

Video metadata is less consistent than photo EXIF metadata, so videos use a multi-stage fallback process.

The date resolution priority must be:

1. Video metadata
2. Filename date/time
3. Filesystem creation/birth time

The first reliable date found must be used.

## 8.1 Metadata

First, inspect available video metadata for a recording/creation date.

The implementation should support common metadata sources, including:

- EXIF, when present
- QuickTime/MOV creation metadata
- Other date metadata exposed by the chosen metadata library/tool

Metadata representing an actual recording or creation date should take precedence over unrelated filesystem timestamps.

---

## 8.2 Filename Date

If no reliable date is available from metadata, inspect the filename for recognizable date/time patterns.

At minimum, the application must recognize:

```text
YYYYMMDD_HHMMSS
```

For example:

```text
20250827_105030.mp4
```

must resolve to:

```text
2025-08-27 10:50:30
```

Other common filename formats may be supported.

The filename parsing logic should be modular so additional patterns can be added easily.

---

## 8.3 Filesystem Creation Time

If neither metadata nor the filename provides a usable date, use the filesystem **creation/birth time**.

This is specifically the final fallback for videos.

Where the operating system exposes a true creation/birth timestamp, that value should be used rather than modification time.

If no creation/birth time is available, the video must be reported as undated.

The application must not silently substitute modification time unless explicitly configured to do so.

---

# 9. Date Resolution Summary

The rules can be summarized as follows.

### Photos

```text
EXIF capture date
       │
       ├── found → use it
       │
       └── not found → undated
```

### Videos

```text
Video metadata
       │
       ├── found → use it
       │
       ▼
Filename date/time
       │
       ├── found → use it
       │
       ▼
Filesystem creation/birth time
       │
       ├── found → use it
       │
       └── not found → undated
```

The selected date and its source must be available to the import planner and, preferably, visible in the preview.

---

# 10. Configurable Destination Path Scheme

The directory structure used in the destination libraries must be configurable.

The default scheme is:

```text
YYYY/MM/DD
```

This means that a media file dated:

```text
2025-08-27
```

will be placed under:

```text
2025/08/27/
```

The scheme applies identically to both the photo and video libraries.

---

## 10.1 Path Components

The scheme must support date components such as:

- `YYYY` — four-digit year
- `YY` — two-digit year
- `MM` — two-digit month
- `DD` — two-digit day

Literal characters should be preserved.

For example:

```text
YYYY/MM/DD
```

produces:

```text
2025/08/27
```

while:

```text
YYYY-MM-DD
```

produces:

```text
2025-08-27
```

and:

```text
YYYY/MM
```

produces:

```text
2025/08
```

Another valid example is:

```text
YYYY/YYYY-MM-DD
```

which produces:

```text
2025/2025-08-27
```

The exact syntax should be implemented in a way that can be extended with additional date components in the future.

---

## 10.2 Configuration

The path scheme must be persisted in the application configuration.

Default:

```toml
import_path = "YYYY/MM/DD"
```

The TUI must allow the user to view and change this setting.

The configured scheme must be validated before an import begins.

Invalid schemes must produce a clear error and must not result in a partially executed import.

---

# 11. Destination Path Generation

Destination paths are generated only after the media date has been resolved.

For example, given:

```text
Source:
  /import/random/DCIM/IMG_1234.DNG

Resolved date:
  2025-08-27

Path scheme:
  YYYY/MM/DD

Photo library:
  /photos
```

the destination must be:

```text
/photos/2025/08/27/IMG_1234.DNG
```

If the path scheme is:

```text
YYYY/MM
```

the destination becomes:

```text
/photos/2025/08/IMG_1234.DNG
```

The source path has no influence on the destination path.

---

# 12. RAW + JPEG Pairing

Many cameras produce a RAW file and a JPEG with the same filename stem:

```text
IMG_1234.DNG
IMG_1234.JPG
```

When both files exist in the **same source directory**, the RAW file takes precedence.

The importer must:

1. Import the RAW file.
2. Skip the corresponding JPEG.
3. Leave the JPEG untouched in the source directory.

The JPEG must not be deleted, renamed, or moved.

## Example

Source:

```text
IMPORT/
└── camera/
    ├── IMG_1234.DNG
    ├── IMG_1234.JPG
    ├── IMG_1235.JPG
    └── IMG_1236.DNG
```

If all files have the same capture date, the photo library becomes:

```text
PHOTO_LIBRARY/
└── 2025/
    └── 08/
        └── 27/
            ├── IMG_1234.DNG
            ├── IMG_1235.JPG
            └── IMG_1236.DNG
```

`IMG_1234.JPG` remains untouched in the source.

A JPEG must not be skipped merely because a matching RAW exists somewhere else in the source tree.

Pairing is based on:

- Same source directory
- Same filename stem
- One recognized RAW file
- One JPEG file

---

# 13. Source Immutability

The source tree must be treated as read-only by the importer.

The application must never:

- Delete source files
- Move source files
- Rename source files
- Modify source files

The importer is strictly copy-based.

This is particularly important for skipped JPEGs: they remain in the source even when a corresponding RAW file is imported.

---

# 14. Existing Destination Files

The importer must safely handle files that already exist in the destination.

It must never silently overwrite an existing file.

At minimum:

- Destination does not exist → copy file.
- Destination exists and is identical → report as already imported / skip.
- Destination exists but differs → report as a conflict.

The implementation should preferably compare file size and/or content hashes to determine whether two files are identical.

Conflicting files must not be overwritten automatically.

---

# 15. Idempotency

The importer must be safe to run repeatedly against the same source directory.

For example:

```text
First run:
  1,000 files imported

Second run:
  0 files copied
  1,000 files already present
```

Repeated imports must not create duplicates or overwrite existing files.

This allows the source directory to function as a persistent import area.

---

# 16. Import Planning

The application must perform scanning and analysis before starting the actual copy operation.

It should first build an **import plan**.

Each planned item should contain at least:

- Source path
- Media type
- Filename
- Resolved date
- Date source
- Destination path
- Planned action
- Reason for skipping, if applicable

Example:

```text
Source:
  /import/DCIM/random/20250827_105030.mp4

Type:
  Video

Resolved date:
  2025-08-27 10:50:30

Date source:
  Filename

Destination:
  /videos/2025/08/27/20250827_105030.mp4

Action:
  COPY
```

This import plan is then used to generate the preview and perform the actual import.

---

# 17. Import Preview

Before copying anything, the TUI should present a summary of the planned operation.

Example:

```text
Import summary
────────────────────────────────

Source:
  /mnt/import

Photos:
  1,248

Videos:
  87

RAW + JPEG pairs:
  312 JPEGs skipped

Already imported:
  42

Undated:
  3

Conflicts:
  1

Files to import:
  978

Proceed with import? [Y/n]
```

The user must explicitly confirm before files are copied.

The preview should make it possible to identify problematic files before starting the import.

---

# 18. Import Progress

During the import, the TUI should display progress information.

Useful information includes:

- Current file
- Files processed / total
- Current operation
- Destination
- Number successfully copied
- Number skipped
- Number failed

The application should remain responsive when processing large collections.

---

# 19. Error Handling

An error affecting an individual file should not normally abort the entire import.

For example:

```text
ERROR: Unable to read metadata:
  /import/camera/IMG_1234.DNG
```

or:

```text
ERROR: Unable to copy:
  /import/video/MOV_1234.MP4
```

The importer should continue processing other files.

The final report must include:

- Successfully imported files
- Already-existing files
- Skipped RAW/JPEG files
- Undated files
- Conflicts
- Failed files

Fatal errors, such as an inaccessible source directory or unavailable destination library, should abort the import with a clear error.

---

# 20. Undated Files

If a file cannot be assigned a date using the applicable resolution rules, it must not be silently placed into an arbitrary date directory.

It should instead be classified as **undated**.

Undated files should be displayed in the import summary and should not be copied unless a future/manual handling mechanism is explicitly added.

The initial implementation does not need to provide manual date assignment.

---

# 21. Architecture

The application should separate its major responsibilities:

```text
                  ┌─────────────────┐
                  │      TUI        │
                  └────────┬────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │ Recursive Scan  │
                  └────────┬────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │ Media Classifier│
                  └────────┬────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │ Date Resolver   │
                  └────────┬────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │ RAW/JPEG Pairing│
                  └────────┬────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │ Import Planner  │
                  └────────┬────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │ TUI Preview     │
                  └────────┬────────┘
                           │
                     Confirmation
                           │
                           ▼
                  ┌─────────────────┐
                  │   File Copier   │
                  └────────┬────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │ Import Report   │
                  └─────────────────┘
```

The date resolver should be independent of the destination path generator.

The date resolver answers:

> "When was this media captured?"

The path generator answers:

> "Given that date and the configured scheme, where should this file go?"

This separation is important because the destination organization is configurable.

---

# 22. Technology

- **Language:** Python
- **Interface:** Terminal User Interface (TUI)
- **Configuration:** Persistent configuration stored in the user's home directory
- **Metadata:** Appropriate Python metadata libraries and/or external metadata tools
- **Filesystem:** Python filesystem APIs
- **Backend:** None
- **Database:** None required
- **Operating system:** Linux

The application should be designed as a local standalone utility.

---

# 23. Non-Goals

The initial version does not need to:

- Modify media metadata
- Modify filenames
- Modify source files
- Delete imported files
- Move source files
- Re-encode media
- Generate thumbnails
- Upload media
- Synchronize destination changes back to the source
- Infer dates from source directory names
- Use filesystem timestamps for photos when valid EXIF data exists
- Automatically use filesystem modification time as a fallback
- Provide manual date correction

---

# 24. Core Design Principles

The application should follow these principles:

### Safe

The source media is never modified.

### Metadata-driven

Destination dates are determined from the media itself whenever possible.

### Deterministic

Date-resolution rules have a clearly defined priority order.

### Repeatable

Running the importer multiple times is safe and does not create duplicates.

### Previewable

The complete import operation is analyzed before copying begins.

### Configurable

The source, photo destination, video destination, and destination path scheme are persisted and configurable.

### Extensible

The metadata parsers, filename date patterns, media types, and destination date components should be implemented so they can be extended without redesigning the application.

---

# 25. Example End-to-End Operation

Given this source tree:

```text
IMPORT/
├── camera/
│   ├── random/
│   │   ├── IMG_001.DNG
│   │   └── IMG_001.JPG
│   └── videos/
│       └── 20250827_105030.mp4
└── phone/
    └── DCIM/
        └── IMG_002.JPG
```

Suppose:

- `IMG_001.DNG` has EXIF capture date `2025-08-27`
- `IMG_002.JPG` has EXIF capture date `2025-08-28`
- `20250827_105030.mp4` has no usable metadata
- Its filename resolves to `2025-08-27 10:50:30`
- The configured path scheme is `YYYY/MM/DD`

The resulting libraries should be:

```text
PHOTO_LIBRARY/
├── 2025/
│   ├── 08/
│   │   ├── 27/
│   │   │   └── IMG_001.DNG
│   │   └── 28/
│   │       └── IMG_002.JPG
```

and:

```text
VIDEO_LIBRARY/
└── 2025/
    └── 08/
        └── 27/
            └── 20250827_105030.mp4
```

The source remains unchanged, including:

```text
IMG_001.JPG
```

because it was paired with the RAW file.

If the user subsequently changes the path scheme to:

```text
YYYY/YYYY-MM-DD
```

future imports should use:

```text
PHOTO_LIBRARY/
└── 2025/
    └── 2025-08-29/
        └── ...
```

and:

```text
VIDEO_LIBRARY/
└── 2025/
    └── 2025-08-29/
        └── ...
```

without changing how dates are determined.
