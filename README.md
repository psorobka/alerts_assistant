# Alerts Assistant

A UI-configurable re-implementation of the Home Assistant built-in
[`alert`](https://www.home-assistant.io/integrations/alert/) integration.

The built-in `alert` integration is YAML-only. **Alerts Assistant** gives you the
same behaviour — watch an entity, and while it stays in a given state, repeatedly
notify until acknowledged or cleared — but everything is added and edited from the
UI, with no restart.

## Features

- Watch any entity for a configurable trigger state.
- Repeat notifications on a fixed or escalating schedule (e.g. `15, 30, 60`).
- Acknowledge to silence (`turn_off`), re-arm (`turn_on`), or `toggle`.
- **Acknowledge straight from the notification** — an action button on mobile_app
  notifications silences the alert with one tap.
- Optional "done" message when the alert clears.
- Optional notification title / message templates and extra `data`.
- Notify via any `notify.*` service, selectable from a list.
- One hub, many alerts: add/edit/delete each alert independently from the UI —
  editing one alert never disturbs the others.

Each alert is exposed as an `alerts_assistant.*` entity.

## How it works

Each alert watches one entity. While that entity sits in the configured **trigger
state**, the alert is "firing" and sends a notification, then keeps re-sending on
the **repeat** schedule until you acknowledge it or the watched entity leaves the
trigger state.

### Lifecycle

1. **Watched entity enters the trigger state** → the alert starts firing and (unless
   *Skip first notification* is set) sends the first notification immediately.
2. **Repeat** → it re-notifies after each interval in the repeat list. A single value
   repeats forever (`30` → every 30 min); multiple values escalate and then hold on
   the last one (`15, 30, 60` → after 15, then 30, then every 60 min).
3. **Acknowledge** (`alerts_assistant.turn_off`, the service, or the **Acknowledge
   button in the notification**) → notifications stop, but the alert stays active in
   the background. No more messages are sent while acknowledged.
4. **Watched entity leaves the trigger state** → the alert clears, sends the optional
   *Done message*, and returns to idle. The acknowledgement is reset, so the next
   time the entity enters the trigger state the alert fires again.

### States

The `alerts_assistant.*` entity reports:

| State  | Meaning                                                        |
| ------ | ------------------------------------------------------------- |
| `idle` | Watched entity is not in the trigger state (nothing to alert) |
| `on`   | Firing and **not** acknowledged (notifications are being sent)|
| `off`  | Firing but **acknowledged** (silenced until it clears)        |

If a notify service fails (e.g. a notifier is temporarily down), the error is logged
and the repeat loop keeps going — one failure never stops the alert.

### Acknowledging from the notification

When *Acknowledge button in notifications* is on (and the alert can be acknowledged),
each firing notification includes an **Acknowledge** action. This uses the Home
Assistant Companion App's
[actionable notifications](https://companion.home-assistant.io/docs/notifications/actionable-notifications/):
tapping the button fires a `mobile_app_notification_action` event, which the
integration matches back to the specific alert and acknowledges it — no need to open
the app. The action is added to the notification's `data.actions`, merged with any
extra data you configured. Other notifiers (Telegram, etc.) ignore the action.

## Installation (HACS)

1. HACS → Integrations → ⋮ → **Custom repositories**.
2. Add `https://github.com/psorobka/alerts_assistant` as an *Integration*.
3. Install **Alerts Assistant**, then restart Home Assistant.

Or copy `custom_components/alerts_assistant` into your `config/custom_components/`.

## Configuration

1. **Settings → Devices & Services → Add Integration → Alerts Assistant** (creates
   the hub; only one is allowed).
2. On the integration card, use **Add** to create an alert.
3. Edit or delete alerts from the same card at any time — no restart needed.

### Alert options

| Option                   | Required | Description                                                                 |
| ------------------------ | -------- | --------------------------------------------------------------------------- |
| **Name**                 | yes      | Friendly name; also derives the `alerts_assistant.<name>` entity id.        |
| **Watched entity**       | yes      | The entity whose state is monitored.                                        |
| **Trigger state**        | yes      | The state that makes the alert fire (default `on`).                         |
| **Notify services**      | yes      | One or more `notify.*` services to call, chosen from the available list.    |
| **Repeat (minutes)**     | yes      | Comma-separated minutes between notifications; escalates then holds the last.|
| **Can be acknowledged**  | —        | If off, the alert cannot be silenced with `turn_off` (default on).          |
| **Acknowledge button in notifications** | — | Adds an Acknowledge action to mobile_app notifications (default on; needs *Can be acknowledged*). |
| **Skip first notification** | —     | Wait one interval before the first notification instead of firing at once.  |
| **Notification title**   | no       | Optional template for the notification title.                               |
| **Notification message** | no       | Optional template; defaults to the alert name.                              |
| **Done message**         | no       | Optional template sent once when the alert clears.                          |
| **Extra notification data** | no    | Optional key/values forwarded to the notify service (e.g. `priority`).      |

## Services

These act on `alerts_assistant.*` entities (like the built-in alert):

| Service                     | Effect                                                        |
| --------------------------- | ------------------------------------------------------------ |
| `alerts_assistant.turn_off` | **Acknowledge** — silence notifications until the alert clears|
| `alerts_assistant.turn_on`  | **Reset** — remove the acknowledgement so it notifies again   |
| `alerts_assistant.toggle`   | Toggle the acknowledged state                                 |

## Differences from the built-in `alert`

- Configured entirely from the UI (config subentries), not YAML.
- One hub config entry owns all alerts; each alert is a subentry you manage
  independently. Adding, editing or removing one alert does not re-notify or
  un-acknowledge the others.
- Notify targets are the legacy `notify.<service>` services (matching the built-in
  alert), selectable from a dropdown.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest -q
```

The test suite includes pseudo-integration tests that run a real Home Assistant
core in-process (via `pytest-homeassistant-custom-component`) and cover the full
firing / repeat / escalate / acknowledge / clear / re-arm matrix as well as the
config and subentry flows.

## Requirements

- Home Assistant **2025.6.0+** (config subentries with reconfigure support).
  Developed and tested against 2026.6.
