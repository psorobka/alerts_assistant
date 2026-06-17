"""Constants for the Alerts Assistant integration."""

from __future__ import annotations

import logging

DOMAIN = "alerts_assistant"
LOGGER = logging.getLogger(__package__)

# Subentry type for a single alert.
SUBENTRY_TYPE_ALERT = "alert"

# Configuration keys (per-alert subentry data).
CONF_NAME = "name"
CONF_ENTITY_ID = "entity_id"
CONF_ALERT_STATE = "state"
CONF_REPEAT = "repeat"
CONF_CAN_ACK = "can_acknowledge"
CONF_SKIP_FIRST = "skip_first"
CONF_NOTIFIERS = "notifiers"
CONF_MESSAGE = "message"
CONF_DONE_MESSAGE = "done_message"
CONF_TITLE = "title"
CONF_DATA = "data"
CONF_ACK_ACTION = "ack_from_notification"

# Defaults mirroring the built-in `alert` integration.
DEFAULT_ALERT_STATE = "on"
DEFAULT_REPEAT = [30.0]
DEFAULT_CAN_ACK = True
DEFAULT_SKIP_FIRST = False
DEFAULT_ACK_ACTION = True

# Notify is a legacy service domain; alerts call `notify.<service>`.
NOTIFY_DOMAIN = "notify"

# Actionable-notification acknowledgement (mobile_app). Each alert exposes an
# action button whose identifier embeds the alert's unique id, and taps arrive
# back on this event.
ACK_ACTION_PREFIX = "ALERTS_ASSISTANT_ACK_"
ACK_ACTION_TITLE = "Acknowledge"
EVENT_MOBILE_APP_NOTIFICATION_ACTION = "mobile_app_notification_action"
