/* TankData management panel. Uses only the current Home Assistant connection. */
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const number = (value, digits = 1) => Number.isFinite(value) ? value.toLocaleString("de-DE", {maximumFractionDigits:digits}) : "–";
const kinds = {refill:"Befüllung",withdrawal:"Entnahme",observation:"Messbeobachtung",correction:"Bestandskorrektur",consumption:"Verbrauch",reset:"Korrekturbasis zurückgesetzt"};
const modes = {counter:"Kumulativer Zähler",flow:"Durchfluss",running:"Laufzustand",power:"Elektrische Leistung"};
const actions = {record_refill:"Befüllen",apply_correction:"Bestand korrigieren"};
const shapes = {rectangle:"Quader",vertical_cylinder:"Zylinder stehend",horizontal_cylinder:"Zylinder liegend",sphere:"Kugel",table:"Peiltabelle"};
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
      if (e.target.name === "unit") this.measurementFields(e.target.value);
      if (e.target.name === "report-anchor") this.changeReportAnchor(e.target);
    });
  }
  set hass(value) {
    this._hass = value;
    if (!this.started && this.isConnected) this.start();
  }
  set narrow(value) {
    this._narrow = value;
    const bar = this.shadowRoot.querySelector("ha-top-app-bar-fixed");
    if (bar) bar.narrow = value;
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
      if (this.selected) await this.loadHistory();
      if (this.selected && this.reportTank === this.selected && !this.reportLoading) await this.loadReport(this.reportSelection);
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
    const request = {type:"ha_tankdata/get_history",config_entry_id:id,limit:50,grouped:true};
    if (more) request.before = this.before;
    let result = await this._hass.callWS(request);
    let rows = result.events;
    if (!more) {
      while (result.before && rows.length < this.history.length) {
        result = await this._hass.callWS({...request,before:result.before});
        rows = rows.concat(result.events);
      }
    }
    if (this.selected !== id) return;
    this.history = more ? this.history.concat(rows) : rows;
    this.historyCount = result.count;
    this.before = result.before;
    this.olderHistory = more;
  }
  historyView(t) {
    const date = value => esc(new Date(value).toLocaleString("de-DE",{timeZone:this._hass.config?.time_zone}));
    const duration = seconds => `${Math.floor(seconds/3600)} h ${Math.floor(seconds%3600/60)} min ${Math.floor(seconds%60)} s`;
    const source = e => esc(t.consumers.find(c=>c.id===e.source_id)?.name || (e.source_id?"Früherer Verbraucher":"Manuell"));
    const rawRow = e => `<tr><td>${date(e.start||e.at)}${e.end?`<br>bis ${date(e.end)}`:""}</td><td>${esc(kinds[e.kind]||e.kind)}</td><td>${e.kind==="reset"?"–":`${number(e.liters,3)} L`}</td><td>${source(e)}</td><td>${e.runtime_seconds?duration(e.runtime_seconds):e.total_cost!==undefined?`${number(e.total_cost,2)} €`:e.measurement?`${number(e.measurement.value,2)} ${esc(e.measurement.unit)}`:"–"}</td></tr>`;
    const rows = this.history.map(e=>{
      if(e.kind!=="run") return rawRow(e);
      return `<tr><td>${date(e.start)}<br>${e.status==="running"?"Bislang":e.status==="finished"?"Ende":"Erfasst bis"} ${date(e.end)}</td><td>Lauf <span class="badge ${e.status==="interrupted"?"warn":""}">${{running:"Läuft",finished:"Beendet",interrupted:"Unterbrochen"}[e.status]}</span></td><td>${number(e.liters,3)} L</td><td>${source(e)}</td><td>${duration(e.runtime_seconds)}</td></tr>`;
    }).join("");
    return `<section><div class="section-heading"><h2>Historie <small>${this.historyCount??this.history.length} ${(this.historyCount??this.history.length)===1?"Eintrag":"Einträge"}</small></h2><button data-action="history-refresh">Aktualisieren</button></div>${rows?`<div class="table-scroll"><table><thead><tr><th>Zeitraum</th><th>Ereignis</th><th>Menge / Bestand</th><th>Quelle</th><th>Laufzeit / Details</th></tr></thead><tbody>${rows}</tbody></table></div>${this.before?'<button data-action="more-history">Ältere laden</button>':""}`:'<p class="muted">Keine Buchungen.</p>'}</section>`;
  }
  render() {
    const tank = this.tanks.find(t => t.id === this.selected);
    // Keep an open native calendar mounted during refresh.
    if (this.shadowRoot.activeElement?.name === "report-anchor") return;
    // Keep HA's header and scroll container mounted during periodic refreshes.
    if (!this.shadowRoot.querySelector("ha-top-app-bar-fixed")) {
      this.shadowRoot.innerHTML = `<style>${this.styles()}</style>
        <ha-top-app-bar-fixed>
          <span slot="title">TankData</span>
          <a slot="actionItems" class="integration-link" href="/config/integrations/integration/ha_tankdata">Integration</a>
          <div id="panel-content"></div>
        </ha-top-app-bar-fixed><div id="dialog-host"></div>`;
      this.shadowRoot.querySelector("ha-top-app-bar-fixed").narrow = Boolean(this._narrow);
    }
    this.shadowRoot.querySelector("#panel-content").innerHTML = `
      <main>${tank ? `<button class="back" data-action="overview">← Alle Tanks</button>` : ""}<div class="heading"><div><h1>${tank ? esc(tank.name) : "Tanks"}</h1></div>${tank ? (tank.device_id ? `<a class="ha-device" href="/config/devices/device/${esc(tank.device_id)}">In Home Assistant öffnen ↗</a>` : "") : `<button class="primary" data-action="new-tank">＋ Tank hinzufügen</button>`}</div>
      ${this.error ? `<p class="error" role="alert">${esc(this.error)} <button data-action="refresh">Erneut laden</button></p>` : ""}
      ${this.notice ? `<p class="notice" role="status">${esc(this.notice)}</p>` : ""}
      ${tank ? `${this.detail(tank)}` : `<div class="grid">${this.tanks.map(t => this.card(t)).join("")}</div>${this.tanks.length ? "" : `<section class="empty"><p>Noch keine Tanks.</p></section>`}`}
      </main>`;
  }
  card(t) {
    const loaded = t.status === "loaded";
    const percent = loaded ? Math.max(0,Math.min(100,t.percent)) : 0;
    return `<button class="tank-card" data-tank="${esc(t.id)}">${loaded ? "" : '<div class="card-top"><span class="badge warn">Nicht geladen</span></div>'}<h2>${esc(t.name)}</h2>${this.tankVisual(t)}<div class="stock">${number(t.stock)} <small>L</small></div><div class="meter"><span style="width:${percent}%"></span></div><div class="card-bottom"><span>${number(t.percent)} % gefüllt</span><span>${number(t.capacity)} L Kapazität</span></div>${t.out_of_bounds ? '<p class="error">Bestand außerhalb der Tankgrenzen</p>' : ""}<p class="muted">${loaded ? `${t.consumers.length} Verbraucher` : "In Geräte & Dienste aktivieren oder Fehler prüfen."}</p></button>`;
  }
  detail(t) {
    if (t.status !== "loaded") return `<section><h2>Tank nicht geladen</h2><p>Für diesen Tank sind derzeit keine Buchungen möglich.</p><a href="/config/integrations/integration/ha_tankdata">Geräte & Dienste öffnen</a></section>`;
    return `<section class="stock-summary"><div class="tank-scene">${this.tankVisual(t)}</div><div class="stock-content"><p class="muted stock-label">Bestand</p><div class="stock">${number(t.stock)} <small>L</small><span class="stock-percent">${number(t.percent)} %</span></div><p class="muted">Kapazität ${number(t.capacity)} L · ${t.consumers.length} Verbraucher</p>${t.out_of_bounds ? '<p class="error">Bestand außerhalb der Tankgrenzen</p>' : ""}<div class="actions">${Object.entries(actions).map(([key,label]) => `<button class="${key === "record_refill" ? "primary" : ""}" data-book="${key}">${label}</button>`).join("")}</div></div></section>
      ${this.analysisView(t)}<section><div class="section-heading"><h2>Verbraucher</h2><button data-action="new-consumer">＋ Verbraucher hinzufügen</button></div>${t.consumers.length ? t.consumers.map(c => `<div class="consumer"><div><strong>${esc(c.name)}</strong><p class="muted">${esc(modes[c.config.mode])} · ${esc(this._hass.states[c.config.entity_id]?.attributes.friendly_name || c.config.entity_id)}${c.config.rate_lph && ["running","power"].includes(c.config.mode) ? ` · ${number(c.config.rate_lph,3)} L/h` : ""}</p></div><span class="badge ${c.valid ? "" : "warn"}">${c.running === true ? "An" : c.running === false ? "Aus" : "Unbekannt"}</span><button data-edit="${esc(c.id)}">Bearbeiten</button><button data-remove="${esc(c.id)}">Entfernen</button></div>`).join("") : '<p class="muted">Keine Verbraucher.</p>'}</section>
      ${this.historyView(t)}`;
  }

  tankVisual(t) {
    if (!t.settings) return "";
    // Orthographic isometric projection. Clip the physical solid at the
    // volume-derived height before projecting; liquid stays level in 3D.
    const shape=t.settings.geometry.shape, f=Math.max(0,Math.min(1,t.fill_height||0));
    const project=([x,y,z])=>[180+64*.8660254*(x-y),176+64*(.5*(x+y)-z)];
    const points=poly=>poly.map(p=>project(p).map(v=>v.toFixed(2)).join(",")).join(" ");
    const polygon=(poly,fill,opacity=1)=>`<polygon points="${points(poly)}" fill="${fill}" opacity="${opacity}"/>`;
    const ring=(fn,n=64)=>Array.from({length:n},(_,i)=>fn(2*Math.PI*i/n));
    const faces=[]; let top, height, outline=[];
    const bridge=(a,b)=>{for(let i=0;i<a.length;i++){let j=(i+1)%a.length;faces.push([a[i],a[j],b[j],b[i]]);}};
    if(shape==="horizontal_cylinder") {
      height=1.4;
      const end=x=>ring(a=>[x,.7*Math.cos(a),.7+.7*Math.sin(a)]);
      const a=end(-1.3),b=end(1.3); bridge(a,b);faces.push(a,b);
      const z=height*f,w=Math.sqrt(Math.max(0,.49-(z-.7)**2));
      top=[[-1.3,-w,z],[1.3,-w,z],[1.3,w,z],[-1.3,w,z]];
      outline=[a,b,[a[56],b[56]],[a[24],b[24]]];
    } else if(shape==="vertical_cylinder") {
      height=1.9;
      const end=z=>ring(a=>[.8*Math.cos(a),.8*Math.sin(a),z]);
      const a=end(0),b=end(height);bridge(a,b);faces.push(a,b);top=end(height*f);
      outline=[a,b,[a[56],b[56]],[a[24],b[24]]];
    } else if(shape==="sphere") {
      height=1.9;
      const latitude=a=>ring(b=>[.95*Math.cos(a)*Math.cos(b),.95*Math.cos(a)*Math.sin(b),.95+.95*Math.sin(a)],48);
      for(let i=0;i<32;i++)bridge(latitude(-Math.PI/2+i*Math.PI/32),latitude(-Math.PI/2+(i+1)*Math.PI/32));
      const z=height*f,r=Math.sqrt(Math.max(0,.95**2-(z-.95)**2));
      top=ring(a=>[r*Math.cos(a),r*Math.sin(a),z]);
    } else {
      height=1.5;
      const end=z=>[[-1,-.7,z],[1,-.7,z],[1,.7,z],[-1,.7,z]];
      const a=end(0),b=end(height);bridge(a,b);faces.push(a,b);top=end(height*f);
      outline=[a,b,...a.map((p,i)=>[p,b[i]])];
    }
    const level=height*f;
    const clip=poly=>{
      const result=[];
      for(let i=0;i<poly.length;i++){
        const a=poly[i],b=poly[(i+1)%poly.length],inside=a[2]<=level,other=b[2]<=level;
        if(inside)result.push(a);
        if(inside!==other){const u=(level-a[2])/(b[2]-a[2]);result.push(a.map((v,k)=>v+u*(b[k]-v)));}
      }
      return result;
    };
    const depth=poly=>poly.reduce((sum,p)=>sum+p[0]+p[1]+p[2],0)/poly.length;
    const ordered=faces.slice().sort((a,b)=>depth(a)-depth(b));
    const fluid=f>0?ordered.map(clip).filter(p=>p.length>=3):[];
    if(f>0)fluid.push(top);
    fluid.sort((a,b)=>depth(a)-depth(b));
    const shade=poly=>{
      if(poly===top)return "#68d8c4";
      const center=poly.reduce((sum,p)=>sum+p[0]-p[1],0)/poly.length;
      return `hsl(171 58% ${Math.max(24,Math.min(43,34+center*5))}%)`;
    };
    const lines=outline.map(poly=>`<polyline points="${points(poly.length>2?[...poly,poly[0]]:poly)}" fill="none" stroke="#98c8c5" stroke-width="1.2" opacity=".6"/>`).join("");
    return `<svg class="tank-visual" viewBox="0 0 360 250" role="img" aria-label="${esc(shapes[shape])}, isometrisch: ${number(t.percent)} Prozent Volumen"><ellipse cx="180" cy="218" rx="116" ry="20" fill="#071c23" opacity=".15"/>${ordered.map(p=>polygon(p,"#a4d0d2",.055)).join("")}${fluid.map(p=>polygon(p,shade(p),.94)).join("")}${lines}${shape==="sphere"?'<circle cx="180" cy="115.2" r="74.46" fill="none" stroke="#98c8c5" stroke-width="1.4" opacity=".6"/>':""}</svg>`;
  }
  async loadReport(selection) {
    const tank = this.selected, request = (this.reportRequest || 0) + 1;
    this.reportRequest = request;
    this.reportLoading = true;
    let report;
    try { report = await this._hass.callWS({type:"ha_tankdata/manage",config_entry_id:tank,operation:"statistics",parameters:selection}); }
    finally { if (this.reportRequest === request) this.reportLoading = false; }
    if (this.selected !== tank || this.reportRequest !== request) return;
    this.report = report;
    this.reportTank = tank;
    this.reportSelection = {...selection};
    this.error = "";
  }
  async changeReportAnchor(input) {
    if (!input.value || !input.checkValidity()) return;
    const tank = this.tanks.find(t => t.id === this.selected);
    const report = this.reportTank === tank.id ? this.report : tank.statistics;
    const anchor = report.period === "month" ? `${input.value}-01` : report.period === "year" ? `${input.value}-01-01` : input.value;
    input.blur();
    try { await this.loadReport({period:report.period,anchor}); }
    catch (e) { this.error = e.message || "Auswertung konnte nicht geladen werden."; }
    this.render();
  }
  reportControls(r) {
    if (r.period === "all") return `<p class="period-title">${esc(r.start.slice(0,4))}–${esc(r.end.slice(0,4))}</p>`;
    const year = Number(r.anchor.slice(0,4));
    let picker;
    if (r.period === "year") {
      const first = Math.min(year, Number(r.earliest.slice(0,4))), last = Math.max(year, Number(r.today.slice(0,4)));
      picker = `<label>Jahr<select name="report-anchor">${Array.from({length:last-first+1},(_,i)=>last-i).map(y=>`<option ${y===year?"selected":""}>${y}</option>`).join("")}</select></label>`;
    } else {
      const month = r.period === "month";
      picker = `<label>${month?"Monat":r.period==="week"?"Woche wählen":"Tag"}<input name="report-anchor" type="${month?"month":"date"}" value="${esc(month?r.anchor.slice(0,7):r.anchor)}" max="${month?r.today.slice(0,7):r.today}" required></label>`;
    }
    const date = value => new Date(`${value}T12:00:00Z`).toLocaleDateString("de-DE",{timeZone:"UTC"});
    return `<div class="period-picker"><button data-action="period-previous" aria-label="Vorheriger Zeitraum">‹</button>${picker}<button data-action="period-next" aria-label="Nächster Zeitraum" ${r.end>=r.today?"disabled":""}>›</button><button data-action="period-current">${{day:"Heute",week:"Diese Woche",month:"Dieser Monat",year:"Dieses Jahr"}[r.period]}</button></div><p class="period-title">${r.period==="day"?date(r.start):`${date(r.start)} – ${date(r.end)}`}</p>`;
  }
  bucketLabel(d,r,long=false) {
    const date = new Date(d.date.length===10 ? `${d.date}T12:00:00Z` : d.date);
    const opts = {timeZone:r.granularity==="hour"?r.timezone:"UTC"};
    if (r.granularity==="hour") return date.toLocaleTimeString("de-DE",{...opts,hour:"2-digit",minute:"2-digit",...(r.days.length!==24?{timeZoneName:"short"}:{})});
    if (r.granularity==="year") return d.date.slice(0,4);
    if (r.granularity==="month") return date.toLocaleDateString("de-DE",{...opts,month:long?"long":"short"});
    return date.toLocaleDateString("de-DE",{...opts,...(r.period==="week"?{weekday:"short"}:{}),...((long||r.period!=="week")?{day:"2-digit"}:{}),...(long?{month:"2-digit"}:{})});
  }
  analysisView(t) {
    const r=this.reportTank===t.id ? this.report : t.statistics, f=t.forecast;
    if (!r) return "";
    const max=Math.max(1,...r.days.map(d=>d.liters));
    const proposals=t.proposals.filter(p=>p.status==="pending");
    const content = `<section><div class="section-heading"><h2>Auswertung</h2><button data-action="settings">Einstellungen</button></div>
      <div class="actions period-tabs">${[["day",r.period==="day"&&r.anchor!==r.today?"Tag":"Heute"],["week","Woche"],["month","Monat"],["year","Jahr"],["all","Gesamt"]].map(([p,label])=>`<button data-period="${p}" aria-pressed="${r.period===p}" class="${r.period===p?"primary":""}">${label}</button>`).join("")}</div>
      ${this.reportControls(r)}
      ${t.consumers.length && r.days.some(d=>!d.future&&(d.coverage===null||d.coverage<.99)) ? '<p><span class="badge warn">Messdaten unvollständig</span></p>' : ""}
      <div class="metrics"><div><strong>${number(r.liters,2)} L</strong><span>Verbrauch</span></div><div><strong>${number(r.cost,2)} €</strong><span>Verbrauchskosten</span></div><div><strong>${number(r.runtime_hours,2)} h</strong><span>Laufzeit</span></div><div><strong>${number(r.inventory_value,2)} €</strong><span>Aktueller Bestandswert</span></div></div>
      <div class="chart-scroll"><div class="calendar-chart ${r.days.length>12?"dense":r.days.length>7?"medium":""}" role="group" aria-label="${{hour:"Stündlicher",day:"Täglicher",month:"Monatlicher",year:"Jährlicher"}[r.granularity]} Verbrauch in Litern">${r.days.map((d,i)=>`<button class="calendar-slot" data-chart-index="${i}" title="${esc(this.bucketLabel(d,r,true))}: ${d.future?"Noch ausstehend":`${number(d.liters,2)} L; Datenabdeckung ${number(d.coverage===null?null:d.coverage*100)} %`}"><div class="bar-space">${d.future?"":`<div class="bar" style="height:${Math.max(1,d.liters/max*120)}px;opacity:${d.coverage>=.99?1:.4}"></div>`}</div><span>${esc(this.bucketLabel(d,r))}</span></button>`).join("")}</div><p class="chart-value muted" role="status" aria-live="polite"></p></div>
      <p class="muted">Aktueller Mischpreis ${number(r.unit_price,3)} €/L</p>
      <details><summary>${{hour:"Stundenwerte",day:"Tageswerte",month:"Monatswerte",year:"Jahreswerte"}[r.granularity]}</summary><p class="muted">Blasse Balken kennzeichnen Datenlücken. Kosten ohne Preisangabe sind unbekannt.</p><div class="table-scroll"><table><thead><tr><th>Zeitraum</th><th>Verbrauch</th><th>Laufzeit</th><th>Kosten</th><th>Abdeckung</th></tr></thead><tbody>${r.days.map(d=>`<tr><td>${esc(this.bucketLabel(d,r,true))}</td><td>${d.future?"–":`${number(d.liters,2)} L`}</td><td>${d.future?"–":`${number(d.runtime_hours,2)} h`}</td><td>${d.future?"–":`${number(d.cost,2)} €`}</td><td>${number(d.coverage===null?null:d.coverage*100)} %</td></tr>`).join("")}</tbody></table></div></details>
      <details><summary>Verbrauch je Gerät</summary>${Object.entries(r.by_source).map(([sid,value])=>`<p>${esc(t.consumers.find(c=>c.id===sid)?.name||"Früherer Verbraucher")}: ${number(value,2)} L</p>`).join("")||"Kein Verbrauch erfasst."}</details><h2 class="forecast-title">Prognose</h2>${f.available?`<div class="metrics"><div><strong>${number(f.next_7)} L</strong><span>Nächste 7 Tage</span></div><div><strong>${number(f.next_30)} L</strong><span>Nächste 30 Tage</span></div><div><strong>${esc(f.reserve_date||"–")}</strong><span>Reserve erreicht</span></div><div><strong>${esc(f.empty_date||"–")}</strong><span>Voraussichtlich leer</span></div></div><details><summary>Berechnungsgrundlage</summary><p class="muted">${esc(f.method)} ${f.sample_days} Messtage. Schwankungsbereich: ${number(f.low_30)}–${number(f.high_30)} L in 30 Tagen; keine garantierte Spanne.</p></details>`:`<p class="muted">${esc(f.reason)}</p>`}
      </section><section><h2>Kalibrierung</h2>
      ${proposals.length?proposals.map(p=>`<article class="proposal"><h3>${esc(t.consumers.find(c=>c.id===p.source_id)?.name||"Früherer Verbraucher")}</h3><p>Durchsatz ändern: <strong>${number(p.old_rate,3)} → ${number(p.new_rate,3)} L/h</strong></p><p class="muted">${number(p.evidence.measured_liters)} L gemessener Verbrauch bei ${number(p.evidence.runtime_hours,2)} h Laufzeit. ${esc(new Date(p.evidence.start).toLocaleDateString("de-DE"))}–${esc(new Date(p.evidence.end).toLocaleDateString("de-DE"))}</p><div class="actions">${[["accept","Wert übernehmen"],["reject","Ablehnen"],["later","Später"]].map(([k,v])=>`<button data-decision="${k}" data-proposal="${esc(p.id)}">${v}</button>`).join("")}</div></article>`).join(""):'<p>Keine offenen Vorschläge.</p>'}
      <details><summary>Bisherige Entscheidungen</summary>${t.proposals.filter(p=>p.status!=="pending").map(p=>`<p>${number(p.old_rate,3)} → ${number(p.new_rate,3)} L/h · ${esc({applied:"Übernommen",rejected:"Abgelehnt",stale:"Veraltet",approved:"Bestätigt, Übernahme ausstehend"}[p.status])} · ${esc(new Date(p.confirmed_at||p.decided_at||p.at).toLocaleString("de-DE"))}</p>`).join("")||"Noch keine Entscheidungen."}</details></section>`;
    const split=content.indexOf("<section><h2>Kalibrierung");
    const calibration=content.slice(split), report=content.slice(0,split);
    return proposals.length ? calibration+report : report+`<details class="calibration-history"><summary>Kalibrierung</summary>${calibration}</details>`;
  }
  async click(event) {
    const button = event.target.closest("button");
    if (!button || this.busy) return;
    const action = button.dataset.action;
    try {
      if (button.dataset.tank) { this.selected = button.dataset.tank; this.history = []; this.historyCount = 0; this.reportTank = null; this.reportRequest = (this.reportRequest || 0) + 1; this.olderHistory = false; await this.loadHistory(); this.render(); }
      else if (button.dataset.chartIndex !== undefined) { this.shadowRoot.querySelector(".chart-value").textContent = button.title; }
      else if (button.dataset.decision) {
        await this._hass.callWS({type:"ha_tankdata/manage",config_entry_id:this.selected,operation:"decide",parameters:{proposal_id:button.dataset.proposal,decision:button.dataset.decision}});
        this.notice = button.dataset.decision === "accept" ? "Durchsatz übernommen." : button.dataset.decision === "later" ? "Vorschlag zurückgestellt." : "Vorschlag abgelehnt.";
        await this.refresh();
      }
      else if (button.dataset.period || action?.startsWith("period-")) {
        const tank = this.tanks.find(t=>t.id===this.selected);
        const r = this.reportTank===tank.id ? this.report : tank.statistics;
        const period = button.dataset.period || r.period;
        let anchor = r.anchor;
        if (action === "period-current" || button.dataset.period === "day") anchor = null;
        else if (action === "period-previous" || action === "period-next") {
          const delta = action === "period-next" ? 1 : -1;
          const date = new Date(`${r.start}T12:00:00Z`);
          if (period === "day" || period === "week") date.setUTCDate(date.getUTCDate()+delta*(period==="week"?7:1));
          else if (period === "month") date.setUTCMonth(date.getUTCMonth()+delta);
          else date.setUTCFullYear(date.getUTCFullYear()+delta);
          anchor = date.toISOString().slice(0,10);
        }
        await this.loadReport({period,...(anchor?{anchor}:{})}); this.render();
      }
      else if (action === "settings") this.openDialog("settings");
      else if (button.dataset.book) this.openDialog("book",button.dataset.book);
      else if (button.dataset.edit) this.openDialog("consumer",button.dataset.edit);
      else if (button.dataset.remove) this.openDialog("remove",button.dataset.remove);
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
      fields = this.input("name","Name","text",c.name || "","maxlength=100") + `<label>Verbrauchsquelle<select name="mode">${Object.entries(modes).map(([v,l]) => `<option value="${v}" ${v === (c.mode || "counter") ? "selected" : ""}>${l}</option>`).join("")}</select></label>` + this.input("entity_id","Quelle","text",c.entity_id || "",'list="source-entities"') + `<datalist id="source-entities">${Object.keys(this._hass.states).filter(id => /^(sensor|binary_sensor|switch|input_boolean)\./.test(id)).map(id => `<option value="${esc(id)}">${esc(this._hass.states[id].attributes.friendly_name || id)}</option>`).join("")}</datalist><div id="rate-fields">${this.input("rate_lph","Durchsatz in L/h","number",c.rate_lph || 1,"min=0.001 step=any")}</div><div id="power-fields">${this.input("on_threshold_w","Ein ab Leistung (W)","number",c.on_threshold_w ?? 100.1,"min=0 step=any")}${this.input("off_threshold_w","Aus bis Leistung (W)","number",c.off_threshold_w ?? 100,"min=0 step=any")}</div><details><summary>Erweiterte Einstellungen</summary>${this.input("max_gap_seconds","Maximale Datenlücke (Sekunden)","number",c.max_gap_seconds || 3600,"min=0.001 step=any")}${this.input("max_rate_lph","Maximal plausible Rate (L/h)","number",c.max_rate_lph || 100,"min=0.001 step=any")}</details>`;
    } else if (kind === "settings") {
      const st = tank.settings, g = st.geometry;
      title = "Tankeinstellungen";
      fields = `<label>Tankgeometrie<select name="shape">${Object.entries(shapes).map(([k,v])=>`<option value="${k}" ${k===g.shape?"selected":""}>${v}</option>`).join("")}</select></label>
        <label>Innere Tankhöhe / Durchmesser (cm, optional)<input name="height_cm" type="number" min="0.001" step="any" value="${esc(g.height_cm ?? "")}"></label>
        <label>Peiltabelle (cm; Liter pro Zeile)<textarea name="points" rows="4" placeholder="0;0&#10;100;1000">${esc((g.points||[]).map(p=>p.join(";")).join("\n"))}</textarea></label>
        <p class="muted">Sonderformen: Hersteller-Peiltabelle verwenden.</p>
        ${this.input("reserve_liters","Reserve (L)","number",st.reserve_liters,"min=0 step=any")}
        <label>Preis des Initialbestands (EUR/L, optional)<input name="initial_price" type="number" min="0" step="any" value="${esc(st.initial_price ?? "")}"></label>
        <label>Kalibriervorschläge<select name="calibration_enabled"><option value="true" ${st.calibration_enabled?"selected":""}>Vorschläge zur Bestätigung</option><option value="false" ${!st.calibration_enabled?"selected":""}>Aus</option></select></label>
        ${this.input("measurement_tolerance_liters","Messunsicherheit pro Messung (L)","number",st.measurement_tolerance_liters,"min=0 step=any")}`;
    } else if (kind === "remove") {
      title = "Verbraucher entfernen";
      fields = `<p>${esc(tank.consumers.find(c => c.id === key)?.name)} entfernen? Die bisherigen Verbrauchsbuchungen bleiben erhalten.</p>`;
    } else {
      title = actions[key];
      const notes = {record_observation:"Dokumentiert den gemessenen Bestand. Der berechnete Bestand bleibt unverändert.",apply_correction:"Setzt den aktuellen Bestand auf den angegebenen Literwert.",reset_calibration:"Hebt die Wirkung bisheriger Bestandskorrekturen auf. Die Historie bleibt erhalten; der angezeigte Bestand kann sich ändern.",recalculate:"Berechnet den Bestand erneut aus der unveränderten Historie."};
      fields = (notes[key] && !["record_refill","apply_correction"].includes(key) ? `<p>${esc(notes[key])}</p>` : "") + (["recalculate","reset_calibration"].includes(key) ? "" : this.input("liters",["apply_correction","record_observation"].includes(key) ? "Neuer Bestand (L)" : "Befüllmenge (L)","number","","min=0 step=any"));
    }
    if (kind === "book" && key === "record_refill") fields += '<label>Gesamtpreis der Lieferung (EUR, optional)<input name="total_cost" type="number" min="0" step="any"></label>';
    if (kind === "book" && ["apply_correction","record_observation"].includes(key)) fields += `<label>Messeinheit<select name="unit"><option value="L">Liter</option><option value="%">Prozent des Volumens</option>${key === "record_observation" ? '<option value="cm">Füllhöhe in cm</option>' : ""}</select></label>`;
    this.shadowRoot.getElementById("dialog-host").innerHTML = `<dialog aria-labelledby="dialog-title"><form><h2 id="dialog-title">${esc(title)}</h2><p class="muted">${esc(kind === "tank" ? "" : tank.name)}</p>${fields}<p class="error" id="form-error" role="alert"></p><div class="dialog-actions"><button type="button" data-action="close">Abbrechen</button><button type="submit" class="primary">${kind === "book" ? esc(actions[key]) : kind === "remove" ? "Entfernen" : "Speichern"}</button></div></form></dialog>`;
    const dialog = this.shadowRoot.querySelector("dialog");
    dialog.addEventListener("cancel",e => { e.preventDefault(); if (!this.busy) this.closeDialog(); });
    dialog.showModal();
    if (kind === "consumer") this.consumerFields(this.shadowRoot.querySelector('[name="mode"]').value);
    if (kind === "book" && ["apply_correction","record_observation"].includes(key)) this.measurementFields("L");
  }
  measurementFields(unit) {
    const input = this.shadowRoot.querySelector('[name="liters"]');
    const tank = this.tanks.find(t => t.id === this.modal.tank);
    input.parentElement.firstChild.textContent = `Neuer Bestand (${unit})`;
    input.max = unit === "%" ? 100 : unit === "cm" ? (tank.settings.geometry.height_cm ?? "") : tank.capacity;
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
    this.shadowRoot.querySelector("dialog")?.close();
    this.shadowRoot.getElementById("dialog-host").replaceChildren();
    this.modal = null;
    this.flow = null;
    this.pendingBooking = null;
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
      if (kind === "settings") {
        const geometry = {shape:data.shape};
        if (data.height_cm !== "") geometry.height_cm = Number(data.height_cm);
        if (data.shape === "table") geometry.points = data.points.trim().split(/\n/).map(line=>line.split(";").map(x=>Number(x.trim().replace(",","."))));
        await this._hass.callWS({type:"ha_tankdata/manage",config_entry_id:tank,operation:"settings",parameters:{geometry,initial_price:data.initial_price===""?null:Number(data.initial_price),reserve_liters:Number(data.reserve_liters),calibration_enabled:data.calibration_enabled==="true",measurement_tolerance_liters:Number(data.measurement_tolerance_liters)}});
      } else if (kind === "book") {
        if (!this.pendingBooking) this.pendingBooking = {config_entry_id:tank,...data,...(key === "recalculate" ? {} : {event_id:`panel-${uuid()}`})};
        if (key === "recalculate") await this._hass.callService("ha_tankdata",key,this.pendingBooking);
        else {
          const params = {...this.pendingBooking}; delete params.config_entry_id;
          if (params.total_cost === "") delete params.total_cost;
          else if ("total_cost" in params) params.total_cost = Number(params.total_cost);
          params.kind = {record_refill:"refill",record_withdrawal:"withdrawal",record_observation:"observation",apply_correction:"correction",reset_calibration:"reset"}[key];
          await this._hass.callWS({type:"ha_tankdata/manage",config_entry_id:tank,operation:"book",parameters:params});
        }
      } else if (kind === "settings") {
      const st = tank.settings, g = st.geometry;
      title = "Tankeinstellungen";
      fields = `<label>Tankgeometrie<select name="shape">${Object.entries(shapes).map(([k,v])=>`<option value="${k}" ${k===g.shape?"selected":""}>${v}</option>`).join("")}</select></label>
        <label>Innere Tankhöhe / Durchmesser (cm, optional)<input name="height_cm" type="number" min="0.001" step="any" value="${esc(g.height_cm ?? "")}"></label>
        <label>Peiltabelle (cm; Liter pro Zeile)<textarea name="points" rows="4" placeholder="0;0&#10;100;1000">${esc((g.points||[]).map(p=>p.join(";")).join("\n"))}</textarea></label>
        <p class="muted">Sonderformen: Hersteller-Peiltabelle verwenden.</p>
        ${this.input("reserve_liters","Reserve (L)","number",st.reserve_liters,"min=0 step=any")}
        <label>Preis des Initialbestands (EUR/L, optional)<input name="initial_price" type="number" min="0" step="any" value="${esc(st.initial_price ?? "")}"></label>
        <label>Kalibriervorschläge<select name="calibration_enabled"><option value="true" ${st.calibration_enabled?"selected":""}>Vorschläge zur Bestätigung</option><option value="false" ${!st.calibration_enabled?"selected":""}>Aus</option></select></label>
        ${this.input("measurement_tolerance_liters","Messunsicherheit pro Messung (L)","number",st.measurement_tolerance_liters,"min=0 step=any")}`;
    } else if (kind === "remove") {
        const consumer = this.tanks.find(t => t.id === tank).consumers.find(c => c.id === key);
        await this._hass.callApi("DELETE",`config/config_entries/entry/${consumer.entry_id}`);
      } else {
        const path = "config/config_entries/flow";
        if (!this.flow) {
          const consumer = key ? this.tanks.find(t => t.id === tank).consumers.find(c => c.id === key) : null;
          const initial = {handler:"ha_tankdata",show_advanced_options:false,...(consumer ? {entry_id:consumer.entry_id} : {})};
          let flow = await this._hass.callApi("POST",path,initial);
          if (flow.type === "menu") flow = await this._hass.callApi("POST",`${path}/${flow.flow_id}`,{next_step_id:kind === "tank" ? "tank" : "consumer"});
          if (flow.type !== "form") throw new Error("Die Einrichtung konnte nicht gestartet werden.");
          this.flow = {path,id:flow.flow_id};
        }
        const result = await this._hass.callApi("POST",`${this.flow.path}/${this.flow.id}`,{...data,...(kind === "consumer" && !key ? {tank_entry_id:tank} : {})});
        if (result.type === "form") throw new Error("Bitte Angaben prüfen: Kapazität, Bestand, Quelle, Durchsatz und Schwellen müssen zusammenpassen.");
        if (!(result.type === "create_entry" || (kind === "consumer" && key && result.type === "abort" && result.reason === "reconfigure_successful"))) throw new Error(result.reason || "Einrichtung fehlgeschlagen.");
        this.flow = null;
        if (kind === "tank") this.selected = result.result.entry_id;
      }
      this.flow = null;
      this.closeDialog();
      this.olderHistory = false;
      this.notice = "Gespeichert.";
      await this.refresh();
      setTimeout(() => { if (this.isConnected && !this.modal) this.refresh(); }, 1000);
    } catch (e) {
      this.shadowRoot.getElementById("form-error").textContent = e.message || "Speichern fehlgeschlagen. Bitte Verbindung und Eingaben prüfen.";
      if (this.pendingBooking) {
        form.querySelectorAll("input, select").forEach(input => input.disabled = true);
        form.querySelector('button[type="submit"]').textContent = "Dieselbe Buchung erneut versuchen";
      }
    } finally {
      this.busy = false;
      form.querySelectorAll("button").forEach(b => b.disabled = false);
    }
  }
  styles() { return `
    .period-picker{display:flex;align-items:end;gap:10px;flex-wrap:wrap;margin-top:18px}.period-picker label{margin:0}.period-picker input,.period-picker select{margin-top:5px}.period-title{font-weight:600}.chart-scroll{container-type:inline-size;width:100%;min-width:0}.calendar-chart{display:flex;gap:clamp(1px,.4vw,6px);width:100%;padding-bottom:32px}.calendar-slot{position:relative;flex:1 1 0;min-width:0;width:0;border:0;border-radius:0;padding:0;background:transparent;font-size:11px}.calendar-slot span{position:absolute;top:133px;left:50%;transform:translateX(-50%);white-space:nowrap;pointer-events:none}.calendar-slot:first-child span{left:0;transform:none}.calendar-slot:last-child span{left:auto;right:0;transform:none}.chart-value{min-height:20px;margin:4px 0;overflow-wrap:anywhere}@container(max-width:650px){.calendar-chart.dense .calendar-slot span{visibility:hidden}.calendar-chart.dense .calendar-slot:nth-child(4n+1) span,.calendar-chart.dense .calendar-slot:last-child span{visibility:visible}.calendar-chart.medium .calendar-slot:nth-child(even):not(:last-child) span{visibility:hidden}}@container(max-width:350px){.calendar-chart{gap:2px}.calendar-slot{font-size:9px}.calendar-chart.dense .calendar-slot:nth-last-child(2) span,.calendar-chart.dense .calendar-slot:nth-last-child(3) span{visibility:hidden}}.bar-space{height:125px;display:flex;align-items:end;border-bottom:1px solid #8885}.bar-space .bar{width:100%}.period-tabs{margin-bottom:12px}
    .tank-visual{height:210px;width:100%;color:#7aa8a3}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:20px;margin:24px 0}.metrics strong{display:block;font-size:24px}.metrics span{display:block;font-size:13px;margin-top:6px;color:var(--secondary-text-color)}.chart{display:flex;align-items:flex-end;gap:2px;height:130px;border-bottom:1px solid #8885}.bar-slot{flex:1;min-width:0}.bar{background:#16877c;border-radius:2px 2px 0 0}.forecast-title{margin-top:30px}.proposal{border:1px solid #16877c;padding:18px;border-radius:12px;margin:16px 0}textarea{width:100%;font:inherit;padding:10px;background:var(--primary-background-color);color:inherit}.stock-summary{display:grid;grid-template-columns:minmax(220px,1fr) 1.3fr;align-items:center;gap:28px;margin-top:24px}.tank-scene{text-align:center}.tank-scene .tank-visual{height:250px;max-width:390px}.stock-content .badge{float:right}.stock-label{margin:0 0 8px}.stock-content .actions{margin-top:24px}.stock-percent{font-size:22px;font-weight:500;color:var(--secondary-text-color);margin-left:18px;letter-spacing:0}.ha-device{display:inline-block;border:1px solid var(--divider-color);border-radius:9px;padding:12px 16px;white-space:nowrap}.heading h1{margin-bottom:0}.heading p.muted{margin-bottom:0}.calibration-history{margin-bottom:22px}.back{margin:0 0 12px!important}@media(max-width:700px){.stock-summary{grid-template-columns:1fr;gap:8px}.tank-scene .tank-visual{height:205px}.stock-content{padding:0 4px 6px}.stock-content .actions button{flex:1}.ha-device{margin-top:8px}}:host{display:block;height:calc(100dvh - var(--safe-area-inset-top,0px) - var(--safe-area-inset-bottom,0px));overflow:hidden;background:var(--primary-background-color,#f5f7fa);color:var(--primary-text-color,#192a35);font-family:var(--paper-font-body1_-_font-family,system-ui)}*{box-sizing:border-box}ha-top-app-bar-fixed{height:100%}.integration-link{color:var(--app-header-text-color);padding:12px 8px}main{max-width:1240px;margin:auto;padding:36px 28px}h1{font-size:34px;margin:4px 0 8px;letter-spacing:-1px}h2{font-size:19px;margin:0 0 16px}small{font-size:.6em;font-weight:500}.heading,.section-heading{display:flex;align-items:center;justify-content:space-between;gap:20px}.eyebrow{font-size:11px;letter-spacing:2px;color:#16877c;font-weight:750}.muted,footer{color:var(--secondary-text-color,#64748b);font-size:14px;line-height:1.6}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:22px;margin-top:30px}.detail-grid{display:grid;grid-template-columns:1fr 1.5fr;gap:22px}.tank-card,section{background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#e1e7ed);border-radius:18px;padding:26px;margin-bottom:22px}.tank-card{text-align:left;width:100%;color:inherit;font:inherit;cursor:pointer}.tank-card:hover{border-color:#16877c}.card-top,.card-bottom{display:flex;justify-content:space-between;align-items:center;gap:12px}.card-top{margin-bottom:20px}.card-bottom{font-size:13px;color:var(--secondary-text-color,#64748b)}.tank-icon{color:#16877c;font-size:30px}.badge{border-radius:20px;background:#16877c18;color:var(--primary-text-color,#126f65);padding:6px 10px;font-size:12px;white-space:nowrap}.warn{background:#e5a42822;color:var(--warning-color,#996d0b)}.stock{font-size:42px;font-weight:700;letter-spacing:-1px}.meter{height:10px;background:var(--divider-color,#e9eef2);border-radius:8px;margin:22px 0 12px;overflow:hidden}.meter span{display:block;height:100%;background:#16877c;border-radius:8px}button{border:1px solid var(--divider-color,#d5dee7);border-radius:9px;background:var(--card-background-color,#fff);color:inherit;padding:11px 15px;font:inherit;font-size:14px;cursor:pointer}button:hover{filter:brightness(.97)}button:focus-visible,a:focus-visible{outline:3px solid #16877c;outline-offset:3px}button:disabled{opacity:.6;cursor:wait}.primary{background:#137e73;color:white;border-color:#137e73;font-weight:600}.actions{display:flex;gap:10px;flex-wrap:wrap}.device-link{display:inline-block;margin-top:24px}a{color:var(--primary-color,#137e73);font-size:14px;text-decoration:none}.back{margin:8px 0 22px;border:0;background:none;padding-left:0}.consumer{display:flex;align-items:center;gap:12px;padding:18px 0;border-top:1px solid var(--divider-color,#e1e7ed)}.consumer>div{flex:1;min-width:0}.consumer p{margin:6px 0;overflow-wrap:anywhere}.table-scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px;text-align:left}th{color:var(--secondary-text-color,#64748b);font-size:12px}td,th{padding:14px 10px;border-bottom:1px solid var(--divider-color,#e1e7ed);white-space:nowrap}.error{color:var(--error-color,#b3261e);line-height:1.5}.notice{background:#16877c18;padding:14px;border-radius:10px}.empty{text-align:center;margin-top:30px;padding:60px 20px}footer{margin:32px 0;font-size:12px}dialog{background:var(--card-background-color,#fff);color:inherit;border:0;border-radius:18px;padding:28px;width:min(540px,calc(100% - 24px));max-height:90vh;overflow:auto;box-shadow:0 20px 80px #0005}dialog::backdrop{background:#0007}label{display:block;font-size:14px;margin:18px 0}input,select{display:block;width:100%;margin-top:7px;padding:12px;border:1px solid var(--divider-color,#c6d0d9);border-radius:8px;background:var(--primary-background-color,#fff);color:inherit;font:inherit}.dialog-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:25px}summary{cursor:pointer;font-size:14px;padding:14px 0}[hidden]{display:none!important}@media(max-width:700px){main{padding:22px 16px}h1{font-size:28px}.heading{align-items:flex-start;flex-direction:column;gap:8px}.detail-grid{grid-template-columns:1fr}.consumer{flex-wrap:wrap}.consumer>div{flex-basis:100%}section,.tank-card{padding:20px}.section-heading{align-items:flex-start;flex-wrap:wrap}.stock{font-size:36px}}
  `; }
}
if (!customElements.get("tankdata-panel")) customElements.define("tankdata-panel", TankDataPanel);
