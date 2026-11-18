import pytest

from ecam_sync.config import ConfigError, load_config

BASE = "ICS_URL=https://example.test/x.ics\nGOOGLE_CALENDAR_ID=cal\nGOOGLE_CREDENTIALS_FILE=/nonexistent.json\n"


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    for key in ("ICS_URL", "GOOGLE_CALENDAR_ID", "GOOGLE_CREDENTIALS_FILE", "TIMEZONE", "MAX_DELETE_FRACTION"):
        monkeypatch.delenv(key, raising=False)

    def write(extra="", prefix=""):
        path = tmp_path / "test.env"
        path.write_text(prefix + BASE + extra, encoding="utf-8")
        return str(path)
    return write


def test_valid_file_with_bom(env_file):
    cfg = load_config(env_file(prefix="\ufeff"))
    assert cfg.ics_url.startswith("https://") and "example.test" not in repr(cfg)


@pytest.mark.parametrize("extra", ["TIMEZONE=Mars/Olympus\n", "MAX_DELETE_FRACTION=0\n",
                                   "MAX_DELETE_FRACTION=2\n", "HORIZON_DAYS=-1\n", "MQTT_PORT=99999\n"])
def test_invalid_values_are_rejected_at_startup(env_file, extra):
    with pytest.raises(ConfigError):
        load_config(env_file(extra))


def test_unreadable_file_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError):
        load_config(str(tmp_path))  # un dossier : lecture impossible
