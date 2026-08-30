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

Under the default import action, `copy`, the source files are never modified, moved, renamed, or
deleted. The user may instead choose `move`, which deletes each source file once it has been
successfully imported — see section 13.

---

# 2. User Interface

The application must provide an interactive TUI rather than requiring command-line arguments for normal operation.

The main interface should allow the user to:

- Select/configure the source/import directory
- Select/configure the photo library destination
- Select/configure the video library destination
- Configure the destination path scheme
- Configure the import action (copy or move)
- Configure the collision policy
- Start an import
- Exit

The TUI should be designed for normal repeated use rather than requiring the user to specify all
options every time.

## 2.1 Configuration Layout

The current value of a setting and the control that changes it must live **together**, as one row per
setting:

```text
Source directory    /mnt/import                        [Change]
Photo library       /srv/photos                        [Change]
Video library       /srv/videos                        [Change]
Path scheme         YYYY/MM/DD                         [Change]
Import action       copy                               [Change]
On collision        skip                               [Change]
```

Any warning about incomplete or dangerous configuration — unset directories, or `move` being
selected — belongs in this same block, directly beneath the settings it refers to. A displayed value,
the control that edits it, and the warning about it must not be scattered into three separate places
on the screen.

The whole configuration block, including the primary action, must fit an ordinary 80x24 terminal
without scrolling.

## 2.2 Mouse

Every control must be operable by mouse as well as by keyboard. Settings are changed by clicking
their row's button, and the import is confirmed by clicking. Nothing may be reachable by keyboard
only.

## 2.3 Primary Action

The button that begins an import is labelled:

```text
Start import process
```

Primary actions must remain reachable regardless of how much content is on screen — a long list of
files must never push the confirm or cancel button out of view.

---

# 3. Persistent Configuration

Application settings must be persisted in the user's XDG configuration directory:

```text
~/.config/media-importer/
└── config.toml
```

The configuration must contain:

```toml
source_path      = "/path/to/import"
photo_library    = "/path/to/photos"
video_library    = "/path/to/videos"
import_path      = "YYYY/MM/DD"
import_action    = "copy"        # copy | move
on_collision     = "skip"        # skip | clobber | rename
clobber_prefers  = "newest"      # newest | oldest  (only used when on_collision = "clobber")
```

`import_action` is described in section 13, `on_collision` and `clobber_prefers` in section 14.2.

On first run, when no configuration file exists yet, `source_path` defaults to the working directory
the application was launched from. That default is written to the configuration file rather than
being recomputed each time, so it is visible and editable like any other setting instead of being an
invisible piece of behaviour.

Previously configured values must automatically be loaded when the application starts.

The default destination path scheme must be:

```text
YYYY/MM/DD
```

---

## 3.1 Path Validation

Before any scan begins, the three configured paths must be validated together.

Each path is first fully resolved to an absolute real path, with all symlinks resolved, so that
indirection cannot be used to defeat the check.

None of the three paths may be nested inside another:

- `photo_library` must not lie inside `source_path`, and `source_path` must not lie inside `photo_library`.
- The same applies to `video_library`.
- A path must not equal another, except that `photo_library` and `video_library` may be identical
  if the user deliberately wants a single combined library.

A nested configuration would cause the scanner to rediscover files it has just written, so it must
be treated as a **fatal error**: the application must report which two paths conflict and must not
begin the import.

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

## 4.1 Symlinks

Symbolic links are ignored entirely.

- The scanner must not follow symlinked directories. This also prevents symlink loops from hanging
  a recursive scan.
- A symlink to a media file must not be imported, even when its target is a supported media file.

Ignored symlinks should be counted and reported so the user can tell the difference between
"not found" and "deliberately skipped".

In the destination libraries, an existing entry that is a symlink must never be overwritten,
clobbered, or renamed. Such a file is reported as an error for that item and the import continues.

---

# 5. Media Classification

The importer must classify discovered files into:

- Photos
- Videos
- Unsupported/unknown files

Supported extensions should be explicitly defined by the application and ideally be configurable.

At minimum, the application should recognize common formats.

### Photos

- JPG / JPEG
- PNG
- TIFF / TIF
- HEIC / HEIF
- WEBP
- Camera RAW formats (see 5.1)

### Videos

- MP4
- MOV
- M4V
- AVI
- MPG / MPEG
- MTS
- 3GP
- MKV
- WEBM
- INSV

Unsupported files must be ignored and must not be copied.

---

## 5.1 RAW Formats

A distinct subset of the photo extensions is recognized as **camera RAW**. This subset exists only
to drive RAW/JPEG pairing (section 12) and has no other effect.

RAW means a camera manufacturer's raw capture format:

```text
DNG  CR2  CR3  NEF  NRW  ARW  ORF  RW2  RAF
PEF  SRW  RWL  ERF  3FR  IIQ  X3F  MEF  MOS  KDC  DCR
```

**TIFF is not RAW.** Neither is PNG, HEIC, WEBP, or JPEG. A TIFF sitting next to a JPEG of the same
name is not a pair and both files are imported normally.

---

## 5.2 Live Photos

Apple Live Photos appear as two files sharing a stem, for example:

```text
IMG_1234.HEIC
IMG_1234.MOV
```

These are **not** treated as a pair. HEIC is not a RAW format, so pairing does not apply. The still
is imported into the photo library and the movie into the video library, each dated independently.

This is intentional and must be documented so that the split is not mistaken for a bug. Suppressing
Live Photo movie sidecars may be added later as an explicit configuration option.

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

## 6.1 Metadata Date Sanity Check

Embedded metadata routinely contains junk dates. The QuickTime epoch `1904-01-01`, the Unix epoch
`1970-01-01`, and the all-zero EXIF value `0000:00:00 00:00:00` are all common in real files, and a
naive reader will happily file media under the year 1904.

Every candidate date obtained from metadata must therefore pass a plausibility check before it is
accepted. A candidate is **garbage** if any of the following hold:

1. It cannot be parsed as a real calendar date and time.
2. It falls before the floor `1990-01-01`.
3. It falls more than **2 years after the file's filesystem modification time (mtime)**.

Rule 3 is deliberately asymmetric. A capture date *older* than mtime is completely normal — the file
has been copied between disks, and copying updates mtime while the capture date stays put. A capture
date meaningfully *newer* than mtime is impossible, because a file cannot have been recorded after
it was last written.

```text
floor   = 1990-01-01
ceiling = mtime + 2 years

EXIF 1904-01-01                     -> garbage (below floor)
EXIF 0000:00:00 00:00:00            -> garbage (unparseable)
EXIF 2015-06-02, mtime 2024-01-10   -> accepted (old file, recently copied)
EXIF 2031-01-01, mtime 2025-08-29   -> garbage (captured in the future)
```

A garbage metadata date must be discarded and resolution must continue to the next tier, exactly as
though the metadata field had been absent. It must never be used, and it must never cause the file
to be skipped outright.

The check applies to metadata dates for both photos and videos. It does not apply to dates derived
from the filename or from the filesystem, which are already bounded by construction.

---

# 7. Photo Date Resolution

For photos, the application should primarily use EXIF metadata to determine the original capture date.

The preferred field is:

```text
DateTimeOriginal
```

When `DateTimeOriginal` is unavailable, the following fields are consulted in this exact order:

```text
1. DateTimeOriginal      (EXIF 0x9003)
2. CreateDate            (EXIF DateTimeDigitized, 0x9004)
3. DateTime              (EXIF ModifyDate, 0x0132)
```

The list is ordered and closed: the first field yielding a date that passes the sanity check in
section 6.1 wins, and no other field is consulted. Leaving the fallback set open-ended would make
photo dating non-deterministic, which section 24 forbids.

A valid camera capture date from EXIF must take precedence over filesystem timestamps.

The source directory structure must never be used to determine the date.

Photos do **not** fall back to the filename or to filesystem timestamps. Unlike video metadata, EXIF
is consistent enough to rely on, and a photo whose EXIF is absent or garbage is reported as undated.

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
3. Filesystem time

The first date that is found *and* passes the sanity check in section 6.1 must be used.

The bulk of the implementation effort belongs in tiers 1 and 2. The filesystem is the last resort
and the least trustworthy source, because it describes the file rather than the recording. Tier 3
exists so that a video is not lost, not because it is expected to be correct.

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

## 8.3 Filesystem Time

If neither metadata nor the filename provides a usable date, use a filesystem timestamp.

This is specifically the final fallback for videos, and it applies to videos only.

Birth time is preferred where it is genuinely available, with modification time as the fallback:

```text
1. birth/creation time  -> date_source = "filesystem birth time"
2. modification time    -> date_source = "filesystem mtime"
```

Birth time is frequently unavailable on the target platform, and the implementation must treat that
as the normal case rather than an error. Linux does not expose birth time through the Python standard
library, and the underlying value does not exist at all on FAT32/exFAT — the format of most camera SD
cards — nor on many WSL drive mounts, on NFS, or on older ext4 inodes. A design that required birth
time would leave a large share of real-world videos undated and therefore never imported.

Because the two are not equally trustworthy, the resolved date source must record **which** timestamp
was used, so that `filesystem mtime` is visible to the user in the preview and in the final report
rather than being silently presented as a capture date.

If no filesystem timestamp can be read at all, the video is reported as undated.

---

# 9. Date Resolution Summary

The rules can be summarized as follows.

### Photos

```text
EXIF DateTimeOriginal / CreateDate / DateTime
       │
       ├── found and plausible → use it
       │
       └── not found → undated
```

### Videos

```text
Video metadata
       │
       ├── found and plausible → use it
       │
       ▼
Filename date/time
       │
       ├── found → use it
       │
       ▼
Filesystem birth time
       │
       ├── available → use it
       │
       ▼
Filesystem mtime
       │
       ├── available → use it
       │
       └── not available → undated
```

At every metadata tier, "found" means found *and* passing the sanity check in section 6.1. A
metadata date rejected as garbage falls through to the next tier.

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
- Same filename stem, compared **case-insensitively** (`IMG_1234.DNG` pairs with `img_1234.jpg`)
- Exactly one recognized camera RAW file (see 5.1)
- Exactly one JPEG file (`.jpg` or `.jpeg`)

---

## 12.1 Ambiguous Groups

Pairing applies only to the clean two-file case. Whenever a stem group in a directory is ambiguous,
**no pairing occurs and every file in the group is imported normally**:

- Two or more RAW files sharing a stem (`IMG_1234.DNG` + `IMG_1234.CR2`) — no way to choose a winner.
- Both `IMG_1234.JPG` and `IMG_1234.JPEG` present alongside a RAW — two JPEG candidates.
- A stem group containing three or more files.
- Any group with no RAW file, or no JPEG file.

Importing both files is the safe failure mode: it wastes disk space, whereas guessing wrong loses a
photo.

---

## 12.2 The RAW Must Be Importable

A JPEG is suppressed **only when its paired RAW is actually going to be imported**.

If the RAW cannot be dated — its EXIF is missing, or every candidate date is rejected as garbage by
the sanity check in section 6.1 — then the RAW is undated and, under section 20, will not be copied.
Suppressing the JPEG in that situation would discard both files and import nothing, even though the
JPEG may carry perfectly good EXIF of its own.

Therefore:

```text
RAW resolves to a usable date
       │
       ├── yes → import RAW, skip JPEG  (reason: "JPEG paired with RAW")
       │
       └── no  → RAW is reported as undated,
                 pairing is abandoned,
                 JPEG is dated and imported on its own merits
```

Both files remain untouched in the source either way.

---

# 13. Source Handling

What happens to a source file is governed by `import_action`.

```toml
import_action = "copy"   # default
import_action = "move"
```

## 13.1 Copy (default)

The source tree is treated as strictly read-only. The application must never:

- Delete source files
- Move source files
- Rename source files
- Modify source files

This is the default, and it is what makes the source directory usable as a persistent import area.

## 13.2 Move

The user may choose `move`, in which case a source file is **deleted after it has been successfully
imported**.

This is the one place where the application removes user data, so the rule is deliberately narrow:

> A source file may be deleted **only** when that same file was just imported, and **only** after its
> destination copy is verifiably complete and in place.

Everything else keeps its source file. Specifically, a source file must be left untouched when it is:

- Skipped as a JPEG paired with a RAW (section 12)
- Undated (section 20)
- Blocked by a collision (section 14.2)
- Already present in the library (section 14.1)
- Ignored as unsupported or as a symlink (sections 4.1, 5)
- Failed for any reason during the copy

The last case matters most: if the destination never landed, the original must survive. Deletion
must therefore never be attempted until the destination file is complete.

Recognizing an already-imported file is explicitly **not** grounds for deletion. An identical copy
existing in the library is not the same thing as this run having imported it, and deleting on that
basis would turn a re-scan into silent data removal.

If the destination is on the same filesystem, the move should avoid rewriting the file's bytes —
moving a multi-gigabyte video must not require copying it first. The technique used must preserve
the same guarantee as a copy: it must fail rather than overwrite if the destination has appeared
since planning.

The user must be told clearly, before confirming an import, that source files will be deleted.

Failure to delete a source file after a successful import is a warning, not a failed import: the
file did reach the library, and reporting it as a failure would be wrong.

---

# 14. Existing Destination Files

The importer must safely handle files that already exist in the destination.

It must never silently overwrite an existing file.

The destination is inspected **only when the computed destination path already exists**. In the
common case — a path that is free — the file is simply copied. There is no index, no database, and
no hashing of the library. This keeps a repeat import over a large library cheap, since the vast
majority of items resolve on a single `stat` of the destination path.

```text
Destination path does not exist
       │
       └── → COPY

Destination path exists
       │
       ├── same file (see 14.1) → SKIP, report as already imported
       │
       └── otherwise            → collision, resolved by policy (see 14.2)
```

---

## 14.1 Already-Imported Detection

An existing destination file is considered **the same file** when all three of the following match:

```text
filename                 (identical by construction, since it is the same destination path)
file size in bytes
resolved capture datetime
```

When all three agree, the item is reported as already imported and nothing is copied. The source
file is left in the import folder untouched, and the user is informed that it was recognized rather
than silently ignored.

Content hashing is deliberately not used. Size plus resolved capture datetime is sufficient to
recognize a file the importer itself wrote on a previous run, which is the case this check exists to
serve.

---

## 14.2 Collisions

A **collision** is any case where a destination path is already occupied by a file that is not the
same file under 14.1.

Collisions arise in two ways, and both are resolved by the same policy:

1. **Against the library.** The destination path is occupied by a file from an earlier import.
2. **Within a single import.** Two different source files resolve to the same destination path — for
   example `/import/cardA/IMG_1234.JPG` and `/import/cardB/IMG_1234.JPG` sharing a capture date.
   This must be detected at planning time, because the second file would otherwise overwrite the
   first while both were planned as an unremarkable `COPY`. The planner must therefore track the
   destination paths it has already assigned within the current plan, not just the paths present on
   disk when the scan began.

The resolution is chosen by the user through `on_collision`:

### `skip` (default)

Do not import the colliding file. The existing destination file is left exactly as it is, the source
file is left in the import folder, and the collision is reported. Nothing is ever destroyed.

### `clobber`

One file wins and replaces the other. The winner is chosen by `clobber_prefers`:

```text
clobber_prefers = "newest"   the later resolved capture datetime wins
clobber_prefers = "oldest"   the earlier resolved capture datetime wins
```

Ties are broken by filesystem mtime. If both are still equal, the file already in the library wins
and the incoming file is skipped, so that a repeated run cannot churn.

When the incoming file wins, it is written atomically — copied to a temporary file in the destination
directory and then renamed over the target — so the destination is never left in a partially written
state, and an interrupted clobber cannot destroy the existing file.

### `rename`

Both files are kept. The incoming file receives a numeric suffix on its stem, choosing the lowest
free index:

```text
IMG_1234.DNG        already present
IMG_1234-1.DNG      first colliding import
IMG_1234-2.DNG      second colliding import
```

The suffix is applied to the stem, never to the extension, so the file type is preserved.

The chosen policy applies uniformly to both kinds of collision. The default is `skip` because it is
the only policy that neither destroys existing data nor silently multiplies files.

Whichever policy applies, the source file is never modified, moved, renamed, or deleted, and every
collision is recorded in the final report.

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

With `import_action = "copy"` this allows the source directory to function as a persistent import
area. With `move`, a second run simply finds less to do, because the imported files are gone —
which is the intended effect rather than a violation of idempotency.

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

Discovered media:
  1,335

  Photos:                    1,248
  Videos:                       87

Not importing:
  RAW + JPEG pairs:            312   (JPEGs skipped)
  Already imported:             42
  Undated:                       3
  Collisions:                    1

Files to import:
  977

Proceed with import? [Y/n]
```

The categories must **partition** the set of discovered media: every discovered file falls into
exactly one of them, and the counts must reconcile exactly.

```text
1,248 + 87 = 1,335 discovered
1,335 − 312 − 42 − 3 − 1 = 977 to import
```

The user must explicitly confirm before files are copied.

The preview should make it possible to identify problematic files before starting the import. Counts
alone are not enough for the exception categories: the user must be able to see the **paths** of the
undated files and the collisions, since those are the items that need action.

---

# 18. Import Progress

The import runs as a sequence of named phases, and the interface must present them as a **log of
steps, each with its own progress bar**:

```text
✔ Scanning source directory      1,335 media files, 12 ignored
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✔ Reading photo metadata         1,248 photos read
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100%

✔ Resolving capture dates        1,332 dated, 3 undated
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100%

✔ Detecting RAW/JPEG pairs       312 JPEGs paired with a RAW
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✔ Checking destinations          977 to import
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100%

▶ Copying files                  IMG_2841.DNG
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━  64%
```

Requirements:

- **Each step has its own progress bar.** A step whose size is not yet known shows an indeterminate
  bar rather than a misleading 0%.
- **Completed steps remain on screen.** A finished step is never replaced or cleared; it stays,
  marked complete, with a short summary of what it did. The screen reads as a log of the whole run.
- **Planning and copying share one log.** The steps that produced the plan must still be visible
  while the copy runs, so confirming the import does not discard the history of how the plan was
  built.
- The view should follow the active step, and should reveal the summary once there is something to
  read or act on.
- The current file, running totals, and failures must be visible.

The application should remain responsive when processing large collections. Scanning, metadata
extraction and copying must therefore run off the interface's event loop.

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
- Already-imported files
- Skipped RAW/JPEG files
- Undated files
- Collisions, with the policy that was applied to each
- Ignored symlinks
- Failed files

For every category other than successful imports, the report must list the **paths** involved, not
just a count. A bare count tells the user that something needs attention without telling them what.

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
- **Configuration:** Persistent TOML configuration under `~/.config/`
- **Metadata:** `exiftool` and `ffprobe`, invoked as external tools
- **Filesystem:** Python filesystem APIs
- **Backend:** None
- **Database:** None
- **Operating system:** Linux and WSL

The application should be designed as a local standalone utility.

---

## 22.1 External Tool Dependencies

Metadata extraction relies on two external programs rather than on pure-Python parsers, because
neither EXIF across every RAW variant nor container metadata across every video format is handled
adequately by any pip-installable library.

```text
exiftool   photo and RAW metadata
ffprobe    video container metadata (shipped with ffmpeg)
```

These are **not** Python packages and cannot be installed by `pip`. The application must therefore:

- Detect at startup whether each tool is present on `PATH`.
- Report a clear, actionable error naming the missing tool and the install command for the user's
  distribution, rather than failing obscurely when the first file is read.
- Treat a missing tool as a fatal error, since date resolution is the core of the application.

Installation must be documented for the major distributions:

```bash
# Debian / Ubuntu / WSL
sudo apt install libimage-exiftool-perl ffmpeg

# Fedora
sudo dnf install perl-Image-ExifTool ffmpeg-free

# Arch
sudo pacman -S perl-image-exiftool ffmpeg
```

On Fedora, `ffmpeg-free` from the main repositories provides `ffprobe`; the RPM Fusion `ffmpeg`
package also works and supports more codecs.

Because this dependency cannot be expressed in a PyPI wheel, the README must state the requirement
prominently in its installation section.

---

# 23. Non-Goals

The initial version does not need to:

- Modify media metadata
- Modify filenames
- Modify the contents of source files
- Re-encode media
- Generate thumbnails
- Upload media
- Synchronize destination changes back to the source
- Infer dates from source directory names
- Use filesystem timestamps for photos at all, in any circumstance
- Use the filename to date a photo
- Follow symlinks
- Hash or index the destination libraries
- Provide manual date correction

Note two deliberate exceptions to the list above:

- Filesystem modification time **is** a sanctioned last-resort fallback for videos (see 8.3). It is
  never used for photos.
- Deleting and moving source files **is** supported, but only under `import_action = "move"` and only
  within the narrow rule in section 13.2. It is never the default.

---

# 24. Core Design Principles

The application should follow these principles:

### Safe

Source media is never modified in place, and under the default `copy` action it is never removed at
all. The `move` action is opt-in, is announced before the user confirms, and removes a source file
only after that file has been successfully imported.

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
