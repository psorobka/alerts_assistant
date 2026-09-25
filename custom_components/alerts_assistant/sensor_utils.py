"""Helpers for classifying Home Assistant sensor state metadata."""

from __future__ import annotations

import math

from homeassistant.core import State


def classify_sensor_state(state: State | None) -> str | None:
    """Return numeric, text, ambiguous, or None when the type is unknown.

    Sensor states are strings in Home Assistant. Metadata is more authoritative
    than the current value; a numeric-looking string without metadata is
    ambiguous because it may be a textual code such as ``"123"``.
    """
    if state is None or state.state in ("unknown", "unavailable"):
        return None

    attributes = state.attributes
    device_class = attributes.get("device_class")
    if device_class == "enum":
        return "text"
    if device_class in ("date", "timestamp"):
        return "text"
    if (
        attributes.get("unit_of_measurement") is not None
        or attributes.get("state_class") is not None
        or device_class is not None
    ):
        return "numeric"

    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return "text"
    return "ambiguous" if math.isfinite(value) else "text"


def sensor_state_matches_mode(state: State | None, mode: str) -> bool:
    """Whether a sensor can reasonably be selected for the requested mode."""
    return classify_sensor_state(state) in (mode, "ambiguous", None)
