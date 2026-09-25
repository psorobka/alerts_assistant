"""Pseudo-integration tests for the alert behaviour on a real HA core."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

from homeassistant.const import STATE_IDLE, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.alerts_assistant.const import (
    ACK_ACTION_PREFIX,
    CONF_NUMERIC_COMPARATOR,
    CONF_NUMERIC_THRESHOLD,
    CONF_SENSOR_MODE,
    CONF_TEXT_STATE,
    DOMAIN,
    EVENT_MOBILE_APP_NOTIFICATION_ACTION,
)

from .conftest import alert_config, make_entry

ENTITY_ID = "alerts_assistant.test"
WATCHED = "input_boolean.test"


async def _setup(hass: HomeAssistant, **overrides):
    """Register a mock notify service and set up one alert."""
    calls = async_mock_service(hass, "notify", "test")
    hass.states.async_set(WATCHED, STATE_OFF)
    entry = make_entry(alert_config(**overrides))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, calls


def _advance(hass: HomeAssistant, minutes: float) -> None:
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(minutes=minutes, seconds=1)
    )


async def test_starts_idle(hass: HomeAssistant) -> None:
    await _setup(hass)
    assert hass.states.get(ENTITY_ID).state == STATE_IDLE


async def test_fires_and_notifies(hass: HomeAssistant) -> None:
    _, calls = await _setup(hass)

    hass.states.async_set(WATCHED, STATE_ON)
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == STATE_ON
    assert len(calls) == 1
    assert calls[0].data["message"] == "Test"


@pytest.mark.parametrize(
    ("comparator", "initial", "trigger", "cleared"),
    [("below", "25", "19.9", "20"), ("above", "15", "20.1", "20")],
)
async def test_numeric_sensor_threshold(hass, comparator, initial, trigger, cleared):
    """Numeric alerts fire on strict threshold crossings and clear afterward."""
    calls = async_mock_service(hass, "notify", "test")
    hass.states.async_set(WATCHED, initial)
    entry = make_entry(
        alert_config(
            **{
                CONF_NUMERIC_COMPARATOR: comparator,
                CONF_NUMERIC_THRESHOLD: 20,
            }
        )
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_IDLE

    hass.states.async_set(WATCHED, trigger)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_ON
    assert len(calls) == 1

    hass.states.async_set(WATCHED, "unavailable")
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_ON

    hass.states.async_set(WATCHED, cleared)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_IDLE


async def test_text_sensor_value_fires_until_value_changes(hass: HomeAssistant) -> None:
    """Text sensors match exact values and ignore temporary unavailable states."""
    calls = async_mock_service(hass, "notify", "test")
    hass.states.async_set(WATCHED, "closed")
    entry = make_entry(
        alert_config(
            **{CONF_SENSOR_MODE: "text", CONF_TEXT_STATE: "open"},
        )
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_IDLE

    hass.states.async_set(WATCHED, "open")
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_ON
    assert len(calls) == 1

    hass.states.async_set(WATCHED, "unavailable")
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_ON

    hass.states.async_set(WATCHED, "closed")
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_IDLE


async def test_numeric_alert_clears_when_sensor_reports_text(
    hass: HomeAssistant,
) -> None:
    """A nonnumeric state does not satisfy a numeric comparison."""
    await _setup(
        hass,
        **{
            CONF_NUMERIC_COMPARATOR: "below",
            CONF_NUMERIC_THRESHOLD: 20,
        },
    )
    hass.states.async_set(WATCHED, "10")
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_ON

    hass.states.async_set(WATCHED, "charging")
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_IDLE


async def test_multi_entity_alerts_run_and_acknowledge_independently(
    hass: HomeAssistant,
) -> None:
    """Every entity selected in one alert has its own ack and repeat lifecycle."""
    calls = async_mock_service(hass, "notify", "test")
    bathroom = ar.async_get(hass).async_create("Bathroom")
    entity_registry = er.async_get(hass)
    bathroom_entity = entity_registry.async_get_or_create(
        "binary_sensor",
        "test_platform",
        "leak_bathroom",
        suggested_object_id="leak_bathroom",
    )
    kitchen_entity = entity_registry.async_get_or_create(
        "binary_sensor",
        "test_platform",
        "leak_kitchen",
        suggested_object_id="leak_kitchen",
    )
    entity_registry.async_update_entity(bathroom_entity.entity_id, area_id=bathroom.id)
    hass.states.async_set(
        bathroom_entity.entity_id, "off", {"friendly_name": "Bathroom leak"}
    )
    hass.states.async_set(
        kitchen_entity.entity_id, "off", {"friendly_name": "Kitchen leak"}
    )
    entry = make_entry(
        alert_config(
            entity_id=bathroom_entity.entity_id,
            entity_ids=[bathroom_entity.entity_id, kitchen_entity.entity_id],
            message="{{ area }}: {{ entity_name }} ({{ entity_id }})",
        )
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    bathroom_alert, kitchen_alert = entry.runtime_data["alert-0"]
    hass.states.async_set(bathroom_entity.entity_id, "on")
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert (
        calls[0].data["message"]
        == f"Bathroom: Bathroom leak ({bathroom_entity.entity_id})"
    )
    assert hass.states.get(bathroom_alert.entity_id).state == STATE_ON
    assert hass.states.get(kitchen_alert.entity_id).state == STATE_IDLE
    triggered_at = hass.states.get(bathroom_alert.entity_id).attributes["triggered_at"]
    assert hass.states.get(bathroom_alert.entity_id).attributes["area"] == "Bathroom"

    await hass.services.async_call(
        DOMAIN,
        "turn_off",
        {"entity_id": bathroom_alert.entity_id},
        blocking=True,
    )
    hass.states.async_set(kitchen_entity.entity_id, "on")
    await hass.async_block_till_done()
    assert len(calls) == 2
    assert hass.states.get(bathroom_alert.entity_id).state == STATE_OFF
    assert (
        hass.states.get(bathroom_alert.entity_id).attributes["triggered_at"]
        == triggered_at
    )
    assert hass.states.get(bathroom_alert.entity_id).attributes["acknowledged"]
    assert hass.states.get(kitchen_alert.entity_id).state == STATE_ON

    hass.states.async_set(bathroom_entity.entity_id, "off")
    await hass.async_block_till_done()
    assert hass.states.get(bathroom_alert.entity_id).state == STATE_IDLE
    assert "triggered_at" not in hass.states.get(bathroom_alert.entity_id).attributes


async def test_repeats_after_interval(hass: HomeAssistant) -> None:
    _, calls = await _setup(hass, repeat=[30.0])

    hass.states.async_set(WATCHED, STATE_ON)
    await hass.async_block_till_done()
    assert len(calls) == 1

    _advance(hass, 30)
    await hass.async_block_till_done()
    assert len(calls) == 2


async def test_escalating_repeat(hass: HomeAssistant) -> None:
    _, calls = await _setup(hass, repeat=[10.0, 30.0])

    hass.states.async_set(WATCHED, STATE_ON)
    await hass.async_block_till_done()
    assert len(calls) == 1  # immediate

    _advance(hass, 10)
    await hass.async_block_till_done()
    assert len(calls) == 2  # after first (10 min) delay

    _advance(hass, 30)
    await hass.async_block_till_done()
    assert len(calls) == 3  # after second (30 min) delay, then stays at 30


async def test_skip_first(hass: HomeAssistant) -> None:
    _, calls = await _setup(hass, skip_first=True, repeat=[30.0])

    hass.states.async_set(WATCHED, STATE_ON)
    await hass.async_block_till_done()
    assert len(calls) == 0

    _advance(hass, 30)
    await hass.async_block_till_done()
    assert len(calls) == 1


async def test_acknowledge_silences(hass: HomeAssistant) -> None:
    _, calls = await _setup(hass, repeat=[30.0])

    hass.states.async_set(WATCHED, STATE_ON)
    await hass.async_block_till_done()
    assert len(calls) == 1

    await hass.services.async_call(
        "alerts_assistant", "turn_off", {"entity_id": ENTITY_ID}, blocking=True
    )
    assert hass.states.get(ENTITY_ID).state == STATE_OFF

    _advance(hass, 30)
    await hass.async_block_till_done()
    assert len(calls) == 1  # no further notifications


async def test_cannot_acknowledge(hass: HomeAssistant) -> None:
    _, _ = await _setup(hass, can_acknowledge=False)

    hass.states.async_set(WATCHED, STATE_ON)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "alerts_assistant", "turn_off", {"entity_id": ENTITY_ID}, blocking=True
    )
    assert hass.states.get(ENTITY_ID).state == STATE_ON


async def test_clears_to_idle_with_done_message(hass: HomeAssistant) -> None:
    _, calls = await _setup(hass, done_message="All clear")

    hass.states.async_set(WATCHED, STATE_ON)
    await hass.async_block_till_done()
    assert len(calls) == 1

    hass.states.async_set(WATCHED, STATE_OFF)
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == STATE_IDLE
    assert len(calls) == 2
    assert calls[-1].data["message"] == "All clear"


async def test_rearms_after_clear(hass: HomeAssistant) -> None:
    _, calls = await _setup(hass)

    hass.states.async_set(WATCHED, STATE_ON)
    await hass.async_block_till_done()
    hass.states.async_set(WATCHED, STATE_OFF)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_IDLE

    hass.states.async_set(WATCHED, STATE_ON)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_ON
    assert len(calls) == 2


async def test_custom_title_and_message(hass: HomeAssistant) -> None:
    _, calls = await _setup(hass, message="Door open!", title="Security")

    hass.states.async_set(WATCHED, STATE_ON)
    await hass.async_block_till_done()

    assert calls[0].data["message"] == "Door open!"
    assert calls[0].data["title"] == "Security"


async def test_notify_failure_does_not_break_loop(hass: HomeAssistant) -> None:
    """S1: a failing notify service must not stop repeats or stick the state."""
    counter = {"n": 0}

    async def boom(call):
        counter["n"] += 1
        raise RuntimeError("notifier offline")

    hass.services.async_register("notify", "test", boom)
    hass.states.async_set(WATCHED, STATE_OFF)
    entry = make_entry(alert_config(repeat=[30.0]))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    hass.states.async_set(WATCHED, STATE_ON)
    await hass.async_block_till_done()

    # State reflects firing (not stuck at idle) despite the notify error.
    assert hass.states.get(ENTITY_ID).state == STATE_ON
    assert counter["n"] == 1

    _advance(hass, 30)
    await hass.async_block_till_done()
    assert counter["n"] == 2  # the repeat loop kept going


async def test_multiple_notifiers_and_data(hass: HomeAssistant) -> None:
    """Each notifier is called, and extra data is forwarded in the payload."""
    calls1 = async_mock_service(hass, "notify", "n1")
    calls2 = async_mock_service(hass, "notify", "n2")
    hass.states.async_set(WATCHED, STATE_OFF)
    entry = make_entry(alert_config(notifiers=["n1", "n2"], data={"priority": "high"}))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    hass.states.async_set(WATCHED, STATE_ON)
    await hass.async_block_till_done()

    assert len(calls1) == 1
    assert len(calls2) == 1
    # User data is preserved and merged with the injected acknowledge action.
    assert calls1[0].data["data"]["priority"] == "high"
    assert "actions" in calls1[0].data["data"]


async def test_qualified_legacy_target_sends_to_service(hass: HomeAssistant) -> None:
    """A fully-qualified legacy target invokes its notify service."""
    calls = async_mock_service(hass, "notify", "legacy")
    hass.states.async_set(WATCHED, STATE_OFF)
    entry = make_entry(alert_config(notifiers=["notify.legacy"]))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    hass.states.async_set(WATCHED, STATE_ON)
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["message"] == "Test"
    assert "actions" in calls[0].data["data"]


async def test_notify_entity_uses_send_message(hass: HomeAssistant) -> None:
    """Modern notify entities receive messages through notify.send_message."""
    calls = async_mock_service(hass, "notify", "send_message")
    hass.states.async_set(WATCHED, STATE_OFF)
    hass.states.async_set("notify.phone", "unknown", {"friendly_name": "Phone"})
    entry = make_entry(
        alert_config(notifiers=["notify.phone"], title="Alert title", data={"x": 1})
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    hass.states.async_set(WATCHED, STATE_ON)
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["entity_id"] == "notify.phone"
    assert calls[0].data["message"] == "Test"
    assert calls[0].data["title"] == "Alert title"
    assert "data" not in calls[0].data


async def test_notification_includes_ack_action(hass: HomeAssistant) -> None:
    """The firing notification carries an Acknowledge action button."""
    entry, calls = await _setup(hass)

    hass.states.async_set(WATCHED, STATE_ON)
    await hass.async_block_till_done()

    subentry_id = next(iter(entry.subentries))
    assert calls[0].data["data"]["actions"] == [
        {"action": f"{ACK_ACTION_PREFIX}{subentry_id}", "title": "Acknowledge"}
    ]


@pytest.mark.parametrize(
    ("language", "title"), [("en", "Acknowledge"), ("pl", "Potwierdź")]
)
async def test_notification_ack_button_uses_home_assistant_language(
    hass: HomeAssistant, monkeypatch, language: str, title: str
) -> None:
    """The push action label follows the configured HA UI language."""
    hass.config.language = language
    translation_key = f"component.{DOMAIN}.common.action_acknowledge"
    monkeypatch.setattr(
        "custom_components.alerts_assistant.alert.async_get_translations",
        AsyncMock(return_value={translation_key: title}),
    )
    entry, calls = await _setup(hass)

    hass.states.async_set(WATCHED, STATE_ON)
    await hass.async_block_till_done()

    assert calls[0].data["data"]["actions"][0]["title"] == title
    assert calls[0].data["data"]["actions"][0]["action"].startswith(ACK_ACTION_PREFIX)
    await hass.config_entries.async_unload(entry.entry_id)


async def test_notification_action_acknowledges(hass: HomeAssistant) -> None:
    """Tapping the notification action acknowledges and silences the alert."""
    entry, calls = await _setup(hass, repeat=[30.0])

    hass.states.async_set(WATCHED, STATE_ON)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_ON

    subentry_id = next(iter(entry.subentries))
    hass.bus.async_fire(
        EVENT_MOBILE_APP_NOTIFICATION_ACTION,
        {"action": f"{ACK_ACTION_PREFIX}{subentry_id}"},
    )
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY_ID).state == STATE_OFF

    _advance(hass, 30)
    await hass.async_block_till_done()
    assert len(calls) == 1  # no further notifications after acknowledging


async def test_done_message_has_no_ack_action(hass: HomeAssistant) -> None:
    _, calls = await _setup(hass, done_message="All clear")

    hass.states.async_set(WATCHED, STATE_ON)
    await hass.async_block_till_done()
    hass.states.async_set(WATCHED, STATE_OFF)
    await hass.async_block_till_done()

    assert calls[-1].data["message"] == "All clear"
    assert "actions" not in calls[-1].data.get("data", {})


async def test_ack_action_can_be_disabled(hass: HomeAssistant) -> None:
    _, calls = await _setup(hass, ack_from_notification=False)

    hass.states.async_set(WATCHED, STATE_ON)
    await hass.async_block_till_done()

    assert "data" not in calls[0].data


async def test_no_ack_action_when_not_acknowledgeable(hass: HomeAssistant) -> None:
    _, calls = await _setup(hass, can_acknowledge=False)

    hass.states.async_set(WATCHED, STATE_ON)
    await hass.async_block_till_done()

    assert "data" not in calls[0].data


async def test_already_firing_at_startup(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "notify", "test")
    hass.states.async_set(WATCHED, STATE_ON)
    entry = make_entry(alert_config())
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == STATE_ON
    assert len(calls) == 1
