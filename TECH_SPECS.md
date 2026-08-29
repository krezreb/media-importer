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
- Be distributable through PyPI and Conda.

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
photo-import/
├── pyproject.toml
├── README.md
├── LICENSE
├── Makefile
├── .gitignore
├── src/
│   └── <package_name>/
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
└── packaging/
    └── conda/
        └── meta.yaml
```

The exact module names may differ, but the separation of responsibilities should be maintained.

---

# 4. CLI Entry Point

The package must expose a console script through `pyproject.toml`.

For example:

```toml
[project.scripts]
photo-import = "photo_import.cli:main"
```

The application must therefore be runnable as:

```bash
photo-import
```

It must also support:

```bash
python -m photo_import
```

Both entry points must launch the same application.

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

Use a human-readable configuration file stored in the user's home configuration directory.

Preferred location:

```text
~/.config/<application-name>/config.toml
```

Use a suitable TOML library or Python's built-in TOML support where available.

Configuration must contain:

```toml
source_path = "/path/to/import"
photo_library = "/path/to/photos"
video_library = "/path/to/videos"
import_path = "YYYY/MM/DD"
```

The application must create the configuration directory and default configuration when required.

---

# 7. Configuration Model

Represent configuration using a typed Python model/dataclass.

At minimum:

```text
source_path
photo_library
video_library
import_path
```

Configuration loading and validation must be centralized in the configuration module.

The rest of the application should consume a validated configuration object rather than parsing TOML directly.

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
Copy
Skip
Conflict
Error
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

Use Python's `pathlib` APIs.

The scanner should handle large directory trees without unnecessarily loading file contents into memory.

---

# 10. Media Classifier

Implement a dedicated media classifier.

Classification should primarily be based on the file extension.

Extension matching must be case-insensitive.

Maintain centralized sets/maps of supported extensions.

Example:

```python
PHOTO_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".dng",
    ".cr2",
    ".cr3",
    ".nef",
    ".orf",
    ".rw2",
    ".arw",
}
```

and:

```python
VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".m4v",
    ".avi",
    ".mpg",
    ".mpeg",
    ".mts",
    ".3gp",
}
```

The exact list should be easy to extend.

---

# 11. Metadata Extraction

Metadata extraction must be isolated behind an abstraction.

The application should use appropriate established libraries/tools rather than implementing media metadata parsing itself.

The metadata abstraction should expose normalized values.

For example:

```python
Metadata(
    capture_datetime=...,
    source="exif",
)
```

or:

```python
Metadata(
    capture_datetime=...,
    source="video_metadata",
)
```

The date resolver must not depend on the implementation details of the metadata extraction library.

---

# 12. Photo Date Resolver

Implement a dedicated photo date resolver.

Resolution priority:

```text
EXIF DateTimeOriginal
        ↓
other supported EXIF capture-date fields
        ↓
undated
```

Do not use:

- Filename
- Filesystem modification time
- Filesystem creation time

as photo date fallbacks unless explicitly added as a future feature.

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
1. Embedded metadata
2. Filename date/time
3. Filesystem birth/creation time
4. Undated
```

The resolver must stop at the first reliable date.

It must return both:

```text
resolved datetime
date source
```

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

For video fallback handling, implement a filesystem birth/creation-time abstraction.

The implementation must use the best available Linux filesystem API.

On systems where true birth time is unavailable, return an explicit unavailable result.

Do not silently substitute:

```text
mtime
```

for birth time.

WSL compatibility must be considered.

The behavior when the underlying filesystem does not expose birth time must be documented.

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

A pair exists when:

```text
same parent directory
same filename stem
one RAW file
one JPEG/JPG file
```

The RAW file takes precedence.

The resulting import plan must mark the JPEG as:

```text
SKIP
```

with a reason such as:

```text
JPEG paired with RAW
```

The JPEG must remain untouched.

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

It should:

1. Classify files.
2. Resolve dates.
3. Detect RAW/JPEG pairs.
4. Generate destination paths.
5. Check destination state.
6. Determine the action.

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

Cases:

### Missing

```text
COPY
```

### Existing and identical

```text
SKIP
```

### Existing and different

```text
CONFLICT
```

The implementation should use an efficient comparison strategy.

A suitable strategy is:

1. Compare file size.
2. If sizes match, compare content using a hash or equivalent mechanism.

Avoid hashing large files unnecessarily when file size already differs.

---

# 24. Import Executor

The importer executes an already-created import plan.

It must not independently reinterpret dates or pairing rules.

For each `COPY` operation:

1. Create destination directory if required.
2. Copy the source file.
3. Verify successful completion.
4. Record the result.

Source files must remain untouched.

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
DestinationConflict
ImportError
```

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

### Planner

- Copy
- Skip
- Conflict
- Undated
- RAW/JPEG skip

### Importer

- Successful copy
- Existing identical file
- Existing conflicting file
- Destination creation
- Interrupted/partial copy handling

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

# 37. Conda Packaging

Provide a Conda package recipe.

Recommended:

```text
packaging/
└── conda/
    └── meta.yaml
```

The recipe must contain:

- Package name
- Version
- Source
- Build requirements
- Runtime requirements
- Entry point
- License
- Metadata

The recipe must install the same Python application as the PyPI package.

---

# 38. Conda Publishing

Provide:

```bash
make publish-conda
```

The target must build and publish the Conda package using standard Conda tooling.

Credentials must come from environment variables.

For example:

```bash
export ANACONDA_API_TOKEN="..."
```

No credentials may be committed to the repository.

The target should fail clearly when credentials are missing.

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
make publish-conda
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

publish-conda
    Build and publish the Conda package.
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

Supported Python version and operating systems.

## Installation

PyPI:

```bash
python3 -m pip install <package-name>
```

Conda:

```bash
conda install -c <channel> <package-name>
```

From source:

```bash
git clone <repository>
cd <repository>
make install
```

## Usage

Explain how to launch:

```bash
photo-import
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

- Photo EXIF priority
- Video metadata priority
- Filename fallback
- Filesystem creation-time fallback

## RAW/JPEG Handling

Explain that the RAW is imported and the paired JPEG is left untouched.

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
make publish-conda
```

and the required environment variables.

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

The version must be available to:

- Python package metadata
- PyPI build
- Conda recipe
- Application if displayed by the CLI/TUI

Avoid maintaining multiple independently edited version strings where possible.

---

# 45. Distribution Consistency

The PyPI and Conda packages must expose the same application and console command.

For example, both:

```bash
pip install <package-name>
```

and:

```bash
conda install -c <channel> <package-name>
```

must result in:

```bash
photo-import
```

being available.

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
make publish-conda
```

TestPyPI should be available for validating a release before publishing to the production PyPI repository.

---

# 47. Implementation Constraints

The implementation must not:

- Require a database
- Require a backend service
- Require Docker
- Require a graphical desktop environment
- Modify the source media
- Hard-code destination directories
- Hard-code user-specific paths
- Hard-code credentials
- Couple media-processing logic to the TUI

The application must remain usable entirely from a Linux/WSL terminal.

---

# 48. Definition of Done

The implementation is considered complete when:

- The application can be installed from PyPI.
- The application can be installed from Conda.
- The application can be installed from source.
- `photo-import` launches the TUI.
- Configuration persists between runs.
- The source directory is recursively scanned.
- Photos and videos are correctly classified.
- Photo dates are resolved from EXIF.
- Video dates follow metadata → filename → creation-time priority.
- The configurable destination path scheme works.
- RAW/JPEG pairs are correctly handled.
- Source files remain untouched.
- Existing destination files are handled safely.
- Repeated imports are idempotent.
- Undated files are reported rather than silently misplaced.
- Individual file errors do not abort the entire import.
- Automated tests cover the core functionality.
- `make test` succeeds.
- `make lint` succeeds.
- `make build` produces valid Python packages.
- `make publish-pypi` publishes using environment-provided credentials.
- `make publish-conda` publishes using environment-provided credentials.
- README installation and usage instructions are complete.
