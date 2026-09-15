/* TankData management panel. Uses only the current Home Assistant connection. */
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const number = (value, digits = 1) => Number.isFinite(value) ? value.toLocaleString("de-DE", {maximumFractionDigits:digits}) : "–";
const kinds = {refill:"Befüllung",withdrawal:"Entnahme",observation:"Messbeobachtung",correction:"Bestandskorrektur",consumption:"Verbrauch",reset:"Korrekturbasis zurückgesetzt"};
const modes = {counter:"Kumulativer Zähler",flow:"Durchfluss",running:"Laufzustand",power:"Elektrische Leistung"};
const actions = {record_refill:"Befüllung",record_withdrawal:"Entnahme",record_observation:"Messbeobachtung",apply_correction:"Bestand korrigieren",recalculate:"Neu berechnen",reset_calibration:"Korrekturbasis zurücksetzen"};
const uuid = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), x => x.toString(16).padStart(2,"0")).join("");

class TankDataPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode:"open"});
    this.tanks = [];
    this.history = [];
    this.selected = null;
    this.busy = false;
    this.modal = null;
    this.shadowRoot.addEventListener("click", e => this.click(e));
    this.shadowRoot.addEventListener("submit", e => this.submit(e));
    this.shadowRoot.addEventListener("change", e => {
      if (e.target.name === "mode") this.consumerFields(e.target.value);
    });
  }
  set hass(value) {
    this._hass = value;
    if (!this.started && this.isConnected) this.start();
  }
  connectedCallback() { if (this._hass) this.start(); }
  disconnectedCallback() { clearInterval(this.timer); this.started = false; }
  start() {
    if (this.started) return;
    this.started = true;
    this.refresh();
    this.timer = setInterval(() => { if (!this.modal) this.refresh(); }, 15000);
  }
  async refresh() {
    if (this.fetching) return;
    this.fetching = true;
    try {
      const data = await this._hass.callWS({type:"ha_tankdata/get_tanks"});
      this.tanks = data.tanks;
      this.version = data.version;
      this.error = "";
      if (this.selected && !this.tanks.some(t => t.id === this.selected)) this.selected = null;
      if (this.selected && !this.olderHistory) await this.loadHistory();
      if (!this.modal) this.render();
    } catch (e) {
      this.error = e.message || "Verbindung zu Home Assistant fehlgeschlagen.";
      if (!this.modal) this.render();
    } finally { this.fetching = false; }
  }
  async loadHistory(more = false) {
    const id = this.selected;
    const tank = this.tanks.find(t => t.id === id);
    if (!tank || tank.status !== "loaded") { this.history = []; return; }
    const request = {type:"ha_tankdata/get_history",config_entry_id:id,limit:50};
    if (more) request.before = this.before;
    const result = await this._hass.callWS(request);
    if (this.selected !== id) return;
    this.history = more ? this.history.concat(result.events) : result.events;
    this.before = result.before;
    this.olderHistory = more;
  }
  render() {
    const tank = this.tanks.find(t => t.id === this.selected);
    this.shadowRoot.innerHTML = `<style>${this.styles()}</style>
      <header><button class="menu" data-action="menu" aria-label="Menü öffnen">☰</button><span class="brand">TankData</span><span class="version">${esc(this.version || "")}</span><a href="/config/integrations/integration/ha_tankdata">Integration</a></header>
      <main><div class="heading"><div><p class="eyebrow">BESTAND IM BLICK</p><h1>${tank ? esc(tank.name) : "Meine Tanks"}</h1><p class="muted">${tank ? "Bestand, Verbraucher und nachvollziehbare Buchungen." : "Alle Tankbestände an einem Ort."}</p></div><button class="primary" data-action="new-tank">＋ Tank hinzufügen</button></div>
      ${this.error ? `<p class="error" role="alert">${esc(this.error)} <button data-action="refresh">Erneut laden</button></p>` : ""}
      ${this.notice ? `<p class="notice" role="status">${esc(this.notice)}</p>` : ""}
      ${tank ? `<button class="back" data-action="overview">← Alle Tanks</button>${this.detail(tank)}` : `<div class="grid">${this.tanks.map(t => this.card(t)).join("")}</div>${this.tanks.length ? "" : `<section class="empty"><h2>Dein erster Tank</h2><p>Lege einen Tank mit Kapazität und gemessenem Bestand an.</p><button class="primary" data-action="new-tank">Tank einrichten</button></section>`}`}
      <footer>Bestände in Litern · Daten bleiben in Home Assistant · Verwaltung für Administratoren</footer></main><div id="dialog-host"></div>`;
  }
  card(t) {
    const loaded = t.status === "loaded";
    const percent = loaded ? Math.max(0,Math.min(100,t.percent)) : 0;
    return `<button class="tank-card" data-tank="${esc(t.id)}"><div class="card-top"><span class="tank-icon" aria-hidden="true">▤</span><span class="badge ${loaded ? "" : "warn"}">${loaded ? "Aktiv" : "Nicht geladen"}</span></div><h2>${esc(t.name)}</h2><div class="stock">${number(t.stock)} <small>L</small></div><div class="meter"><span style="width:${percent}%"></span></div><div class="card-bottom"><span>${number(t.percent)} % gefüllt</span><span>${number(t.capacity)} L Kapazität</span></div>${t.out_of_bounds ? '<p class="error">Bestand außerhalb der Tankgrenzen</p>' : ""}<p class="muted">${loaded ? `${t.consumers.length} Verbraucher · ${number(t.consumed,3)} L berechnet` : "In Geräte & Dienste aktivieren oder Fehler prüfen."}</p></button>`;
  }
  detail(t) {
    if (t.status !== "loaded") return `<section><h2>Tank nicht geladen</h2><p>Für diesen Tank sind derzeit keine Buchungen möglich.</p><a href="/config/integrations/integration/ha_tankdata">Geräte & Dienste öffnen</a></section>`;
    return `<div class="detail-grid">${this.card(t)}<section><h2>Bestand buchen</h2><p class="muted">Messungen dokumentieren, Lieferungen und Entnahmen erfassen.</p><div class="actions">${Object.entries(actions).map(([key,label]) => `<button data-book="${key}">${label}</button>`).join("")}</div>${t.device_id ? `<a class="device-link" href="/config/devices/device/${esc(t.device_id)}">Tankgerät in Home Assistant öffnen ↗</a>` : ""}</section></div>
      <section><div class="section-heading"><h2>Verbraucher</h2><button data-action="new-consumer">＋ Verbraucher hinzufügen</button></div>${t.consumers.length ? t.consumers.map(c => `<div class="consumer"><div><strong>${esc(c.name)}</strong><p class="muted">${esc(modes[c.config.mode])} · ${esc(c.config.entity_id)}${c.config.rate_lph && ["running","power"].includes(c.config.mode) ? ` · ${number(c.config.rate_lph,3)} L/h` : ""}</p></div><span class="badge ${c.valid ? "" : "warn"}">${c.valid ? "Quelle gültig" : "Quelle prüfen"}</span><button data-edit="${esc(c.id)}">Bearbeiten</button><button data-remove="${esc(c.id)}">Entfernen</button></div>`).join("") : '<p class="muted">Noch kein Verbraucher. Manuelle Buchungen sind bereits möglich.</p>'}</section>
      <section><div class="section-heading"><h2>Historie <small>${t.event_count} Ereignisse</small></h2><button data-action="history-refresh">Aktualisieren</button></div><p class="muted">Initialbestand als feste Basis gespeichert. Neueste Ereignisse zuerst.</p>${this.history.length ? `<div class="table-scroll"><table><thead><tr><th>Zeitpunkt</th><th>Ereignis</th><th>Menge / Bestand</th><th>Quelle</th></tr></thead><tbody>${this.history.map(e => `<tr><td>${esc(new Date(e.at).toLocaleString("de-DE"))}</td><td>${esc(kinds[e.kind] || e.kind)}</td><td>${e.kind === "reset" ? "–" : `${number(e.liters,3)} L`}</td><td>${esc(t.consumers.find(c => c.id === e.source_id)?.name || (e.source_id ? "Früherer Verbraucher" : "Manuell"))}</td></tr>`).join("")}</tbody></table></div>${this.before ? '<button data-action="more-history">Ältere Ereignisse laden</button>' : ""}` : '<p class="muted">Noch keine Ereignisse seit der Einrichtung.</p>'}</section>`;
  }
  async click(event) {
    const button = event.target.closest("button");
    if (!button || this.busy) return;
    const action = button.dataset.action;
    try {
      if (button.dataset.tank) { this.selected = button.dataset.tank; this.olderHistory = false; await this.loadHistory(); this.render(); }
      else if (button.dataset.book) this.openDialog("book",button.dataset.book);
      else if (button.dataset.edit) this.openDialog("consumer",button.dataset.edit);
      else if (button.dataset.remove) this.openDialog("remove",button.dataset.remove);
      else if (action === "menu") this.dispatchEvent(new Event("hass-toggle-menu",{bubbles:true,composed:true}));
      else if (action === "overview") { this.selected = null; this.render(); }
      else if (action === "new-tank") this.openDialog("tank");
      else if (action === "new-consumer") this.openDialog("consumer");
      else if (action === "close") this.closeDialog();
      else if (action === "more-history") { await this.loadHistory(true); this.render(); }
      else if (action === "history-refresh") { this.olderHistory = false; await this.refresh(); }
      else if (action === "refresh") await this.refresh();
    } catch (e) { this.error = e.message || "Vorgang fehlgeschlagen."; this.render(); }
  }
  input(name,label,type="number",value="",extra="") {
    return `<label>${label}<input name="${name}" type="${type}" value="${esc(value)}" ${extra} required></label>`;
  }
  openDialog(kind,key) {
    this.modal = {kind,key,tank:this.selected};
    this.pendingBooking = null;
    this.flow = null;
    const tank = this.tanks.find(t => t.id === this.selected);
    let title, fields;
    if (kind === "tank") {
      title = "Tank hinzufügen";
      fields = this.input("name","Name","text","","maxlength=100") + this.input("capacity","Kapazität in Litern","number","","min=0.001 step=any") + this.input("initial","Gemessener Bestand in Litern","number","","min=0 step=any");
    } else if (kind === "consumer") {
      const c = tank.consumers.find(c => c.id === key)?.config || {};
      title = key ? "Verbraucher bearbeiten" : "Verbraucher hinzufügen";
      fields = this.input("name","Name","text",c.name || "","maxlength=100") + `<label>Verbrauchsquelle<select name="mode">${Object.entries(modes).map(([v,l]) => `<option value="${v}" ${v === (c.mode || "counter") ? "selected" : ""}>${l}</option>`).join("")}</select></label>` + this.input("entity_id","Quell-Entity","text",c.entity_id || "",'list="source-entities"') + `<datalist id="source-entities">${Object.keys(this._hass.states).filter(id => /^(sensor|binary_sensor|switch|input_boolean)\./.test(id)).map(id => `<option value="${esc(id)}">${esc(this._hass.states[id].attributes.friendly_name || id)}</option>`).join("")}</datalist><div id="rate-fields">${this.input("rate_lph","Durchsatz in L/h","number",c.rate_lph || 1,"min=0.001 step=any")}</div><div id="power-fields">${this.input("on_threshold_w","Ein ab Leistung (W)","number",c.on_threshold_w ?? 100.1,"min=0 step=any")}${this.input("off_threshold_w","Aus bis Leistung (W)","number",c.off_threshold_w ?? 100,"min=0 step=any")}</div><details><summary>Erweiterte Einstellungen</summary>${this.input("max_gap_seconds","Maximale Datenlücke (Sekunden)","number",c.max_gap_seconds || 3600,"min=0.001 step=any")}${this.input("max_rate_lph","Maximal plausible Rate (L/h)","number",c.max_rate_lph || 100,"min=0.001 step=any")}</details><p class="muted">Änderungen wirken auf neue Intervalle. Die Historie bleibt erhalten.</p>`;
    } else if (kind === "remove") {
      title = "Verbraucher entfernen";
      fields = `<p>${esc(tank.consumers.find(c => c.id === key)?.name)} entfernen? Die bisherigen Verbrauchsbuchungen bleiben erhalten.</p>`;
    } else {
      title = actions[key];
      const notes = {record_observation:"Dokumentiert den gemessenen Bestand. Der berechnete Bestand bleibt unverändert.",apply_correction:"Setzt den aktuellen Bestand auf den angegebenen Literwert.",reset_calibration:"Hebt die Wirkung bisheriger Bestandskorrekturen auf. Die Historie bleibt erhalten; der angezeigte Bestand kann sich ändern.",recalculate:"Berechnet den Bestand erneut aus der unveränderten Historie."};
      fields = `<p>${esc(notes[key] || "Die Menge wird als neues Ereignis gebucht.")}</p>` + (["recalculate","reset_calibration"].includes(key) ? "" : this.input("liters",["apply_correction","record_observation"].includes(key) ? "Gemessener Bestand (L)" : "Menge (L)","number","","min=0 step=any"));
    }
    this.shadowRoot.getElementById("dialog-host").innerHTML = `<dialog aria-labelledby="dialog-title"><form><h2 id="dialog-title">${esc(title)}</h2><p class="muted">${esc(kind === "tank" ? "Ein Tank entspricht einem Gerät in Home Assistant." : tank.name)}</p>${fields}<p class="error" id="form-error" role="alert"></p><div class="dialog-actions"><button type="button" data-action="close">Abbrechen</button><button type="submit" class="primary">${kind === "book" ? "Jetzt ausführen" : "Speichern"}</button></div></form></dialog>`;
    const dialog = this.shadowRoot.querySelector("dialog");
    dialog.addEventListener("cancel",e => { e.preventDefault(); if (!this.busy) this.closeDialog(); });
    dialog.showModal();
    if (kind === "consumer") this.consumerFields(this.shadowRoot.querySelector('[name="mode"]').value);
  }
  consumerFields(mode) {
    for (const [id,show] of [["rate-fields",["power","running"].includes(mode)],["power-fields",mode === "power"]]) {
      const element = this.shadowRoot.getElementById(id);
      element.hidden = !show;
      element.querySelectorAll("input").forEach(input => input.disabled = !show);
    }
  }
  closeDialog() {
    if (this.flow) this._hass.callApi("DELETE",`${this.flow.path}/${this.flow.id}`).catch(() => {});
    this.modal = null;
    this.flow = null;
    this.render();
  }
  async submit(event) {
    event.preventDefault();
    if (this.busy || !this.modal) return;
    const form = event.target;
    const data = Object.fromEntries(new FormData(form));
    for (const k of ["capacity","initial","liters","rate_lph","max_gap_seconds","max_rate_lph","on_threshold_w","off_threshold_w"]) if (k in data) data[k] = Number(data[k]);
    this.busy = true;
    form.querySelectorAll("button").forEach(b => b.disabled = true);
    try {
      const {kind,key,tank} = this.modal;
      if (kind === "book") {
        if (!this.pendingBooking) this.pendingBooking = {config_entry_id:tank,...data,...(key === "recalculate" ? {} : {event_id:`panel-${uuid()}`})};
        await this._hass.callService("ha_tankdata",key,this.pendingBooking);
      } else if (kind === "remove") {
        await this._hass.callWS({type:"config_entries/subentries/delete",entry_id:tank,subentry_id:key});
      } else {
        const path = kind === "tank" ? "config/config_entries/flow" : "config/config_entries/subentries/flow";
        if (!this.flow) {
          const initial = kind === "tank" ? {handler:"ha_tankdata",show_advanced_options:false} : {handler:[tank,"consumer"],...(key ? {subentry_id:key} : {})};
          const flow = await this._hass.callApi("POST",path,initial);
          if (flow.type !== "form") throw new Error("Die Einrichtung konnte nicht gestartet werden.");
          this.flow = {path,id:flow.flow_id};
        }
        const result = await this._hass.callApi("POST",`${this.flow.path}/${this.flow.id}`,data);
        if (result.type === "form") throw new Error("Bitte Angaben prüfen: Kapazität, Bestand, Quell-Entity, Durchsatz und Schwellen müssen zusammenpassen.");
        if (!(result.type === "create_entry" || (kind === "consumer" && key && result.type === "abort" && result.reason === "reconfigure_successful"))) throw new Error(result.reason || "Einrichtung fehlgeschlagen.");
        this.flow = null;
        if (kind === "tank") this.selected = result.result.entry_id;
      }
      this.modal = null;
      this.olderHistory = false;
      this.notice = "Gespeichert. Die Anzeige wird aktualisiert.";
      await this.refresh();
      setTimeout(() => { if (this.isConnected && !this.modal) this.refresh(); }, 1000);
    } catch (e) {
      this.shadowRoot.getElementById("form-error").textContent = e.message || "Speichern fehlgeschlagen. Bitte Verbindung und Eingaben prüfen.";
      if (this.pendingBooking) {
        form.querySelectorAll("input").forEach(input => input.disabled = true);
        form.querySelector('button[type="submit"]').textContent = "Dieselbe Buchung erneut versuchen";
      }
    } finally {
      this.busy = false;
      form.querySelectorAll("button").forEach(b => b.disabled = false);
    }
  }
  styles() { return `
    :host{display:block;height:100%;overflow:auto;background:var(--primary-background-color,#f5f7fa);color:var(--primary-text-color,#192a35);font-family:var(--paper-font-body1_-_font-family,system-ui)}*{box-sizing:border-box}header{height:64px;padding:0 28px;display:flex;align-items:center;gap:16px;background:var(--card-background-color,#fff);border-bottom:1px solid var(--divider-color,#e1e7ed)}header a{margin-left:auto}.brand{font-weight:750;font-size:21px}.version{font-size:12px;color:var(--secondary-text-color,#64748b)}main{max-width:1240px;margin:auto;padding:36px 28px}h1{font-size:34px;margin:4px 0 8px;letter-spacing:-1px}h2{font-size:19px;margin:0 0 16px}small{font-size:.6em;font-weight:500}.heading,.section-heading{display:flex;align-items:center;justify-content:space-between;gap:20px}.eyebrow{font-size:11px;letter-spacing:2px;color:#16877c;font-weight:750}.muted,footer{color:var(--secondary-text-color,#64748b);font-size:14px;line-height:1.6}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:22px;margin-top:30px}.detail-grid{display:grid;grid-template-columns:1fr 1.5fr;gap:22px}.tank-card,section{background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#e1e7ed);border-radius:18px;padding:26px;margin-bottom:22px}.tank-card{text-align:left;width:100%;color:inherit;font:inherit;cursor:pointer}.tank-card:hover{border-color:#16877c}.card-top,.card-bottom{display:flex;justify-content:space-between;align-items:center;gap:12px}.card-top{margin-bottom:20px}.card-bottom{font-size:13px;color:var(--secondary-text-color,#64748b)}.tank-icon{color:#16877c;font-size:30px}.badge{border-radius:20px;background:#16877c18;color:var(--primary-text-color,#126f65);padding:6px 10px;font-size:12px;white-space:nowrap}.warn{background:#e5a42822;color:var(--warning-color,#996d0b)}.stock{font-size:42px;font-weight:700;letter-spacing:-1px}.meter{height:10px;background:var(--divider-color,#e9eef2);border-radius:8px;margin:22px 0 12px;overflow:hidden}.meter span{display:block;height:100%;background:#16877c;border-radius:8px}button{border:1px solid var(--divider-color,#d5dee7);border-radius:9px;background:var(--card-background-color,#fff);color:inherit;padding:11px 15px;font:inherit;font-size:14px;cursor:pointer}button:hover{filter:brightness(.97)}button:focus-visible,a:focus-visible{outline:3px solid #16877c;outline-offset:3px}button:disabled{opacity:.6;cursor:wait}.primary{background:#137e73;color:white;border-color:#137e73;font-weight:600}.menu{border:0;font-size:20px;padding:8px}.actions{display:flex;gap:10px;flex-wrap:wrap}.device-link{display:inline-block;margin-top:24px}a{color:var(--primary-color,#137e73);font-size:14px;text-decoration:none}.back{margin:8px 0 22px;border:0;background:none;padding-left:0}.consumer{display:flex;align-items:center;gap:12px;padding:18px 0;border-top:1px solid var(--divider-color,#e1e7ed)}.consumer>div{flex:1;min-width:0}.consumer p{margin:6px 0;overflow-wrap:anywhere}.table-scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px;text-align:left}th{color:var(--secondary-text-color,#64748b);font-size:12px}td,th{padding:14px 10px;border-bottom:1px solid var(--divider-color,#e1e7ed);white-space:nowrap}.error{color:var(--error-color,#b3261e);line-height:1.5}.notice{background:#16877c18;padding:14px;border-radius:10px}.empty{text-align:center;margin-top:30px;padding:60px 20px}footer{margin:32px 0;font-size:12px}dialog{background:var(--card-background-color,#fff);color:inherit;border:0;border-radius:18px;padding:28px;width:min(540px,calc(100% - 24px));max-height:90vh;overflow:auto;box-shadow:0 20px 80px #0005}dialog::backdrop{background:#0007}label{display:block;font-size:14px;margin:18px 0}input,select{display:block;width:100%;margin-top:7px;padding:12px;border:1px solid var(--divider-color,#c6d0d9);border-radius:8px;background:var(--primary-background-color,#fff);color:inherit;font:inherit}.dialog-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:25px}summary{cursor:pointer;font-size:14px;padding:14px 0}[hidden]{display:none!important}@media(max-width:700px){header{padding:0 12px}main{padding:22px 16px}h1{font-size:28px}.heading{align-items:flex-start;flex-direction:column;gap:8px}.detail-grid{grid-template-columns:1fr}.consumer{flex-wrap:wrap}.consumer>div{flex-basis:100%}section,.tank-card{padding:20px}.section-heading{align-items:flex-start;flex-wrap:wrap}.stock{font-size:36px}}
  `; }
}
if (!customElements.get("tankdata-panel")) customElements.define("tankdata-panel", TankDataPanel);
