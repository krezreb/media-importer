# Photo & Video Import CLI — Technical Specification

## 1. Project Goals

Implement the Photo & Video Import CLI as a standalone Python application.

The application must:

- Run on Linux and WSL.
- Be launched from a Bash-compatible shell.
- Provide an interactive terminal user interface (TUI).
- Recursively scan arbitrary source directories.
- Extract media capture dates from metadata and defined fallbacks.
- Build an import plan before copying files.
- Copy photos and videos into separate libraries.
- Organize destination files using a configurable date path scheme.
- Never modify the source media.
- Be safe to run repeatedly.
- Be distributable through PyPI.

---

# 2. Python Version

Target a currently supported Python 3 version.

The supported minimum Python version must be declared explicitly in `pyproject.toml`.

All application code must be compatible with that version.

Python version compatibility should be tested in CI where practical.

---

# 3. Project Layout

Use a modern `src/` package layout.

Recommended structure:

```text
media-importer/
├── pyproject.toml
├── README.md
├── LICENSE          (MIT)
├── Makefile
├── .gitignore
├── src/
│   └── media_importer/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── config.py
│       ├── models.py
│       ├── scanner.py
│       ├── classifier.py
│       ├── metadata.py
│       ├── date_resolver.py
│       ├── filename_dates.py
│       ├── pairing.py
│       ├── path_scheme.py
│       ├── planner.py
│       ├── importer.py
│       └── tui/
│           ├── __init__.py
│           └── app.py
├── tests/
│   ├── test_classifier.py
│   ├── test_date_resolver.py
│   ├── test_filename_dates.py
│   ├── test_pairing.py
│   ├── test_path_scheme.py
│   ├── test_planner.py
│   ├── test_importer.py
│   └── fixtures/
└── .github/
    └── workflows/
```

The exact module names may differ, but the separation of responsibilities should be maintained.

## 3.1 Naming

These names are authoritative and must be used consistently:

```text
distribution / PyPI name   media-importer
import package             media_importer
console script             media-importer
config directory           ~/.config/media-importer/
```

## 3.2 License

The project is licensed **MIT**.

A `LICENSE` file containing the MIT text must be present at the repository root, and the same license
must be declared in `pyproject.toml` so it reaches the built package metadata. These are the only two
places the license is recorded — do not restate it elsewhere.

---

# 4. CLI Entry Point

The package must expose a console script through `pyproject.toml`.

For example:

```toml
[project.scripts]
media-importer = "media_importer.cli:main"
```

The application must therefore be runnable as:

```bash
media-importer
```

It must also support:

```bash
python -m media_importer
```

Both entry points must launch the same application.

## 4.1 No Command-Line Flags in v1

v1 accepts **no command-line arguments at all**. Both entry points launch straight into the TUI.

There is no `--version`, no `--dry-run`, no `--config`, and no way to override configured paths from
the shell. Every setting is viewed and changed inside the TUI and persisted to the configuration
file (section 6). `--dry-run` in particular is unnecessary: the import preview (SPEC section 17) is
already a mandatory dry run that the user must confirm before anything is copied.

The entry point must therefore not build an argument parser. Any unexpected argument is ignored
rather than triggering a usage error, so that the application never fails to start over argv.

---

# 5. TUI Framework

Use an established Python terminal UI framework.

**Textual** is the preferred choice.

The TUI must not contain core media-processing logic.

Instead, it should invoke application services responsible for:

- Scanning
- Metadata extraction
- Date resolution
- Planning
- Import execution

This ensures that the core functionality can be tested without running the TUI.

---

# 6. Configuration

Use a human-readable configuration file stored in the user's XDG configuration directory:

```text
~/.config/media-importer/config.toml
```

Honour `$XDG_CONFIG_HOME` when it is set, falling back to `~/.config` otherwise.

Read TOML with the standard library `tomllib` (Python 3.11+). Writing requires a third-party
library such as `tomli-w`, since `tomllib` is read-only.

Configuration must contain:

```toml
source_path      = "/path/to/import"
photo_library    = "/path/to/photos"
video_library    = "/path/to/videos"
import_path      = "YYYY/MM/DD"
import_action    = "copy"
on_collision     = "skip"
clobber_prefers  = "newest"
```

When no configuration file exists, `source_path` is initialised to `Path.cwd()` and written to the
new file. Persisting it keeps the default visible and editable rather than making it an invisible
behaviour that changes with the working directory.

The application must create the configuration directory and default configuration when required.

Unknown keys should be preserved on rewrite rather than silently dropped, so that a config written
by a newer version is not destroyed by an older one.

---

# 7. Configuration Model

Represent configuration using a typed Python model/dataclass:

```text
source_path      Path
photo_library    Path
video_library    Path
import_path      str
import_action    ImportAction      enum: COPY | MOVE
on_collision     CollisionPolicy   enum: SKIP | CLOBBER | RENAME
clobber_prefers  ClobberPreference enum: NEWEST | OLDEST
```

`import_action`, `on_collision` and `clobber_prefers` must be parsed into enums at load time, not
carried as raw strings. An unrecognized value is a `ConfigurationError`, not a silent fallback to the
default — silently treating a typo'd `import_action` as `copy` would be merely wrong, whereas
silently treating it as `move` would delete data.

This is the complete v1 schema. Supported media extensions are **not** configurable in v1; they are
defined in code (section 10). If that changes later, the extension sets move here rather than being
read ad hoc from elsewhere.

Configuration loading and validation must be centralized in the configuration module.

The rest of the application should consume a validated configuration object rather than parsing TOML directly.

---

## 7.1 Path Nesting Validation

Configuration validation must reject a nesting relationship between the three configured paths.

Resolve each path with `Path.resolve()` first, so that symlinked indirection cannot defeat the check,
then compare using `Path.is_relative_to()` in both directions:

```python
def _assert_not_nested(a: Path, b: Path) -> None:
    if a.is_relative_to(b) or b.is_relative_to(a):
        raise ConfigurationError(...)
```

Check `source_path` against `photo_library`, and `source_path` against `video_library`.
`photo_library` and `video_library` may be equal to one another, but neither may contain the other
unless they are equal.

A nested configuration makes the scanner rediscover files the importer just wrote. Raise
`ConfigurationError` before scanning begins, naming both offending paths.

---

# 8. Media Model

Define typed internal models for discovered media.

A media item should contain at least:

```text
source_path
filename
media_type
extension
```

After date resolution:

```text
resolved_datetime
date_source
```

After planning:

```text
destination_path
action
reason
```

Use enums for values such as:

```text
Photo
Video
Unknown
```

and:

```text
COPY
SKIP              already imported, or JPEG paired with RAW
COLLISION         destination occupied by a different file
UNDATED           no usable date, not importable
ERROR
```

`reason` must distinguish the several causes that share the `SKIP` action, so the report can break
them out separately:

```text
ALREADY_IMPORTED
JPEG_PAIRED_WITH_RAW
COLLISION_SKIPPED
SYMLINK
UNSUPPORTED_EXTENSION
```

This avoids passing loosely structured strings throughout the application.

---

# 9. Recursive Scanner

Implement a dedicated scanner responsible only for discovering files.

Input:

```text
source_path
```

Output:

```text
iterable/list of filesystem paths
```

The scanner must recursively traverse the source directory.

It must not:

- Determine dates
- Copy files
- Modify files
- Make import decisions
- Follow symlinks

Use Python's `pathlib` APIs.

The scanner should handle large directory trees without unnecessarily loading file contents into memory.
Prefer `os.scandir` semantics (which `Path.iterdir` uses) and yield results lazily rather than
materializing the whole tree.

## 9.1 Symlink Handling

Symlinks are skipped, both directories and files.

Use `Path.is_symlink()` — note that `Path.is_dir()` and `Path.is_file()` follow links and will
therefore not identify one. Check `is_symlink()` **first**:

```python
if entry.is_symlink():
    yield Ignored(entry, reason=IgnoreReason.SYMLINK)
    continue
```

Not descending into symlinked directories also removes any possibility of an infinite scan through a
symlink loop, so no separate cycle detection or visited-inode set is required.

Ignored symlinks must be reported as their own category, distinct from unsupported extensions.

---

# 10. Media Classifier

Implement a dedicated media classifier.

Classification should primarily be based on the file extension.

Extension matching must be case-insensitive.

Maintain centralized sets/maps of supported extensions.

Example:

```python
# Camera manufacturer raw formats. This set exists only to drive
# RAW/JPEG pairing (section 17). TIFF is deliberately NOT here.
RAW_EXTENSIONS = {
    ".dng", ".cr2", ".cr3", ".nef", ".nrw", ".arw",
    ".orf", ".rw2", ".raf", ".pef", ".srw", ".rwl",
    ".erf", ".3fr", ".iiq", ".x3f", ".mef", ".mos",
    ".kdc", ".dcr",
}

JPEG_EXTENSIONS = {".jpg", ".jpeg"}

PHOTO_EXTENSIONS = {
    ".png",
    ".tif", ".tiff",
    ".heic", ".heif",
    ".webp",
} | JPEG_EXTENSIONS | RAW_EXTENSIONS
```

and:

```python
VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".m4v", ".avi",
    ".mpg", ".mpeg", ".mts", ".3gp",
    ".mkv", ".webm", ".insv",
}
```

`RAW_EXTENSIONS` and `JPEG_EXTENSIONS` are subsets of `PHOTO_EXTENSIONS`, never separate
classification categories: a RAW file classifies as `Photo`, and the RAW subset is consulted only by
the pairing stage.

HEIC/HEIF must be present — it has been the iPhone default since 2017 and is the single most likely
extension to be encountered when importing from a phone.

Match on `path.suffix.lower()`. The exact lists should be easy to extend.

---

# 11. Metadata Extraction

Metadata extraction must be isolated behind an abstraction.

The application shells out to two established external tools rather than parsing media metadata
itself:

```text
exiftool   photos and RAW    exiftool -json -DateTimeOriginal -CreateDate -DateTime <file>
ffprobe    videos            ffprobe -v quiet -print_format json -show_format -show_streams <file>
```

Both emit JSON, so neither needs output scraping. Invoke them with `subprocess.run` using an argument
list — never `shell=True`, since filenames are untrusted input — and always apply a timeout so a
malformed file cannot hang the import.

## 11.1 Tool Availability

Both tools must be probed once at startup via `shutil.which`. A missing tool is a fatal
`ConfigurationError` naming the tool and the install command for the user's distribution, raised
before scanning rather than on the first file read.

Because these are not Python packages, `pip install` cannot supply them. See section 41 for the
per-distribution install instructions that the README must carry.

## 11.2 Batching

`exiftool` startup cost dominates per-file runtime, so invoking it once per file makes a large import
needlessly slow. Prefer passing many files to a single invocation, or use its `-stay_open` mode, and
correlate results by the `SourceFile` field in the JSON output.

## 11.3 Normalized Result

The abstraction exposes normalized values, never tool-specific structures:

```python
Metadata(
    capture_datetime=...,   # naive or aware datetime, or None
    source="exif:DateTimeOriginal",
)
```

The date resolver must not depend on the implementation details of either tool, so that a future
switch to a pure-Python backend touches only this module.

---

# 12. Photo Date Resolver

Implement a dedicated photo date resolver.

Resolution priority — an ordered, closed list:

```text
1. EXIF DateTimeOriginal   (0x9003)
2. EXIF CreateDate         (DateTimeDigitized, 0x9004)
3. EXIF DateTime           (ModifyDate, 0x0132)
        ↓
undated
```

The first field yielding a value that passes the sanity check in section 13.1 wins. The list is
closed rather than open-ended so that photo dating is deterministic and testable.

Do not use:

- Filename
- Filesystem modification time
- Filesystem creation time

as photo date fallbacks. Unlike video containers, EXIF is consistent enough to rely on, and this
restriction is a deliberate product decision rather than a temporary limitation.

The resolver must return:

```text
datetime
+
date source
```

or an explicit "undated" result.

---

# 13. Video Date Resolver

Implement a separate video date resolver.

Resolution priority:

```text
1. Embedded metadata      (ffprobe, sanity-checked)
2. Filename date/time
3. Filesystem birth time  (where genuinely available)
4. Filesystem mtime
5. Undated
```

The resolver must stop at the first reliable date, where "reliable" for tier 1 means the value also
passes the sanity check below. A rejected metadata date falls through to tier 2 exactly as if the
field had been absent.

Implementation effort belongs in tiers 1 and 2. Tiers 3 and 4 describe the file, not the recording,
and exist only so a video is not lost.

It must return both:

```text
resolved datetime
date source
```

`date_source` must distinguish `filesystem birth time` from `filesystem mtime`, since the two carry
very different confidence and the user needs to see which was used.

---

## 13.1 Metadata Date Sanity Check

Implement the plausibility check as a standalone, independently testable function shared by both
resolvers. Real files routinely carry `1904-01-01` (the QuickTime epoch), `1970-01-01`, and the
all-zero EXIF value `0000:00:00 00:00:00`.

```python
FLOOR = datetime(1990, 1, 1)
CEILING_SLACK = timedelta(days=730)  # 2 years

def is_plausible(candidate: datetime, mtime: datetime) -> bool:
    return FLOOR <= candidate <= mtime + CEILING_SLACK
```

A candidate is garbage when it is unparseable, falls below `FLOOR`, or falls more than two years
after the file's mtime.

The ceiling is deliberately asymmetric. A capture date *older* than mtime is normal, because copying
a file updates mtime while the capture date stays put — so an archival import of genuinely old media
keeps its correct dates. A capture date meaningfully *newer* than mtime is physically impossible.

```text
floor   = 1990-01-01
ceiling = mtime + 2 years

EXIF 1904-01-01                    -> garbage (below floor)
EXIF 0000:00:00 00:00:00           -> garbage (unparseable)
EXIF 2015-06-02, mtime 2024-01-10  -> accepted
EXIF 2031-01-01, mtime 2025-08-29  -> garbage (future)
```

Applies to metadata dates only. Filename and filesystem dates are bounded by construction.

Compare naive to naive: if a metadata value carries a timezone, normalize it before comparing
against mtime, which is naive local.

---

# 14. Filename Date Parser

Filename date parsing must be implemented as an independent component.

At minimum recognize:

```text
YYYYMMDD_HHMMSS
```

Example:

```text
20250827_105030.mp4
```

→

```text
2025-08-27 10:50:30
```

The parser should use a collection of patterns rather than hard-coding one expression into the video resolver.

This allows additional patterns to be added later.

Filename matching should avoid interpreting arbitrary numeric sequences as dates unless they match a recognized pattern.

---

# 15. Filesystem Birth Time

For video fallback handling, implement a filesystem timestamp abstraction that prefers birth time and
falls back to mtime.

**Birth time is not reachable from the Python standard library on Linux.** `os.stat()` exposes no
`st_birthtime` there — that attribute exists only on macOS/BSD and, since 3.12, Windows — and there
is no `os.statx` binding. Obtaining it requires a `ctypes` `statx(2)` call requesting `STATX_BTIME`,
and then checking the returned mask to see whether the kernel actually supplied it.

Even with that call, the value is frequently absent:

```text
FAT32 / exFAT     no btime          <- the format of most camera SD cards
WSL DrvFs / 9p    usually no btime
NFS               generally no btime
ext4              absent on inodes created before ~2011
```

The abstraction must therefore return an explicit three-state result rather than a bare datetime:

```python
BirthTime(value=..., available=True)
BirthTime(value=None, available=False)
```

The resolver then falls back to mtime and records `date_source = "filesystem mtime"`. This is a
sanctioned fallback, not a silent substitution: the distinction is preserved all the way through to
the preview and the final report, so the user can always tell which timestamp dated a file.

A design that required true birth time would leave most camera-card video undated and therefore never
imported, which is why mtime is accepted here.

The README must document this behaviour and note that on most Linux filesystems video dating will
fall through to mtime whenever metadata and filename both fail.

---

# 16. Date Handling and Timezones

Internally, media capture dates should use Python `datetime` objects.

If metadata contains timezone information, preserve it where practical.

If the metadata provides a naive local date/time, do not invent a timezone.

Destination directory generation only requires the calendar date:

```text
year
month
day
```

Timezone conversion should therefore not be performed unless required by the metadata source.

---

# 17. RAW/JPEG Pair Detection

Implement RAW/JPEG pairing as a separate processing stage.

A pair exists when all of the following hold:

```text
same parent directory
same filename stem, compared case-insensitively
exactly one file whose extension is in RAW_EXTENSIONS
exactly one file whose extension is in JPEG_EXTENSIONS
```

Group by `(parent, stem.lower())`. Case-insensitive stem matching means `IMG_1234.DNG` pairs with
`img_1234.jpg`.

TIFF is not RAW, so a `.tif` beside a `.jpg` is not a pair and both are imported.

## 17.1 Ambiguous Groups

Pairing applies only to the clean two-file case. If a group is ambiguous, **no pairing occurs and
every member is imported normally**:

- Two or more RAW files sharing a stem (`IMG_1234.DNG` + `IMG_1234.CR2`)
- Both `.jpg` and `.jpeg` present alongside a RAW
- Three or more files in the group
- No RAW, or no JPEG

Importing both is the safe failure mode: it costs disk space, whereas guessing wrong loses a photo.

## 17.2 Pairing Requires an Importable RAW

The JPEG is suppressed **only when the RAW will actually be imported**.

Pairing must therefore run *after* date resolution, not before it. If the RAW resolves to undated —
no EXIF, or every candidate rejected by the sanity check — then suppressing the JPEG would discard
both files and import nothing, even though the JPEG may carry good EXIF of its own.

```text
RAW resolved date is usable
       │
       ├── yes → RAW: COPY
       │         JPEG: SKIP, reason JPEG_PAIRED_WITH_RAW
       │
       └── no  → RAW: UNDATED (reported)
                 JPEG: dated and imported on its own merits
```

This ordering constraint is the reason the planner sequence in section 21 resolves dates before
detecting pairs.

The JPEG must remain untouched in the source in every case.

Pair detection must occur before import execution.

---

# 18. Destination Path Scheme

Implement destination path formatting as an independent component.

Configuration:

```toml
import_path = "YYYY/MM/DD"
```

Supported tokens initially:

```text
YYYY
YY
MM
DD
```

The formatter accepts a resolved `datetime` and returns a relative path.

Example:

```python
format_path(date, "YYYY/MM/DD")
```

returns:

```text
2025/08/27
```

Example:

```python
format_path(date, "YYYY-MM-DD")
```

returns:

```text
2025-08-27
```

The path formatter must not know whether the media is a photo or video.

---

# 19. Path Scheme Validation

The configured path scheme must be validated before an import begins.

Validation must reject:

- Unknown tokens
- Invalid path syntax
- Absolute paths
- Path traversal components
- Empty/invalid schemes

The resulting formatted path must always remain relative to the configured library root.

---

# 20. Destination Path Safety

Destination paths must be constructed using `pathlib`.

Never concatenate untrusted paths using raw string operations.

The original filename must be treated as untrusted input.

The implementation must ensure that a filename cannot escape the configured library root.

Examples of dangerous names such as:

```text
../../foo.jpg
```

must not result in writes outside the destination library.

---

# 21. Import Planner

The planner is responsible for converting discovered media into a complete import plan.

It should, in this order:

1. Classify files.
2. Resolve dates.
3. Detect RAW/JPEG pairs.
4. Generate destination paths.
5. Check destination state.
6. Detect in-plan destination collisions.
7. Determine the action.

Steps 2 and 3 must not be reordered: pairing needs to know whether the RAW resolved to a usable date
(section 17.2).

Step 6 requires the planner to maintain a map of destination paths it has already assigned during
this plan, so that two source files targeting the same destination are caught even though neither
conflicts with anything on disk. See section 23.1.

The planner must not copy files.

---

# 22. Import Plan Model

Each planned operation should contain:

```text
source_path
media_type
filename
resolved_datetime
date_source
destination_path
action
reason
```

Example:

```text
source:
  /mnt/import/random/20250827_105030.mp4

type:
  video

date:
  2025-08-27 10:50:30

date_source:
  filename

destination:
  /mnt/videos/2025/08/27/20250827_105030.mp4

action:
  COPY
```

---

# 23. Destination Comparison

Before planning a copy, inspect whether the destination already exists.

The check is a single `stat` on the destination path. In the common case the path is free and the
item is planned `COPY` with no further work. There is **no index, no database, and no hashing of the
library** — a repeat import over a large library must not read the contents of files it already has.

Cases:

### Missing

```text
COPY
```

### Existing and the same file

```text
SKIP   reason = ALREADY_IMPORTED
```

Two files are the same when **all three** of these match:

```text
filename                  (identical by construction — same destination path)
size in bytes
resolved capture datetime
```

Size plus resolved capture datetime is enough to recognize a file this importer wrote on an earlier
run, which is the only case this check needs to serve. The source file stays in the import folder,
untouched, and the user is told it was recognized rather than silently passed over.

### Existing and different

```text
COLLISION   resolved by the configured policy (section 23.2)
```

### Existing but a symlink

```text
ERROR
```

Never overwrite, clobber, or rename a symlink in the destination. Report and continue.

---

## 23.1 In-Plan Collisions

A destination path can also be claimed twice within a single import — two cards, two cameras, or a
reused card producing `/import/a/IMG_1234.JPG` and `/import/b/IMG_1234.JPG` with the same capture
date.

Checking only the on-disk state misses this entirely: both items would be planned `COPY` to the same
path, and the second copy would silently destroy the first, violating the never-overwrite rule while
reporting two clean successes.

The planner must therefore keep a `dict[Path, PlanItem]` of destinations assigned so far. A second
claim on the same destination is a collision and goes through the same policy as an on-disk one.

Note also that the destination state observed at plan time goes stale as the executor runs. The
executor must not re-derive decisions, but it must still perform the copy itself in a way that cannot
clobber a file that appeared in the meantime (section 25).

---

## 23.2 Collision Policy

Driven by `on_collision`, applied identically to on-disk and in-plan collisions.

### `skip` (default)

Plan `SKIP` with reason `COLLISION_SKIPPED`. The existing file is untouched, the source file stays in
the import folder, the collision is reported. Nothing is destroyed.

### `clobber`

One file wins, by `clobber_prefers`:

```text
"newest"   later resolved capture datetime wins
"oldest"   earlier resolved capture datetime wins
```

Tie-break on mtime. If still tied, the incumbent wins and the incoming file is skipped — this makes
repeated runs stable instead of rewriting the same file every time.

A winning incoming file must be written through the atomic temp-and-rename path in section 25, so an
interrupted clobber cannot leave the destination truncated or missing.

### `rename`

Keep both. Suffix the incoming file's **stem**, never the extension, choosing the lowest free index:

```text
IMG_1234.DNG      existing
IMG_1234-1.DNG    first colliding import
IMG_1234-2.DNG    second colliding import
```

Index selection must consult both the filesystem and the in-plan destination map, or two colliding
items in one run will both choose `-1`.

`skip` is the default because it is the only policy that neither destroys existing data nor silently
multiplies files.

---

# 24. Import Executor

The importer executes an already-created import plan.

It must not independently reinterpret dates or pairing rules.

For each `COPY` operation:

1. Create destination directory if required.
2. Copy the source file.
3. Verify successful completion.
4. Record the result.
5. Under `import_action = "move"`, and only now that step 3 has succeeded, delete the source.

## 24.1 Move

The executor takes the `ImportAction` as a parameter; the planner is unaware of it, because whether a
file is imported is a separate question from what happens to the original afterwards.

Deletion happens **after** the destination is in place, never before and never in parallel. If any
step fails, the source survives.

Only files the executor actually imported may be deleted. Skipped, undated, colliding,
already-imported, ignored and failed items are never touched — the executor only ever iterates
`plan.to_copy`, which gives this property structurally rather than by a check that could be
forgotten.

### Same-filesystem fast path

Rewriting the bytes of a multi-gigabyte video to move it across one disk is unacceptable. Prefer
`os.link` followed by unlinking the source:

- It is atomic.
- It fails if the destination exists, preserving the same exclusive-create guarantee as an ordinary
  copy (section 25).
- It preserves timestamps for free.
- It is instant regardless of file size.

`os.link` raises `OSError` (EXDEV) across filesystems; fall back to the ordinary copy-then-delete
path there.

### Failure to delete

If the destination copy succeeded but the source cannot be removed, log a warning and count the item
as **imported**. The file did reach the library, and reporting a successful import as a failure would
be misleading.

---

# 25. Atomicity

Where practical, file copies should avoid leaving apparently completed destination files after an interrupted copy.

A suitable approach is:

```text
source
  ↓
temporary destination file
  ↓
successful copy
  ↓
atomic rename to final destination
```

The implementation must ensure that a partially copied file is not mistaken for a successfully imported file on the next run.

Concretely:

- The temporary file must be created **in the destination directory**, not in `/tmp`. `os.rename` is
  only atomic within a single filesystem, and the library is very often on a different mount than
  the system temp directory.
- Give temporaries a recognizable prefix (e.g. `.<name>.partial-<pid>`), and sweep stale ones from
  the destination directory at the start of a run. An interrupted run otherwise leaves debris that a
  later scan of that tree would see as a real file.
- For a `COPY` to a path expected to be free, create the final file with `O_EXCL` semantics, or
  re-check immediately before the rename. This closes the window between the planner's `stat` and
  the executor's write, during which another process — or another item in the same plan — could have
  created the file.
- Use `shutil.copy2` so mtime is preserved on the imported copy. Downstream tools read library file
  timestamps, and `copy` would reset them all to import time.

---

# 26. Import Progress

The importer should expose progress information independently of the TUI.

For example, through a callback/event interface:

```text
on_file_started
on_file_completed
on_file_failed
```

The TUI can subscribe to these events.

This keeps the importer independent of the presentation layer.

---

# 27. Error Handling

Use explicit exception types for expected application errors.

Examples:

```text
ConfigurationError
MetadataError
DateResolutionError
DestinationCollision
MediaImportError
```

Do **not** name an exception `ImportError`. That shadows a Python builtin, and a bare
`except ImportError:` anywhere in the codebase or in a dependency would then catch application errors
alongside genuine module-import failures. Use `MediaImportError`.

All application exceptions should derive from a single package-level base class so callers can catch
the whole family.

Individual file failures should not normally abort the entire import.

Fatal configuration/filesystem errors may abort the operation.

Errors should contain enough information to identify the affected file.

---

# 28. Logging

Use Python's standard `logging` package.

Do not use `print()` for application logging.

Logging levels:

```text
DEBUG
INFO
WARNING
ERROR
```

The TUI may provide a user-friendly presentation of errors while logging retains technical details.

---

# 29. TUI Architecture

The TUI should act as a presentation layer.

It should communicate with application services through well-defined Python APIs.

The TUI must not:

- Read EXIF directly
- Parse video metadata
- Determine destination dates
- Copy files directly
- Parse configuration files directly

This logic belongs to the application layer.

---

# 30. Testing Strategy

Use `pytest`.

Tests must cover all core logic without requiring the TUI.

Required test categories:

### Scanner

- Recursive discovery
- Empty directories
- Nested directories

### Classifier

- Photo extensions
- Video extensions
- Case-insensitivity
- Unknown extensions

### Photo dates

- DateTimeOriginal
- EXIF fallback
- Missing metadata
- Invalid metadata

### Video dates

- Metadata date
- Filename date
- Birth time
- Priority ordering
- No available date

### Filename parser

At minimum:

```text
20250827_105030.mp4
```

### RAW/JPEG

- Matching pair
- Different directories
- Different stems
- RAW without JPEG
- JPEG without RAW

### Path scheme

Test all supported tokens and representative schemes.

### Metadata sanity check

- `1904-01-01` rejected (below floor)
- `0000:00:00 00:00:00` rejected (unparseable)
- Capture far older than mtime accepted (archival import)
- Capture more than 2 years after mtime rejected
- A rejected metadata date falls through to the next tier rather than making the file undated

### Config validation

- `photo_library` inside `source_path` rejected
- `source_path` inside `video_library` rejected
- Nesting via a symlink still rejected (paths resolved first)
- `photo_library == video_library` accepted
- Unknown `on_collision` / `clobber_prefers` value raises `ConfigurationError`

### Symlinks

- Symlinked file not imported
- Symlinked directory not descended
- Symlink loop does not hang the scan
- Symlink in the destination is never overwritten

### Planner

- Copy
- Skip
- Collision
- Undated
- RAW/JPEG skip
- Two source files resolving to one destination path (in-plan collision)
- Path traversal: a hostile filename cannot escape the library root

### Collision policy

- `skip` leaves both files untouched
- `clobber` + `newest` replaces the older file
- `clobber` + `oldest` keeps the incumbent
- `clobber` tie on capture date falls through to mtime, then to incumbent
- `rename` picks the lowest free index
- `rename` with two in-plan collisions does not assign `-1` twice

### Importer

- Successful copy
- Existing identical file (same size + same resolved date) skipped
- Existing colliding file
- Destination creation
- Interrupted/partial copy handling
- Stale `.partial` temporary files swept before a run
- mtime preserved on the copied file
- End-to-end idempotency: a second run over the same source copies zero files

---

# 31. Test Fixtures

Tests should use small generated fixtures wherever possible.

Media metadata test fixtures may be included in the repository where required.

Tests must not depend on the user's actual photo library or filesystem.

Temporary directories should be created using pytest's temporary-path facilities.

---

# 32. Code Quality

Use:

- Type hints
- `pathlib`
- Dataclasses and/or typed models
- Standard exception handling
- Clear module boundaries

Use a standard formatter/linter.

A suitable combination is:

- Ruff for linting
- Ruff formatter for formatting
- pytest for tests

The exact tooling can be changed, but automated linting and formatting must be provided.

---

# 33. Dependency Management

All runtime dependencies must be declared in `pyproject.toml`.

Development dependencies should be defined separately, for example through an optional dependency group:

```toml
[project.optional-dependencies]
dev = [...]
```

The project must not rely on globally installed Python packages.

---

# 34. Build System

Use a modern PEP 517/518-compatible build system.

`pyproject.toml` must contain all package metadata required to build:

- Source distribution
- Wheel

The package must be buildable in a clean Python environment.

---

# 35. PyPI Packaging

The project must generate standard PyPI artifacts:

```text
dist/
├── <package>-<version>.tar.gz
└── <package>-<version>-py3-none-any.whl
```

The package must contain the console entry point.

The README should be used as the package's long description.

---

# 36. PyPI Publishing

Provide Makefile targets for publishing.

Required:

```bash
make publish-pypi
make publish-testpypi
```

Use standard Python packaging/upload tooling.

Credentials must be supplied through environment variables.

For example:

```bash
export TWINE_USERNAME="..."
export TWINE_PASSWORD="..."
```

The Makefile must not contain credentials.

Publishing targets should fail with a clear error when required credentials are unavailable.

---

# 37. Conda Packaging — Out of Scope for v1

Conda packaging is **deferred**. v1 ships through PyPI and from source only.

The recipe would be a second set of package metadata to keep version-synced with `pyproject.toml`,
and `conda-build` is not itself pip-installable into the development environment, so it adds a
parallel toolchain for no v1 benefit.

If it is added later, it belongs at `packaging/conda/meta.yaml`, must derive its version from the
single source of truth in section 44 rather than restating it, and must declare `exiftool` and
`ffmpeg` as runtime dependencies — something conda can express and a PyPI wheel cannot, which is the
main argument for eventually doing it.

Nothing in v1 may be structured in a way that blocks this later.

---

# 38. Conda Publishing — Out of Scope for v1

Deferred along with section 37. There is no `make publish-conda` target in v1 and no
`ANACONDA_API_TOKEN`.

---

# 39. Makefile

Provide a top-level `Makefile`.

At minimum:

```text
make install
make run
make test
make lint
make format
make clean
make build
make package
make publish-testpypi
make publish-pypi
```

Suggested semantics:

```text
install
    Install the project and development dependencies.

run
    Launch the application locally.

test
    Run the test suite.

lint
    Run static analysis.

format
    Format the source tree.

clean
    Remove generated artifacts.

build
    Build the Python package.

package
    Build all distribution artifacts.

publish-testpypi
    Build and publish to TestPyPI.

publish-pypi
    Build and publish to PyPI.
```

Publishing should depend on successful tests/builds where appropriate.

---

# 40. Build Reproducibility

The package must build successfully from a clean checkout.

Build artifacts must not be committed to Git.

The following should normally be ignored:

```text
build/
dist/
*.egg-info/
.pytest_cache/
.ruff_cache/
__pycache__/
```

---

# 41. README

The repository must contain a complete `README.md`.

The README must cover:

## Introduction

What the application does and why it exists.

## Features

Including:

- Recursive scanning
- Metadata-driven date resolution
- Separate photo/video libraries
- RAW/JPEG pairing
- Configurable destination layout
- Safe repeated imports

## Requirements

Supported Python version and operating systems (Linux and WSL).

### System dependencies

The README must give a **complete** per-distribution system prerequisite command — one that installs
Python, pip, the virtualenv package, and both metadata tools together, so a reader can get from a
bare machine to a working install without assembling it themselves.

At minimum apt and dnf must be covered:

```bash
# Debian / Ubuntu / WSL
sudo apt update
sudo apt install -y python3 python3-pip python3-venv \
                    libimage-exiftool-perl ffmpeg

# Fedora
sudo dnf install -y python3 python3-pip \
                    perl-Image-ExifTool ffmpeg-free

# Arch
sudo pacman -S --needed python python-pip perl-image-exiftool ffmpeg
```

Followed by a verification step the reader can run (`python3 --version`, `exiftool -ver`,
`ffprobe -version`), cross-referenced to `make check-tools`.

The following caveats must be documented, because each one is a real install failure:

- `ffprobe` has no package of its own; it ships inside `ffmpeg`.
- On Fedora, `ffmpeg-free` from the main repositories provides `ffprobe`; the RPM Fusion `ffmpeg`
  build also works and covers more codecs.
- On Debian and Ubuntu, `python3-venv` is a separate package. Without it `make install` fails when
  it creates the virtualenv.
- Python 3.11 is the minimum. Ubuntu 22.04 (3.10) and Debian 11 (3.9) are too old; Debian 12,
  Ubuntu 24.04, Fedora and Arch are current enough.

This section must appear prominently, before the install commands, since a PyPI wheel cannot express
a system dependency.

## Installation

PyPI:

```bash
python3 -m pip install media-importer
```

From source:

```bash
git clone <repository>
cd media-importer
make install
```

## Usage

Explain how to launch:

```bash
media-importer
```

and how the TUI works.

## Configuration

Document the configuration file and all configuration fields.

## Path Scheme

Document:

```text
YYYY
YY
MM
DD
```

with examples.

## Date Resolution

Document:

- Photo EXIF priority, and that photos never fall back to filename or filesystem time
- Video metadata priority
- Filename fallback
- Filesystem birth-time fallback, and that it degrades to mtime on most Linux filesystems
- The plausibility check that rejects implausible metadata dates

## Collision Handling

Document `on_collision` (`skip` / `clobber` / `rename`) and `clobber_prefers`, with an example of
each, and note that `skip` is the default because it never destroys data.

## RAW/JPEG Handling

Explain that the RAW is imported and the paired JPEG is left untouched, that only camera RAW formats
count (TIFF does not), and that an undated RAW does not suppress its JPEG.

Note that Apple Live Photos (`.HEIC` + `.MOV`) are not pairs and are deliberately split across the
two libraries.

## Development

Explain:

```bash
make install
make run
make test
make lint
make format
```

## Packaging

Explain:

```bash
make build
make package
```

## Publishing

Document:

```bash
make publish-testpypi
make publish-pypi
```

and the required environment variables (`TWINE_USERNAME`, `TWINE_PASSWORD`).

---

# 42. Environment Variables

Publishing credentials must be supplied through environment variables.

The exact variables depend on the chosen publishing tools, but the README must document them explicitly.

No secrets may be read from source-controlled configuration.

No credentials should be printed in normal command output.

---

# 43. CI

A CI workflow is recommended.

At minimum, CI should:

1. Install the package.
2. Install development dependencies.
3. Run the test suite.
4. Run linting.
5. Verify the package builds successfully.

Publishing should not happen automatically unless explicitly configured for releases.

---

# 44. Versioning

The project must have a single authoritative package version.

Define it once, in `pyproject.toml`, and read it at runtime with
`importlib.metadata.version("media-importer")`. Do not maintain a second hand-edited `__version__`
string that can drift out of sync.

The version must be available to:

- Python package metadata
- PyPI build
- The application, for display in the TUI

---

# 45. Distribution Consistency

Installing from PyPI or from source must expose the same application and console command.

Both:

```bash
pip install media-importer
```

and:

```bash
git clone <repository> && cd media-importer && make install
```

must result in:

```bash
media-importer
```

being available on `PATH`, and in `python -m media_importer` launching the same application.

Neither install path supplies `exiftool` or `ffprobe`; both rely on the distribution packages
documented in section 11.1.

---

# 46. Development Workflow

A clean checkout should support:

```bash
make install
make test
make run
```

A release workflow should support:

```bash
make clean
make test
make lint
make build
```

followed by:

```bash
make publish-pypi
```

TestPyPI should be available for validating a release before publishing to the production PyPI repository.

---

# 47. Implementation Constraints

The implementation must not:

- Require a database
- Require an index or content hashing of the destination libraries
- Require a backend service
- Require Docker
- Require a graphical desktop environment
- Modify the source media
- Hard-code destination directories
- Hard-code user-specific paths
- Hard-code credentials
- Couple media-processing logic to the TUI

The application must remain usable entirely from a Linux/WSL terminal.

`exiftool` and `ffprobe` are a deliberate exception to the "no external dependencies" spirit of this
list. They are ordinary distribution packages rather than services, and no pip-installable library
covers EXIF across every RAW variant and container metadata across every video format well enough to
replace them.

---

# 48. Definition of Done

The implementation is considered complete when:

- The application can be installed from PyPI.
- The application can be installed from source.
- `media-importer` launches the TUI, and so does `python -m media_importer`.
- A missing `exiftool` or `ffprobe` produces a clear startup error naming the install command.
- Configuration persists between runs.
- The source directory is recursively scanned.
- Photos and videos are correctly classified.
- Photo dates are resolved from EXIF, and photos never fall back to filename or filesystem time.
- Video dates follow metadata → filename → birth time → mtime priority.
- Implausible metadata dates are rejected and fall through to the next tier.
- A configuration nesting a library inside the source is rejected before scanning.
- Symlinks are ignored in both the source and the destination.
- The configurable destination path scheme works.
- RAW/JPEG pairs are correctly handled, and a JPEG is never suppressed by an undated RAW.
- Destination collisions are resolved by the configured policy, including two source files that
  resolve to the same destination path within one run.
- Source files remain untouched.
- Existing destination files are handled safely.
- Repeated imports are idempotent.
- Undated files are reported rather than silently misplaced.
- Individual file errors do not abort the entire import.
- Automated tests cover the core functionality.
- `make test` succeeds.
- `make lint` succeeds.
- `make build` produces valid Python packages.
- `make publish-testpypi` completes a real upload to TestPyPI using environment-provided credentials.
- `make publish-pypi` is verified to build and authenticate, and fails clearly when credentials are
  absent. Actually publishing to production PyPI is a release action, not an acceptance criterion —
  it claims a name irreversibly and cannot be undone.
- README installation and usage instructions are complete.
