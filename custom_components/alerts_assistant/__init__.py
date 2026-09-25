"""The Alerts Assistant integration.

A UI-configurable re-implementation of the built-in `alert` integration. A single
hub config entry holds any number of alert subentries; each subentry becomes an
`alerts_assistant.*` entity with idle/on/off states and turn_on/turn_off/toggle
services (turn_off acknowledges, like the built-in alert).
"""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SERVICE_TOGGLE, SERVICE_TURN_OFF, SERVICE_TURN_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers import label_registry as lr
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.helpers.typing import ConfigType

from .alert import Alert, build_alerts
from .const import (
    CONF_DEVICE_CLASS,
    CONF_ENTITY_DOMAIN,
    CONF_ENTITY_ID,
    CONF_ENTITY_IDS,
    CONF_LABEL_IDS,
    CONF_MISSING_ENTITY_IDS,
    CONF_MISSING_LABEL_IDS,
    CONF_NAME,
    DOMAIN,
    LOGGER,
    RESOLVED_ENTITY_IDS,
    SUBENTRY_TYPE_ALERT,
)
from .sensor_utils import sensor_state_matches_mode

# This integration is configured from config entries only (no YAML).
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
CARD_URL = "/alerts_assistant/alerts-assistant-card.js"

# runtime_data maps subentry_id -> independently running alert entities.
type AlertsAssistantConfigEntry = ConfigEntry[dict[str, list[Alert]]]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up frontend card, entity component and acknowledge services."""
    # HTTP is absent in Home Assistant's isolated component test harnesses.
    # In a normal HA instance this serves and automatically loads the card.
    if hass.http is not None and "frontend" in hass.config.components:
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    CARD_URL,
                    str(Path(__file__).parent / "www" / "alerts-assistant-card.js"),
                    cache_headers=False,
                )
            ]
        )
        add_extra_js_url(hass, CARD_URL)

    component: EntityComponent[Alert] = EntityComponent(LOGGER, DOMAIN, hass)
    hass.data[DOMAIN] = component

    component.async_register_entity_service(SERVICE_TURN_OFF, None, "async_turn_off")
    component.async_register_entity_service(SERVICE_TURN_ON, None, "async_turn_on")
    component.async_register_entity_service(SERVICE_TOGGLE, None, "async_toggle")
    return True


def _desired_alerts(
    hass: HomeAssistant,
    entry: AlertsAssistantConfigEntry,
    excluded_entity_ids: set[str] | None = None,
) -> dict[str, dict]:
    """Return alert configs with current members resolved from selected labels."""
    registry = er.async_get(hass)
    return {
        subentry_id: _resolve_members(
            dict(subentry.data), registry, hass, excluded_entity_ids or set()
        )
        for subentry_id, subentry in entry.subentries.items()
        if subentry.subentry_type == SUBENTRY_TYPE_ALERT
    }


def _resolve_members(
    config: dict,
    registry: er.EntityRegistry,
    hass: HomeAssistant,
    excluded_entity_ids: set[str],
) -> dict:
    """Expand label membership while retaining explicitly selected entities."""
    entity_ids = set(config.get(CONF_ENTITY_IDS, [])) - excluded_entity_ids
    if config.get(CONF_ENTITY_ID):
        entity_id = config[CONF_ENTITY_ID]
        if entity_id not in excluded_entity_ids:
            entity_ids.add(entity_id)
    label_registry = lr.async_get(hass)
    labels = {
        label_id
        for label_id in config.get(CONF_LABEL_IDS, [])
        if label_registry.async_get_label(label_id) is not None
    }
    device_class = config.get(CONF_DEVICE_CLASS)
    if device_class:
        entity_ids = {
            entity_id
            for entity_id in entity_ids
            if _entity_matches_device_class(hass, registry, entity_id, device_class)
        }
    if labels:
        sensor_mode = config.get("sensor_mode")
        entity_ids.update(
            entity.entity_id
            for entity in registry.entities.values()
            if (
                labels.intersection(entity.labels)
                and entity.disabled_by is None
                and entity.entity_id.startswith(
                    f"{config.get(CONF_ENTITY_DOMAIN, 'binary_sensor')}."
                )
                and _entity_matches_device_class(
                    hass, registry, entity.entity_id, device_class
                )
                and _label_member_matches_mode(
                    hass, entity.entity_id, sensor_mode, config
                )
            )
        )
    result = dict(config)
    result[RESOLVED_ENTITY_IDS] = sorted(entity_ids)
    return result


def _entity_matches_device_class(
    hass: HomeAssistant,
    registry: er.EntityRegistry,
    entity_id: str,
    device_class: str | None,
) -> bool:
    """Match class metadata from the registry or the current entity state."""
    if device_class is None:
        return True
    entry = registry.async_get(entity_id)
    if entry and entry.device_class:
        return entry.device_class == device_class
    state = hass.states.get(entity_id)
    return bool(state and state.attributes.get("device_class") == device_class)


def _label_member_matches_mode(
    hass: HomeAssistant,
    entity_id: str,
    sensor_mode: str | None,
    config: dict,
) -> bool:
    """Keep label additions aligned with numeric/text sensor mode when possible."""
    if config.get(CONF_ENTITY_DOMAIN) != "sensor" or sensor_mode not in (
        "numeric",
        "text",
    ):
        return True
    state_obj = hass.states.get(entity_id)
    return sensor_state_matches_mode(state_obj, sensor_mode)


async def async_setup_entry(
    hass: HomeAssistant, entry: AlertsAssistantConfigEntry
) -> bool:
    """Set up alert entities from the hub entry's subentries."""
    label_registry = lr.async_get(hass)
    for subentry in entry.subentries.values():
        data = dict(subentry.data)
        labels = data.get(CONF_LABEL_IDS, [])
        missing_labels = [
            label_id
            for label_id in labels
            if label_registry.async_get_label(label_id) is None
        ]
        if missing_labels:
            data[CONF_LABEL_IDS] = [
                label_id for label_id in labels if label_id not in missing_labels
            ]
            if not data[CONF_LABEL_IDS]:
                data.pop(CONF_LABEL_IDS)
            data[CONF_MISSING_LABEL_IDS] = sorted(
                set(data.get(CONF_MISSING_LABEL_IDS, [])) | set(missing_labels)
            )
            hass.config_entries.async_update_subentry(entry, subentry, data=data)

    component: EntityComponent[Alert] = hass.data[DOMAIN]
    entry.runtime_data = {}

    entities = []
    for subentry_id, config in _desired_alerts(hass, entry).items():
        alerts = build_alerts(hass, subentry_id, config)
        entry.runtime_data[subentry_id] = alerts
        entities.extend(alerts)
    await component.async_add_entities(entities)

    # Reconcile entities on any subentry add/edit/delete, instead of reloading
    # the whole entry (which would re-notify and un-acknowledge every alert).
    entry.async_on_unload(entry.add_update_listener(_async_reconcile))

    async def _entity_registry_changed(event) -> None:
        """Refresh alerts when entities are removed or their labels change."""
        entity_id = event.data.get("entity_id", "")
        if entity_id.startswith(f"{DOMAIN}."):
            return
        if event.data.get("action") == "remove":
            for subentry in entry.subentries.values():
                data = dict(subentry.data)
                changed = False
                explicit_ids = set(data.get(CONF_ENTITY_IDS, []))
                if data.get(CONF_ENTITY_ID):
                    explicit_ids.add(data[CONF_ENTITY_ID])
                if entity_id in explicit_ids:
                    missing = set(data.get(CONF_MISSING_ENTITY_IDS, []))
                    missing.add(entity_id)
                    data[CONF_MISSING_ENTITY_IDS] = sorted(missing)
                    changed = True
                if data.get(CONF_ENTITY_ID) == entity_id:
                    data.pop(CONF_ENTITY_ID)
                    changed = True
                if CONF_ENTITY_IDS in data:
                    entity_ids = [
                        selected_id
                        for selected_id in data[CONF_ENTITY_IDS]
                        if selected_id != entity_id
                    ]
                    if entity_ids != data[CONF_ENTITY_IDS]:
                        changed = True
                        if entity_ids:
                            data[CONF_ENTITY_IDS] = entity_ids
                        else:
                            data.pop(CONF_ENTITY_IDS)
                if changed:
                    hass.config_entries.async_update_subentry(
                        entry, subentry, data=data
                    )
        await _async_reconcile(
            hass,
            entry,
            excluded_entity_ids=(
                {entity_id} if event.data.get("action") == "remove" else set()
            ),
        )

    entry.async_on_unload(
        hass.bus.async_listen("entity_registry_updated", _entity_registry_changed)
    )

    async def _label_registry_changed(event) -> None:
        """Refresh alerts when a referenced label is deleted."""
        if event.data.get("action") != "remove":
            return
        label_id = event.data.get("label_id")
        for subentry in entry.subentries.values():
            data = dict(subentry.data)
            labels = [item for item in data.get(CONF_LABEL_IDS, []) if item != label_id]
            if labels != data.get(CONF_LABEL_IDS, []):
                missing = set(data.get(CONF_MISSING_LABEL_IDS, []))
                missing.add(label_id)
                data[CONF_MISSING_LABEL_IDS] = sorted(missing)
                if labels:
                    data[CONF_LABEL_IDS] = labels
                else:
                    data.pop(CONF_LABEL_IDS)
                hass.config_entries.async_update_subentry(entry, subentry, data=data)
        await _async_reconcile(hass, entry)

    entry.async_on_unload(
        hass.bus.async_listen(lr.EVENT_LABEL_REGISTRY_UPDATED, _label_registry_changed)
    )
    await _async_reconcile(hass, entry)
    return True


async def _async_reconcile(
    hass: HomeAssistant,
    entry: AlertsAssistantConfigEntry,
    excluded_entity_ids: set[str] | None = None,
) -> None:
    """Add/remove/replace only the alerts whose subentries changed."""
    component: EntityComponent[Alert] = hass.data[DOMAIN]
    live = entry.runtime_data
    desired = _desired_alerts(hass, entry, excluded_entity_ids)
    ent_reg = er.async_get(hass)

    new_entities = []
    for subentry_id, config in desired.items():
        alerts = live.get(subentry_id, [])
        logical_config = {
            key: value
            for key, value in config.items()
            if key
            not in (
                RESOLVED_ENTITY_IDS,
                CONF_ENTITY_ID,
                CONF_ENTITY_IDS,
                CONF_LABEL_IDS,
                CONF_MISSING_ENTITY_IDS,
                CONF_MISSING_LABEL_IDS,
            )
        }
        if alerts and alerts[0].source_config != logical_config:
            for alert in alerts:
                await alert.async_remove()
            alerts = []

        wanted_ids = set(config[RESOLVED_ENTITY_IDS])
        retained = []
        for alert in alerts:
            if alert._watched_entity_id in wanted_ids:
                retained.append(alert)
                continue
            entity_id = alert.entity_id
            await alert.async_remove()
            if entity_id and ent_reg.async_get(entity_id) is not None:
                ent_reg.async_remove(entity_id)

        existing_ids = {alert._watched_entity_id for alert in retained}
        missing_ids = wanted_ids - existing_ids
        if missing_ids:
            member_config = {
                **config,
                RESOLVED_ENTITY_IDS: sorted(missing_ids),
            }
            created = build_alerts(hass, subentry_id, member_config)
            retained.extend(created)
            new_entities.extend(created)
        live[subentry_id] = retained

        issue_id = f"no_entities_{subentry_id}"
        missing_targets = config.get(CONF_MISSING_ENTITY_IDS) or config.get(
            CONF_MISSING_LABEL_IDS
        )
        if wanted_ids and not missing_targets:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
        else:
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="no_entities",
                translation_placeholders={
                    "alert_name": config.get(CONF_NAME, subentry_id),
                    "missing_targets": ", ".join(
                        [
                            *config.get(CONF_MISSING_ENTITY_IDS, []),
                            *config.get(CONF_MISSING_LABEL_IDS, []),
                        ]
                    )
                    or (
                        "brak pasujących encji"
                        if hass.config.language == "pl"
                        else "no matching entities"
                    ),
                },
            )

    # Remove subentries that were deleted.
    for subentry_id in live.keys() - desired.keys():
        for alert in live.pop(subentry_id):
            entity_id = alert.entity_id
            await alert.async_remove()
            if entity_id and ent_reg.async_get(entity_id) is not None:
                ent_reg.async_remove(entity_id)
        ir.async_delete_issue(hass, DOMAIN, f"no_entities_{subentry_id}")
    if new_entities:
        await component.async_add_entities(new_entities)


async def async_unload_entry(
    hass: HomeAssistant, entry: AlertsAssistantConfigEntry
) -> bool:
    """Remove alert entities from state, keeping their registry entries."""
    for alerts in list(getattr(entry, "runtime_data", {}).values()):
        for alert in alerts:
            await alert.async_remove()
    entry.runtime_data = {}
    return True


async def async_remove_entry(
    hass: HomeAssistant, entry: AlertsAssistantConfigEntry
) -> None:
    """Purge all alert registry entries when the integration is removed."""
    ent_reg = er.async_get(hass)
    for entity_id, reg_entry in list(ent_reg.entities.items()):
        if reg_entry.platform == DOMAIN:
            ent_reg.async_remove(entity_id)
    issue_registry = ir.async_get(hass)
    for issue_domain, issue_id in list(issue_registry.issues):
        if issue_domain == DOMAIN and issue_id.startswith("no_entities_"):
            ir.async_delete_issue(hass, DOMAIN, issue_id)
