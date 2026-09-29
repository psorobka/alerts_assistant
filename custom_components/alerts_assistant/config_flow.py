"""Config and subentry flows for Alerts Assistant."""

from __future__ import annotations

import math
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector
from homeassistant.helpers.selector import SelectOptionDict
import voluptuous as vol

from .const import (
    CONF_ACK_ACTION,
    CONF_ALERT_STATE,
    CONF_CAN_ACK,
    CONF_DATA,
    CONF_DEVICE_CLASS,
    CONF_DONE_MESSAGE,
    CONF_ENTITY_DOMAIN,
    CONF_ENTITY_ID,
    CONF_ENTITY_IDS,
    CONF_LABEL_IDS,
    CONF_MESSAGE,
    CONF_NAME,
    CONF_NOTIFIERS,
    CONF_NUMERIC_COMPARATOR,
    CONF_NUMERIC_THRESHOLD,
    CONF_REPEAT,
    CONF_SENSOR_MODE,
    CONF_SKIP_FIRST,
    CONF_TEXT_STATE,
    CONF_TITLE,
    CONF_WATCH_LABELS,
    CONF_WATCH_TARGET,
    DEFAULT_ACK_ACTION,
    DEFAULT_ALERT_STATE,
    DEFAULT_CAN_ACK,
    DEFAULT_SKIP_FIRST,
    DOMAIN,
    LOGGER,
    NOTIFY_DOMAIN,
    SUBENTRY_TYPE_ALERT,
)
from .sensor_utils import classify_sensor_state, sensor_state_matches_mode

TEMPLATE_FIELDS = (CONF_TITLE, CONF_MESSAGE, CONF_DONE_MESSAGE)

DEFAULT_REPEAT_TEXT = "30"


def _is_polish(language: str | None) -> bool:
    """Return whether Home Assistant is using Polish, including regional tags."""
    return (language or "").lower().startswith("pl")


def _smart_alert_defaults(
    *,
    language: str,
    sensor_mode: str | None,
    device_class: str | None,
    comparator: str = "below",
) -> dict[str, str]:
    """Suggest an alert name and notification templates for a sensor class."""
    polish = _is_polish(language)
    area = "{% if area %} ({{ area }}){% endif %}"

    def with_area(template: str) -> str:
        return template.replace("{area}", area)

    if sensor_mode == "numeric" and device_class == "battery":
        return {
            CONF_NAME: "Niski poziom baterii" if polish else "Low battery",
            CONF_TITLE: (
                "Niski poziom baterii: {{ entity_name }}"
                if polish
                else "Low battery: {{ entity_name }}"
            ),
            CONF_MESSAGE: with_area(
                "Bateria {{ entity_name }}{area} ma {{ value }} {{ unit }}."
                if polish
                else "Battery {{ entity_name }}{area} is at {{ value }} {{ unit }}."
            ),
            CONF_DONE_MESSAGE: (
                with_area("Poziom baterii {{ entity_name }}{area} wrócił do normy.")
                if polish
                else with_area(
                    "Battery level for {{ entity_name }}{area} is back to normal."
                )
            ),
        }

    if sensor_mode == "numeric" and device_class == "temperature":
        low = comparator == "below"
        if polish:
            title = (
                "Niska temperatura: {{ entity_name }}"
                if low
                else "Wysoka temperatura: {{ entity_name }}"
            )
        else:
            title = (
                "Low temperature: {{ entity_name }}"
                if low
                else "High temperature: {{ entity_name }}"
            )
        return {
            CONF_NAME: (
                ("Niska temperatura" if low else "Wysoka temperatura")
                if polish
                else ("Low temperature" if low else "High temperature")
            ),
            CONF_TITLE: title,
            CONF_MESSAGE: with_area("{{ entity_name }}{area}: {{ value }} {{ unit }}."),
            CONF_DONE_MESSAGE: (
                with_area("Temperatura w {{ entity_name }}{area} wróciła do normy.")
                if polish
                else with_area(
                    "Temperature at {{ entity_name }}{area} is back to normal."
                )
            ),
        }

    if sensor_mode == "text":
        return {
            CONF_NAME: "Zmiana stanu" if polish else "State change",
            CONF_TITLE: (
                "Stan czujnika: {{ entity_name }}"
                if polish
                else "Sensor state: {{ entity_name }}"
            ),
            CONF_MESSAGE: with_area(
                "{{ entity_name }}{area} zgłasza: {{ value }}."
                if polish
                else "{{ entity_name }}{area} reports: {{ value }}."
            ),
            CONF_DONE_MESSAGE: (
                with_area("{{ entity_name }}{area} przestał zgłaszać stan alarmowy.")
                if polish
                else with_area(
                    "{{ entity_name }}{area} is no longer reporting the alert state."
                )
            ),
        }

    if device_class == "moisture":
        return {
            CONF_NAME: "Zalanie" if polish else "Water leak",
            CONF_TITLE: (
                "Wykryto wodę: {{ entity_name }}"
                if polish
                else "Water detected: {{ entity_name }}"
            ),
            CONF_MESSAGE: with_area(
                "Wykryto wodę przy czujniku {{ entity_name }}{area}."
                if polish
                else "Water detected by {{ entity_name }}{area}."
            ),
            CONF_DONE_MESSAGE: (
                with_area("Zalanie ustąpiło przy czujniku {{ entity_name }}{area}.")
                if polish
                else with_area(
                    "The water alert at {{ entity_name }}{area} has cleared."
                )
            ),
        }

    return {
        CONF_NAME: "Alert czujnika" if polish else "Sensor alert",
        CONF_TITLE: (
            "Alert: {{ entity_name }}" if polish else "Alert: {{ entity_name }}"
        ),
        CONF_MESSAGE: with_area(
            "Czujnik {{ entity_name }}{area} zgłosił stan alarmowy ({{ value }})."
            if polish
            else "{{ entity_name }}{area} entered its alert state ({{ value }})."
        ),
        CONF_DONE_MESSAGE: (
            with_area("Alert czujnika {{ entity_name }}{area} ustąpił.")
            if polish
            else with_area("The alert from {{ entity_name }}{area} has cleared.")
        ),
    }


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


def _domain_schema(default: str | None = None, *, language: str = "en") -> vol.Schema:
    """Choose binary, numeric sensor, or text sensor before entity selection."""
    selector_config = selector.SelectSelectorConfig(
        options=[
            SelectOptionDict(
                value="binary_sensor",
                label="Czujnik binarny" if _is_polish(language) else "Binary sensor",
            ),
            SelectOptionDict(
                value="sensor_numeric",
                label="Sensor liczbowy" if _is_polish(language) else "Numeric sensor",
            ),
            SelectOptionDict(
                value="sensor_text",
                label="Sensor tekstowy" if _is_polish(language) else "Text sensor",
            ),
        ],
        mode=selector.SelectSelectorMode.DROPDOWN,
    )
    field = (
        vol.Required(CONF_ENTITY_DOMAIN, default=default)
        if default
        else vol.Required(CONF_ENTITY_DOMAIN)
    )
    return vol.Schema({field: selector.SelectSelector(selector_config)})


def _target_schema(
    domain: str,
    sensor_options: list[SelectOptionDict] | None = None,
) -> vol.Schema:
    """Build an entity picker filtered to the selected entity domain."""
    device_class_selector = getattr(selector, "DeviceClassSelector", None)
    if device_class_selector:
        device_class_field = device_class_selector(
            selector.DeviceClassSelectorConfig(domain=domain)
        )
    else:
        device_classes = (
            BinarySensorDeviceClass if domain == "binary_sensor" else SensorDeviceClass
        )
        device_class_field = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    SelectOptionDict(
                        value=device_class.value,
                        label=device_class.value.replace("_", " ").capitalize(),
                    )
                    for device_class in device_classes
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )
    return vol.Schema(
        {
            vol.Optional(CONF_WATCH_TARGET): (
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=sensor_options,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
                if sensor_options is not None
                else selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=domain, multiple=True)
                )
            ),
            vol.Optional(CONF_WATCH_LABELS): selector.LabelSelector(
                selector.LabelSelectorConfig(multiple=True)
            ),
            vol.Optional(CONF_DEVICE_CLASS): device_class_field,
        }
    )


def _alert_schema(
    notify_options: list[SelectOptionDict],
    entity_id: str | None,
    default_state: str,
    *,
    sensor_mode: str | None = None,
    numeric_comparator: str = "below",
    numeric_threshold: float = 20,
    text_state: str = "",
    language: str = "en",
) -> vol.Schema:
    """Build alert fields appropriate for binary or numeric entities."""
    fields: dict[Any, Any] = {
        vol.Required(CONF_NAME): selector.TextSelector(),
    }
    if sensor_mode == "numeric":
        fields.update(
            {
                vol.Required(
                    CONF_NUMERIC_COMPARATOR,
                    default=numeric_comparator,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            SelectOptionDict(
                                value="below",
                                label="Poniżej" if _is_polish(language) else "Below",
                            ),
                            SelectOptionDict(
                                value="above",
                                label="Powyżej" if _is_polish(language) else "Above",
                            ),
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_NUMERIC_THRESHOLD,
                    default=numeric_threshold,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX, step="any"
                    )
                ),
            }
        )
    elif sensor_mode == "text":
        fields[vol.Required(CONF_TEXT_STATE, default=text_state)] = (
            selector.TextSelector()
        )
    else:
        fields[vol.Required(CONF_ALERT_STATE, default=default_state)] = (
            selector.StateSelector(
                selector.StateSelectorConfig(
                    **({"entity_id": entity_id} if entity_id else {})
                )
            )
        )
    fields.update(
        {
            vol.Required(CONF_NOTIFIERS): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=notify_options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    custom_value=True,
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
    return vol.Schema(fields)


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

    _selected_entity_ids: list[str]
    _selected_explicit_entity_ids: list[str]
    _selected_label_ids: list[str]
    _entity_domain: str

    def _set_entity_type(self, choice: str, data: dict[str, Any] | None = None) -> None:
        """Resolve the first-step choice into a domain and sensor value mode."""
        if choice == "binary_sensor":
            self._entity_domain = "binary_sensor"
            self._sensor_mode = None
            return
        self._entity_domain = "sensor"
        if choice in ("sensor_numeric", "sensor_text"):
            self._sensor_mode = choice.removeprefix("sensor_")
            return
        data = data or {}
        if data.get(CONF_SENSOR_MODE) in ("numeric", "text"):
            self._sensor_mode = data[CONF_SENSOR_MODE]
        elif CONF_NUMERIC_COMPARATOR in data:
            self._sensor_mode = "numeric"
        else:
            entity_ids = data.get(CONF_ENTITY_IDS) or [data.get(CONF_ENTITY_ID)]
            entity_id = next((item for item in entity_ids if item), None)
            state = self.hass.states.get(entity_id) if entity_id else None
            classification = classify_sensor_state(state)
            self._sensor_mode = (
                "numeric" if classification in ("numeric", "ambiguous") else "text"
            )

    def _notify_targets(self) -> list[SelectOptionDict]:
        """List legacy notify targets without duplicate modern entity entries.

        Mobile app devices expose both a legacy notify service and a modern
        notify entity. The service is the selectable option because it supports
        custom data and actionable notification buttons. Modern entities remain
        available through the selector's custom value field.
        """
        options = sorted(
            [
                SelectOptionDict(
                    value=f"{NOTIFY_DOMAIN}.{service}",
                    label=self._notify_label(service),
                )
                for service in self.hass.services.async_services().get(
                    NOTIFY_DOMAIN, {}
                )
                if service != "send_message"
            ],
            key=lambda option: option["label"].casefold(),
        )
        LOGGER.debug("Found %d notification service target(s)", len(options))
        return options

    def _notify_label(self, service: str) -> str:
        """Return a friendly label for a legacy notify service."""
        if service == "persistent_notification":
            return (
                "Powiadomienie w Home Assistant"
                if _is_polish(self.hass.config.language)
                else "Home Assistant notification"
            )
        if service.startswith("mobile_app_"):
            device = service.removeprefix("mobile_app_")
            state = self.hass.states.get(f"notify.{device}")
            if state and (friendly_name := state.attributes.get("friendly_name")):
                return friendly_name
            return device.replace("_", " ").title()
        return service.replace("_", " ").title()

    def _notify_target_label(self, target: str) -> str:
        """Return a readable label for an existing notification target."""
        if target.startswith(f"{NOTIFY_DOMAIN}."):
            state = self.hass.states.get(target)
            if state and (friendly_name := state.attributes.get("friendly_name")):
                return friendly_name
            return self._notify_label(target.removeprefix(f"{NOTIFY_DOMAIN}."))
        return target

    def _entity_options_for_target(
        self, target: list[str] | str
    ) -> list[SelectOptionDict]:
        """Resolve selected entity targets into options."""
        entity_ids = set(target if isinstance(target, list) else [target]) - {None, ""}
        registry = er.async_get(self.hass)

        options = []
        for entity_id in sorted(entity_ids):
            state = self.hass.states.get(entity_id)
            registry_entry = registry.async_get(entity_id)
            label = (
                (state.attributes.get("friendly_name") if state else None)
                or (registry_entry.name if registry_entry else None)
                or entity_id
            )
            options.append(SelectOptionDict(value=entity_id, label=label))
        return sorted(options, key=lambda option: option["label"].casefold())

    def _target_form(
        self, step_id: str, errors: dict[str, str] | None = None
    ) -> SubentryFlowResult:
        """Show the entity and label selectors."""
        sensor_options = (
            self._sensor_options(self._sensor_mode)
            if self._entity_domain == "sensor"
            else None
        )
        schema = _target_schema(self._entity_domain, sensor_options)
        LOGGER.debug(
            "Showing %s target form for domain=%s, sensor_mode=%s, choices=%s",
            step_id,
            self._entity_domain,
            getattr(self, "_sensor_mode", None),
            len(sensor_options) if sensor_options is not None else "selector",
        )
        if step_id == "reconfigure_target":
            subentry = self._get_reconfigure_subentry()
            suggested = {}
            entity_ids = subentry.data.get(CONF_ENTITY_IDS) or [
                subentry.data.get(CONF_ENTITY_ID)
            ]
            entity_ids = [entity_id for entity_id in entity_ids if entity_id]
            if entity_ids:
                if self._entity_domain == "sensor":
                    available = {option["value"] for option in sensor_options or []}
                    registry = er.async_get(self.hass)
                    sensor_options = list(sensor_options or [])
                    for entity_id in entity_ids:
                        if entity_id in available:
                            continue
                        entry = registry.async_get(entity_id)
                        mismatch = (
                            " (typ stanu nie pasuje)"
                            if _is_polish(self.hass.config.language)
                            else " (current state has a different type)"
                        )
                        sensor_options.append(
                            SelectOptionDict(
                                value=entity_id,
                                label=(entry.name if entry else entity_id) + mismatch,
                            )
                        )
                    schema = _target_schema(self._entity_domain, sensor_options)
                suggested[CONF_WATCH_TARGET] = entity_ids
            if subentry.data.get(CONF_LABEL_IDS):
                suggested[CONF_WATCH_LABELS] = subentry.data[CONF_LABEL_IDS]
            if subentry.data.get(CONF_DEVICE_CLASS):
                suggested[CONF_DEVICE_CLASS] = subentry.data[CONF_DEVICE_CLASS]
            schema = self.add_suggested_values_to_schema(schema, suggested)
        return self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            errors=errors or {},
        )

    def _sensor_options(self, mode: str) -> list[SelectOptionDict]:
        """List currently available sensors whose state matches the chosen type."""
        registry = er.async_get(self.hass)
        options = []
        for entity in registry.entities.values():
            if entity.entity_id.split(".", 1)[0] != "sensor":
                continue
            if entity.disabled_by is not None:
                continue
            state = self.hass.states.get(entity.entity_id)
            if not sensor_state_matches_mode(state, mode):
                continue
            classification = classify_sensor_state(state)
            label = (
                (state.attributes.get("friendly_name") if state else None)
                or entity.name
                or entity.entity_id
            )
            if classification == "ambiguous":
                label += (
                    " (typ niejednoznaczny)"
                    if _is_polish(self.hass.config.language)
                    else " (type unclear)"
                )
            elif classification is None:
                label += (
                    " (typ nieznany)"
                    if _is_polish(self.hass.config.language)
                    else " (type unknown)"
                )
            options.append(SelectOptionDict(value=entity.entity_id, label=label))
        return sorted(options, key=lambda option: option["label"].casefold())

    async def _handle_target(
        self, user_input: dict[str, Any], step_mode: str
    ) -> SubentryFlowResult:
        """Resolve the chosen target and continue to an entity-specific form."""
        target = user_input.get(CONF_WATCH_TARGET, [])
        label_ids = user_input.get(CONF_WATCH_LABELS, [])
        self._selected_device_class = user_input.get(CONF_DEVICE_CLASS)
        if isinstance(label_ids, str):
            label_ids = [label_ids]
        LOGGER.debug(
            "Resolving %s targets: domain=%s, entity_count=%d, label_count=%d, "
            "device_class=%s",
            step_mode,
            self._entity_domain,
            len(target) if isinstance(target, list) else int(bool(target)),
            len(label_ids),
            self._selected_device_class,
        )
        if self._selected_device_class and not target and not label_ids:
            registry = er.async_get(self.hass)
            target = [
                entity.entity_id
                for entity in registry.entities.values()
                if entity.disabled_by is None
                and entity.entity_id.startswith(f"{self._entity_domain}.")
                and self._entity_matches_device_class(
                    entity.entity_id, self._selected_device_class
                )
                and (
                    self._entity_domain != "sensor"
                    or (state := self.hass.states.get(entity.entity_id)) is None
                    or sensor_state_matches_mode(state, self._sensor_mode)
                )
            ]
        options = self._entity_options_for_target(target)
        registry = er.async_get(self.hass)
        labeled_ids = {
            entity.entity_id
            for entity in registry.entities.values()
            if (
                set(entity.labels).intersection(label_ids)
                and entity.disabled_by is None
                and entity.entity_id.startswith(f"{self._entity_domain}.")
                and self._entity_matches_device_class(
                    entity.entity_id, self._selected_device_class
                )
                and (
                    self._entity_domain != "sensor"
                    or (state := self.hass.states.get(entity.entity_id)) is None
                    or sensor_state_matches_mode(state, self._sensor_mode)
                )
            )
        }
        option_by_id = {option["value"]: option for option in options}
        for entity_id in labeled_ids:
            if entity_id not in option_by_id:
                state = self.hass.states.get(entity_id)
                option_by_id[entity_id] = SelectOptionDict(
                    value=entity_id,
                    label=(
                        state.attributes.get("friendly_name", entity_id)
                        if state
                        else entity_id
                    ),
                )
        options = sorted(
            option_by_id.values(), key=lambda option: option["label"].casefold()
        )
        if self._selected_device_class:
            options = [
                option
                for option in options
                if self._entity_matches_device_class(
                    option["value"], self._selected_device_class
                )
            ]
        if not options and not label_ids:
            LOGGER.info(
                "No matching alert targets selected (domain=%s, device_class=%s)",
                self._entity_domain,
                self._selected_device_class,
            )
            return self._target_form(
                f"{step_mode}_target", {CONF_WATCH_TARGET: "no_entities"}
            )

        self._selected_label_ids = list(dict.fromkeys(label_ids))
        self._selected_explicit_entity_ids = [
            option["value"]
            for option in self._entity_options_for_target(target)
            if self._entity_matches_device_class(
                option["value"], self._selected_device_class
            )
        ]
        # A label means “all matching entities”, including future members.
        # Manual entity selection is already performed in the target dialog.
        self._selected_entity_ids = [option["value"] for option in options]
        LOGGER.info(
            "Alert targets selected: %d current entity/entities and %d label(s)%s",
            len(self._selected_entity_ids),
            len(self._selected_label_ids),
            f" (device_class={self._selected_device_class})"
            if self._selected_device_class
            else "",
        )
        LOGGER.debug(
            "Resolved alert target entity ids: %s; label ids: %s",
            self._selected_entity_ids,
            self._selected_label_ids,
        )
        if step_mode == "user":
            return await self.async_step_user_alert()
        return await self.async_step_reconfigure_alert()

    def _entity_matches_device_class(
        self, entity_id: str, device_class: str | None
    ) -> bool:
        """Match a class against registry metadata or current state attributes."""
        if device_class is None:
            return True
        registry_entry = er.async_get(self.hass).async_get(entity_id)
        if registry_entry and registry_entry.device_class:
            return registry_entry.device_class == device_class
        state = self.hass.states.get(entity_id)
        return bool(state and state.attributes.get("device_class") == device_class)

    def _alert_form_schema(
        self, step_mode: str, suggested: dict[str, Any]
    ) -> vol.Schema:
        """Build an alert form with state suggestions for its selected entity."""
        if step_mode == "user":
            selected_device_class = self._selected_device_class
            if selected_device_class is None:
                classes = set()
                registry = er.async_get(self.hass)
                for entity_id in self._selected_entity_ids:
                    entity = registry.async_get(entity_id)
                    state = self.hass.states.get(entity_id)
                    device_class = (entity.device_class if entity else None) or (
                        state.attributes.get("device_class") if state else None
                    )
                    if device_class:
                        classes.add(device_class)
                if len(classes) == 1:
                    selected_device_class = classes.pop()
            defaults = _smart_alert_defaults(
                language=self.hass.config.language,
                sensor_mode=(
                    self._sensor_mode if self._entity_domain == "sensor" else None
                ),
                device_class=selected_device_class,
                comparator=suggested.get(CONF_NUMERIC_COMPARATOR, "below"),
            )
            suggested = {**defaults, **suggested}

        options = self._notify_targets()
        if step_mode == "reconfigure":
            subentry = self._get_reconfigure_subentry()
            option_values = {option["value"] for option in options}
            options.extend(
                SelectOptionDict(value=target, label=self._notify_target_label(target))
                for target in subentry.data.get(CONF_NOTIFIERS, [])
                if target not in option_values
            )

        selected_entity_id = (
            self._selected_entity_ids[0] if self._selected_entity_ids else None
        )
        entity_state = (
            self.hass.states.get(selected_entity_id) if selected_entity_id else None
        )
        default_state = (
            entity_state.state
            if entity_state and entity_state.state not in ("unknown", "unavailable")
            else DEFAULT_ALERT_STATE
        )
        stored = suggested
        sensor_mode = None
        if self._entity_domain == "sensor":
            sensor_mode = self._sensor_mode
        schema = _alert_schema(
            options,
            selected_entity_id,
            default_state,
            sensor_mode=sensor_mode,
            numeric_comparator=stored.get(CONF_NUMERIC_COMPARATOR, "below"),
            numeric_threshold=stored.get(CONF_NUMERIC_THRESHOLD, 20),
            text_state=stored.get(CONF_TEXT_STATE, default_state),
            language=self.hass.config.language,
        )
        LOGGER.debug(
            "Building %s alert form with fields=%s and %d notification target(s)",
            step_mode,
            [getattr(key, "schema", str(key)) for key in schema.schema],
            len(options),
        )
        return self.add_suggested_values_to_schema(schema, suggested)

    def _validate(
        self, user_input: dict[str, Any], entity_ids: list[str]
    ) -> tuple[dict[str, Any] | None, dict[str, str]]:
        """Validate alert options and attach the selected entity id."""
        errors: dict[str, str] = {}
        data = dict(user_input)
        data[CONF_ENTITY_DOMAIN] = self._entity_domain
        if self._selected_device_class:
            data[CONF_DEVICE_CLASS] = self._selected_device_class
        else:
            data.pop(CONF_DEVICE_CLASS, None)
        if self._entity_domain == "sensor":
            data.pop(CONF_ALERT_STATE, None)
            sensor_mode = getattr(self, "_sensor_mode", None) or user_input.get(
                CONF_SENSOR_MODE, "numeric"
            )
            data[CONF_SENSOR_MODE] = sensor_mode
            if sensor_mode == "numeric":
                data.pop(CONF_TEXT_STATE, None)
                try:
                    threshold = float(user_input[CONF_NUMERIC_THRESHOLD])
                    if not math.isfinite(threshold):
                        raise ValueError
                    data[CONF_NUMERIC_THRESHOLD] = threshold
                except (ValueError, TypeError, KeyError):
                    errors[CONF_NUMERIC_THRESHOLD] = "invalid_threshold"
                if user_input.get(CONF_NUMERIC_COMPARATOR) not in ("above", "below"):
                    errors[CONF_NUMERIC_COMPARATOR] = "invalid_comparator"
            elif sensor_mode == "text":
                data.pop(CONF_NUMERIC_COMPARATOR, None)
                data.pop(CONF_NUMERIC_THRESHOLD, None)
                if not user_input.get(CONF_TEXT_STATE):
                    errors[CONF_TEXT_STATE] = "invalid_text_state"
            else:
                errors[CONF_SENSOR_MODE] = "invalid_sensor_mode"
        else:
            data.pop(CONF_SENSOR_MODE, None)
            data.pop(CONF_TEXT_STATE, None)
            data.pop(CONF_NUMERIC_COMPARATOR, None)
            data.pop(CONF_NUMERIC_THRESHOLD, None)
        stored_entity_ids = (
            self._selected_explicit_entity_ids
            if self._selected_label_ids
            else entity_ids
        )
        if stored_entity_ids:
            data[CONF_ENTITY_ID] = stored_entity_ids[0]
        elif self._selected_label_ids:
            data.pop(CONF_ENTITY_ID, None)
        else:
            return None, {CONF_WATCH_TARGET: "no_entities"}
        if len(stored_entity_ids) != 1:
            data[CONF_ENTITY_IDS] = stored_entity_ids
        else:
            data.pop(CONF_ENTITY_IDS, None)
        if self._selected_label_ids:
            data[CONF_LABEL_IDS] = list(self._selected_label_ids)
        else:
            data.pop(CONF_LABEL_IDS, None)
        # Store legacy services in the same fully-qualified format as targets
        # shown in the selector. Bare service names remain accepted for old flows.
        data[CONF_NOTIFIERS] = [
            target if "." in target else f"{NOTIFY_DOMAIN}.{target}"
            for target in user_input.get(CONF_NOTIFIERS, [])
        ]

        try:
            data[CONF_REPEAT] = _parse_repeat(user_input[CONF_REPEAT])
        except ValueError:
            errors[CONF_REPEAT] = "invalid_repeat"

        if not user_input.get(CONF_NOTIFIERS):
            errors[CONF_NOTIFIERS] = "no_notifiers"

        if errors:
            LOGGER.debug("Alert form validation failed for fields: %s", sorted(errors))
            return None, errors

        # Drop empty optional fields so they don't linger in stored data.
        for key in (*TEMPLATE_FIELDS, CONF_DATA):
            if not data.get(key):
                data.pop(key, None)
        return data, errors

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Choose entities or labels to monitor."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=_domain_schema(language=self.hass.config.language),
            )
        self._set_entity_type(user_input[CONF_ENTITY_DOMAIN])
        LOGGER.debug(
            "Starting alert flow for domain=%s, sensor_mode=%s",
            self._entity_domain,
            getattr(self, "_sensor_mode", None),
        )
        return self._target_form("user_target")

    async def async_step_user_target(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Choose entities or labels to monitor."""
        if user_input is None:
            return self._target_form("user_target")
        return await self._handle_target(user_input, "user")

    async def async_step_user_alert(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Configure alert options, including the selected entity's state."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = self._validate(user_input, self._selected_entity_ids)
            if data is not None:
                LOGGER.info(
                    "Configured alert '%s' for %d entity/entities, %d label(s), "
                    "and %d notification target(s)",
                    data[CONF_NAME],
                    len(data.get(CONF_ENTITY_IDS, []))
                    or int(bool(data.get(CONF_ENTITY_ID))),
                    len(data.get(CONF_LABEL_IDS, [])),
                    len(data.get(CONF_NOTIFIERS, [])),
                )
                LOGGER.debug(
                    "Alert '%s' config: entities=%s, labels=%s, device_class=%s, "
                    "notifiers=%s",
                    data[CONF_NAME],
                    data.get(CONF_ENTITY_IDS, [data.get(CONF_ENTITY_ID)]),
                    data.get(CONF_LABEL_IDS, []),
                    data.get(CONF_DEVICE_CLASS),
                    data.get(CONF_NOTIFIERS, []),
                )
                return self.async_create_entry(title=data[CONF_NAME], data=data)
            suggested = user_input
        else:
            suggested = {}

        schema = self._alert_form_schema("user", suggested)
        return self.async_show_form(
            step_id="user_alert",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "entity_id": ", ".join(self._selected_entity_ids)
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Choose entities or labels for an existing alert."""
        subentry = self._get_reconfigure_subentry()
        if user_input is None:
            domain = subentry.data.get(CONF_ENTITY_DOMAIN)
            if domain == "binary_sensor":
                choice = "binary_sensor"
            else:
                old_ids = subentry.data.get(CONF_ENTITY_IDS) or [
                    subentry.data.get(CONF_ENTITY_ID)
                ]
                old_domain = next(
                    (
                        entity_id.split(".", 1)[0]
                        for entity_id in old_ids
                        if entity_id and "." in entity_id
                    ),
                    "binary_sensor",
                )
                if old_domain != "sensor":
                    choice = "binary_sensor"
                else:
                    self._set_entity_type("sensor_numeric", dict(subentry.data))
                    choice = f"sensor_{self._sensor_mode}"
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=_domain_schema(choice, language=self.hass.config.language),
            )
        self._set_entity_type(user_input[CONF_ENTITY_DOMAIN])
        return self._target_form("reconfigure_target")

    async def async_step_reconfigure_target(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Choose replacement entities or labels."""
        if user_input is None:
            return self._target_form("reconfigure_target")
        return await self._handle_target(user_input, "reconfigure")

    async def async_step_reconfigure_alert(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit alert options for the selected entity."""
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = self._validate(user_input, self._selected_entity_ids)
            if data is not None:
                LOGGER.info(
                    "Updated alert '%s' for %d entity/entities, %d label(s), "
                    "and %d notification target(s)",
                    data[CONF_NAME],
                    len(data.get(CONF_ENTITY_IDS, []))
                    or int(bool(data.get(CONF_ENTITY_ID))),
                    len(data.get(CONF_LABEL_IDS, [])),
                    len(data.get(CONF_NOTIFIERS, [])),
                )
                LOGGER.debug(
                    "Updated alert '%s' config: entities=%s, labels=%s, "
                    "device_class=%s, notifiers=%s",
                    data[CONF_NAME],
                    data.get(CONF_ENTITY_IDS, [data.get(CONF_ENTITY_ID)]),
                    data.get(CONF_LABEL_IDS, []),
                    data.get(CONF_DEVICE_CLASS),
                    data.get(CONF_NOTIFIERS, []),
                )
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

        schema = self._alert_form_schema("reconfigure", suggested)
        return self.async_show_form(
            step_id="reconfigure_alert",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "entity_id": ", ".join(self._selected_entity_ids)
            },
        )
