"""Sensor-state classification tests."""

from homeassistant.core import State
import pytest

from custom_components.alerts_assistant.sensor_utils import (
    classify_sensor_state,
    sensor_state_matches_mode,
)


@pytest.mark.parametrize(
    ("value", "attributes", "expected"),
    [
        ("unavailable", {}, None),
        ("open", {"device_class": "enum"}, "text"),
        ("2026-09-25", {"device_class": "date"}, "text"),
        ("12", {"unit_of_measurement": "%"}, "numeric"),
        ("open", {}, "text"),
        ("12", {}, "ambiguous"),
        ("nan", {}, "text"),
    ],
)
def test_classify_sensor_state(value, attributes, expected):
    assert classify_sensor_state(State("sensor.test", value, attributes)) == expected


def test_unknown_state_matches_any_mode() -> None:
    assert sensor_state_matches_mode(None, "numeric")
    assert sensor_state_matches_mode(State("sensor.test", "5"), "text")
    assert not sensor_state_matches_mode(State("sensor.test", "open"), "numeric")
