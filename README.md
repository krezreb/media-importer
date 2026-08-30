# media-importer

Import photos and videos from any directory into date-organized libraries, driven by the media's own
metadata rather than by where the files happen to sit.

Point it at a camera card, a phone backup, or a decade of accumulated mess. It reads each file's
capture date, works out where the file belongs, shows you exactly what it is about to do, and only
then copies. **Your source files are never modified, moved, renamed, or deleted.**

```text
IMPORT/                                PHOTO_LIBRARY/
├── camera/                            └── 2025/
│   ├── random/                            └── 08/
│   │   ├── IMG_001.DNG   ───────────►         ├── 27/
│   │   └── IMG_001.JPG   (skipped)            │   └── IMG_001.DNG
│   └── videos/                                └── 28/
│       └── 20250827_105030.mp4  ─┐                └── IMG_002.JPG
└── phone/                         │
    └── DCIM/                      │      VIDEO_LIBRARY/
        └── IMG_002.JPG  ──────────┼──►   └── 2025/08/27/20250827_105030.mp4
                                   │
```

## Features

- **Recursive scanning.** The source layout is irrelevant and is never reproduced in the destination.
- **Metadata-driven dates.** EXIF for photos; container metadata, then filename, then filesystem
  time for videos.
- **Implausible dates rejected.** The `1904-01-01` and `0000:00:00` junk that real files are full of
  is caught instead of filed.
- **Separate photo and video libraries.**
- **RAW + JPEG pairing.** When a camera wrote both, the RAW is imported and the JPEG left alone.
- **Configurable destination layout.** `YYYY/MM/DD` by default, and freely changeable.
- **Safe repeated imports.** Run it as often as you like; nothing is duplicated or overwritten.
- **Preview before copying.** Every import is planned in full and shown to you for confirmation.

## Requirements

- Linux or WSL
- Python 3.11 or newer
- `exiftool` and `ffprobe`

Capture dates are read by `exiftool` and `ffprobe`. These are **not** Python packages, so `pip`
cannot install them, and `media-importer` refuses to start without them.

### System dependencies

Install everything the application needs, including Python itself, in one command.

**Debian / Ubuntu / WSL**

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv \
                    libimage-exiftool-perl ffmpeg
```

**Fedora**

```bash
sudo dnf install -y python3 python3-pip \
                    perl-Image-ExifTool ffmpeg-free
```

**Arch**

```bash
sudo pacman -S --needed python python-pip perl-image-exiftool ffmpeg
```

Then check that everything is in place:

```bash
python3 --version     # must be 3.11 or newer
exiftool -ver
ffprobe -version | head -1
```

If you are installing from source, `make check-tools` does the last two for you.

#### Notes

- **`ffprobe` has no package of its own** — it ships inside `ffmpeg`.
- **On Fedora**, `ffmpeg-free` comes from the main repositories and provides `ffprobe`. The RPM
  Fusion `ffmpeg` build works too and covers more codecs; use it if you already have that repository
  enabled.
- **On Debian and Ubuntu**, `python3-venv` is a separate package and is easy to miss. Without it
  `make install` fails when it tries to create the virtualenv.
- **Python 3.11 is the minimum.** Debian 12, Ubuntu 24.04, and current Fedora and Arch all ship
  something new enough. Ubuntu 22.04 (Python 3.10) and Debian 11 (3.9) do not — use a newer release,
  or install a newer Python alongside the system one.

## Installation

From PyPI:

```bash
python3 -m pip install media-importer
```

From source:

```bash
git clone https://github.com/krezreb/media-importer
cd media-importer
make install
```

## Usage

```bash
media-importer
```

or equivalently:

```bash
python -m media_importer
```

There are no command-line options. Everything is configured inside the TUI and remembered between
runs, because this is a tool you use repeatedly rather than one you re-specify every time.

The main screen shows your current settings and lets you change any of them. Choosing **Start
import** scans the source, builds a complete plan, and shows you a summary:

```text
Import summary

  Source                 /mnt/import
  Discovered media       1,335
    Photos               1,248
    Videos                  87

  Not importing
    RAW + JPEG pairs       312
    Already imported        42
    Undated                  3
    Collisions               1
    Errors                   0

  Files to import        977
```

Nothing has been copied at this point. The problem categories list the actual file paths, so you can
see what needs attention before committing. Confirm, and the import runs with live progress; an
error on one file is reported and the rest continue.

## Configuration

Settings live in `~/.config/media-importer/config.toml` (or `$XDG_CONFIG_HOME/media-importer/`) and
are written whenever you change something in the TUI.

```toml
source_path      = "/mnt/import"
photo_library    = "/srv/photos"
video_library    = "/srv/videos"
import_path      = "YYYY/MM/DD"
on_collision     = "skip"
clobber_prefers  = "newest"
```

| Key | Meaning |
| --- | --- |
| `source_path` | Directory scanned recursively for media. Never modified. |
| `photo_library` | Destination root for photos. Created if missing. |
| `video_library` | Destination root for videos. Created if missing. |
| `import_path` | Destination layout. See below. |
| `on_collision` | `skip`, `clobber`, or `rename`. See below. |
| `clobber_prefers` | `newest` or `oldest`. Only used when `on_collision = "clobber"`. |

The source and the two libraries may not be nested inside one another — that would make the scanner
rediscover files it had just written, so it is rejected before an import starts.

## Path scheme

`import_path` describes the directory structure inside each library.

| Token | Meaning | Example |
| --- | --- | --- |
| `YYYY` | four-digit year | `2025` |
| `YY` | two-digit year | `25` |
| `MM` | two-digit month | `08` |
| `DD` | two-digit day | `27` |

Anything else is a literal. For a photo dated 2025-08-27:

```text
YYYY/MM/DD        ->  2025/08/27/IMG_1234.DNG
YYYY-MM-DD        ->  2025-08-27/IMG_1234.DNG
YYYY/MM           ->  2025/08/IMG_1234.DNG
YYYY/YYYY-MM-DD   ->  2025/2025-08-27/IMG_1234.DNG
```

The scheme applies identically to both libraries and is validated before any import begins.

> Literal text in a scheme must not contain an uppercase `Y`, `M`, or `D` — that is how a typo like
> `YYY` or `MMM` gets caught rather than silently treated as a directory name. Use lowercase for
> literal folders, e.g. `media/YYYY/MM`.

Changing the scheme only affects future imports. Files already in the library stay where they are; it
does not reorganize what you have already imported.

## Date resolution

Every file's date is resolved before a destination is chosen, and the tool records **where the date
came from** so you can see it in the preview.

### Photos

```text
EXIF DateTimeOriginal  ->  EXIF CreateDate  ->  EXIF DateTime  ->  undated
```

Photos never fall back to the filename or to a filesystem timestamp. EXIF is consistent enough to
rely on, and inventing a date from a file's mtime is worse than admitting there isn't one.

### Videos

```text
container metadata  ->  filename  ->  filesystem birth time  ->  filesystem mtime  ->  undated
```

Video metadata is far less consistent than EXIF, so there is a real fallback chain. Recognized
filename patterns include `20250827_105030`, `IMG_20250827_105030`, `PXL_20250827_105030123`, and
`2025-08-27 10.50.30`.

### Implausible dates

A date read from metadata is rejected, and resolution falls through to the next step, when it is
unparseable, earlier than 1990, or more than two years later than the file's mtime.

That last rule is deliberately one-sided. A capture date *older* than mtime is completely normal —
copying a file updates its mtime while the capture date stays put — so importing a genuinely old
archive keeps its real dates. A capture date meaningfully *newer* than mtime is impossible.

### A note on birth time

Linux exposes no creation time through the Python standard library, so it is read via `statx(2)`
where possible. Even then the value often does not exist: not on FAT32 or exFAT (the format of most
camera SD cards), usually not on WSL drive mounts or NFS, and not on ext4 inodes created before about
2011. Video dating therefore falls through to mtime fairly often. When it does, the preview and the
report say so explicitly rather than presenting mtime as a capture date.

### Undated files

A file with no usable date is reported as **undated** and is not copied. It is not guessed at, and it
is not dumped into an arbitrary directory. It stays in your source folder, listed by path in the
summary, waiting for you to decide. Manual date assignment is not part of this version.

## RAW + JPEG handling

Many cameras write a RAW and a JPEG side by side:

```text
IMG_1234.DNG
IMG_1234.JPG
```

When both sit in the **same source directory** with the same stem, the RAW is imported and the JPEG
is skipped — left completely untouched in your source folder.

Pairing only applies to the unambiguous case: exactly one camera RAW and exactly one JPEG sharing a
stem, and nothing else. Two RAWs, or both a `.jpg` and a `.jpeg`, and both files are simply imported.
Importing both costs disk space; guessing wrong loses a photo.

Two things that are deliberately *not* pairs:

- **TIFF next to JPEG.** TIFF is an ordinary photo format, not a camera RAW.
- **Live Photos** (`IMG_1234.HEIC` + `IMG_1234.MOV`). The still goes to the photo library and the
  movie to the video library, each dated on its own.

And if the RAW turns out to be undated, the pairing is abandoned and the JPEG is imported on its own
merits — otherwise a bad RAW would take a perfectly good JPEG down with it.

## Collisions

A collision is when a destination path is already taken by a *different* file. This happens with two
cameras producing `IMG_1234.JPG` on the same day, or a reused memory card.

A file that is merely *already imported* is not a collision — it is recognized and skipped.

| `on_collision` | Behaviour |
| --- | --- |
| `skip` (default) | Don't import. Nothing is destroyed, and the collision is reported. |
| `clobber` | One file wins, per `clobber_prefers` (`newest` or `oldest` capture date). Ties fall back to mtime, then to keeping the existing file. |
| `rename` | Keep both. The incoming file becomes `IMG_1234-1.JPG`, then `-2`, and so on. |

This covers both a clash with the existing library and two source files in a single run that resolve
to the same destination — the second of which would otherwise silently overwrite the first.

## Safety

- Source files are never modified, moved, renamed, or deleted.
- Existing destination files are never silently overwritten.
- Copies are written to a temporary file in the destination directory and moved into place
  atomically, so an interrupted run cannot leave a truncated file that looks imported.
- Stale partial files from a killed run are swept on the next import.
- Symlinks are ignored, in both the source and the libraries.
- File timestamps are preserved on the copy.

## Development

```bash
make install    # install with dev dependencies
make run        # launch the app
make test       # run the test suite
make lint       # ruff check + format check
make format     # apply formatting
```

The core is fully testable without the TUI: metadata extraction sits behind an interface that tests
replace with a fake, so no test needs `exiftool`, `ffprobe`, or any real media file.

## Packaging

```bash
make build      # build sdist + wheel
make package    # build and validate with twine
```

## Publishing

```bash
make publish-testpypi
make publish-pypi
```

Credentials come from the environment and are never stored in the repository:

```bash
export TWINE_USERNAME=__token__
export TWINE_PASSWORD=<your API token>
```

Both targets run the tests and linter first, and fail with a clear message if `TWINE_PASSWORD` is
unset.

## License

MIT. See [LICENSE](LICENSE).
