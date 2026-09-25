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
  assert.equal(window.customCards[0].type, "custom:alerts-assistant-card");
});
