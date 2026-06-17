"""Config and subentry flows for Alerts Assistant."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
import voluptuous as vol

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
    DEFAULT_SKIP_FIRST,
    DOMAIN,
    NOTIFY_DOMAIN,
    SUBENTRY_TYPE_ALERT,
)

TEMPLATE_FIELDS = (CONF_TITLE, CONF_MESSAGE, CONF_DONE_MESSAGE)

DEFAULT_REPEAT_TEXT = "30"


def _parse_repeat(value: str) -> list[float]:
    """Parse a comma-separated list of minutes into floats.

    Raises ValueError if any entry is not a positive number, or the list is empty.
    """
    parts = [part.strip() for part in str(value).split(",") if part.strip()]
    if not parts:
        raise ValueError("empty")
    result = [float(part) for part in parts]
    if any(minutes <= 0 for minutes in result):
        raise ValueError("not_positive")
    return result


def _repeat_to_text(value: Any) -> str:
    """Render a stored repeat list back to an editable text field."""
    if isinstance(value, (list, tuple)):
        return ", ".join(
            str(int(v)) if float(v).is_integer() else str(v) for v in value
        )
    return str(value)


def _alert_schema(notify_options: list[str]) -> vol.Schema:
    """Build the add/edit schema for a single alert."""
    return vol.Schema(
        {
            vol.Required(CONF_NAME): selector.TextSelector(),
            vol.Required(CONF_ENTITY_ID): selector.EntitySelector(),
            vol.Required(
                CONF_ALERT_STATE, default=DEFAULT_ALERT_STATE
            ): selector.TextSelector(),
            vol.Required(CONF_NOTIFIERS): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=notify_options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_REPEAT, default=DEFAULT_REPEAT_TEXT
            ): selector.TextSelector(),
            vol.Required(
                CONF_CAN_ACK, default=DEFAULT_CAN_ACK
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_ACK_ACTION, default=DEFAULT_ACK_ACTION
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_SKIP_FIRST, default=DEFAULT_SKIP_FIRST
            ): selector.BooleanSelector(),
            vol.Optional(CONF_TITLE): selector.TemplateSelector(),
            vol.Optional(CONF_MESSAGE): selector.TemplateSelector(),
            vol.Optional(CONF_DONE_MESSAGE): selector.TemplateSelector(),
            vol.Optional(CONF_DATA): selector.ObjectSelector(),
        }
    )


class AlertsAssistantConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the (single-instance) hub config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the single hub entry."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is None:
            return self.async_show_form(step_id="user")
        return self.async_create_entry(title="Alerts Assistant", data={})

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Alerts are added as subentries of the hub."""
        return {SUBENTRY_TYPE_ALERT: AlertSubentryFlowHandler}


class AlertSubentryFlowHandler(ConfigSubentryFlow):
    """Add and reconfigure individual alerts."""

    def _notify_services(self) -> list[str]:
        return sorted(self.hass.services.async_services().get(NOTIFY_DOMAIN, {}))

    def _validate(
        self, user_input: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, dict[str, str]]:
        """Validate input, returning (cleaned_data, errors).

        Notifier membership and template syntax are already enforced by the
        Select/Template selectors at schema level, so only the free-text
        `repeat` field and an empty notifier list need checking here.
        """
        errors: dict[str, str] = {}
        data = dict(user_input)

        try:
            data[CONF_REPEAT] = _parse_repeat(user_input[CONF_REPEAT])
        except ValueError:
            errors[CONF_REPEAT] = "invalid_repeat"

        if not user_input.get(CONF_NOTIFIERS):
            errors[CONF_NOTIFIERS] = "no_notifiers"

        if errors:
            return None, errors

        # Drop empty optional fields so they don't linger in stored data.
        for key in (*TEMPLATE_FIELDS, CONF_DATA):
            if not data.get(key):
                data.pop(key, None)
        return data, errors

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a new alert."""
        options = self._notify_services()
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = self._validate(user_input)
            if data is not None:
                return self.async_create_entry(title=data[CONF_NAME], data=data)
        schema = _alert_schema(options)
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit an existing alert."""
        subentry = self._get_reconfigure_subentry()
        # Keep already-selected notifiers selectable even if the service is
        # momentarily unregistered.
        options = sorted(
            set(self._notify_services()) | set(subentry.data.get(CONF_NOTIFIERS, []))
        )
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = self._validate(user_input)
            if data is not None:
                # Replace data wholesale (data= not data_updates=) so cleared
                # optional fields are actually removed. The entry's update
                # listener then reconciles entities (no reload needed here).
                return self.async_update_and_abort(
                    self._get_entry(),
                    subentry,
                    title=data[CONF_NAME],
                    data=data,
                )
            suggested = user_input
        else:
            suggested = {
                **subentry.data,
                CONF_REPEAT: _repeat_to_text(subentry.data.get(CONF_REPEAT, "")),
            }
        schema = self.add_suggested_values_to_schema(
            _alert_schema(options), suggested
        )
        return self.async_show_form(
            step_id="reconfigure", data_schema=schema, errors=errors
        )
