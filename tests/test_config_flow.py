"""Config flow and subentry flow tests."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
import pytest
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.alerts_assistant.const import DOMAIN, SUBENTRY_TYPE_ALERT

from .conftest import alert_config, make_entry

VALID_INPUT = {
    "name": "Garage",
    "entity_id": "binary_sensor.garage",
    "state": "on",
    "notifiers": ["test"],
    "repeat": "30",
    "can_acknowledge": True,
    "skip_first": False,
}


async def test_user_flow_creates_hub(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Alerts Assistant"


async def test_single_instance_only(hass: HomeAssistant) -> None:
    make_entry().add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_subentry_user_flow_adds_alert(hass: HomeAssistant) -> None:
    async_mock_service(hass, "notify", "test")
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_ALERT), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], dict(VALID_INPUT)
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    subentries = list(entry.subentries.values())
    assert len(subentries) == 1
    assert subentries[0].title == "Garage"
    # repeat string is parsed into a list of minutes
    assert subentries[0].data["repeat"] == [30.0]


async def test_subentry_stores_optional_data(hass: HomeAssistant) -> None:
    async_mock_service(hass, "notify", "test")
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_ALERT), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**VALID_INPUT, "data": {"priority": "high"}}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    subentry = next(iter(entry.subentries.values()))
    assert subentry.data["data"] == {"priority": "high"}


async def test_subentry_invalid_repeat(hass: HomeAssistant) -> None:
    async_mock_service(hass, "notify", "test")
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_ALERT), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**VALID_INPUT, "repeat": "abc"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"repeat": "invalid_repeat"}


async def test_unknown_notifier_rejected_by_selector(hass: HomeAssistant) -> None:
    """With no notify.test registered, the select selector rejects it (S4)."""
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_ALERT), context={"source": SOURCE_USER}
    )
    with pytest.raises(InvalidData):
        await hass.config_entries.subentries.async_configure(
            result["flow_id"], dict(VALID_INPUT)
        )


async def test_invalid_template_rejected_by_selector(hass: HomeAssistant) -> None:
    """The template selector rejects invalid templates at config time (N4)."""
    async_mock_service(hass, "notify", "test")
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_ALERT), context={"source": SOURCE_USER}
    )
    with pytest.raises(InvalidData):
        await hass.config_entries.subentries.async_configure(
            result["flow_id"], {**VALID_INPUT, "message": "{{ unclosed"}
        )


async def test_subentry_requires_notifier(hass: HomeAssistant) -> None:
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_ALERT), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**VALID_INPUT, "notifiers": []}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"notifiers": "no_notifiers"}


async def test_subentry_reconfigure(hass: HomeAssistant) -> None:
    entry = make_entry(alert_config(name="Old", entity_id="binary_sensor.x"))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    subentry_id = next(iter(entry.subentries))
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_ALERT),
        context={"source": "reconfigure", "subentry_id": subentry_id},
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**VALID_INPUT, "name": "New"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries[subentry_id].data["name"] == "New"


async def test_reconfigure_clears_optional_field(hass: HomeAssistant) -> None:
    """S2: removing an optional template on edit actually clears it."""
    entry = make_entry(
        alert_config(name="Old", entity_id="binary_sensor.x", message="hello")
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    subentry_id = next(iter(entry.subentries))
    assert entry.subentries[subentry_id].data.get("message") == "hello"

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_ALERT),
        context={"source": "reconfigure", "subentry_id": subentry_id},
    )
    # VALID_INPUT carries no message field -> it should be dropped.
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**VALID_INPUT, "name": "Old"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert "message" not in entry.subentries[subentry_id].data
