"""Setup, unload and reload tests for the integration."""

from __future__ import annotations

from types import MappingProxyType

from homeassistant.config_entries import ConfigEntryState, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.alerts_assistant.const import DOMAIN, SUBENTRY_TYPE_ALERT

from .conftest import alert_config, make_entry


async def test_setup_creates_entities_and_services(hass: HomeAssistant) -> None:
    hass.states.async_set("input_boolean.test", "off")
    entry = make_entry(
        alert_config(name="Test", entity_id="input_boolean.test"),
        alert_config(name="Other", entity_id="input_boolean.other"),
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("alerts_assistant.test") is not None
    assert hass.states.get("alerts_assistant.other") is not None

    for service in ("turn_on", "turn_off", "toggle"):
        assert hass.services.has_service(DOMAIN, service)


async def test_unload_removes_entities(hass: HomeAssistant) -> None:
    entry = make_entry(alert_config())
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("alerts_assistant.test") is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    # Unload keeps the registry entry but the live state goes unavailable.
    state = hass.states.get("alerts_assistant.test")
    assert state is not None and state.state == "unavailable"


async def test_reload_rebuilds_entities(hass: HomeAssistant) -> None:
    entry = make_entry(alert_config())
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("alerts_assistant.test") is not None


async def test_adding_subentry_adds_entity(hass: HomeAssistant) -> None:
    """A new subentry triggers a reload and a new entity appears."""
    entry = make_entry(alert_config(name="Test", entity_id="input_boolean.test"))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("alerts_assistant.other") is None

    new = ConfigSubentry(
        data=MappingProxyType(
            alert_config(name="Other", entity_id="input_boolean.other")
        ),
        subentry_type=SUBENTRY_TYPE_ALERT,
        title="Other",
        unique_id=None,
    )
    hass.config_entries.async_add_subentry(entry, new)
    await hass.async_block_till_done()

    assert hass.states.get("alerts_assistant.other") is not None


async def test_editing_one_alert_does_not_disturb_others(hass: HomeAssistant) -> None:
    """B1: reconciling after a change must not re-fire/un-ack other alerts."""
    calls_a = async_mock_service(hass, "notify", "a")
    async_mock_service(hass, "notify", "b")
    async_mock_service(hass, "notify", "c")
    hass.states.async_set("input_boolean.a", "off")
    hass.states.async_set("input_boolean.b", "off")

    entry = make_entry(
        alert_config(name="AlertA", entity_id="input_boolean.a", notifiers=["a"]),
        alert_config(name="AlertB", entity_id="input_boolean.b", notifiers=["b"]),
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Fire AlertA and acknowledge it.
    hass.states.async_set("input_boolean.a", "on")
    await hass.async_block_till_done()
    await hass.services.async_call(
        DOMAIN, "turn_off", {"entity_id": "alerts_assistant.alerta"}, blocking=True
    )
    assert hass.states.get("alerts_assistant.alerta").state == "off"
    assert len(calls_a) == 1

    # Add a third, unrelated alert -> triggers reconciliation.
    new = ConfigSubentry(
        data=MappingProxyType(
            alert_config(name="AlertC", entity_id="input_boolean.c", notifiers=["c"])
        ),
        subentry_type=SUBENTRY_TYPE_ALERT,
        title="AlertC",
        unique_id=None,
    )
    hass.config_entries.async_add_subentry(entry, new)
    await hass.async_block_till_done()

    # AlertA stays acknowledged with no extra notification.
    assert hass.states.get("alerts_assistant.alerta").state == "off"
    assert len(calls_a) == 1


async def test_deleting_alert_purges_registry(hass: HomeAssistant) -> None:
    """B2: deleting an alert removes its entity from the registry (no orphan)."""
    hass.states.async_set("input_boolean.test", "off")
    entry = make_entry(alert_config())
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    assert ent_reg.async_get("alerts_assistant.test") is not None

    subentry_id = next(iter(entry.subentries))
    hass.config_entries.async_remove_subentry(entry, subentry_id)
    await hass.async_block_till_done()

    assert hass.states.get("alerts_assistant.test") is None
    assert ent_reg.async_get("alerts_assistant.test") is None


async def test_remove_entry_purges_registry(hass: HomeAssistant) -> None:
    """B2: removing the whole integration leaves no orphaned entities."""
    hass.states.async_set("input_boolean.test", "off")
    entry = make_entry(alert_config())
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    assert ent_reg.async_get("alerts_assistant.test") is not None

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert ent_reg.async_get("alerts_assistant.test") is None
