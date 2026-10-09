import pytest

from android_fleet.core.settings import Settings


def test_compose_environment_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANDROID_FLEET_FAKE_ADB", "false")
    monkeypatch.setenv("ANDROID_FLEET_POLL_INTERVAL", "12")
    monkeypatch.setenv("ADB_BINARY", "/usr/bin/adb")
    monkeypatch.setenv("ADB_SERVER_HOST", "")
    monkeypatch.setenv("ADB_SERVER_PORT", "5038")
    settings = Settings()
    assert settings.fake_adb is False
    assert settings.poll_interval_seconds == 12
    assert settings.adb_binary == "/usr/bin/adb"
    assert settings.adb_server_host is None
    assert settings.adb_server_port == 5038


def test_settings_allow_explicit_injection() -> None:
    assert Settings(fake_adb=False, poll_interval_seconds=5).fake_adb is False
