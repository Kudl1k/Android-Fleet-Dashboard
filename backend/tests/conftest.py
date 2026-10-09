"""Keep normal tests isolated from local persistent development inventory."""

import pytest


@pytest.fixture(autouse=True)
def isolated_registry_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANDROID_FLEET_REGISTRY_PATH", ":memory:")
    monkeypatch.setenv("ANDROID_FLEET_HISTORY_PATH", ":memory:")
    monkeypatch.delenv("ANDROID_FLEET_CONTROL_TOKEN", raising=False)
