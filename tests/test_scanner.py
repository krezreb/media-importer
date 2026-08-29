import pytest
from tests.conftest import make_file

from media_importer.errors import ConfigurationError
from media_importer.models import IgnoreReason
from media_importer.scanner import scan


def names(root):
    return sorted(e.path.name for e in scan(root) if not e.is_ignored)


def ignored(root):
    return sorted(e.path.name for e in scan(root) if e.is_ignored)


def test_finds_files_recursively(tmp_path):
    make_file(tmp_path / "a.jpg")
    make_file(tmp_path / "deep/nested/tree/b.mp4")
    make_file(tmp_path / "deep/c.png")
    assert names(tmp_path) == ["a.jpg", "b.mp4", "c.png"]


def test_empty_directory(tmp_path):
    assert names(tmp_path) == []


def test_empty_nested_directories(tmp_path):
    (tmp_path / "a/b/c").mkdir(parents=True)
    assert names(tmp_path) == []


def test_finds_files_of_any_type(tmp_path):
    """The scanner discovers; the classifier decides. It must not filter."""
    make_file(tmp_path / "a.txt")
    make_file(tmp_path / "b.jpg")
    assert names(tmp_path) == ["a.txt", "b.jpg"]


def test_missing_source_is_fatal(tmp_path):
    with pytest.raises(ConfigurationError):
        list(scan(tmp_path / "nope"))


def test_source_that_is_a_file_is_fatal(tmp_path):
    target = make_file(tmp_path / "a.jpg")
    with pytest.raises(ConfigurationError):
        list(scan(target))


class TestSymlinks:
    def test_symlinked_file_is_ignored(self, tmp_path):
        make_file(tmp_path / "real.jpg")
        (tmp_path / "link.jpg").symlink_to(tmp_path / "real.jpg")
        assert names(tmp_path) == ["real.jpg"]
        assert ignored(tmp_path) == ["link.jpg"]

    def test_symlinked_directory_is_not_descended(self, tmp_path):
        make_file(tmp_path / "real/a.jpg")
        (tmp_path / "link").symlink_to(tmp_path / "real")
        assert names(tmp_path) == ["a.jpg"]
        assert ignored(tmp_path) == ["link"]

    def test_symlink_loop_does_not_hang(self, tmp_path):
        """Not following links removes the need for cycle detection entirely."""
        inner = tmp_path / "a"
        inner.mkdir()
        make_file(inner / "x.jpg")
        (inner / "loop").symlink_to(tmp_path)
        assert names(tmp_path) == ["x.jpg"]

    def test_broken_symlink_is_ignored(self, tmp_path):
        (tmp_path / "dangling.jpg").symlink_to(tmp_path / "gone.jpg")
        assert names(tmp_path) == []
        assert ignored(tmp_path) == ["dangling.jpg"]

    def test_ignore_reason_is_recorded(self, tmp_path):
        make_file(tmp_path / "real.jpg")
        (tmp_path / "link.jpg").symlink_to(tmp_path / "real.jpg")
        events = [e for e in scan(tmp_path) if e.is_ignored]
        assert events[0].ignore_reason is IgnoreReason.SYMLINK
