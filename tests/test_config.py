from pathlib import Path

import pytest

from media_importer import config as config_module
from media_importer.config import Config, from_dict, load, save, validate_for_import
from media_importer.errors import ConfigurationError
from media_importer.models import ClobberPreference, CollisionPolicy, ImportAction


def test_creates_default_on_first_run(tmp_path):
    target = tmp_path / "config.toml"
    cfg = load(target)
    assert target.exists()
    assert cfg.import_path == "YYYY/MM/DD"
    assert cfg.on_collision is CollisionPolicy.SKIP
    assert cfg.clobber_prefers is ClobberPreference.NEWEST


def test_round_trip(tmp_path, libraries):
    source, photos, videos = libraries
    target = tmp_path / "config.toml"
    cfg = Config(
        source_path=source,
        photo_library=photos,
        video_library=videos,
        import_path="YYYY/MM",
        on_collision=CollisionPolicy.RENAME,
    )
    save(cfg, target)
    loaded = load(target)
    assert loaded.source_path == source
    assert loaded.import_path == "YYYY/MM"
    assert loaded.on_collision is CollisionPolicy.RENAME


def test_values_persist_between_runs(tmp_path, libraries):
    source, photos, videos = libraries
    target = tmp_path / "config.toml"
    save(Config(source_path=source, photo_library=photos, video_library=videos), target)
    assert load(target).photo_library == photos


def test_unknown_keys_are_preserved(tmp_path):
    """A config written by a newer version must survive an older one."""
    target = tmp_path / "config.toml"
    target.write_text('import_path = "YYYY"\nfuture_option = "keep me"\n')
    cfg = load(target)
    save(cfg, target)
    assert "future_option" in target.read_text()


def test_invalid_collision_policy_is_rejected(tmp_path):
    target = tmp_path / "config.toml"
    target.write_text('on_collision = "explode"\n')
    with pytest.raises(ConfigurationError, match="explode"):
        load(target)


def test_invalid_clobber_preference_is_rejected(tmp_path):
    target = tmp_path / "config.toml"
    target.write_text('clobber_prefers = "sideways"\n')
    with pytest.raises(ConfigurationError):
        load(target)


def test_malformed_toml_is_rejected(tmp_path):
    target = tmp_path / "config.toml"
    target.write_text("this is not = = toml")
    with pytest.raises(ConfigurationError):
        load(target)


def test_config_dir_honours_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert config_module.config_dir() == tmp_path / "xdg" / "media-importer"


def test_config_dir_defaults_to_dot_config(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert config_module.config_dir() == tmp_path / ".config" / "media-importer"


class TestValidation:
    def test_accepts_a_good_config(self, config):
        validate_for_import(config)

    def test_incomplete_config_is_rejected(self, libraries):
        source, photos, _ = libraries
        cfg = Config(source_path=source, photo_library=photos)
        with pytest.raises(ConfigurationError, match="video_library"):
            validate_for_import(cfg)

    def test_missing_source_is_rejected(self, config, tmp_path):
        config.source_path = tmp_path / "gone"
        with pytest.raises(ConfigurationError, match="does not exist"):
            validate_for_import(config)

    def test_libraries_are_created(self, config, tmp_path):
        config.photo_library = tmp_path / "new-photos"
        validate_for_import(config)
        assert config.photo_library.is_dir()

    def test_photo_library_inside_source_is_rejected(self, config):
        config.photo_library = config.source_path / "photos"
        with pytest.raises(ConfigurationError, match="nested"):
            validate_for_import(config)

    def test_source_inside_video_library_is_rejected(self, config, tmp_path):
        config.video_library = config.source_path.parent
        with pytest.raises(ConfigurationError, match="nested"):
            validate_for_import(config)

    def test_source_equal_to_library_is_rejected(self, config):
        config.photo_library = config.source_path
        with pytest.raises(ConfigurationError):
            validate_for_import(config)

    def test_nesting_via_symlink_is_still_rejected(self, config, tmp_path):
        """Paths are resolved first, so indirection cannot defeat the check."""
        link = tmp_path / "sneaky"
        link.symlink_to(config.source_path / "inside")
        (config.source_path / "inside").mkdir()
        config.photo_library = link
        with pytest.raises(ConfigurationError, match="nested"):
            validate_for_import(config)

    def test_the_two_libraries_may_be_identical(self, config):
        config.video_library = config.photo_library
        validate_for_import(config)

    def test_invalid_scheme_is_rejected(self, config):
        config.import_path = "YYY/MM"
        with pytest.raises(ConfigurationError):
            validate_for_import(config)


def test_from_dict_expands_user(monkeypatch, tmp_path):
    # expanduser() consults $HOME, not Path.home().
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = from_dict({"source_path": "~/pics"})
    assert cfg.source_path == tmp_path / "pics"


class TestImportAction:
    def test_default_is_copy(self):
        assert Config().import_action is ImportAction.COPY

    def test_move_is_parsed(self, tmp_path):
        target = tmp_path / "config.toml"
        target.write_text('import_action = "move"\n')
        assert load(target).import_action is ImportAction.MOVE

    def test_invalid_action_is_rejected(self, tmp_path):
        target = tmp_path / "config.toml"
        target.write_text('import_action = "teleport"\n')
        with pytest.raises(ConfigurationError, match="teleport"):
            load(target)

    def test_round_trips(self, tmp_path, libraries):
        source, photos, videos = libraries
        target = tmp_path / "config.toml"
        save(
            Config(
                source_path=source,
                photo_library=photos,
                video_library=videos,
                import_action=ImportAction.MOVE,
            ),
            target,
        )
        assert load(target).import_action is ImportAction.MOVE
        assert 'import_action = "move"' in target.read_text()


class TestDefaultSourceDirectory:
    def test_first_run_defaults_to_the_working_directory(self, tmp_path, monkeypatch):
        work = tmp_path / "somewhere"
        work.mkdir()
        monkeypatch.chdir(work)
        cfg = load(tmp_path / "config.toml")
        assert cfg.source_path == work

    def test_the_default_is_persisted_not_implicit(self, tmp_path, monkeypatch):
        """It must be visible and editable in the config file, not recomputed."""
        work = tmp_path / "somewhere"
        work.mkdir()
        monkeypatch.chdir(work)
        target = tmp_path / "config.toml"
        load(target)
        assert str(work) in target.read_text()

    def test_an_existing_config_is_not_overridden_by_cwd(self, tmp_path, monkeypatch, libraries):
        source, _, _ = libraries
        target = tmp_path / "config.toml"
        target.write_text(f'source_path = "{source}"\n')
        monkeypatch.chdir(tmp_path)
        assert load(target).source_path == source
