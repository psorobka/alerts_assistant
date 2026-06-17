"""Shared fixtures and helpers for Alerts Assistant tests."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigSubentryData
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.alerts_assistant.const import DOMAIN, SUBENTRY_TYPE_ALERT

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of the custom integration in every test."""
    yield


def alert_config(**overrides: Any) -> dict[str, Any]:
    """Return a valid alert subentry config, with overrides applied."""
    config: dict[str, Any] = {
        "name": "Test",
        "entity_id": "input_boolean.test",
        "state": "on",
        "notifiers": ["test"],
        "repeat": [30.0],
        "can_acknowledge": True,
        "skip_first": False,
    }
    config.update(overrides)
    return config


def make_entry(*alerts: dict[str, Any]) -> MockConfigEntry:
    """Build a hub MockConfigEntry with one subentry per alert config."""
    subentries = [
        ConfigSubentryData(
            data=config,
            subentry_type=SUBENTRY_TYPE_ALERT,
            title=config["name"],
            unique_id=None,
        )
        for config in alerts
    ]
    return MockConfigEntry(
        domain=DOMAIN,
        title="Alerts Assistant",
        unique_id=DOMAIN,
        subentries_data=subentries,
    )
