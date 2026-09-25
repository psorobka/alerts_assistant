const CARD_TYPE = "alerts-assistant-card";

const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[char]);

const formatElapsed = (started, now = Date.now(), language = "en") => {
  const timestamp = Date.parse(started);
  if (!Number.isFinite(timestamp)) return "";
  const minutes = Math.max(0, Math.floor((now - timestamp) / 60000));
  const polish = language.toLowerCase().startsWith("pl");
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  const hourUnit = polish ? "godz." : "h";
  if (hours < 24) return remainder ? `${hours} ${hourUnit} ${remainder} min` : `${hours} ${hourUnit}`;
  const days = Math.floor(hours / 24);
  return `${days} d ${hours % 24} ${hourUnit}`;
};

const TEXT = {
  en: { title: "Alerts", other: "Other", empty: "No active alerts", cleared: "No alerts", active: "Active", acknowledged: "Acknowledged", resolved: "Cleared", ack: "Acknowledge", rearm: "Re-arm" },
  pl: { title: "Alerty", other: "Pozostałe", empty: "Brak aktywnych alertów", cleared: "Brak alertów", active: "Aktywny", acknowledged: "Potwierdzony", resolved: "Zakończony", ack: "Potwierdź", rearm: "Uzbrój ponownie" },
};

const getAlerts = (states, showCleared = false) => Object.entries(states)
  .filter(([id, state]) => id.startsWith("alerts_assistant.")
    && ["on", "off", "idle"].includes(state.state))
  .map(([entity_id, state]) => ({ entity_id, state, active: state.state !== "idle" }))
  .filter((alert) => alert.active || showCleared)
  .sort((a, b) => (a.state.attributes.area || "").localeCompare(b.state.attributes.area || "")
    || (a.state.attributes.friendly_name || a.entity_id).localeCompare(b.state.attributes.friendly_name || b.entity_id));

const groupAlerts = (alerts, groupByArea = true, otherLabel = "Other") => {
  const groups = new Map();
  for (const alert of alerts) {
    const room = groupByArea ? (alert.state.attributes.area || otherLabel) : "";
    if (!groups.has(room)) groups.set(room, []);
    groups.get(room).push(alert);
  }
  return groups;
};

class AlertsAssistantCard extends HTMLElement {
  setConfig(config = {}) {
    this.config = { show_cleared: false, group_by_area: true, ...config };
    this.render();
  }

  set hass(hass) {
    this._hass = hass;
    this.render();
  }

  get hass() { return this._hass; }

  text(key) {
    const language = this._hass?.locale?.language?.toLowerCase().startsWith("pl") ? "pl" : "en";
    return key === "title" && this.config.title ? this.config.title : TEXT[language][key];
  }

  connectedCallback() {
    this._root = this.attachShadow({ mode: "open" });
    this._root.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-entity]");
      if (!button || !this._hass) return;
      this._hass.callService("alerts_assistant", button.dataset.service, {
        entity_id: button.dataset.entity,
      });
    });
    this.render();
  }

  disconnectedCallback() {
    clearInterval(this._timer);
  }

  render() {
    if (!this._root || !this._hass || !this.config) return;
    clearInterval(this._timer);
    const alerts = getAlerts(this._hass.states, this.config.show_cleared);
    const groups = groupAlerts(alerts, this.config.group_by_area, this.text("other"));
    const cards = [...groups].map(([room, members]) => `
      ${room ? `<h2>${escapeHtml(room)}</h2>` : ""}
      ${members.map((alert) => this.renderAlert(alert)).join("")}
    `).join("");
    const emptyText = this.config.show_cleared ? this.text("cleared") : this.text("empty");
    this._root.innerHTML = `<style>
      :host{display:block}ha-card{padding:16px;color:var(--primary-text-color)}
      h1{font-size:1.3em;margin:0 0 12px}h2{font-size:1em;margin:18px 0 6px;color:var(--secondary-text-color)}
      .row{display:flex;align-items:center;gap:12px;padding:10px 0;border-top:1px solid var(--divider-color)}
      .icon{font-size:1.3em}.body{flex:1;min-width:0}.name{font-weight:500}.meta{color:var(--secondary-text-color);font-size:.9em;margin-top:3px}
      button{background:var(--primary-color);color:var(--text-primary-color);border:0;border-radius:4px;padding:8px 12px;cursor:pointer}
      .ack{color:var(--success-color,var(--state-active-color))}.empty{color:var(--secondary-text-color);padding:12px 0}
    </style><ha-card><h1>${escapeHtml(this.config.title || this.text("title"))}</h1>${cards || `<div class="empty">${emptyText}</div>`}</ha-card>`;
    if (alerts.some((alert) => alert.active && alert.state.attributes.triggered_at)) {
      this._timer = setInterval(() => this.render(), 60000);
    }
  }

  renderAlert({ entity_id, state, active }) {
    const attrs = state.attributes;
    const name = attrs.friendly_name || entity_id;
    const acknowledged = state.state === "off" || attrs.acknowledged;
    const language = this._hass?.locale?.language || "en";
    const elapsed = active ? formatElapsed(attrs.triggered_at, Date.now(), language) : "";
    const status = !active ? this.text("resolved") : acknowledged ? this.text("acknowledged") : this.text("active");
    const action = active
      ? `<button data-entity="${escapeHtml(entity_id)}" data-service="${acknowledged ? "turn_on" : "turn_off"}">${this.text(acknowledged ? "rearm" : "ack")}</button>`
      : "";
    return `<div class="row"><span class="icon">${active ? (acknowledged ? "✓" : "⚠️") : "○"}</span>
      <div class="body"><div class="name">${escapeHtml(name)}</div>
      <div class="meta ${acknowledged ? "ack" : ""}">${status}${elapsed ? ` · ${elapsed}` : ""}</div></div>${action}</div>`;
  }

  getCardSize() { return 3; }
}

if (!customElements.get(CARD_TYPE)) customElements.define(CARD_TYPE, AlertsAssistantCard);
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === `custom:${CARD_TYPE}`)) {
  window.customCards.push({
    type: `custom:${CARD_TYPE}`,
    name: "Alerts Assistant",
    description: "Displays and acknowledges Alerts Assistant alerts, grouped by room.",
  });
}

window.AlertsAssistantCardInternals = { formatElapsed, escapeHtml, getAlerts, groupAlerts };
