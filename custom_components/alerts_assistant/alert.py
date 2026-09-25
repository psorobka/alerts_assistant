"""Alert entity for the Alerts Assistant integration.

The behaviour mirrors the built-in `alert` integration: watch an entity, and while
it sits in a configured state, repeatedly fire notifications until the alert is
acknowledged or the watched entity leaves that state.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
import math
from typing import Any

from homeassistant.const import STATE_IDLE, STATE_OFF, STATE_ON
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
)
from homeassistant.helpers.template import Template
from homeassistant.helpers.translation import async_get_translations
from homeassistant.util.dt import now

from .const import (
    ACK_ACTION_PREFIX,
    ACK_ACTION_TITLE,
    CONF_ACK_ACTION,
    CONF_ALERT_STATE,
    CONF_CAN_ACK,
    CONF_DATA,
    CONF_DONE_MESSAGE,
    CONF_ENTITY_ID,
    CONF_ENTITY_IDS,
    CONF_LABEL_IDS,
    CONF_MESSAGE,
    CONF_MISSING_ENTITY_IDS,
    CONF_MISSING_LABEL_IDS,
    CONF_NAME,
    CONF_NOTIFIERS,
    CONF_NUMERIC_COMPARATOR,
    CONF_NUMERIC_THRESHOLD,
    CONF_REPEAT,
    CONF_SENSOR_MODE,
    CONF_SKIP_FIRST,
    CONF_TEXT_STATE,
    CONF_TITLE,
    DEFAULT_ACK_ACTION,
    DEFAULT_ALERT_STATE,
    DEFAULT_CAN_ACK,
    DEFAULT_REPEAT,
    DEFAULT_SKIP_FIRST,
    DOMAIN,
    EVENT_MOBILE_APP_NOTIFICATION_ACTION,
    LOGGER,
    NOTIFY_DOMAIN,
    RESOLVED_ENTITY_IDS,
)

# notify service payload keys (kept local to avoid importing the notify component).
ATTR_MESSAGE = "message"
ATTR_TITLE = "title"
ATTR_DATA = "data"
ATTR_ACTIONS = "actions"
ATTR_ACTION = "action"


class Alert(Entity):
    """Representation of a single configurable alert."""

    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        unique_id: str,
        name: str,
        watched_entity_id: str,
        state: str,
        repeat: list[float],
        skip_first: bool,
        message_template: Template | None,
        done_message_template: Template | None,
        notifiers: list[str],
        can_ack: bool,
        title_template: Template | None,
        data: dict[str, Any] | None,
        ack_action: bool,
        template_variables: dict[str, Any] | None = None,
        numeric_comparator: str | None = None,
        numeric_threshold: float | None = None,
        sensor_mode: str | None = None,
        text_state: str | None = None,
    ) -> None:
        """Initialise the alert."""
        self.hass = hass
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._watched_entity_id = watched_entity_id
        self._alert_state = state
        self._numeric_comparator = numeric_comparator
        self._numeric_threshold = numeric_threshold
        self._sensor_mode = sensor_mode or (
            "numeric" if numeric_comparator is not None else None
        )
        self._text_state = text_state
        self._skip_first = skip_first
        self._data = data
        self._message_template = message_template
        self._done_message_template = done_message_template
        self._title_template = title_template
        self._notifiers = notifiers
        self._can_ack = can_ack
        # Identifier embedded in the mobile_app notification action button.
        self._ack_action = ack_action
        self._template_variables = template_variables or {}
        self._ack_action_id = f"{ACK_ACTION_PREFIX}{unique_id}"

        self._delay = [timedelta(minutes=val) for val in repeat]
        self._next_delay = 0
        self._firing = False
        self._ack = False
        self._triggered_at = None
        self._cancel: Callable[[], None] | None = None
        self._send_done_message = False
        # Snapshot of the subentry data this alert was built from, used to detect
        # which alerts actually changed when subentries are reconciled.
        self.source_config: dict[str, Any] = {}

    async def async_added_to_hass(self) -> None:
        """Subscribe to watched entity changes once registered."""
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._watched_entity_id], self.watched_entity_change
            )
        )
        # Listen for taps on this alert's "Acknowledge" notification button.
        if self._ack_action and self._can_ack:
            self.async_on_remove(
                self.hass.bus.async_listen(
                    EVENT_MOBILE_APP_NOTIFICATION_ACTION,
                    self._handle_notification_action,
                )
            )
        # Pick up an already-matching state at startup.
        state = self.hass.states.get(self._watched_entity_id)
        if state is not None and self._matches_alert(state.state) is True:
            await self.begin_alerting()

    def _matches_alert(self, value: str) -> bool | None:
        """Return whether the entity satisfies this alert's trigger condition."""
        if self._sensor_mode == "text":
            if value in ("unknown", "unavailable"):
                return None
            return value == self._text_state
        if self._numeric_comparator is None or self._numeric_threshold is None:
            return value == self._alert_state
        if value in ("unknown", "unavailable"):
            return None
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(numeric_value):
            return False
        if self._numeric_comparator == "below":
            return numeric_value < self._numeric_threshold
        return numeric_value > self._numeric_threshold

    async def _handle_notification_action(self, event: Event) -> None:
        """Acknowledge when this alert's notification action is tapped."""
        if event.data.get(ATTR_ACTION) != self._ack_action_id:
            return
        if self._firing and not self._ack:
            await self.async_turn_off()

    async def async_will_remove_from_hass(self) -> None:
        """Cancel any pending notification when the entity is removed."""
        if self._cancel is not None:
            self._cancel()
            self._cancel = None

    @property
    def state(self) -> str:
        """Return the alert state: on (firing), off (acknowledged) or idle."""
        if self._firing:
            return STATE_OFF if self._ack else STATE_ON
        return STATE_IDLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the watched entity and stable alert start time in Home Assistant."""
        attributes: dict[str, Any] = {
            "watched_entity": self._watched_entity_id,
        }
        if area := self._template_variables.get("area"):
            attributes["area"] = area
        if self._firing:
            attributes["acknowledged"] = self._ack
            if self._triggered_at is not None:
                attributes["triggered_at"] = self._triggered_at.isoformat()
        return attributes

    async def watched_entity_change(self, event: Event[EventStateChangedData]) -> None:
        """React to the watched entity changing state."""
        new_state = event.data["new_state"]
        if new_state is None:
            return
        matches = self._matches_alert(new_state.state)
        if matches is True and not self._firing:
            await self.begin_alerting()
        elif matches is False and self._firing:
            await self.end_alerting()

    async def begin_alerting(self) -> None:
        """Begin the alert procedure."""
        LOGGER.debug("Beginning alert: %s", self.name)
        self._ack = False
        self._firing = True
        self._triggered_at = now()
        self._next_delay = 0
        if not self._skip_first:
            await self._notify()
        else:
            await self._schedule_notify()
        self.async_write_ha_state()

    async def end_alerting(self) -> None:
        """End the alert procedure."""
        LOGGER.debug("Ending alert: %s", self.name)
        if self._cancel is not None:
            self._cancel()
            self._cancel = None
        self._ack = False
        self._firing = False
        if self._send_done_message:
            await self._notify_done_message()
        self._triggered_at = None
        self.async_write_ha_state()

    async def _schedule_notify(self) -> None:
        """Schedule the next notification."""
        delay = self._delay[self._next_delay]
        next_msg = now() + delay
        self._cancel = async_track_point_in_time(self.hass, self._notify, next_msg)
        self._next_delay = min(self._next_delay + 1, len(self._delay) - 1)

    async def _notify(self, *args: Any) -> None:
        """Send the alert notification and schedule the next one.

        Notification errors are caught so a single failing notify service (or a
        bad template) never stops the repeat loop or leaves the alert stuck.
        """
        if not self._firing:
            return
        if not self._ack:
            LOGGER.info("Alerting: %s", self.name)
            self._send_done_message = True
            try:
                if self._message_template is not None:
                    message = self._message_template.async_render(
                        parse_result=False, variables=self._template_variables
                    )
                else:
                    message = self.name
                await self._send_notification_message(message, include_ack=True)
            except Exception:  # noqa: BLE001 - never break the repeat loop
                LOGGER.exception("Error notifying alert %s", self.name)
        await self._schedule_notify()

    async def _notify_done_message(self) -> None:
        """Send the optional "all clear" notification."""
        self._send_done_message = False
        if self._done_message_template is None:
            return
        try:
            message = self._done_message_template.async_render(
                parse_result=False, variables=self._template_variables
            )
            await self._send_notification_message(message)
        except Exception:  # noqa: BLE001 - clearing must always complete
            LOGGER.exception("Error sending done message for alert %s", self.name)

    async def _send_notification_message(
        self, message: Any, *, include_ack: bool = False
    ) -> None:
        """Call each configured notify service with the message payload."""
        if not self._notifiers:
            return

        msg_payload: dict[str, Any] = {ATTR_MESSAGE: message}
        if self._title_template is not None:
            msg_payload[ATTR_TITLE] = self._title_template.async_render(
                parse_result=False, variables=self._template_variables
            )

        data: dict[str, Any] = dict(self._data) if self._data else {}
        if include_ack and self._ack_action and self._can_ack:
            actions = list(data.get(ATTR_ACTIONS, []))
            translations = await async_get_translations(
                self.hass, self.hass.config.language, "common", [DOMAIN]
            )
            action_title = translations.get(
                f"component.{DOMAIN}.common.action_acknowledge", ACK_ACTION_TITLE
            )
            actions.append({ATTR_ACTION: self._ack_action_id, "title": action_title})
            data[ATTR_ACTIONS] = actions
        if data:
            msg_payload[ATTR_DATA] = data

        for target in self._notifiers:
            # Notify entities use the generic send_message entity service.
            # Legacy notify services accept the full payload, including custom
            # data and actionable notification buttons.
            if self.hass.states.get(target) is not None:
                entity_payload = {
                    key: value
                    for key, value in msg_payload.items()
                    if key in (ATTR_MESSAGE, ATTR_TITLE)
                }
                await self.hass.services.async_call(
                    NOTIFY_DOMAIN,
                    "send_message",
                    {"entity_id": target, **entity_payload},
                    context=self._context,
                )
                continue

            service = target.removeprefix(f"{NOTIFY_DOMAIN}.")
            await self.hass.services.async_call(
                NOTIFY_DOMAIN, service, dict(msg_payload), context=self._context
            )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Unacknowledge the alert (re-arm notifications)."""
        LOGGER.debug("Reset alert: %s", self.name)
        self._ack = False
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Acknowledge the alert, silencing further notifications."""
        LOGGER.debug("Acknowledged alert: %s", self.name)
        if self._can_ack:
            self._ack = True
        self.async_write_ha_state()

    async def async_toggle(self, **kwargs: Any) -> None:
        """Toggle acknowledged state."""
        if self._ack:
            await self.async_turn_on()
        else:
            await self.async_turn_off()


@callback
def build_alerts(
    hass: HomeAssistant, unique_id: str, config: dict[str, Any]
) -> list[Alert]:
    """Construct one independent alert entity for each monitored entity."""

    def _template(value: str | None) -> Template | None:
        if value is None or value == "":
            return None
        return Template(value, hass)

    entity_ids = list(
        dict.fromkeys(
            config.get(
                RESOLVED_ENTITY_IDS,
                config.get(CONF_ENTITY_IDS, [config.get(CONF_ENTITY_ID)]),
            )
        )
    )
    entity_ids = [entity_id for entity_id in entity_ids if entity_id]
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    area_reg = ar.async_get(hass)
    alerts = []
    for entity_id in entity_ids:
        state_obj = hass.states.get(entity_id)
        entity_name = (
            state_obj.attributes.get("friendly_name", entity_id)
            if state_obj
            else entity_id
        )
        registry_entry = ent_reg.async_get(entity_id)
        area_id = registry_entry.area_id if registry_entry else None
        if not area_id and registry_entry and registry_entry.device_id:
            device = dev_reg.async_get(registry_entry.device_id)
            area_id = device.area_id if device else None
        area = area_reg.async_get_area(area_id) if area_id else None
        area_name = area.name if area else ""
        display_name = config[CONF_NAME]
        grouped = len(entity_ids) > 1 or bool(config.get(CONF_LABEL_IDS))
        if grouped:
            display_name = f"{display_name} - {area_name or entity_name}"
        stable_id = f"{unique_id}_{entity_id}" if grouped else unique_id
        alert = Alert(
            hass=hass,
            unique_id=stable_id,
            name=display_name,
            watched_entity_id=entity_id,
            state=config.get(CONF_ALERT_STATE, DEFAULT_ALERT_STATE),
            numeric_comparator=config.get(CONF_NUMERIC_COMPARATOR),
            numeric_threshold=config.get(CONF_NUMERIC_THRESHOLD),
            sensor_mode=config.get(CONF_SENSOR_MODE),
            text_state=config.get(CONF_TEXT_STATE),
            repeat=config.get(CONF_REPEAT, DEFAULT_REPEAT),
            skip_first=config.get(CONF_SKIP_FIRST, DEFAULT_SKIP_FIRST),
            message_template=_template(config.get(CONF_MESSAGE)),
            done_message_template=_template(config.get(CONF_DONE_MESSAGE)),
            notifiers=config.get(CONF_NOTIFIERS, []),
            can_ack=config.get(CONF_CAN_ACK, DEFAULT_CAN_ACK),
            title_template=_template(config.get(CONF_TITLE)),
            data=config.get(CONF_DATA),
            ack_action=config.get(CONF_ACK_ACTION, DEFAULT_ACK_ACTION),
            template_variables={
                "entity_id": entity_id,
                "entity_name": entity_name,
                "area": area_name,
            },
        )
        alert.source_config = {
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
        alerts.append(alert)
    return alerts
