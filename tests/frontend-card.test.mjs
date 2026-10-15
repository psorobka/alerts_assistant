import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import test from "node:test";

class HTMLElement {}
const registry = new Map();
const window = {};
vm.runInNewContext(fs.readFileSync(new URL("../custom_components/alerts_assistant/www/alerts-assistant-card.js", import.meta.url), "utf8"), {
  HTMLElement,
  customElements: { get: (name) => registry.get(name), define: (name, klass) => registry.set(name, klass) },
  window,
  Date,
  Map,
  Object,
  String,
  Number,
  Math,
  CustomEvent: class {
    constructor(type, options) { this.type = type; Object.assign(this, options); }
  },
  setInterval,
  clearInterval,
});
const card = window.AlertsAssistantCardInternals;

test("elapsed time formats minutes, hours and days", () => {
  const now = Date.parse("2026-01-01T12:00:00Z");
  assert.equal(card.formatElapsed("2026-01-01T11:45:00Z", now), "15 min");
  assert.equal(card.formatElapsed("2026-01-01T10:00:00Z", now), "2 h");
  assert.equal(card.formatElapsed("2026-01-01T10:00:00Z", now, "pl-PL"), "2 godz.");
  assert.equal(card.formatElapsed("2025-12-30T10:00:00Z", now), "2 d 2 h");
});

test("active alerts are grouped by area and unavailable entities are ignored", () => {
  const alerts = card.getAlerts({
    "alerts_assistant.kitchen": { state: "on", attributes: { area: "Kitchen", friendly_name: "Leak" } },
    "alerts_assistant.hall": { state: "off", attributes: { area: "Hall", friendly_name: "Smoke" } },
    "alerts_assistant.cleared": { state: "idle", attributes: { area: "Kitchen" } },
    "alerts_assistant.unavailable": { state: "unavailable", attributes: {} },
    "sensor.other": { state: "on", attributes: {} },
  });
  const groups = card.groupAlerts(alerts);
  assert.deepEqual(Array.from(groups.keys()), ["Hall", "Kitchen"]);
  assert.deepEqual(alerts.map(({ entity_id }) => entity_id), ["alerts_assistant.hall", "alerts_assistant.kitchen"]);
});

test("cleared alerts can be included and entities without an area use Other", () => {
  const alerts = card.getAlerts({
    "alerts_assistant.cleared": { state: "idle", attributes: {} },
  }, true);
  assert.equal(alerts.length, 1);
  assert.equal(Array.from(card.groupAlerts(alerts).keys())[0], "Other");
});

test("card registers itself in Home Assistant", () => {
  assert.equal(registry.has("alerts-assistant-card"), true);
  assert.equal(registry.has("alerts-assistant-card-editor"), true);
  assert.equal(window.customCards[0].type, "alerts-assistant-card");
});

test("all alerts show OK, start time and acknowledgement status", () => {
  const Card = registry.get("alerts-assistant-card");
  const view = new Card();
  view._hass = { locale: { language: "pl" } };
  view.config = { show_cleared: true };
  const started = "2026-01-01T10:00:00Z";
  const firing = view.renderAlert({ entity_id: "alerts_assistant.leak", state: {
    state: "on", attributes: { friendly_name: "Wyciek", triggered_at: started },
  }, active: true });
  assert.match(firing, /Od: /);
  assert.match(firing, /data-service="turn_off"/);
  const acknowledged = view.renderAlert({ entity_id: "alerts_assistant.leak", state: {
    state: "off", attributes: { triggered_at: started, acknowledged: true },
  }, active: true });
  assert.match(acknowledged, /ACK · Potwierdzony/);
  const idle = view.renderAlert({ entity_id: "alerts_assistant.leak", state: {
    state: "idle", attributes: {},
  }, active: false });
  assert.match(idle, />OK</);
});

test("visual editor switches between active and all alerts", () => {
  const Editor = registry.get("alerts-assistant-card-editor");
  const editor = new Editor();
  let onChange;
  let selected;
  let emitted;
  editor.attachShadow = () => ({
    addEventListener: (_name, callback) => { onChange = callback; },
    querySelector: () => ({ set value(value) { selected = value; } }),
  });
  editor.dispatchEvent = (event) => { emitted = event; };
  editor.connectedCallback();
  editor.setConfig({ title: "Home", show_cleared: false });
  assert.equal(selected, "active");
  onChange({ target: { id: "display", value: "all" } });
  assert.equal(emitted.type, "config-changed");
  assert.equal(emitted.detail.config.show_cleared, true);
  assert.equal(emitted.detail.config.title, "Home");
});
