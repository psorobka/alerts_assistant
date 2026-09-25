"""Setup, unload and reload tests for the integration."""

from __future__ import annotations

from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigEntryState, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers import label_registry as lr
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.alerts_assistant import async_setup
from custom_components.alerts_assistant.const import DOMAIN, SUBENTRY_TYPE_ALERT

from .conftest import alert_config, make_entry


async def test_setup_registers_and_loads_frontend_card(hass: HomeAssistant) -> None:
    """The bundled card is served and loaded as a frontend module."""
    http = MagicMock()
    http.async_register_static_paths = AsyncMock()
    with (
        patch.object(hass, "http", http),
        patch(
            "custom_components.alerts_assistant.add_extra_js_url"
        ) as add_extra_js_url,
    ):
        assert await async_setup(hass, {})

    static_path = http.async_register_static_paths.await_args.args[0][0]
    assert static_path.url_path == "/alerts_assistant/alerts-assistant-card.js"
    assert static_path.path.endswith("www/alerts-assistant-card.js")
    add_extra_js_url.assert_called_once_with(
        hass, "/alerts_assistant/alerts-assistant-card.js"
    )


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


async def test_label_members_are_added_after_setup(hass: HomeAssistant) -> None:
    """Label-based alerts pick up entities labeled after their setup."""
    calls = async_mock_service(hass, "notify", "test")
    label = lr.async_get(hass).async_create("Leak sensors")
    config = {
        "name": "Leaks",
        "entity_ids": [],
        "label_ids": [label.label_id],
        "state": "on",
        "notifiers": ["test"],
        "repeat": [30.0],
        "can_acknowledge": True,
        "skip_first": False,
    }
    entry = make_entry(config)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data["alert-0"] == []
    assert ir.async_get(hass).async_get_issue(DOMAIN, "no_entities_alert-0")

    registry = er.async_get(hass)
    sensor = registry.async_get_or_create(
        "binary_sensor",
        DOMAIN,
        "new_leak_sensor",
        config_entry=entry,
        suggested_object_id="new_leak_sensor",
    )
    hass.states.async_set(sensor.entity_id, "off")
    registry.async_update_entity(sensor.entity_id, labels={label.label_id})
    await hass.async_block_till_done()

    alerts = entry.runtime_data["alert-0"]
    assert len(alerts) == 1
    assert ir.async_get(hass).async_get_issue(DOMAIN, "no_entities_alert-0") is None
    hass.states.async_set(sensor.entity_id, "on")
    await hass.async_block_till_done()
    assert calls[0].data["message"] == alerts[0].name
    assert hass.states.get(alerts[0].entity_id).state == "on"

    registry.async_update_entity(sensor.entity_id, labels=set())
    await hass.async_block_till_done()
    assert entry.runtime_data["alert-0"] == []
    assert hass.states.get(alerts[0].entity_id) is None
    assert ir.async_get(hass).async_get_issue(DOMAIN, "no_entities_alert-0")


async def test_removing_one_explicit_entity_removes_only_its_alert(
    hass: HomeAssistant,
) -> None:
    """Removing one selected entity leaves alerts for the other members running."""
    entry = make_entry(
        alert_config(
            name="Group",
            entity_id=None,
            entity_ids=[f"input_boolean.member_{index}" for index in range(10)],
        )
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    for index in range(10):
        entity_id = f"input_boolean.member_{index}"
        registry.async_get_or_create(
            "input_boolean",
            DOMAIN,
            f"member_{index}",
            config_entry=entry,
            suggested_object_id=f"member_{index}",
        )
        hass.states.async_set(entity_id, "off")

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    alerts = entry.runtime_data["alert-0"]
    assert len(alerts) == 10
    removed_alert = next(
        alert
        for alert in alerts
        if alert._watched_entity_id == "input_boolean.member_4"
    )
    retained_alerts = [alert for alert in alerts if alert is not removed_alert]
    retained_ids = {
        alert._watched_entity_id for alert in alerts if alert is not removed_alert
    }

    registry.async_remove("input_boolean.member_4")
    await hass.async_block_till_done()

    assert len(entry.runtime_data["alert-0"]) == 9
    assert {
        alert._watched_entity_id for alert in entry.runtime_data["alert-0"]
    } == retained_ids
    assert all(alert in entry.runtime_data["alert-0"] for alert in retained_alerts)
    assert ir.async_get(hass).async_get_issue(DOMAIN, "no_entities_alert-0") is not None
    assert (
        "input_boolean.member_4"
        in entry.subentries["alert-0"].data["missing_entity_ids"]
    )
    assert (
        "input_boolean.member_4" not in entry.subentries["alert-0"].data["entity_ids"]
    )
    assert hass.states.get(removed_alert.entity_id) is None
    assert all(
        hass.states.get(alert.entity_id) is not None
        for alert in entry.runtime_data["alert-0"]
    )
    subentry = entry.subentries["alert-0"]
    data = dict(subentry.data)
    data.pop("missing_entity_ids")
    hass.config_entries.async_update_subentry(entry, subentry, data=data)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, "no_entities_alert-0") is None


async def test_removing_referenced_label_removes_its_alerts(
    hass: HomeAssistant,
) -> None:
    """Deleting a label drops its members and removes their alert entities."""
    label = lr.async_get(hass).async_create("Temporary label")
    entry = make_entry(
        {
            **alert_config(
                name="Labeled",
                entity_id=None,
                entity_ids=[],
                label_ids=[label.label_id],
            ),
        }
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    entity = registry.async_get_or_create(
        "binary_sensor",
        DOMAIN,
        "labeled_member",
        config_entry=entry,
        suggested_object_id="labeled_member",
    )
    hass.states.async_set(entity.entity_id, "off")
    registry.async_update_entity(entity.entity_id, labels={label.label_id})

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    alerts = entry.runtime_data["alert-0"]
    assert len(alerts) == 1
    alert_entity_id = alerts[0].entity_id

    lr.async_get(hass).async_delete(label.label_id)
    await hass.async_block_till_done()

    assert entry.runtime_data["alert-0"] == []
    assert hass.states.get(alert_entity_id) is None
    assert "label_ids" not in entry.subentries["alert-0"].data
    assert ir.async_get(hass).async_get_issue(DOMAIN, "no_entities_alert-0") is not None
    assert label.label_id in entry.subentries["alert-0"].data["missing_label_ids"]
