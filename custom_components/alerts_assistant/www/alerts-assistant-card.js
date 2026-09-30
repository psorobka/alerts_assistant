const CARD_TYPE = "alerts-assistant-card";
const CARD_EDITOR_TYPE = "alerts-assistant-card-editor";

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
  en: { title: "Alerts", other: "Other", empty: "No active alerts", cleared: "No alerts", active: "Active", acknowledged: "ACK · Acknowledged", resolved: "OK", since: "Since", ack: "Acknowledge", rearm: "Re-arm", display: "Show alerts", activeOnly: "Active only", all: "All (including OK)" },
  pl: { title: "Alerty", other: "Pozostałe", empty: "Brak aktywnych alertów", cleared: "Brak alertów", active: "Aktywny", acknowledged: "ACK · Potwierdzony", resolved: "OK", since: "Od", ack: "Potwierdź", rearm: "Uzbrój ponownie", display: "Pokaż alerty", activeOnly: "Tylko aktywne", all: "Wszystkie (także OK)" },
};

const formatStarted = (started, language = "en") => {
  const timestamp = Date.parse(started);
  if (!Number.isFinite(timestamp)) return "";
  return new Intl.DateTimeFormat(language, { dateStyle: "short", timeStyle: "short" }).format(timestamp);
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
  static getConfigElement() { return document.createElement(CARD_EDITOR_TYPE); }

  static getStubConfig() { return { show_cleared: false }; }

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
    const started = active ? formatStarted(attrs.triggered_at, language) : "";
    const status = !active ? this.text("resolved") : acknowledged ? this.text("acknowledged") : this.text("active");
    const action = active
      ? `<button data-entity="${escapeHtml(entity_id)}" data-service="${acknowledged ? "turn_on" : "turn_off"}">${this.text(acknowledged ? "rearm" : "ack")}</button>`
      : "";
    return `<div class="row"><span class="icon">${active ? (acknowledged ? "✓" : "⚠️") : "○"}</span>
      <div class="body"><div class="name">${escapeHtml(name)}</div>
      <div class="meta ${acknowledged ? "ack" : ""}">${status}${elapsed ? ` · ${elapsed}` : ""}</div>
      ${started ? `<div class="meta">${this.text("since")}: ${escapeHtml(started)}</div>` : ""}</div>${action}</div>`;
  }

  getCardSize() { return 3; }
}

class AlertsAssistantCardEditor extends HTMLElement {
  setConfig(config) {
    this.config = config;
    this.render();
  }

  set hass(hass) {
    this._hass = hass;
    this.render();
  }

  connectedCallback() {
    this._root = this.attachShadow({ mode: "open" });
    this._root.addEventListener("change", (event) => {
      if (event.target.id !== "display") return;
      this.config = { ...this.config, show_cleared: event.target.value === "all" };
      this.dispatchEvent(new CustomEvent("config-changed", {
        detail: { config: this.config }, bubbles: true, composed: true,
      }));
    });
    this.render();
  }

  render() {
    if (!this._root || !this.config) return;
    const language = this._hass?.locale?.language?.toLowerCase().startsWith("pl") ? "pl" : "en";
    const text = TEXT[language];
    this._root.innerHTML = `<style>
      label{display:block;margin-bottom:8px;color:var(--primary-text-color)}
      select{width:100%;padding:10px;border:1px solid var(--divider-color);border-radius:4px;
        background:var(--card-background-color);color:var(--primary-text-color)}
    </style><label for="display">${text.display}</label>
      <select id="display"><option value="active">${text.activeOnly}</option>
      <option value="all">${text.all}</option></select>`;
    this._root.querySelector("select").value = this.config.show_cleared ? "all" : "active";
  }
}

if (!customElements.get(CARD_TYPE)) customElements.define(CARD_TYPE, AlertsAssistantCard);
if (!customElements.get(CARD_EDITOR_TYPE)) customElements.define(CARD_EDITOR_TYPE, AlertsAssistantCardEditor);
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === CARD_TYPE)) {
  window.customCards.push({
    type: CARD_TYPE,
    name: "Alerts Assistant",
    description: "Displays and acknowledges Alerts Assistant alerts, grouped by room.",
    preview: false,
  });
}

window.AlertsAssistantCardInternals = { formatElapsed, formatStarted, escapeHtml, getAlerts, groupAlerts };
