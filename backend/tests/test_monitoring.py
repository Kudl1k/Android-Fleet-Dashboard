import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from prometheus_client.parser import text_string_to_metric_families

from android_fleet.devices.models import Device, DeviceState
from android_fleet.metrics.catalog import DEFINITIONS
from android_fleet.metrics.exporter import METRICS, render_metrics
from android_fleet.metrics.models import MetricSnapshot, MetricValue

NOW = datetime(2026, 10, 9, tzinfo=UTC)


def exposition(values: tuple[MetricValue, ...], *, age: float = 0) -> str:
    device = Device("d", "d", "Demo", DeviceState.ONLINE, last_seen=NOW, root_available=False)
    snapshot = MetricSnapshot("d", NOW - timedelta(seconds=age), values)
    return render_metrics([device], {"d": snapshot}, now=NOW).decode()


def test_exporter_covers_catalog_with_expected_units_labels() -> None:
    assert set(METRICS) == set(DEFINITIONS)
    values = []
    label_examples = {
        "core": "0",
        "mount": "/data",
        "interface": "wlan0",
        "sensor": "cpu0",
        "type": "cpu",
    }
    for name, definition in DEFINITIONS.items():
        values.append(
            MetricValue(
                name,
                1.0
                if name
                in {"thermal_status", "battery_status", "battery_health", "battery_charging"}
                else 0.5,
                definition.unit,
                tuple((key, label_examples[key]) for key in definition.labels),
            )
        )
    families = list(text_string_to_metric_families(exposition(tuple(values))))
    samples = {sample.name: sample for family in families for sample in family.samples}
    assert set(METRICS.values()) <= samples.keys()
    for name, prometheus_name in METRICS.items():
        assert samples[prometheus_name].labels == {
            "device_id": "d",
            **{key: label_examples[key] for key in DEFINITIONS[name].labels},
        }
    assert "android_device_last_seen_timestamp_seconds" in samples
    assert "android_metrics_last_collection_timestamp_seconds" in samples


def test_network_metrics_are_raw_counters_and_reset_without_adjustment() -> None:
    for raw in (1000, 1):
        output = exposition(
            (MetricValue("network_receive", raw, "bytes", (("interface", "wlan0"),)),)
        )
        families = {family.name: family for family in text_string_to_metric_families(output)}
        assert families["android_network_receive_bytes"].type == "counter"
        assert families["android_network_receive_bytes"].samples[0].value == raw


@pytest.mark.parametrize("age", [121, -1])
def test_stale_or_future_snapshot_is_omitted(age: float) -> None:
    output = exposition((MetricValue("cpu_usage", 0.5, "ratio"),), age=age)
    assert "android_cpu_usage_ratio{device_id=" not in output
    assert "android_metrics_last_collection_timestamp_seconds{device_id=" not in output
    assert 'android_device_up{device_id="d"} 1.0' in output


def test_duplicate_invalid_or_unbounded_values_are_omitted() -> None:
    values = [
        MetricValue("cpu_usage", 0.5, "ratio"),
        MetricValue("cpu_usage", 0.9, "ratio"),
        MetricValue("cpu_usage", 2, "ratio"),
        MetricValue("memory_used", float("nan"), "bytes"),
        MetricValue("cpu_frequency", 1, "hertz", (("core", "256"),)),
        MetricValue("storage_total", 1, "bytes", (("mount", "/unbounded"),)),
        MetricValue("battery_voltage", 1, "wrong"),
    ]
    values.extend(
        MetricValue("network_receive", 1, "bytes", (("interface", f"if{i}"),)) for i in range(40)
    )
    values.extend(
        MetricValue("thermal_temperature", 20, "celsius", (("sensor", f"s{i}"), ("type", "cpu")))
        for i in range(40)
    )
    families = list(text_string_to_metric_families(exposition(tuple(values))))
    samples = [sample for family in families for sample in family.samples]
    assert len([s for s in samples if s.name == "android_cpu_usage_ratio"]) == 1
    assert len([s for s in samples if s.name == "android_network_receive_bytes_total"]) == 32
    assert len([s for s in samples if s.name == "android_temperature_celsius"]) == 32
    assert not any(
        s.name
        in {
            "android_memory_used_bytes",
            "android_cpu_frequency_hz",
            "android_storage_total_bytes",
            "android_battery_voltage_volts",
        }
        for s in samples
    )


@pytest.mark.parametrize("max_age", [0, -1, float("nan"), float("inf")])
def test_invalid_freshness_settings_rejected(max_age: float) -> None:
    with pytest.raises(ValueError):
        render_metrics([], {}, max_age_seconds=max_age)


def test_versioned_dashboards_use_supported_metrics_and_prometheus_datasource() -> None:
    root = Path(__file__).resolve().parents[2] / "monitoring" / "grafana"
    files = sorted((root / "dashboards").glob("*.json"))
    assert len(files) == 2
    known = {
        *METRICS.values(),
        "android_device_up",
        "android_metrics_last_collection_timestamp_seconds",
    }
    dashboards = [json.loads(path.read_text()) for path in files]
    assert len({dashboard["uid"] for dashboard in dashboards}) == 2
    for dashboard in dashboards:
        assert dashboard["schemaVersion"] >= 39
        assert dashboard["editable"]
        assert dashboard["panels"]
        for panel in dashboard["panels"]:
            assert panel["datasource"]["uid"] == "prometheus"
            for target in panel["targets"]:
                assert target["datasource"]["uid"] == "prometheus"
                assert set(re.findall(r"android_[a-z_]+", target["expr"])) <= known
                assert "or vector(0)" not in target["expr"]
                if "network_" in target["expr"]:
                    assert "rate(" in target["expr"]
                    assert "$__rate_interval" in target["expr"]
                if panel["fieldConfig"]["defaults"]["unit"] == "percentunit":
                    assert panel["fieldConfig"]["defaults"]["max"] == 1
    detail = next(d for d in dashboards if d["uid"] == "android-fleet-device")
    variable = detail["templating"]["list"][0]
    assert variable["datasource"]["uid"] == "prometheus"
    assert variable["query"]["query"] == "label_values(android_device_up, device_id)"
    assert (
        "/var/lib/grafana/dashboards"
        in (root / "provisioning" / "dashboards" / "fleet.yml").read_text()
    )
