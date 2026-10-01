"use strict";

const $ = (id) => document.getElementById(id);
const TZ = -new Date().getTimezoneOffset() * 60; // charts show local time
const LW = window.LightweightCharts;

let state = null;
let selected = null;
let book = "paper";
let dragging = false;
let fitted = {};
let priceLines = [];

// ---------------------------------------------------------------- formatting
const ccy = () => (state && state.currency) || "EUR";
const money = (v, sign = false) =>
  v == null ? "—" : (sign && v > 0 ? "+" : "") + v.toFixed(2) + " " + ccy();
const pct = (v, d = 2, sign = true) =>
  v == null || !isFinite(v) ? "—" : (sign && v > 0 ? "+" : "") + (v * 100).toFixed(d) + " %";
const px = (v) => {
  if (v == null) return "—";
  const d = v >= 1000 ? 2 : v >= 10 ? 3 : v >= 1 ? 4 : 6;
  return v.toLocaleString("es-ES", { minimumFractionDigits: d, maximumFractionDigits: d });
};
const cls = (v) => (v > 0 ? "up" : v < 0 ? "down" : "");
const time = (ts) => new Date(ts * 1000).toLocaleTimeString("es-ES");
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

// ---------------------------------------------------------------- charts
const chartOpts = (h) => ({
  autoSize: true,
  height: h,
  layout: { background: { color: "transparent" }, textColor: "#7f8ea3", fontSize: 11 },
  grid: { vertLines: { color: "#18202b" }, horzLines: { color: "#18202b" } },
  rightPriceScale: { borderColor: "#233040" },
  timeScale: { borderColor: "#233040", timeVisible: true, secondsVisible: true },
  crosshair: { mode: 0 },
});

const priceChart = LW.createChart($("chart"), chartOpts(380));
const candles = priceChart.addCandlestickSeries({
  upColor: "#22c55e", downColor: "#ef4444", borderVisible: false,
  wickUpColor: "#22c55e", wickDownColor: "#ef4444",
  priceFormat: { type: "price", precision: 2, minMove: 0.01 },
});
const flowChart = LW.createChart($("flow"), {
  ...chartOpts(90),
  timeScale: { visible: false },
});
const flow = flowChart.addHistogramSeries({ priceFormat: { type: "volume" } });
priceChart.timeScale().subscribeVisibleLogicalRangeChange((r) => {
  if (r) flowChart.timeScale().setVisibleLogicalRange(r);
});
const equityChart = LW.createChart($("equity"), chartOpts(220));
const equityLine = equityChart.addAreaSeries({
  lineColor: "#60a5fa", topColor: "rgba(96,165,250,.25)", bottomColor: "rgba(96,165,250,0)", lineWidth: 2,
});
const bhLine = equityChart.addLineSeries({ color: "#a78bfa", lineWidth: 1, lineStyle: 2, priceLineVisible: false });

function precisionFor(p) {
  return p >= 1000 ? 2 : p >= 10 ? 3 : p >= 1 ? 4 : 6;
}

function drawChart() {
  const sym = state.symbols[selected];
  if (!sym) return;
  const bars = sym.bars || [];
  const last = bars.length ? bars[bars.length - 1].c : 0;
  const prec = precisionFor(last);
  candles.applyOptions({ priceFormat: { type: "price", precision: prec, minMove: 10 ** -prec } });
  candles.setData(bars.map((b) => ({ time: b.t + TZ, open: b.o, high: b.h, low: b.l, close: b.c })));
  flow.setData(bars.map((b) => ({
    time: b.t + TZ, value: b.sv, color: b.sv >= 0 ? "rgba(34,197,94,.6)" : "rgba(239,68,68,.6)",
  })));

  const step = state.bar_seconds || 5;
  const snap = (ts) => Math.floor(ts / step) * step + TZ;
  const first = bars.length ? bars[0].t : Infinity;
  const markers = [];
  for (const t of state.trades || []) {
    if (t.book !== "paper" || t.symbol !== selected) continue;
    if (t.entry_ts >= first) markers.push({ time: snap(t.entry_ts), position: "belowBar", color: "#60a5fa", shape: "arrowUp", text: "B" });
    if (t.exit_ts >= first) markers.push({ time: snap(t.exit_ts), position: "aboveBar", color: t.pnl > 0 ? "#22c55e" : "#ef4444", shape: "arrowDown", text: (t.net_return * 100).toFixed(2) + "%" });
  }
  const pos = sym.position;
  if (pos && pos.entry_ts >= first) markers.push({ time: snap(pos.entry_ts), position: "belowBar", color: "#60a5fa", shape: "arrowUp", text: "B" });
  markers.sort((a, b) => a.time - b.time);
  candles.setMarkers(markers);

  priceLines.forEach((l) => candles.removePriceLine(l));
  priceLines = [];
  if (pos) {
    const line = (price, color, title) => candles.createPriceLine({ price, color, title, lineWidth: 1, lineStyle: 2, axisLabelVisible: true });
    priceLines.push(line(pos.entry_price, "#60a5fa", "entrada"), line(pos.stop, "#ef4444", "stop"), line(pos.target, "#22c55e", "objetivo"));
  }
  if (!fitted[selected] && bars.length > 5) {
    priceChart.timeScale().fitContent();
    fitted[selected] = true;
  }
  const f = sym.features;
  $("chart-meta").textContent = `velas de ${step}s · ${bars.length} barras` + (f ? ` · σ/barra ${pct(f.sigma, 3, false)}` : "");
}

// ---------------------------------------------------------------- panels
function renderHeader() {
  const s = state;
  const feed = s.feed || {};
  const sim = s.simulation;
  const ok = s.feed_healthy && feed.connected;
  $("mode").textContent = (sim ? "SIMULACIÓN" : "PAPER") + (s.session === "us_equity" ? " · ACCIONES" : " · CRIPTO")
    + (s.venue === "alpaca-paper" ? " · ÓRDENES EN ALPACA PAPER" : "");
  $("mode").className = "badge " + (sim ? "sim" : "paper");
  $("sim-controls").classList.toggle("hidden", !sim);
  if (sim) for (const b of $("sim-controls").children) b.classList.toggle("on", Number(b.dataset.speed) === sim.speed);
  $("feed-dot").className = "dot " + (ok ? "ok" : "bad");
  const age = feed.last_message_age_s;
  const simDate = sim ? new Date(sim.sim_ts * 1000).toLocaleString("es-ES", { dateStyle: "short", timeStyle: "medium" }) : "";
  const stocks = s.session === "us_equity";
  const source = stocks ? (sim ? "acciones EE. UU." : "Alpaca (IEX)") : "Binance";
  $("source").textContent = stocks ? "Acciones EE. UU." : "Binance spot";
  $("feed-text").textContent = sim
    ? `Histórico ${source} · ${simDate} · ${(sim.progress * 100).toFixed(1)} %${sim.finished ? " · terminado" : ""}`
    : ok
      ? `${source} en vivo · ${feed.messages.toLocaleString("es-ES")} msgs · ${age != null ? age.toFixed(1) + " s" : ""}`
      : `feed caído ${feed.last_error ? "· " + feed.last_error.slice(0, 60) : ""}`;
  if (!dragging) {
    $("agg").value = s.aggressiveness;
    $("agg-val").textContent = Math.round(s.aggressiveness);
  }
  $("kill").classList.toggle("on", s.kill_switch);
  if (!armed.kill) $("kill").textContent = s.kill_switch ? "KILL SWITCH ACTIVO · reactivar" : "KILL SWITCH";
  if (!armed.flatten) $("flatten").textContent = "Cerrar todo";
  $("pause").classList.toggle("on", s.paused);
  $("pause").textContent = s.paused ? "Reanudar" : "Pausar";

  const banner = $("banner");
  const warm = Object.values(s.symbols).map((x) => x.warmup).filter((w) => w.seen < w.needed);
  let msg = "", info = false;
  if (s.kill_switch) msg = "KILL SWITCH ACTIVO — el Risk Engine rechaza toda orden, incluidas las salidas.";
  else if (!ok) msg = "Sin datos de mercado frescos: el Risk Engine bloquea las órdenes (datos obsoletos / API).";
  else if (sim && sim.finished) {
    const a = s.account;
    msg = `Simulación terminada: tu cartera ${pct(a.equity / a.initial - 1)} · Buy & Hold ${pct(a.buy_hold_equity / a.initial - 1)}.`;
    info = true;
  }
  else if (s.paused) { msg = "Pausado: no se abren posiciones nuevas; las salidas siguen activas."; info = true; }
  else if (s.session === "us_equity" && s.market_open === false) {
    msg = "Mercado de EE. UU. cerrado (abre 15:30 hora de España). El bot es intradía: nunca mantiene posiciones de noche.";
    info = true;
  }
  else if (s.session === "us_equity" && s.seconds_to_close != null && s.seconds_to_close < 900) {
    msg = `Últimos ${Math.ceil(s.seconds_to_close / 60)} min de sesión: no se abren posiciones y se cerrará todo 5 min antes del cierre.`;
    info = true;
  }
  else if (warm.length) {
    const w = warm[0];
    msg = `Calentando indicadores: ${w.seen}/${w.needed} barras (≈ ${Math.ceil(((w.needed - w.seen) * (s.bar_seconds || 5)) / 60)} min).`;
    info = true;
  }
  banner.textContent = msg;
  banner.className = "banner" + (info ? " info" : "") + (msg ? "" : " hidden");
}

function renderKpis() {
  const a = state.account;
  const paper = (state.trades || []).filter((t) => t.book === "paper");
  $("k-equity").textContent = money(a.equity);
  $("k-equity-s").innerHTML = `caja ${money(a.cash)} · inicio ${money(a.initial)}`;
  const day = a.day_start_equity > 0 ? a.equity / a.day_start_equity - 1 : 0;
  $("k-day").innerHTML = `<span class="${cls(day)}">${pct(day)}</span>`;
  const dd = a.equity_peak > 0 ? a.equity / a.equity_peak - 1 : 0;
  $("k-dd").textContent = `drawdown ${pct(dd, 2, false)} · límite -${(state.profile.max_daily_loss * 100).toFixed(1)} %/día`;
  $("k-real").innerHTML = `<span class="${cls(a.realized_pnl)}">${money(a.realized_pnl, true)}</span>`;
  $("k-fees").textContent = `comisiones ${money(a.fees_paid)}`;
  $("k-trades").textContent = state.paper_trades ?? paper.length;
  const wins = paper.filter((t) => t.pnl > 0).length;
  $("k-win").textContent = paper.length ? `acierto ${((wins / paper.length) * 100).toFixed(0)} % (últimas ${paper.length})` : "aún ninguna";
  const c = state.counters;
  $("k-signals").textContent = c.signals;
  $("k-sig-s").textContent = `✓ ${c.approved} · ✗ ${c.rejected} · ⏸ ${c.throttled} · coste ✗ ${c.cost_blocked}`;
  const k = state.costs;
  $("k-cost").textContent = pct(k.round_trip_fees_pct + 2 * k.slippage_pct, 2, false);
  $("k-cost-s").textContent = `fees ${pct(k.round_trip_fees_pct, 2, false)} + slip · latencia ${(k.latency_s * 1000).toFixed(0)} ms`;
}

function renderSymbols() {
  const names = Object.keys(state.symbols);
  if (!selected || !state.symbols[selected]) selected = names[0];
  const tabs = $("tabs");
  if (tabs.childElementCount !== names.length) {
    tabs.innerHTML = names.map((n) => `<button data-sym="${esc(n)}">${esc(n)}</button>`).join("");
  }
  for (const b of tabs.children) b.classList.toggle("on", b.dataset.sym === selected);

  $("symbols").innerHTML = names.map((n) => {
    const s = state.symbols[n];
    const f = s.features || {};
    const mid = s.bid && s.ask ? (s.bid + s.ask) / 2 : null;
    const w = s.warmup;
    const p = s.position;
    return `<div class="sym ${n === selected ? "on" : ""}" data-sym="${esc(n)}">
      <div class="sym-head"><span class="sym-name">${esc(n)}</span><span class="sym-px">${px(mid)}</span></div>
      <div class="sym-grid">
        <div><span>spread</span><br><b class="num">${pct(s.spread_pct, 3, false)}</b></div>
        <div><span>z-score</span><br><b class="num ${cls(-f.zscore)}">${f.zscore != null ? f.zscore.toFixed(2) : "—"}</b></div>
        <div><span>flujo</span><br><b class="num ${cls(f.order_flow_imbalance)}">${f.order_flow_imbalance != null ? f.order_flow_imbalance.toFixed(2) : "—"}</b></div>
        <div><span>libro</span><br><b class="num ${cls(f.book_imbalance)}">${f.book_imbalance != null ? f.book_imbalance.toFixed(2) : "—"}</b></div>
        <div><span>mom.</span><br><b class="num ${cls(f.momentum)}">${pct(f.momentum, 3)}</b></div>
        <div><span>tendencia</span><br><b class="num ${cls(f.ema_fast - f.ema_slow)}">${f.ema_fast == null ? "—" : f.ema_fast > f.ema_slow ? "▲" : "▼"}</b></div>
      </div>
      ${w.seen < w.needed ? `<div class="bar"><i style="width:${(100 * w.seen) / w.needed}%"></i></div>` : ""}
      ${p ? `<div class="pos">${esc(p.strategy_id)} · ${p.quantity} @ ${px(p.entry_price)}<br>
        stop ${px(p.stop)} · obj. ${px(p.target)} · <b class="${cls(p.unrealized)}">${money(p.unrealized, true)}</b>${p.exiting ? " · saliendo…" : ""}</div>` : ""}
    </div>`;
  }).join("");
}

function renderStrategies() {
  const p = state.profile;
  $("thresholds").textContent = `umbral: edge ≥ ${p.min_edge_score.toFixed(0)} · confianza ≥ ${(p.min_confidence * 100).toFixed(1)} % · EV neto ≥ ${pct(p.min_expected_net_edge, 2, false)}`;
  $("strategies").querySelector("tbody").innerHTML = state.strategies.map((s) => {
    const tgt = s.last_target_pct, min = s.last_min_target_pct;
    const ratio = tgt != null && min ? `<span class="${tgt >= min ? "up" : "down"}">${pct(tgt, 2, false)}</span> / ${pct(min, 2, false)}` : "—";
    return `<tr title="${esc(s.description)}">
    <td>${esc(s.strategy_id)}</td>
    <td>${s.signals}</td>
    <td>${s.cost_blocked}</td>
    <td>${ratio}</td>
    <td>${s.n_trades}</td>
    <td>${s.n_trades ? (s.win_rate * 100).toFixed(1) + " %" : "—"}</td>
    <td class="${cls(s.mean_net_return)}">${s.n_trades ? pct(s.mean_net_return, 3) : "—"}</td>
    <td>${s.adjusted_p_value.toFixed(3)}</td>
    <td>${s.edge_score.toFixed(1)}</td>
    <td class="${cls(s.shadow_cum_return)}">${s.n_trades ? pct(s.shadow_cum_return, 2) : "—"}</td>
    <td>${s.open_shadow}</td>
    <td><span class="pill ${s.eligible ? "ok" : "no"}">${s.eligible ? "OPERA" : "SIN EVIDENCIA"}</span></td>
  </tr>`;
  }).join("");
}

function renderDecisions() {
  $("decisions").innerHTML = (state.decisions || []).slice(0, 50).map((d) => `<li>
    <span class="muted">${time(d.ts)}</span> <span class="act ${esc(d.action)}">${esc(d.action)}</span>
    ${esc(d.side)} ${esc(d.symbol)} · ${esc(d.strategy_id)}${d.notional ? ` · ${money(d.notional)}` : ""}
    <span class="why">${esc(d.detail || "")}${d.reasons && d.reasons.length ? " — " + esc(d.reasons.join(" · ")) : ""}</span>
  </li>`).join("") || `<li class="muted">Sin decisiones todavía. Cada señal (aprobada o rechazada) aparecerá aquí.</li>`;
}

function renderEquity() {
  const rows = [];
  for (const e of state.equity || []) {
    const time = Math.floor(e.t) + TZ;
    if (!rows.length || time > rows[rows.length - 1].time) rows.push({ time, v: e.v, bh: e.bh });
  }
  equityLine.setData(rows.map((r) => ({ time: r.time, value: r.v })));
  bhLine.setData(rows.filter((r) => r.bh != null).map((r) => ({ time: r.time, value: r.bh })));
}

async function renderTrades() {
  let rows = [];
  try {
    rows = await (await fetch(`/api/trades?book=${book}&limit=100`)).json();
  } catch { return; }
  $("trades").querySelector("tbody").innerHTML = rows.map((t) => `<tr>
    <td>${time(t.exit_ts)}</td><td>${esc(t.symbol)}</td><td>${esc(t.strategy_id)}</td>
    <td>${px(t.entry_price)}</td><td>${px(t.exit_price)}</td>
    <td class="${cls(t.net_return)}">${pct(t.net_return, 3)}</td>
    <td class="${cls(t.pnl)}">${book === "paper" ? money(t.pnl, true) : "—"}</td>
    <td>${esc(t.exit_reason)}</td>
  </tr>`).join("") || `<tr><td colspan="8" class="muted">Sin operaciones ${book === "paper" ? "paper" : "en sombra"} todavía.</td></tr>`;
}

function render() {
  renderHeader();
  renderKpis();
  renderSymbols();
  drawChart();
  renderStrategies();
  renderDecisions();
  renderEquity();
}

// ---------------------------------------------------------------- controls
async function control(body) {
  const r = await fetch("/api/control", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!r.ok) alert("Control rechazado: " + r.status);
}

// Two-step confirmation inside the button itself: native confirm() dialogs are suppressed in
// some embedded browsers, which made the kill switch impossible to turn off.
const armed = {};
function confirmClick(id, label, action) {
  const btn = $(id);
  if (armed[id]) {
    clearTimeout(armed[id]);
    delete armed[id];
    btn.classList.remove("armed");
    action();
    return;
  }
  btn.classList.add("armed");
  btn.textContent = label;
  armed[id] = setTimeout(() => {
    delete armed[id];
    btn.classList.remove("armed");
    if (state) renderHeader();
  }, 4000);
}

$("kill").onclick = () => {
  if (state && state.kill_switch) {
    confirmClick("kill", "¿Reactivar órdenes? Pulsa otra vez", () => control({ kill_switch: false }));
  } else {
    control({ kill_switch: true }); // engaging the emergency brake never asks
  }
};
$("pause").onclick = () => control({ paused: !(state && state.paused) });
$("flatten").onclick = () =>
  confirmClick("flatten", "¿Vender todo? Pulsa otra vez", () => control({ flatten: true }));
const agg = $("agg");
agg.oninput = () => { dragging = true; $("agg-val").textContent = agg.value; };
agg.onchange = async () => { await control({ aggressiveness: Number(agg.value) }); dragging = false; };

document.addEventListener("click", (ev) => {
  const el = ev.target.closest("[data-sym]");
  if (el) { selected = el.dataset.sym; if (state) render(); }
  const sp = ev.target.closest("[data-speed]");
  if (sp) control({ speed: Number(sp.dataset.speed) });
  const b = ev.target.closest("[data-book]");
  if (b) {
    book = b.dataset.book;
    for (const x of $("book-seg").children) x.classList.toggle("on", x.dataset.book === book);
    renderTrades();
  }
});

// ---------------------------------------------------------------- live updates
function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onmessage = (m) => { state = JSON.parse(m.data); render(); };
  ws.onclose = () => {
    $("feed-dot").className = "dot bad";
    $("feed-text").textContent = "sin conexión con el trader local — reintentando…";
    setTimeout(connect, 1500);
  };
}
connect();
renderTrades();
setInterval(renderTrades, 3000);

// ---------------------------------------------------------------- research lab
const STATUS_ES = { candidate: "candidata", challenger: "challenger", champion: "champion", retired: "retirada" };
const ago = (ts) => {
  if (!ts) return "—";
  const s = (state && state.now ? state.now : Date.now() / 1000) - ts;
  if (Math.abs(s) < 90) return `${Math.round(s)} s`;
  if (Math.abs(s) < 5400) return `${Math.round(s / 60)} min`;
  return `${(s / 3600).toFixed(1)} h`;
};

async function renderLab() {
  let lab;
  try {
    lab = await (await fetch("/api/research")).json();
  } catch { return; }
  const st = lab.status || {};
  let txt = "desactivado";
  if (st.enabled !== false) {
    if (st.running) txt = `investigando… (desde hace ${ago(st.last_started)})`;
    else {
      const next = st.next_due ? (st.next_due - (state ? state.now : Date.now() / 1000)) : null;
      txt = `último ciclo hace ${ago(st.last_finished)}` + (next != null ? ` · próximo en ${next > 0 ? (next / 3600).toFixed(1) + " h" : "breve"}` : "");
    }
    if (st.last_error) txt += ` · error: ${st.last_error.slice(0, 80)}`;
  }
  $("lab-status").textContent = txt;
  $("lab-run").disabled = !!st.running || st.enabled === false;
  const counts = st.rules || {};
  $("lab-counts").innerHTML = ["challenger", "champion", "candidate", "retired"].map((k) =>
    `<span class="pill ${k}">${STATUS_ES[k]}: ${counts[k] || 0}</span>`).join("");

  const pctOr = (v, d = 3) => (v == null ? "—" : pct(v, d));
  $("lab-rules").querySelector("tbody").innerHTML = (lab.rules || []).map((r) => {
    const res = (r.metrics || {}).research || {};
    const gold = (r.metrics || {}).golden || {};
    const live = r.live || (r.metrics || {}).forward || {};
    return `<tr title="${esc(r.description || r.name)}">
      <td>${esc(r.name)}<div class="muted">${esc(r.rule_id)}</div></td>
      <td>${esc(r.symbol)}</td>
      <td><span class="pill ${esc(r.status)}">${STATUS_ES[r.status] || esc(r.status)}</span></td>
      <td class="${cls(res.oos_ev)}">${pctOr(res.oos_ev)}</td>
      <td class="${cls(gold.mean_net_return)}">${gold.n_trades != null ? `${pctOr(gold.mean_net_return)} (${gold.n_trades})` : "—"}</td>
      <td>${live.n_trades ?? 0}</td>
      <td class="${cls(live.mean_net_return)}">${live.n_trades ? pctOr(live.mean_net_return) : "—"}</td>
      <td>${live.edge_score != null ? Number(live.edge_score).toFixed(1) : "—"}</td>
      <td>${ago(r.updated_at)}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="9" class="muted">Aún no hay reglas: el primer ciclo de research las buscará. Puede que ninguna supere la validación — eso también es información.</td></tr>`;

  $("lab-events").innerHTML = (lab.events || []).map((e) => `<li>
    <span class="muted">${time(e.ts)}</span> ${esc(e.rule_id)}
    <span class="pill ${esc(e.to_status)}">${STATUS_ES[e.to_status] || esc(e.to_status)}</span>
    <span class="why">${esc(e.reason || "")}</span></li>`).join("") || `<li class="muted">Sin movimientos todavía.</li>`;
  $("lab-lessons").innerHTML = (lab.lessons || []).map((l) => `<li>
    <span class="muted">${time(l.ts)} · ${esc(l.kind)}</span><span class="why">${esc(l.text)}</span></li>`).join("")
    || `<li class="muted">Las lecciones aparecen tras cada ciclo, promoción o retirada.</li>`;
  const HYP_ES = { proposed: "pendiente", promoted: "promovida", rejected: "rechazada", invalid: "inválida" };
  $("ai-hyps").querySelector("tbody").innerHTML = (lab.hypotheses || []).map((h) => {
    const v = h.verdict || {};
    let res = "—";
    if (h.status === "invalid") res = esc(h.reason || "");
    else if (v.symbols_tested != null) {
      const fails = Object.keys(v.failed_checks || {}).slice(0, 2).join(", ");
      res = `${v.symbols_tested} símbolos · mejor ${esc(v.best_symbol || "—")} ${v.best_oos_ev != null ? pct(v.best_oos_ev, 3) : ""}`
        + ` (${v.best_oos_trades ?? 0} op.) · candidatas ${v.candidates}${fails ? " · falla: " + esc(fails) : ""}`;
    } else if (h.status === "proposed") res = "se examinará en el próximo ciclo";
    return `<tr><td>${new Date(h.created_at * 1000).toLocaleString("es-ES", { dateStyle: "short", timeStyle: "short" })}</td>
      <td>${esc(h.name)}</td><td>${esc(h.timeframe || "—")}</td>
      <td>${esc((h.claim || "").slice(0, 220))}</td>
      <td><span class="pill ${esc(h.status)}">${HYP_ES[h.status] || esc(h.status)}</span></td>
      <td class="muted">${res}</td></tr>`;
  }).join("") || `<tr><td colspan="6" class="muted">Sin hipótesis todavía. El analista propone ideas antes de cada ciclo de research si OPENAI_API_KEY y un modelo están en .env.</td></tr>`;
  $("lab-runs").querySelector("tbody").innerHTML = (lab.runs || []).map((r) => {
    const s = r.summary || {};
    return `<tr><td>${r.id}</td><td>${new Date(r.started_at * 1000).toLocaleString("es-ES", { dateStyle: "short", timeStyle: "short" })}</td>
      <td>${s.n_hypotheses ?? "—"}</td><td>${s.n_global_discoveries ?? "—"}</td><td>${s.n_candidates ?? "—"}</td>
      <td>${(s.promoted || []).length}</td><td>${esc(r.status)}</td></tr>`;
  }).join("") || `<tr><td colspan="7" class="muted">Ningún ciclo todavía.</td></tr>`;
}

$("lab-run").onclick = async () => {
  const r = await fetch("/api/research/run", { method: "POST" });
  if (!r.ok) alert("No se pudo lanzar el research: " + r.status);
  renderLab();
};
renderLab();
setInterval(renderLab, 5000);

async function renderGoLive() {
  let g;
  try {
    g = await (await fetch("/api/golive")).json();
  } catch { return; }
  const panel = $("golive-panel");
  const banner = $("golive-banner");
  if (!g.enabled) {
    panel.classList.add("hidden");
    banner.className = "banner ready hidden";
    return;
  }
  panel.classList.remove("hidden");
  const when = g.evaluated_at ? new Date(g.evaluated_at * 1000).toLocaleString("es-ES", { dateStyle: "short", timeStyle: "short" }) : "—";
  $("golive-status").innerHTML = (g.ready
    ? `<span class="gate-ok">LISTO PARA REAL</span>`
    : `<span class="gate-no">Aún no</span>`) + ` · ${g.passed}/${g.total} criterios · evaluado ${when}`;
  $("golive-table").querySelector("tbody").innerHTML = (g.criteria || []).map((c) => `<tr>
      <td class="${c.ok ? "gate-ok" : "gate-no"}">${c.ok ? "✓" : "✗"}</td>
      <td>${esc(c.label)}</td><td>${esc(c.value)}</td><td class="muted">${esc(c.target)}</td>
      <td class="muted">${esc(c.detail || "")}</td></tr>`).join("");
  if (g.ready) {
    banner.textContent = "✓ La cuenta paper ha superado la puerta a real (" + g.passed + "/" + g.total + ")."
      + (g.live_broker_available ? " Puedes plantearte pasar a real." : " Siguiente paso: construir el conector real del broker; nada se activa solo.");
    banner.className = "banner ready";
  } else banner.className = "banner ready hidden";
}
renderGoLive();
setInterval(renderGoLive, 60000);
