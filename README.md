# Alerts Assistant

[![CI](https://github.com/psorobka/alerts_assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/psorobka/alerts_assistant/actions/workflows/ci.yml)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A UI-configurable re-implementation of the Home Assistant built-in
[`alert`](https://www.home-assistant.io/integrations/alert/) integration.

The built-in `alert` integration is YAML-only. **Alerts Assistant** gives you the
same behaviour — watch an entity, and while it stays in a given state, repeatedly
notify until acknowledged or cleared — but everything is added and edited from the
UI, with no restart.

## Features

- Watch one or more entities for a configurable trigger state. Every selected entity
  gets an independent alert, acknowledgement, and repeat schedule.
- Watch entities by Home Assistant label; entities added to or removed from a label
  are picked up automatically.
- Choose between binary, numeric, and text sensors. Numeric sensors support above / below
  thresholds; text sensors match an exact state.
- Filter selected entities and label members by device class, such as `moisture`.
- Get a translated Home Assistant repair warning if a selected entity or label is
  removed, or if the alert has no active entities.
- Repeat notifications on a fixed or escalating schedule (e.g. `15, 30, 60`).
- Acknowledge to silence (`turn_off`), re-arm (`turn_on`), or `toggle`.
- **Acknowledge straight from the notification** — an action button on mobile_app
  notifications silences the alert with one tap.
- Optional "done" message when the alert clears.
- Optional notification title / message templates and extra `data`.
- Notify via `notify.*` services or entities, selectable by friendly name or entered manually.
- Built-in Lovelace card with active alert grouping by room, elapsed time, and per-alert acknowledgement.
- One hub, many alerts: add/edit/delete each alert independently from the UI —
  editing one alert never disturbs the others.

Each alert is exposed as an `alerts_assistant.*` entity.

## How it works

Each alert watches one or more entities. Each watched entity gets its own alert
entity and independent lifecycle. While the configured trigger condition is
true, its alert is "firing" and sends a notification, then keeps re-sending on
the **repeat** schedule until you acknowledge it or the condition clears. You
can select entities directly or use one or more Home Assistant labels as a
dynamic set. The first setup step asks whether you are monitoring a
`binary_sensor`, numeric `sensor`, or text `sensor`; the next list is filtered by
sensor metadata (`device_class`, `state_class`, and unit) and the current value.
Sensors with no reliable type information appear in both sensor lists and are
marked as unclear, so a numeric-looking text value such as `123` can still be
selected as text.
The entity/label picker also has an optional **Device class** filter, such as
`moisture`; it narrows both manually selected entities and label members.

An alert can watch several manually selected entities, one or more labels, or both.
Each matching entity gets a separate `alerts_assistant.*` entity and its own alert
lifecycle. Templates receive the triggering entity's `entity_id`, `entity_name`, and
`area`, so a grouped alert can mention the room that needs attention.

If a manually selected entity or label is deleted, the affected target is removed
from the active configuration and a yellow Home Assistant **Repair** warning asks
you to review the alert. Other entities in the group keep running. The warning also
appears when no entities currently match the alert, and clears after you edit the
alert and choose available targets. If you submit the target step without choosing
an entity or label, the form shows a localized validation message instead of saving
an empty alert.

For a `binary_sensor`, choose the trigger state, such as `on` for a wet leak
detector. For a numeric `sensor`, choose **below** or **above** and set a
threshold, for example `battery < 20`. The alert stays active while that
comparison is true. `unknown` and `unavailable` readings do not clear an active
numeric alert. For text sensors, provide the exact value to match, such as
`open`. If a numeric sensor later reports a text value, it no longer matches the
numeric condition and the alert clears.

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

While an alert is active, its entity exposes `triggered_at` (ISO timestamp),
`watched_entity`, `area` when assigned, and `acknowledged`. The start time stays the
same after acknowledgement and disappears when the alert clears. Add the
`alerts_assistant.*` entities to an **Entities** dashboard card to see each sensor's
current status; open an entity's more-info panel to inspect its start time and area.

### Alerts dashboard card

Alerts Assistant registers its Lovelace card automatically; no separate HACS
frontend repository or resource URL is needed. In a dashboard, choose **Edit
dashboard → Add card**, search for **Alerts Assistant**, and add it. The card finds
all `alerts_assistant.*` entities automatically, groups active alerts by area,
shows how long each has been active, and lets you acknowledge or re-arm each alert
individually. Alerts without an area appear under **Other**. Cleared alerts are
hidden by default; optional YAML settings are:

```yaml
type: custom:alerts-assistant-card
title: Home alerts
show_cleared: false
group_by_area: true
```

### Acknowledging from the notification

When *Acknowledge button in notifications* is on (and the alert can be acknowledged),
each firing notification includes an **Acknowledge** action. This uses the Home
Assistant Companion App's
[actionable notifications](https://companion.home-assistant.io/docs/notifications/actionable-notifications/):
tapping the button fires a `mobile_app_notification_action` event, which the
integration matches back to the specific alert and acknowledges it — no need to open
the app. The action is added to the notification's `data.actions`, merged with any
extra data you configured. Legacy `notify.mobile_app_*` services are required for
action buttons. Modern notify entities receive title and message through
`notify.send_message`; they do not support custom data or action buttons.
The action label follows Home Assistant's configured language (Polish or English).

## Installation (HACS)

1. HACS → Integrations → ⋮ → **Custom repositories**.
2. Add `https://github.com/psorobka/alerts_assistant` as an *Integration*.
3. Install **Alerts Assistant**, then restart Home Assistant.

Or copy `custom_components/alerts_assistant` into your `config/custom_components/`.

## Configuration

1. **Settings → Devices & Services → Add Integration → Alerts Assistant** creates
   the hub; only one is allowed.
2. On the integration card, use **Add** to create an alert and choose whether to
   monitor a binary sensor, numeric sensor, or text sensor.
3. Select one or more entities, labels, or both. Optionally filter them by device
   class, then configure the trigger, notification targets, and repeat behavior.
4. Edit or delete alerts from the same card at any time — no restart needed.

### Alert options

| Option                   | Required | Description                                                                 |
| ------------------------ | -------- | --------------------------------------------------------------------------- |
| **Name**                 | yes      | Friendly name; also derives the `alerts_assistant.<name>` entity id.        |
| **Entity type**          | yes      | Binary sensor, numeric sensor, or text sensor. Numeric sensors use a threshold; text sensors match an exact value. |
| **Entities**             | yes*     | Select one or more entities to monitor. Each gets an independent alert.       |
| **Entity labels**        | no       | Optionally monitor every entity with the selected labels; membership updates automatically, including future members. |
| **Device class**         | no       | Optionally filter manually selected entities and label members by class.      |
| **Trigger condition**    | yes      | For `binary_sensor`, the state that fires the alert (default `on`). For numeric `sensor`, use a below/above comparison and threshold. Text sensors match an exact value. |
| **Notification targets** | yes      | One or more `notify.*` services or entities, chosen from the list or entered manually. |
| **Repeat (minutes)**     | yes      | Comma-separated minutes between notifications; escalates then holds the last.|
| **Can be acknowledged**  | —        | If off, the alert cannot be silenced with `turn_off` (default on).          |
| **Acknowledge button in notifications** | — | Adds an Acknowledge action to mobile_app notifications (default on; needs *Can be acknowledged*). |
| **Skip first notification** | —     | Wait one interval before the first notification instead of firing at once.  |
| **Notification title**   | no       | Optional template for the notification title.                               |
| **Notification message** | no       | Optional template; defaults to the alert name.                              |
| **Done message**         | no       | Optional template sent once when the alert clears.                          |
| **Extra notification data** | no    | Optional key/values forwarded to the notify service (e.g. `priority`).      |

*Select at least one entity or label. If an entity or label is deleted later, a
yellow Repair warning identifies the alert that needs review. Removing one member
from a group leaves its other alert entities running.

For multi-entity alerts, each notification template receives `entity_id`,
`entity_name`, and `area` for the sensor that triggered that alert. For example:

```jinja2
Wykryto zalanie: {{ area or entity_name }}
```

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
- Notify targets include legacy `notify.<service>` services and modern notify
  entities, selected by friendly name or entered manually.

## Local testing with Home Assistant

You can run a local Home Assistant development instance with Docker and mount this
checkout as its `Alerts Assistant` integration. Run the commands below from the
repository root.

### Start (PowerShell)

```powershell
New-Item -ItemType Directory -Force .ha-dev/config | Out-Null
Set-Content .ha-dev/config/configuration.yaml "default_config:`n"

docker run --detach --name alerts-assistant-ha --restart unless-stopped `
  --publish 8123:8123 `
  --volume "${PWD}\.ha-dev\config:/config" `
  --volume "${PWD}\custom_components\alerts_assistant:/config/custom_components/alerts_assistant:ro" `
  homeassistant/home-assistant:stable
```

Run `docker run` only the first time. If the `alerts-assistant-ha` container
already exists, use `docker start alerts-assistant-ha` instead.

Open [http://localhost:8123](http://localhost:8123) and finish Home Assistant's
first-run setup. Then go to **Settings → Devices & Services → Add Integration**
and select **Alerts Assistant**. The integration files are mounted from this
checkout; restart Home Assistant after changing Python code:

```powershell
docker restart alerts-assistant-ha
```

To try an alert without connecting a phone or external service, create an
`input_boolean` helper in Home Assistant, then add an alert that watches it,
triggers on `on`, repeats every `1` minute, and targets
`notify.persistent_notification`. Turn the helper on to see the notification in
Home Assistant; turn it off to clear the alert.

The HA configuration and onboarding data are stored in `.ha-dev/config/` (which
is git-ignored), so they survive container restarts and recreations. Manage the
container with:

```powershell
docker stop alerts-assistant-ha
docker start alerts-assistant-ha
docker logs --follow alerts-assistant-ha
```

To remove only the container while keeping its configuration, run
`docker rm --force alerts-assistant-ha`, then repeat the start commands above.

The integration includes English and Polish UI translations in
`custom_components/alerts_assistant/translations/`. Home Assistant uses the
language selected in your user profile.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements_test.txt -r requirements_dev.txt
.venv/bin/pytest -q --cov --cov-report=term-missing
.venv/bin/ruff check .
.venv/bin/ruff format .
```

The add-on also has a Chromium end-to-end test. It starts a temporary Home
Assistant container with this checkout mounted as the integration, creates an
alert through the integration flow, and verifies the real Lovelace card against
HA's state and services. Install Node.js 22 and Docker, then run:

```bash
npm ci
npx playwright install --with-deps chromium
npm run test:ha
```

On Windows, run these commands inside a WSL distro with Node.js 22 and Docker
Desktop's WSL integration enabled. For example:

```bash
cd /mnt/c/Users/<your-user>/Documents/ChatGPT/alerts_assistant
npm ci
npx playwright install --with-deps chromium
node --test tests/frontend-card.test.mjs
npm run test:ha
```

The test suite includes pseudo-integration tests that run a real Home Assistant
core in-process (via `pytest-homeassistant-custom-component`) and cover the full
firing / repeat / escalate / acknowledge / clear / re-arm matrix as well as the
config and subentry flows.

CI runs Ruff linting and formatting checks, the test suite with coverage, Hassfest
manifest validation, and HACS validation. Dependabot checks GitHub Actions and
Python dependencies weekly.

## Credits

Created with help from [Claude Code](https://claude.com/claude-code) and
[ChatGPT](https://chatgpt.com/).

## Requirements

- Home Assistant **2025.6.0+** (config subentries with reconfigure support).
  Developed and tested against 2026.6.

## License

This project is licensed under the [MIT License](LICENSE).

