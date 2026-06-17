"""Alert entity for the Alerts Assistant integration.

The behaviour mirrors the built-in `alert` integration: watch an entity, and while
it sits in a configured state, repeatedly fire notifications until the alert is
acknowledged or the watched entity leaves that state.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.const import STATE_IDLE, STATE_OFF, STATE_ON
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
)
from homeassistant.helpers.template import Template
from homeassistant.util.dt import now

from .const import (
    ACK_ACTION_PREFIX,
    ACK_ACTION_TITLE,
    EVENT_MOBILE_APP_NOTIFICATION_ACTION,
    LOGGER,
    NOTIFY_DOMAIN,
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
    ) -> None:
        """Initialise the alert."""
        self.hass = hass
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._watched_entity_id = watched_entity_id
        self._alert_state = state
        self._skip_first = skip_first
        self._data = data
        self._message_template = message_template
        self._done_message_template = done_message_template
        self._title_template = title_template
        self._notifiers = notifiers
        self._can_ack = can_ack
        # Identifier embedded in the mobile_app notification action button.
        self._ack_action = ack_action
        self._ack_action_id = f"{ACK_ACTION_PREFIX}{unique_id}"

        self._delay = [timedelta(minutes=val) for val in repeat]
        self._next_delay = 0
        self._firing = False
        self._ack = False
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
        if state is not None and state.state == self._alert_state:
            await self.begin_alerting()

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

    async def watched_entity_change(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """React to the watched entity changing state."""
        new_state = event.data["new_state"]
        if new_state is None:
            return
        if new_state.state == self._alert_state and not self._firing:
            await self.begin_alerting()
        elif new_state.state != self._alert_state and self._firing:
            await self.end_alerting()

    async def begin_alerting(self) -> None:
        """Begin the alert procedure."""
        LOGGER.debug("Beginning alert: %s", self.name)
        self._ack = False
        self._firing = True
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
                    message = self._message_template.async_render(parse_result=False)
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
            message = self._done_message_template.async_render(parse_result=False)
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
                parse_result=False
            )

        data: dict[str, Any] = dict(self._data) if self._data else {}
        if include_ack and self._ack_action and self._can_ack:
            actions = list(data.get(ATTR_ACTIONS, []))
            actions.append(
                {ATTR_ACTION: self._ack_action_id, "title": ACK_ACTION_TITLE}
            )
            data[ATTR_ACTIONS] = actions
        if data:
            msg_payload[ATTR_DATA] = data

        for target in self._notifiers:
            await self.hass.services.async_call(
                NOTIFY_DOMAIN, target, dict(msg_payload), context=self._context
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
def build_alert(
    hass: HomeAssistant, unique_id: str, config: dict[str, Any]
) -> Alert:
    """Construct an :class:`Alert` from subentry config data."""
    from .const import (
        CONF_ACK_ACTION,
        CONF_ALERT_STATE,
        CONF_CAN_ACK,
        CONF_DATA,
        CONF_DONE_MESSAGE,
        CONF_ENTITY_ID,
        CONF_MESSAGE,
        CONF_NAME,
        CONF_NOTIFIERS,
        CONF_REPEAT,
        CONF_SKIP_FIRST,
        CONF_TITLE,
        DEFAULT_ACK_ACTION,
        DEFAULT_ALERT_STATE,
        DEFAULT_CAN_ACK,
        DEFAULT_REPEAT,
        DEFAULT_SKIP_FIRST,
    )

    def _template(value: str | None) -> Template | None:
        if value is None or value == "":
            return None
        return Template(value, hass)

    alert = Alert(
        hass=hass,
        unique_id=unique_id,
        name=config[CONF_NAME],
        watched_entity_id=config[CONF_ENTITY_ID],
        state=config.get(CONF_ALERT_STATE, DEFAULT_ALERT_STATE),
        repeat=config.get(CONF_REPEAT, DEFAULT_REPEAT),
        skip_first=config.get(CONF_SKIP_FIRST, DEFAULT_SKIP_FIRST),
        message_template=_template(config.get(CONF_MESSAGE)),
        done_message_template=_template(config.get(CONF_DONE_MESSAGE)),
        notifiers=config.get(CONF_NOTIFIERS, []),
        can_ack=config.get(CONF_CAN_ACK, DEFAULT_CAN_ACK),
        title_template=_template(config.get(CONF_TITLE)),
        data=config.get(CONF_DATA),
        ack_action=config.get(CONF_ACK_ACTION, DEFAULT_ACK_ACTION),
    )
    alert.source_config = dict(config)
    return alert
