import pytest

from android_fleet.collectors.battery import parse_battery
from android_fleet.metrics.catalog import valid_metric
from android_fleet.metrics.models import MetricValue


@pytest.mark.parametrize("status,charging", [(2, 1), (3, 0), (4, 0), (5, 0)])
def test_battery_status_and_health_are_observed(status: int, charging: int) -> None:
    values = {value.name: value.value for value in parse_battery(f"status: {status}\nhealth: 2")}
    assert values == {"battery_status": status, "battery_charging": charging, "battery_health": 2}


def test_unknown_charging_is_absent_and_missing_fields_are_not_zero() -> None:
    assert {v.name for v in parse_battery("status: 1\nhealth: 1")} == {
        "battery_status",
        "battery_health",
    }
    assert parse_battery("status: 0\nhealth: 8") == ()
    assert parse_battery("status: 2.5\nhealth: NaN") == ()
    assert parse_battery("permission denied") == ()


@pytest.mark.parametrize(
    "name,unit",
    [("battery_status", "level"), ("battery_health", "level"), ("battery_charging", "boolean")],
)
def test_fractional_status_is_rejected(name: str, unit: str) -> None:
    assert not valid_metric(MetricValue(name, 1.5, unit))
