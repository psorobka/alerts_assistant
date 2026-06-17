"""The Alerts Assistant integration.

A UI-configurable re-implementation of the built-in `alert` integration. A single
hub config entry holds any number of alert subentries; each subentry becomes an
`alerts_assistant.*` entity with idle/on/off states and turn_on/turn_off/toggle
services (turn_off acknowledges, like the built-in alert).
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SERVICE_TOGGLE, SERVICE_TURN_OFF, SERVICE_TURN_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.helpers.typing import ConfigType

from .alert import Alert, build_alert
from .const import DOMAIN, LOGGER, SUBENTRY_TYPE_ALERT

# runtime_data maps subentry_id -> live Alert entity.
type AlertsAssistantConfigEntry = ConfigEntry[dict[str, Alert]]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the entity component and acknowledge services."""
    component: EntityComponent[Alert] = EntityComponent(LOGGER, DOMAIN, hass)
    hass.data[DOMAIN] = component

    component.async_register_entity_service(SERVICE_TURN_OFF, None, "async_turn_off")
    component.async_register_entity_service(SERVICE_TURN_ON, None, "async_turn_on")
    component.async_register_entity_service(SERVICE_TOGGLE, None, "async_toggle")
    return True


def _desired_alerts(entry: AlertsAssistantConfigEntry) -> dict[str, dict]:
    """Return {subentry_id: config} for every alert subentry."""
    return {
        subentry_id: dict(subentry.data)
        for subentry_id, subentry in entry.subentries.items()
        if subentry.subentry_type == SUBENTRY_TYPE_ALERT
    }


async def async_setup_entry(
    hass: HomeAssistant, entry: AlertsAssistantConfigEntry
) -> bool:
    """Set up alert entities from the hub entry's subentries."""
    component: EntityComponent[Alert] = hass.data[DOMAIN]
    entry.runtime_data = {}

    entities = []
    for subentry_id, config in _desired_alerts(entry).items():
        alert = build_alert(hass, subentry_id, config)
        entry.runtime_data[subentry_id] = alert
        entities.append(alert)
    await component.async_add_entities(entities)

    # Reconcile entities on any subentry add/edit/delete, instead of reloading
    # the whole entry (which would re-notify and un-acknowledge every alert).
    entry.async_on_unload(entry.add_update_listener(_async_reconcile))
    return True


async def _async_reconcile(
    hass: HomeAssistant, entry: AlertsAssistantConfigEntry
) -> None:
    """Add/remove/replace only the alerts whose subentries changed."""
    component: EntityComponent[Alert] = hass.data[DOMAIN]
    live = entry.runtime_data
    desired = _desired_alerts(entry)
    ent_reg = er.async_get(hass)

    # Remove alerts that were deleted, or replace ones whose config changed.
    for subentry_id in list(live):
        deleted = subentry_id not in desired
        changed = not deleted and live[subentry_id].source_config != desired[subentry_id]
        if not (deleted or changed):
            continue
        alert = live.pop(subentry_id)
        entity_id = alert.entity_id
        await alert.async_remove()
        # Purge the registry entry only on real deletion (not on edits, which
        # reuse the same unique_id and therefore the same entity_id).
        if deleted and entity_id and ent_reg.async_get(entity_id) is not None:
            ent_reg.async_remove(entity_id)

    # Add new alerts and re-add replaced ones.
    new_entities = []
    for subentry_id, config in desired.items():
        if subentry_id in live:
            continue
        alert = build_alert(hass, subentry_id, config)
        live[subentry_id] = alert
        new_entities.append(alert)
    if new_entities:
        await component.async_add_entities(new_entities)


async def async_unload_entry(
    hass: HomeAssistant, entry: AlertsAssistantConfigEntry
) -> bool:
    """Remove alert entities from state, keeping their registry entries."""
    for alert in list(getattr(entry, "runtime_data", {}).values()):
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
