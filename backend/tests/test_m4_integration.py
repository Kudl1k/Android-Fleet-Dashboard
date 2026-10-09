"""Real application wiring: strict confirmations and persistent correlated audit."""

from pathlib import Path

from fastapi.testclient import TestClient

from android_fleet.core.settings import Settings
from android_fleet.main import create_app


def test_invalid_confirmation_denial_and_request_outcomes(tmp_path: Path) -> None:
    settings = Settings(
        anonymous_viewer=True,
        registry_path=tmp_path / "devices.db",
        history_path=tmp_path / "metrics.db",
        control_token="test-administrator",
    )
    headers = {"Authorization": "Bearer test-administrator"}
    app = create_app(settings=settings)
    with TestClient(app) as client:
        endpoint = "/api/v1/devices/pixel-stock/operations"
        denied = client.post(endpoint, json={"action": "reboot", "confirmed": True})
        assert denied.status_code == 403
        invalid = client.post(
            endpoint, headers=headers, json={"action": "reboot", "confirmed": "true"}
        )
        assert invalid.status_code == 422
        events = client.get("/api/v1/audit", headers=headers, params={"action": "reboot"}).json()
        assert events["total"] == 2
        assert {event["authorization"] for event in events["items"]} == {"allowed", "denied"}
        assert all(event["device_id"] == "pixel-stock" for event in events["items"])
        assert all(event["request_id"] for event in events["items"])
        assert client.get("/api/v1/operations", headers=headers).json()["total"] == 0
        for metric in (
            "android_alert_evaluation_healthy",
            "android_alert_evaluations_total",
            "android_alert_evaluation_errors_total",
        ):
            assert metric in client.get("/metrics").text
    restarted = create_app(settings=settings)
    with TestClient(restarted) as client:
        assert (
            client.get("/api/v1/audit", headers=headers, params={"action": "reboot"}).json()[
                "total"
            ]
            == 2
        )
        assert client.get("/api/v1/devices").status_code == 200
