"""Config flow and subentry flow tests."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr
from homeassistant.helpers.selector import (
    EntitySelector,
    LabelSelector,
    SelectSelector,
    StateSelector,
)
import pytest
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.alerts_assistant.const import (
    CONF_ALERT_STATE,
    CONF_DEVICE_CLASS,
    CONF_ENTITY_ID,
    CONF_NUMERIC_COMPARATOR,
    CONF_NUMERIC_THRESHOLD,
    CONF_SENSOR_MODE,
    CONF_TEXT_STATE,
    DOMAIN,
    SUBENTRY_TYPE_ALERT,
)

from .conftest import alert_config, make_entry

VALID_INPUT = {
    "name": "Garage",
    "state": "on",
    "notifiers": ["test"],
    "repeat": "30",
    "can_acknowledge": True,
    "skip_first": False,
}
TARGET_INPUT = {"target": ["binary_sensor.garage"]}


async def _start_alert_flow(hass: HomeAssistant, entry):
    """Start adding an alert and select one entity to monitor."""
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_ALERT), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"entity_domain": "binary_sensor"}
    )
    assert result["step_id"] == "user_target"
    target_selector = next(
        selector
        for key, selector in result["data_schema"].schema.items()
        if getattr(key, "schema", None) == "target"
    )
    assert isinstance(target_selector, EntitySelector)

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], TARGET_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user_alert"
    state_selector = next(
        selector
        for key, selector in result["data_schema"].schema.items()
        if getattr(key, "schema", None) == CONF_ALERT_STATE
    )
    assert isinstance(state_selector, StateSelector)
    assert state_selector.config["entity_id"] == "binary_sensor.garage"
    return result


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

    result = await _start_alert_flow(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], dict(VALID_INPUT)
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    subentries = list(entry.subentries.values())
    assert len(subentries) == 1
    assert subentries[0].title == "Garage"
    assert subentries[0].data[CONF_ENTITY_ID] == "binary_sensor.garage"
    assert subentries[0].data["repeat"] == [30.0]


async def test_entity_target_step_is_filtered_by_selected_domain(
    hass: HomeAssistant,
) -> None:
    """The flow chooses a domain, then only matching entities."""
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    entity_registry = er.async_get(hass)
    entities = []
    for object_id in ("test_motion", "test_battery"):
        registry_entry = entity_registry.async_get_or_create(
            "binary_sensor",
            DOMAIN,
            object_id,
            suggested_object_id=object_id,
        )
        hass.states.async_set(registry_entry.entity_id, "off")
        entities.append(registry_entry.entity_id)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_ALERT), context={"source": SOURCE_USER}
    )
    assert result["step_id"] == "user"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"entity_domain": "binary_sensor"}
    )
    assert result["step_id"] == "user_target"
    target_selector = next(
        selector
        for key, selector in result["data_schema"].schema.items()
        if getattr(key, "schema", None) == "target"
    )
    assert isinstance(target_selector, EntitySelector)
    assert target_selector.config["multiple"] is True
    assert target_selector.config["domain"] == ["binary_sensor"]
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"target": entities}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user_alert"
    state_selector = next(
        selector
        for key, selector in result["data_schema"].schema.items()
        if getattr(key, "schema", None) == CONF_ALERT_STATE
    )
    assert state_selector.config["entity_id"] in entities
    state_marker = next(
        key
        for key in result["data_schema"].schema
        if getattr(key, "schema", None) == CONF_ALERT_STATE
    )
    assert state_marker.default() == "off"


async def test_sensor_flow_uses_numeric_threshold_fields(hass: HomeAssistant) -> None:
    """Sensors use a comparator and threshold instead of a state selector."""
    async_mock_service(hass, "notify", "test")
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    sensor = er.async_get(hass).async_get_or_create(
        "sensor", DOMAIN, "battery", suggested_object_id="battery"
    )
    text_sensor = er.async_get(hass).async_get_or_create(
        "sensor", DOMAIN, "door", suggested_object_id="door"
    )
    hass.states.async_set(sensor.entity_id, "80")
    hass.states.async_set(text_sensor.entity_id, "open")
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_ALERT), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"entity_domain": "sensor_numeric"}
    )
    assert result["step_id"] == "user_target"
    entity_selector = next(
        item
        for key, item in result["data_schema"].schema.items()
        if getattr(key, "schema", None) == "target"
    )
    assert isinstance(entity_selector, SelectSelector)
    assert [option["value"] for option in entity_selector.config["options"]] == [
        sensor.entity_id,
    ]
    assert "type unclear" in entity_selector.config["options"][0]["label"]
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"target": [sensor.entity_id]}
    )
    markers = {getattr(key, "schema", None) for key in result["data_schema"].schema}
    assert CONF_NUMERIC_COMPARATOR in markers
    assert CONF_NUMERIC_THRESHOLD in markers
    assert CONF_ALERT_STATE not in markers
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            **{key: value for key, value in VALID_INPUT.items() if key != "state"},
            CONF_NUMERIC_COMPARATOR: "below",
            CONF_NUMERIC_THRESHOLD: 20,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    subentry = next(iter(entry.subentries.values()))
    assert subentry.data["entity_domain"] == "sensor"
    assert subentry.data[CONF_NUMERIC_THRESHOLD] == 20
    assert subentry.data[CONF_SENSOR_MODE] == "numeric"
    assert CONF_ALERT_STATE not in subentry.data


async def test_sensor_flow_suggests_text_and_saves_text_condition(
    hass: HomeAssistant,
) -> None:
    """Text sensor states default to exact text matching."""
    async_mock_service(hass, "notify", "test")
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    sensor = er.async_get(hass).async_get_or_create(
        "sensor", DOMAIN, "door_status", suggested_object_id="door_status"
    )
    hass.states.async_set(sensor.entity_id, "open")
    numeric_sensor = er.async_get(hass).async_get_or_create(
        "sensor", DOMAIN, "battery_level", suggested_object_id="battery_level"
    )
    hass.states.async_set(numeric_sensor.entity_id, "75")
    enum_sensor = er.async_get(hass).async_get_or_create(
        "sensor", DOMAIN, "status_code", suggested_object_id="status_code"
    )
    hass.states.async_set(enum_sensor.entity_id, "123", {"device_class": "enum"})
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_ALERT), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"entity_domain": "sensor_text"}
    )
    assert result["step_id"] == "user_target"
    entity_selector = next(
        item
        for key, item in result["data_schema"].schema.items()
        if getattr(key, "schema", None) == "target"
    )
    assert {option["value"] for option in entity_selector.config["options"]} == {
        sensor.entity_id,
        numeric_sensor.entity_id,
        enum_sensor.entity_id,
    }
    option_labels = {
        option["value"]: option["label"] for option in entity_selector.config["options"]
    }
    assert "type unclear" in option_labels[numeric_sensor.entity_id]
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"target": [sensor.entity_id]}
    )
    markers = {getattr(key, "schema", None) for key in result["data_schema"].schema}
    assert CONF_TEXT_STATE in markers
    assert CONF_NUMERIC_THRESHOLD not in markers
    form_value = next(
        key
        for key in result["data_schema"].schema
        if getattr(key, "schema", None) == CONF_TEXT_STATE
    )
    assert form_value.default() == "open"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            **{key: value for key, value in VALID_INPUT.items() if key != "state"},
            CONF_TEXT_STATE: "open",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    subentry = next(iter(entry.subentries.values()))
    assert subentry.data[CONF_SENSOR_MODE] == "text"
    assert subentry.data[CONF_TEXT_STATE] == "open"


async def test_multi_entity_target_is_saved(hass: HomeAssistant) -> None:
    """Selected entities are stored together for independent alert instances."""
    async_mock_service(hass, "notify", "test")
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    registry = er.async_get(hass)
    entity_ids = []
    for object_id in ("leak_bathroom", "leak_kitchen"):
        entity = registry.async_get_or_create(
            "binary_sensor", DOMAIN, object_id, suggested_object_id=object_id
        )
        hass.states.async_set(entity.entity_id, "off")
        entity_ids.append(entity.entity_id)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_ALERT), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"entity_domain": "binary_sensor"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"target": entity_ids}
    )
    assert result["step_id"] == "user_alert"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], dict(VALID_INPUT)
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    subentry = next(iter(entry.subentries.values()))
    assert subentry.data["entity_ids"] == entity_ids


async def test_label_target_is_saved_and_resolves_members(hass: HomeAssistant) -> None:
    """Labels select every currently matching entity for the alert."""
    async_mock_service(hass, "notify", "test")
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    label = lr.async_get(hass).async_create("Leak sensors")
    registry = er.async_get(hass)
    entity_ids = []
    for object_id in ("bathroom_leak", "kitchen_leak"):
        entity = registry.async_get_or_create(
            "binary_sensor", DOMAIN, object_id, suggested_object_id=object_id
        )
        registry.async_update_entity(entity.entity_id, labels={label.label_id})
        hass.states.async_set(entity.entity_id, "off")
        entity_ids.append(entity.entity_id)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_ALERT), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"entity_domain": "binary_sensor"}
    )
    label_selector = next(
        selector
        for key, selector in result["data_schema"].schema.items()
        if getattr(key, "schema", None) == "labels"
    )
    assert isinstance(label_selector, LabelSelector)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"labels": [label.label_id]}
    )
    assert result["step_id"] == "user_alert"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], dict(VALID_INPUT)
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    subentry = next(iter(entry.subentries.values()))
    assert subentry.data["label_ids"] == [label.label_id]
    assert subentry.data["entity_ids"] == []
    assert {
        alert._watched_entity_id for alert in entry.runtime_data[subentry.subentry_id]
    } == set(entity_ids)


async def test_device_class_filters_entities_and_label_members(
    hass: HomeAssistant,
) -> None:
    """The selected class narrows manual targets and label expansion."""
    async_mock_service(hass, "notify", "test")
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    label = lr.async_get(hass).async_create("Safety sensors")
    registry = er.async_get(hass)
    moisture = registry.async_get_or_create(
        "binary_sensor", DOMAIN, "leak_probe", suggested_object_id="leak_probe"
    )
    occupancy = registry.async_get_or_create(
        "binary_sensor", DOMAIN, "motion_probe", suggested_object_id="motion_probe"
    )
    for entity, device_class in (
        (moisture, "moisture"),
        (occupancy, "occupancy"),
    ):
        registry.async_update_entity(entity.entity_id, labels={label.label_id})
        hass.states.async_set(entity.entity_id, "off", {"device_class": device_class})

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_ALERT), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"entity_domain": "binary_sensor"}
    )
    class_selector = next(
        item
        for key, item in result["data_schema"].schema.items()
        if getattr(key, "schema", None) == CONF_DEVICE_CLASS
    )
    assert class_selector.config["domain"] == "binary_sensor"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "target": [moisture.entity_id, occupancy.entity_id],
            "labels": [label.label_id],
            CONF_DEVICE_CLASS: "moisture",
        },
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], dict(VALID_INPUT)
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    subentry = next(iter(entry.subentries.values()))
    assert subentry.data[CONF_DEVICE_CLASS] == "moisture"
    assert subentry.data[CONF_ENTITY_ID] == moisture.entity_id
    assert {
        alert._watched_entity_id for alert in entry.runtime_data[subentry.subentry_id]
    } == {moisture.entity_id}


async def test_subentry_stores_optional_data(hass: HomeAssistant) -> None:
    async_mock_service(hass, "notify", "test")
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await _start_alert_flow(hass, entry)
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

    result = await _start_alert_flow(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**VALID_INPUT, "repeat": "abc"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"repeat": "invalid_repeat"}


async def test_empty_target_selection_has_translated_error(hass: HomeAssistant) -> None:
    """Submitting no entity or label returns the localized no_entities code."""
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_ALERT), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"entity_domain": "binary_sensor"}
    )
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {})

    assert result["step_id"] == "user_target"
    assert result["errors"] == {"target": "no_entities"}


async def test_manual_notify_target_is_accepted(hass: HomeAssistant) -> None:
    """A manually entered notify target is accepted and stored fully qualified."""
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)

    result = await _start_alert_flow(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**VALID_INPUT, "notifiers": ["notify.custom_target"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    subentry = next(iter(entry.subentries.values()))
    assert subentry.data["notifiers"] == ["notify.custom_target"]


async def test_bare_service_target_is_normalized(hass: HomeAssistant) -> None:
    """Bare service names from older versions are normalized on save."""
    async_mock_service(hass, "notify", "test")
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)

    result = await _start_alert_flow(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], dict(VALID_INPUT)
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    subentry = next(iter(entry.subentries.values()))
    assert subentry.data["notifiers"] == ["notify.test"]


async def test_invalid_template_rejected_by_selector(hass: HomeAssistant) -> None:
    """The template selector rejects invalid templates at config time (N4)."""
    async_mock_service(hass, "notify", "test")
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)

    result = await _start_alert_flow(hass, entry)
    with pytest.raises(InvalidData):
        await hass.config_entries.subentries.async_configure(
            result["flow_id"], {**VALID_INPUT, "message": "{{ unclosed"}
        )


async def test_subentry_requires_notifier(hass: HomeAssistant) -> None:
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)

    result = await _start_alert_flow(hass, entry)
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
        result["flow_id"], {"entity_domain": "binary_sensor"}
    )
    assert result["step_id"] == "reconfigure_target"
    target_marker = next(
        key
        for key in result["data_schema"].schema
        if getattr(key, "schema", None) == "target"
    )
    assert target_marker.description == {"suggested_value": ["binary_sensor.x"]}
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"target": ["binary_sensor.x"]}
    )
    assert result["step_id"] == "reconfigure_alert"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**VALID_INPUT, "name": "New"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries[subentry_id].data["name"] == "New"


async def test_reconfigure_can_choose_multiple_entities(
    hass: HomeAssistant,
) -> None:
    entry = make_entry(alert_config(name="Old", entity_id="binary_sensor.old"))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    subentry_id = next(iter(entry.subentries))

    entity_registry = er.async_get(hass)
    entity = entity_registry.async_get_or_create(
        "binary_sensor",
        DOMAIN,
        "reconfigured_motion",
        config_entry=entry,
        suggested_object_id="reconfigured_motion",
    )
    other_entity = entity_registry.async_get_or_create(
        "binary_sensor",
        DOMAIN,
        "reconfigured_battery",
        config_entry=entry,
        suggested_object_id="reconfigured_battery",
    )
    hass.states.async_set(entity.entity_id, "off")
    hass.states.async_set(other_entity.entity_id, "80")

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_ALERT),
        context={"source": "reconfigure", "subentry_id": subentry_id},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"entity_domain": "binary_sensor"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"target": [entity.entity_id, other_entity.entity_id]},
    )
    assert result["step_id"] == "reconfigure_alert"
    assert set(result["description_placeholders"]["entity_id"].split(", ")) == {
        entity.entity_id,
        other_entity.entity_id,
    }

    state_selector = next(
        selector
        for key, selector in result["data_schema"].schema.items()
        if getattr(key, "schema", None) == CONF_ALERT_STATE
    )
    assert state_selector.config["entity_id"] in {
        entity.entity_id,
        other_entity.entity_id,
    }
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**VALID_INPUT, "name": "Updated"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert entry.subentries[subentry_id].data[CONF_ENTITY_ID] in {
        entity.entity_id,
        other_entity.entity_id,
    }
    assert set(entry.subentries[subentry_id].data["entity_ids"]) == {
        entity.entity_id,
        other_entity.entity_id,
    }


async def test_reconfigure_clears_optional_field(hass: HomeAssistant) -> None:
    """Removing an optional template on edit actually clears it."""
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
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"entity_domain": "binary_sensor"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"target": ["binary_sensor.x"]}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**VALID_INPUT, "name": "Old"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert "message" not in entry.subentries[subentry_id].data
