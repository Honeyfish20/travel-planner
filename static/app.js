"use strict";
// Requires i18n.js (I18N, t, E, tz, pick, en, LANG, applyStatic).
const AGENTS = [
  ["intake", ["需求解析 Agent", "Intake agent"], "LLM", ["识别出行类型、同行人和预算；读取家庭档案", "Trip type, travellers and budget; loads the family profile"]],
  ["constraints", ["同行人约束 Agent", "Constraint agent"], ["规则", "Rules"], ["过敏、步行、婴儿车、午休 → 过滤景点和餐厅", "Allergies, walking, stroller, naps → filter attractions and restaurants"]],
  ["transport", ["城际交通 Agent", "Transport agent"], "LLM", ["在航班和高铁中选择往返", "Picks return flights or high-speed rail"]],
  ["hotel", ["酒店 Agent", "Hotel agent"], "LLM", ["家庭房、无障碍、英文服务、住宿标准", "Family rooms, accessibility, English service, policy caps"]],
  ["ground", ["接送 Agent", "Transfer agent"], "LLM", ["人数、儿童座椅、可预付", "Group size, child seats, prepayable"]],
  ["inbound", ["入境准备 Agent", "Entry-prep agent"], "LLM", ["签证、支付、网络清单（仅入境游）", "Visa, payment and internet checklist (inbound only)"]],
  ["weather", ["天气 Agent", "Weather agent"], "API", ["Open-Meteo 逐日、分时段天气，判断是否适合户外", "Open-Meteo daily and hourly weather; outdoor suitability"]],
  ["trending", ["热门景点 Agent", "Trending agent"], "MCP + LLM", ["Exa / 博查检索相似游客攻略，匹配合作优惠券", "Exa / Bocha search of similar trips; partner coupons"]],
  ["itinerary", ["行程编排 Agent", "Itinerary agent"], "LLM", ["按天气和热度排程，生成后按约束和天气复核", "Schedules by weather and popularity, then re-checks"]],
  ["check", ["合规与费用 Agent", "Check & cost agent"], ["规则", "Rules"], ["政策、约束、天气、优惠券、零钱和网络提醒", "Policy, constraints, weather, coupons, cash and internet tips"]],
];
const L = (pair) => (Array.isArray(pair) ? pair[en() ? 1 : 0] : pair);
const $ = (sel) => document.querySelector(sel);
let source = null, finished = true, currentPlan = null, currentQuery = "";
const stepEvents = {};
const expenses = [];

// DOM helpers: text nodes only, so model output can never inject HTML.
function el(tag, cls, ...kids) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false || kid === "") continue;
    node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return node;
}
const money = (v, cur) => (cur && cur !== "CNY" ? cur + " " : "¥") + Number(v || 0).toLocaleString(en() ? "en-US" : "zh-CN", { maximumFractionDigits: 2 });
const badge = (text, cls) => el("span", "badge " + cls, text);
const card = (title, ...kids) => el("section", "card", el("h2", null, title), ...kids);
const reason = (text, prefix) => (text ? el("p", "reason", (prefix || t("reason")) + text) : null);
const join = (arr) => arr.filter((x) => x !== null && x !== undefined && x !== "").join(t("sep"));
const city = (name) => tz(name);
const poiName = (p) => (en() && p.name_en ? p.name_en : p.name);
function kv(rows) {
  const dl = el("dl", "kv");
  for (const [k, v] of rows) if (v !== null && v !== undefined && v !== "") dl.append(el("dt", null, k), el("dd", null, v));
  return dl;
}
function table(caption, head, rows, numCols = []) {
  const tb = el("table");
  if (caption) tb.append(el("caption", null, caption));
  if (head) tb.append(el("thead", null, el("tr", null, head.map((h, i) => el("th", numCols.includes(i) ? "num" : null, h)))));
  const body = el("tbody");
  for (const r of rows) {
    const tr = el("tr", r.cls || null);
    (r.cells || r).forEach((c, i) => tr.append(el("td", numCols.includes(i) ? "num" : null, c)));
    body.append(tr);
  }
  tb.append(body);
  return tb;
}
function linkTo(url, text) {
  const a = el("a", null, text);
  if (/^https:\/\//.test(url)) { a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer"; }
  return a;
}
function sources(list) {
  if (!list || !list.length) return null;
  return el("div", "src", t("source"), list.map((s, i) => [i ? "; " : "", s.url ? linkTo(s.url, s.source) : s.source, ` (${s.title}, ${t("updated")} ${s.updated})`]));
}
function notice(text, cls) {
  const box = $("#notice");
  box.replaceChildren();
  if (text) { const a = el("div", "alert " + cls, text); a.setAttribute("role", cls === "bad" ? "alert" : "status"); box.append(a); }
}
async function api(path, options = {}) {
  const r = await fetch(path, options);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error || `HTTP ${r.status}`);
  return body;
}
const postJSON = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const memberLabel = (m) => (m.age === null || m.age === undefined ? m.role : m.role + t("age", { n: m.age }));

// ------------------------------------------------------------------ steps
function renderSteps() {
  const ul = $("#steps");
  ul.replaceChildren();
  for (const [key, name, kind, desc] of AGENTS) {
    const li = el("li", "idle", el("span", "dot"), el("div", null, el("div", "step-name", L(name), el("span", "kind", L(kind))), el("div", "step-sub", L(desc))));
    li.id = "step-" + key;
    ul.append(li);
    if (stepEvents[key]) setStep(stepEvents[key]);
  }
}
function setStep(ev) {
  stepEvents[ev.agent] = ev;
  const li = document.getElementById("step-" + ev.agent);
  if (!li) return;
  li.className = ev.status;
  const sub = li.querySelector(".step-sub");
  if (ev.status === "running") sub.textContent = t("step.running");
  else if (ev.status === "error") sub.textContent = t("step.failed", { msg: ev.message || "" });
  else sub.textContent = `${pick(ev, "summary") || t("step.done")} · ${(ev.elapsed_ms / 1000).toFixed(1)}s`;
}

// ------------------------------------------------------------------ result cards (1/2)
function overviewCard(d) {
  const r = d.request, it = d.itinerary, c = d.cost;
  const tags = [badge(E("trip", r.trip_type), "neutral")];
  if (r.is_inbound) tags.push(badge(t("ov.inbound"), "neutral"));
  if (r.trip_type === "business") tags.push(d.needs_approval ? badge(t("ov.approval"), "bad") : badge(t("ov.no_approval"), "ok"));
  if (r.memory_note) tags.push(badge(en() ? "Loaded from profile" : r.memory_note, "ok"));
  if (d.profile_saved) tags.push(badge(t("ov.saved", { id: d.profile_saved }), "gray"));
  if (it.generated_by === "fallback") tags.push(badge(t("ov.fallback"), "warn"));
  const net = c.total_after_coupons_cny;
  const total = money(net) + (c.total_home !== null ? t("ov.total_home", { v: money(c.total_home, c.home_currency) }) : "") +
    (c.coupon_savings_cny ? t("ov.coupon_off", { v: money(c.coupon_savings_cny) }) : "");
  const wx = d.weather.days;
  const wxLine = `${wx.map((x) => x.icon).join(" ")} ${Math.round(Math.min(...wx.map((x) => x.t_min)))}–${Math.round(Math.max(...wx.map((x) => x.t_max)))}°C (${pick(d.weather, "source_label")})`;
  return card(it.title || `${city(r.origin)} → ${city(r.destination)}`,
    el("div", null, tags),
    it.summary ? el("p", null, it.summary) : null,
    kv([[t("ov.route"), t("ov.route_v", { o: city(r.origin), d: city(r.destination), km: r.distance_km, scope: t(r.domestic ? "ov.domestic" : "ov.cross") })],
        [t("ov.dates"), t("ov.dates_v", { a: r.depart_date, b: r.return_date, n: r.nights })],
        [t("ov.members"), join(r.members.map(memberLabel))],
        [t("ov.purpose"), r.purpose], [t("ov.prefs"), join(r.preferences || [])],
        [t("ov.nat"), r.nationality ? `${r.nationality} / ${r.language}` : null],
        [t("ov.weather"), wxLine],
        [t("ov.total"), total]]));
}

function membersCard(d) {
  const r = d.request, b = d.constraints;
  const rows = r.members.map((m) => [m.role, m.age ?? "—", E("mobility", m.mobility) + (m.max_walk_km ? t("mem.walk", { n: m.max_walk_km }) : ""),
    join(m.allergies) || "—", E("diet", m.diet) || "—", m.group || "—"]);
  const exP = b.pois_excluded.map((e) => el("li", null, el("strong", null, e.name), t("colon"), e.reason));
  const exR = b.restaurants_excluded.map((e) => el("li", null, el("strong", null, e.name), t("colon"), e.reason));
  return card(t("mem.h"),
    table(null, t("mem.cols"), rows),
    el("h3", null, t("mem.rules_h")),
    el("ul", "plain", b.constraints.rules.map((x) => el("li", null, x))),
    exP.length || exR.length ? el("details", null, el("summary", null, t("mem.excluded", { p: exP.length, r: exR.length })),
      exP.length ? el("ul", "plain", exP) : null, exR.length ? el("ul", "plain", exR) : null) : null);
}

function transportOption(label, o, fare) {
  return el("div", "option",
    el("div", "option-head", el("strong", null, `${label} ${o.number}`), badge(t(o.mode === "rail" ? "tr.rail" : "tr.flight"), "gray"), badge(tz(o.cabin), "neutral"),
      o.preferred && o.mode === "flight" ? badge(t("tr.pref_air"), "ok") : null),
    el("div", null, `${tz(o.carrier)} · ${o.depart.slice(5)} → ${o.arrive.slice(5)} · ${t("hours", { n: o.duration_h })}${o.stops ? t("tr.stops", { n: o.stops }) : ""}`),
    el("div", "muted", `${o.from_hub} → ${o.to_hub}`),
    el("div", "price", money(o.price_cny) + t("per_adult") + t("tr.party", { v: money(fare) })));
}

function transportCard(d) {
  const tr = d.transport;
  return card(t("tr.h"), transportOption(t("tr.out"), tr.outbound, tr.party_fare.outbound), transportOption(t("tr.back"), tr.return, tr.party_fare.return),
    reason(tr.reason), tr.filtered_out ? el("p", "muted", t("tr.filtered", { n: tr.filtered_out })) : null);
}

function hotelCard(d) {
  const h = d.hotel;
  if (!h.hotel) return card(t("ho.h"), el("p", "muted", en() ? t("ho.none") : h.reason));
  const x = h.hotel;
  const tags = [badge(t("ho.stars", { n: x.stars }), "neutral"), x.preferred ? badge(t("ho.pref"), "ok") : null,
    x.kids_facilities ? badge(t("ho.kids"), "gray") : null, x.accessible ? badge(t("ho.access"), "gray") : null, x.english_service ? badge(t("ho.english"), "gray") : null];
  return card(t("ho.h"),
    el("div", "option", el("div", "option-head", el("strong", null, x.name), tags),
      el("div", "muted", `${tz(x.area)} · ${t("ho.dist", { n: x.distance_to_center_km })} · ${t(x.breakfast ? "ho.bf" : "ho.no_bf")}`),
      el("div", "price", t("ho.price", { room: tz(h.room_type), p: money(h.nightly_cny), r: h.rooms, n: h.nights, t: money(h.total_cny) })),
      h.cap_cny ? el("div", "muted", t("ho.cap", { v: money(h.cap_cny) })) : null),
    h.relaxed ? el("p", "alert warn", t("ho.relaxed")) : null,
    reason(h.reason));
}

function groundCard(d) {
  const g = d.ground;
  const opt = (label, x, amount) => el("div", "option",
    el("div", "option-head", el("strong", null, `${label}${t("colon")}${tz(x.mode)}`), x.preferred ? badge(t("gr.pref"), "ok") : null,
      x.child_seat ? badge(t("gr.seat"), "gray") : null, x.prepay ? badge(t("gr.prepay"), "gray") : null),
    el("div", "muted", `${t("minutes", { n: x.duration_min })} · ${money(amount)}`));
  return card(t("gr.h"), opt(t("gr.arr"), g.arrival, g.arrival_cny), opt(t("gr.dep"), g.departure, g.departure_cny), reason(g.reason));
}

function costItemLabel(i, d) {
  if (!en()) return i.label;
  const r = d.request, h = d.hotel;
  const pois = d.itinerary.days.reduce((n, day) => n + day.poi_count, 0);
  const meals = d.itinerary.days.reduce((n, day) => n + day.items.filter((x) => x.restaurant).length, 0);
  return {
    transport: t("co.item.transport", { n: r.party_size }),
    hotel: h.hotel ? t("co.item.hotel", { n: h.nights, r: h.rooms, room: tz(h.room_type) }) : t("co.item.hotel_none"),
    transfer: t("co.item.transfer"), tickets: t("co.item.tickets", { n: pois }), meals: t("co.item.meals", { n: meals }),
  }[i.key] || i.label;
}

function costCard(d) {
  const c = d.cost;
  const rows = c.items.map((i) => [costItemLabel(i, d), money(i.amount)]);
  rows.push({ cls: "total", cells: [t("total"), money(c.total_cny)] });
  if (c.coupon_savings_cny) {
    rows.push([t("co.coupons"), "−" + money(c.coupon_savings_cny)]);
    rows.push({ cls: "total", cells: [t("co.after"), money(c.total_after_coupons_cny)] });
  }
  if (c.total_home !== null) rows.push([t("co.home"), money(c.total_home, c.home_currency)]);
  if (c.budget_cny !== null) rows.push([t("co.budget"), el("span", null, money(c.budget_cny), " ", c.within_budget ? badge(t("co.in_budget"), "ok") : badge(t("co.over_budget"), "warn"))]);
  const per = table(t("co.per_caption"), t("co.per_cols"),
    c.per_member.map((p) => [p.member, money(p.transport), money(p.tickets), money(p.meals)]), [1, 2, 3]);
  return card(t("co.h"),
    table(t("co.caption"), null, rows, [1]),
    c.home_currency !== "CNY" ? el("p", "muted", c.fx_note) : null,
    el("details", null, el("summary", null, t("co.by_person")), per),
    c.split.length ? el("div", null, el("h3", null, t("co.split_h")),
      table(t("co.split_caption"), t("co.split_cols"),
        c.split.map((s) => [s.group, s.members, money(s.personal), money(s.shared), money(s.total)]), [1, 2, 3, 4])) : null);
}

// ------------------------------------------------------------------ result cards (2/2): itinerary, weather, trending, reminders
function wxChip(w) {
  if (!w) return null;
  const temp = w.temp !== null && w.temp !== undefined ? ` ${Math.round(w.temp)}°C` : "";
  return el("span", "wx-chip" + (w.outdoor_ok ? "" : " bad"), `${w.icon} ${pick(w, "text")}${temp}${w.precip_prob >= 30 ? t("it.rain", { p: w.precip_prob }) : ""}`);
}

function itineraryCard(d) {
  const it = d.itinerary;
  const box = card(t("it.h"));
  for (const day of it.days) {
    const w = day.weather;
    box.append(el("div", "day-head", el("h3", null, day.date),
      w ? el("span", null, `${w.icon} ${pick(w, "text")} ${Math.round(w.t_min)}–${Math.round(w.t_max)}°C`) : null,
      el("span", "muted", t("it.day_stats", { n: day.poi_count, km: day.walk_km }))));
    if (w) box.append(el("p", "muted", pick(w, "summary")));
    const ul = el("ul", "timeline");
    for (const i of day.items) {
      const extra = [];
      if (i.poi) extra.push(t("it.poi_line", { cat: tz(i.poi.category), io: t(i.poi.indoor ? "it.indoor" : "it.outdoor"), h: i.poi.duration_h, km: i.poi.walk_km }));
      if (i.restaurant) {
        const r = i.restaurant;
        extra.push([tz(r.cuisine), t("it.pp", { v: money(r.price_pp) }), r.kid_menu ? t("it.kid_menu") : "", r.english_menu ? t("it.en_menu") : "",
          t(r.foreign_card ? "it.card" : "it.cash")].filter(Boolean).join(" · "));
      }
      ul.append(el("li", i.type, i.time ? el("span", "time", i.time) : null, badge(E("item", i.type), "gray"), el("strong", null, i.title),
        i.type === "poi" || i.type === "meal" ? wxChip(i.weather) : null, i.weather_swapped ? badge(t("it.swapped"), "warn") : null,
        i.detail ? el("div", "muted", i.detail) : null, extra.map((x) => el("div", "muted", x))));
    }
    box.append(ul);
  }
  if (it.rain_backup && it.rain_backup.length)
    box.append(el("h3", null, t("it.rain_backup")), el("ul", "plain", it.rain_backup.map((p) => el("li", null, t("it.rain_line", { name: poiName(p), cat: tz(p.category), h: p.duration_h })))));
  if (it.weather_fixes && it.weather_fixes.length)
    box.append(el("details", null, el("summary", null, t("it.wx_fixes", { n: it.weather_fixes.length })), el("ul", "plain", it.weather_fixes.map((f) => el("li", null, f)))));
  if (it.weather_conflicts && it.weather_conflicts.length)
    box.append(el("div", "alert warn", t("it.wx_alert"), el("ul", "plain", it.weather_conflicts.map((f) => el("li", null, f)))));
  if (it.fixes && it.fixes.length)
    box.append(el("details", null, el("summary", null, t("it.fixes", { n: it.fixes.length })), el("ul", "plain", it.fixes.map((f) => el("li", null, f)))));
  return box;
}

function weatherCard(d) {
  const w = d.weather;
  const box = card(t("wx.h", { city: en() ? w.city_en || city(w.city) : w.city, src: pick(w, "source_label") }));
  if (pick(w, "note")) box.append(el("p", "alert warn", pick(w, "note")));
  for (const day of w.days) {
    box.append(el("div", "wx-day",
      el("div", "wx-head", el("span", "big", day.icon), el("strong", null, day.date), el("span", null, `${pick(day, "text")} ${Math.round(day.t_min)}–${Math.round(day.t_max)}°C`),
        el("span", "muted", t("wx.day_meta", { p: day.precip_prob_max, uv: day.uv_max })), badge(pick(day, "source_label"), day.source === "forecast" ? "ok" : "gray")),
      el("div", null, pick(day, "summary")),
      el("div", "muted", t("wx.clothing") + pick(day, "clothing")),
      el("div", "wx-grid", day.blocks.map((b) => el("div", "wx-block " + (b.outdoor_ok ? "ok" : "bad"),
        el("b", null, `${pick(b, "label")} ${b.start}–${b.end}`), `${b.icon} ${pick(b, "text")} ${Math.round(b.temp)}°C`,
        el("div", null, t("wx.block_meta", { p: b.precip_prob, a: Math.round(b.feels_min), b: Math.round(b.feels_max) })),
        el("div", null, pick(b, "advice")))))));
  }
  const alerts = en() && w.alerts_en ? w.alerts_en : w.alerts;
  if (alerts.length) box.append(el("div", "alert warn", el("strong", null, t("wx.alerts")), el("ul", "plain", alerts.map((a) => el("li", null, a)))));
  if (w.attribution) box.append(el("p", "src", w.attribution));
  return box;
}

function couponLabel(c) {
  if (!en()) return c.label;
  return c.kind === "percent" ? t("cp.pct", { n: c.value }) : t("cp.amt", { n: c.value }) + t(c.scope === "person" ? "cp.per" : "cp.order");
}

function couponBox(c) {
  return el("div", "coupon" + (c.eligible ? "" : " off"),
    el("div", "option-head", el("strong", null, `${c.poi_name} · ${couponLabel(c)}`),
      c.eligible ? badge(t("cp.save", { v: money(c.saving_cny) }), "ok") : badge(t("cp.unavailable"), "gray"), badge(t("cp.demo"), "gray")),
    el("div", null, t("cp.code"), el("code", null, c.code), t("cp.valid", { partner: c.partner, d: c.valid_until })),
    el("div", "muted", c.terms + (c.eligible ? t("cp.use") : t("cp.why", { r: c.ineligible_reason }))));
}

function trendingCard(d) {
  const tr = d.trending;
  const box = card(t("hot.h"));
  const provStatus = (p) => (p.ok ? t("hot.prov_ok", { n: p.count })
    : (p.error && /BOCHA/.test(p.error) ? t("hot.prov_unconfigured") : p.error || t("hot.prov_none")));
  const prov = Object.values(tr.providers).map((p) => badge(`${tz(p.name)}${t("colon")}${provStatus(p)}`, p.ok ? "ok" : "gray"));
  box.append(el("div", null, badge(t("hot.basis." + tr.basis), tr.basis === "web" ? "neutral" : "warn"), prov));
  if (!tr.coverage) box.append(el("p", "muted", t("hot.no_catalog")));
  if (tr.insights.length) box.append(el("h3", null, t("hot.insights")), el("ul", "plain", tr.insights.map((x) => el("li", null, x))));
  const planned = new Set(d.itinerary.days.flatMap((day) => day.items.filter((i) => i.type === "poi" && i.poi).map((i) => i.poi.id)));
  for (const h of tr.hot) {
    const status = planned.has(h.poi.id) ? badge(t("hot.planned"), "ok") : (h.allowed ? badge(t("hot.optional"), "gray") : badge(t("hot.excluded"), "warn"));
    box.append(el("div", "hot", el("span", "rank", h.rank),
      el("div", null,
        el("div", "option-head", el("strong", null, poiName(h.poi)), el("span", "muted", en() ? h.poi.name : h.poi.name_en), status,
          h.coupon ? badge(couponLabel(h.coupon), h.coupon.eligible ? "ok" : "gray") : null, h.mentions ? badge(t("hot.mentions", { n: h.mentions }), "neutral") : null),
        el("div", "muted", t("hot.meta", { cat: tz(h.poi.category), io: t(h.poi.indoor ? "it.indoor" : "it.outdoor"), h: h.poi.duration_h, p: money(h.poi.price_adult) })),
        h.reason ? el("div", null, h.reason) : null,
        !h.allowed && h.excluded_reason ? el("div", "muted", t("hot.why_excluded") + h.excluded_reason) : null,
        h.sources.length ? el("div", "src", t("source"), h.sources.map((s, i) => [i ? "; " : "", linkTo(s.url, `[${s.n}] ${s.title}`), ` (${tz(s.provider)})`])) : null)));
  }
  if (tr.others.length) box.append(el("h3", null, t("hot.others")),
    el("ul", "plain", tr.others.map((o) => el("li", null, el("strong", null, o.name), o.note ? t("colon") + o.note : "",
      el("span", "src", " ", o.sources.map((s, i) => [i ? ", " : "", linkTo(s.url, `[${s.n}]`)]))))));
  box.append(el("details", null, el("summary", null, t("hot.queries")),
    el("ul", "plain", tr.queries.map((q) => el("li", null, `${tz(q.provider)}${t("colon")}${q.query}`))),
    tr.results.length ? el("ol", "plain", tr.results.map((s) => el("li", null, linkTo(s.url, s.title), ` (${tz(s.provider)}${s.published ? " · " + s.published : ""})`)))
      : el("p", "muted", t("hot.no_results")),
    tr.analysis_error ? el("p", "muted", t("hot.analysis_failed") + tr.analysis_error) : null));
  return box;
}

function couponsCard(d) {
  const inPlan = d.cost.coupons;
  const planned = new Set(inPlan.map((c) => c.poi_id));
  const more = d.trending.hot.filter((h) => h.coupon && h.allowed && !planned.has(h.poi.id)).map((h) => h.coupon);
  if (!inPlan.length && !more.length) return null;
  return card(t("cp.h"),
    inPlan.length ? [el("h3", null, t("cp.in_plan", { v: money(d.cost.coupon_savings_cny) })), inPlan.map(couponBox)] : null,
    more.length ? [el("h3", null, t("cp.more")), more.map(couponBox)] : null,
    el("p", "muted", t("cp.note")));
}

function remindersCard(d) {
  const box = card(t("rm.h"));
  const w = d.weather;
  const wxTips = [...new Set(w.days.flatMap((day) => (en() && day.tips_en ? day.tips_en : day.tips)))];
  const alerts = en() && w.alerts_en ? w.alerts_en : w.alerts;
  if (wxTips.length || alerts.length) box.append(el("h3", null, t("rm.weather")), el("ul", "plain", alerts.concat(wxTips).map((x) => el("li", null, x))));
  if (d.network) {
    box.append(el("h3", null, t("rm.network")));
    for (const e of d.network.events) {
      box.append(el("div", "event", el("div", "when", `${pick(e, "when")} · ${pick(e, "place")}`),
        el("div", null, t("rm.impact") + (en() ? e.impact_en : e.impact_zh)), el("div", null, t("rm.action") + (en() ? e.action_en : e.action_zh)),
        en() ? null : el("div", "muted", e.impact_en + " " + e.action_en),
        e.links.length ? el("div", "src", t("rm.guides"), e.links.map((l, i) => [i ? "; " : "", linkTo(l.url, l.title)])) : null));
    }
    box.append(el("details", null, el("summary", null, t("rm.all_guides")),
      el("ul", "plain", d.network.guides.map((g) => el("li", null, linkTo(g.url, g.title))))),
      el("p", "muted", t("rm.checked", { d: d.network.checked })));
  }
  if (d.cash) {
    const c = d.cash;
    const home = c.total_home !== null ? t("ov.total_home", { v: money(c.total_home, c.home_currency) }) : "";
    const rows = [];
    for (const day of c.breakdown) for (const x of day.items) rows.push([day.date.slice(5), pick(x, "place"), money(x.amount), pick(x, "reason")]);
    box.append(el("h3", null, t("rm.cash")),
      el("p", null, t("rm.cash_line", { n: d.request.party_size }), el("strong", null, money(c.total_cny)), t("rm.cash_after", { home }),
        c.denominations.map((n) => `¥${n.note} × ${n.count}`).join(t("sep"))),
      el("ul", "plain", (en() && c.reasons_en ? c.reasons_en : c.reasons).map((r) => el("li", null, r))),
      el("details", null, el("summary", null, t("rm.cash_detail", { a: money(c.raw_cny), b: money(c.total_cny) })),
        table(null, t("rm.cash_cols"), rows, [2])),
      el("p", "muted", c.fx_note));
  }
  if (d.itinerary.tips.length) box.append(el("h3", null, t("rm.tips")), el("ul", "plain", d.itinerary.tips.map((x) => el("li", null, x))));
  return box;
}

// ------------------------------------------------------------------ checks, inbound, share
function checksCard(d) {
  const rows = d.checks.map((c) => [tz(c.rule), badge(E("status", c.status), { pass: "ok", warn: "warn", fail: "bad" }[c.status] || "gray"), c.detail]);
  return card(t("ck.h"), table(t("ck.caption"), t("ck.cols"), rows));
}

function phraseCards(title, cards) {
  return card(title, cards.map((c) => el("div", "phrase", c.title ? el("div", "muted", c.title) : null, el("div", "zh", c.zh), el("div", "en", c.en))));
}

function inboundCards(d) {
  const ib = d.inbound, pp = d.payment_plan;
  if (!ib) return [];
  const byPhase = {};
  for (const x of ib.checklist) (byPhase[x.phase] = byPhase[x.phase] || []).push(x);
  const list = card(t("ib.h"),
    el("h3", null, t("ib.visa")), el("p", null, ib.visa_note), sources(ib.visa_sources),
    ["before", "arrival", "during"].filter((p) => byPhase[p]).map((p) => [el("h3", null, E("phase", p)),
      el("ul", "plain", byPhase[p].map((x) => el("li", null, x.task, sources(x.sources))))]),
    el("p", "muted", t("ib.kb", { d: ib.kb_updated })));
  const out = [list];
  if (pp) {
    const pre = pp.prepay.map((x) => [x.coupon ? el("span", null, pick(x, "item"), " ", badge(en() ? x.coupon_code : x.coupon, "ok")) : pick(x, "item"), money(x.amount)]);
    pre.push({ cls: "total", cells: [t("pp.prepay_total"), money(pp.prepay_total)] });
    const on = pp.onsite.map((x) => [pick(x, "item"), x.method_key ? t("pp.method." + x.method_key) : x.method, money(x.amount)]);
    on.push({ cls: "total", cells: [t("pp.onsite_total"), "", money(pp.onsite_total)] });
    out.push(card(t("pp.h"), el("p", null, pick(pp, "note")),
      table(t("pp.prepay"), t("pp.prepay_cols"), pre, [1]),
      table(t("pp.onsite"), t("pp.onsite_cols"), on, [2]),
      pp.cash_suggest_cny ? el("p", null, t("pp.cash"), el("strong", null, money(pp.cash_suggest_cny)), t("pp.cash_see")) : null));
  }
  out.push(phraseCards(t("ph.pay"), ib.payment_phrases), phraseCards(t("ph.emergency"), [ib.emergency_card]));
  return out;
}

function shareCard(d) {
  const lang = el("select", null, [["zh", "简体中文"], ["en", "English"], ["ja", "日本語"], ["ko", "한국어"]].map(([v, x]) => { const o = el("option", null, x); o.value = v; return o; }));
  lang.id = "share-lang";
  lang.value = d.request.language;
  const btn = el("button", "btn shrink", t("sh.btn"));
  btn.type = "button";
  const out = el("div");
  out.setAttribute("aria-live", "polite");
  btn.addEventListener("click", async () => {
    btn.disabled = true; btn.textContent = t("sh.loading"); out.replaceChildren();
    try {
      const s = await postJSON("/api/share", { plan_id: d.plan_id, language: lang.value });
      const text = [s.title, s.post, s.caption, s.hashtags.join(" ")].filter(Boolean).join("\n\n");
      const copy = el("button", "btn ghost", t("sh.copy"));
      copy.type = "button";
      copy.addEventListener("click", async () => { try { await navigator.clipboard.writeText(text); copy.textContent = t("sh.copied"); } catch { copy.textContent = t("sh.copy_failed"); } });
      const actions = el("div", "row", copy);
      if (navigator.share) {
        const sys = el("button", "btn ghost", t("sh.system"));
        sys.type = "button";
        sys.addEventListener("click", () => navigator.share({ title: s.title, text }).catch(() => {}));
        actions.append(sys);
      }
      out.append(el("h3", null, s.title), el("div", "share-post", s.post), el("p", null, el("strong", null, t("sh.caption")), s.caption), el("p", "muted", s.hashtags.join(" ")), actions);
    } catch (e) { out.append(el("p", "alert bad", t("sh.failed", { msg: e.message }))); }
    btn.disabled = false; btn.textContent = t("sh.btn");
  });
  const label = el("label", null, t("sh.lang"));
  label.htmlFor = "share-lang";
  return card(t("sh.h"), el("div", "row", el("div", null, label, lang), btn), el("p", "muted", t("sh.note")), out);
}

function renderResult(d) {
  currentPlan = d;
  const out = $("#result");
  out.replaceChildren();
  out.append(overviewCard(d), weatherCard(d), membersCard(d), trendingCard(d),
    el("div", "grid2", transportCard(d), hotelCard(d)),
    el("div", "grid2", groundCard(d), costCard(d)),
    itineraryCard(d));
  const coupons = couponsCard(d);
  if (coupons) out.append(coupons);
  out.append(checksCard(d), remindersCard(d), ...inboundCards(d));
  if (d.constraints.diet_cards.length) out.append(phraseCards(t("ph.diet"), d.constraints.diet_cards));
  out.append(shareCard(d));
}

// ------------------------------------------------------------------ planning
let planState = "idle"; // idle | running | done | error
let lastNotice = null;  // [key, vars, cls] so notices can be re-translated

function showNotice(key, vars, cls) {
  lastNotice = key ? [key, vars, cls] : null;
  notice(key ? t(key, vars) : "", cls);
}

function setSubmit() {
  const running = planState === "running";
  $("#submit").disabled = running;
  $("#submit").textContent = t(running ? "btn.planning" : "btn.plan");
}

function finish(state) {
  finished = true;
  planState = state;
  setSubmit();
}

function renderResultArea() {
  if (planState === "running") $("#result").replaceChildren(el("div", "card empty", t("result.loading")));
  else if (currentPlan) renderResult(currentPlan);
  else if (planState === "idle") $("#result").replaceChildren(el("div", "card empty", t("result.empty")));
}

function start(query, profile) {
  if (source) source.close();
  for (const k of Object.keys(stepEvents)) delete stepEvents[k];
  finished = false;
  planState = "running";
  currentPlan = null;
  currentQuery = query;
  renderSteps();
  showNotice(null);
  $("#elapsed").textContent = "";
  $("#elapsed").dataset.ms = "";
  renderResultArea();
  setSubmit();
  const qs = "q=" + encodeURIComponent(query) + (profile ? "&profile=" + encodeURIComponent(profile) : "");
  source = new EventSource("/api/plan/stream?" + qs);
  source.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    if (ev.type === "step") setStep(ev);
    else if (ev.type === "result") {
      source.close();
      finish("done");
      renderResult(ev.data);
      $("#elapsed").dataset.ms = ev.elapsed_ms;
      $("#elapsed").textContent = t("plan.done", { s: (ev.elapsed_ms / 1000).toFixed(1) });
      if (ev.data.profile_saved) showProfile(ev.data.profile_saved, true);
    } else if (ev.type === "error") {
      source.close();
      finish("error");
      showNotice("plan.failed", { msg: ev.message }, "bad");
      $("#result").replaceChildren();
    }
  };
  // The server closes the stream after the final event; we close first, so
  // onerror only fires on a real connection problem.
  source.onerror = () => {
    source.close();
    if (!finished) { finish("error"); showNotice("plan.disconnected", null, "bad"); }
  };
}

$("#form").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("#query").value.trim();
  const profile = $("#profile").value.trim();
  if (profile && !/^[\w\u4e00-\u9fff-]{1,32}$/.test(profile)) { showNotice("err.profile_id", null, "bad"); return; }
  localStorage.setItem("profileId", profile);
  if (q) start(q, profile); else $("#query").focus();
});

// Example chips: tag + label translated; the query follows the UI language (except foreign-language examples).
function renderChips() {
  for (const chip of document.querySelectorAll(".chip")) {
    chip.replaceChildren(el("b", null, t(chip.dataset.key + ".tag")), " ", t(chip.dataset.key));
  }
}
for (const chip of document.querySelectorAll(".chip")) {
  chip.addEventListener("click", () => {
    $("#query").value = (en() && chip.dataset.qEn) || chip.dataset.q;
    if (chip.dataset.profile) { $("#profile").value = chip.dataset.profile; showProfile(chip.dataset.profile, true); }
    $("#query").focus();
  });
}

// ------------------------------------------------------------------ profile
let lastProfile = null; // [id, quiet] for re-translation
async function showProfile(id, quiet) {
  const info = $("#profile-info");
  lastProfile = [id, quiet];
  if (!id) { info.textContent = t("profile.enter"); return; }
  try {
    const r = await api("/api/profile?id=" + encodeURIComponent(id));
    const p = r.profile;
    const members = p.members.map((m) => memberLabel(m) + (m.allergies.length ? t("profile.allergy", { a: m.allergies.join("/") }) : "")).join(t("sep"));
    info.textContent = t("profile.info", { id, members, updated: p.updated });
  } catch (e) {
    info.textContent = quiet ? t("profile.missing_quiet", { id }) : t("profile.missing", { msg: e.message });
  }
}
$("#load-profile").addEventListener("click", () => showProfile($("#profile").value.trim()));
$("#del-profile").addEventListener("click", async () => {
  const id = $("#profile").value.trim();
  if (!id || !confirm(t("profile.confirm_delete", { id }))) return;
  lastProfile = null;
  try {
    const r = await api("/api/profile?id=" + encodeURIComponent(id), { method: "DELETE" });
    $("#profile-info").textContent = t(r.deleted ? "profile.deleted" : "profile.not_exist", { id });
  } catch (e) { $("#profile-info").textContent = t("profile.delete_failed", { msg: e.message }); }
});

// ------------------------------------------------------------------ inbound Q&A
$("#ask-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = $("#ask-q").value.trim();
  if (!q) { $("#ask-q").focus(); return; }
  const btn = $("#ask-btn"), out = $("#ask-out");
  btn.disabled = true; out.replaceChildren(el("p", "muted", t("ask.loading")));
  try {
    const r = await postJSON("/api/ask", { question: q, language: $("#ask-lang").value });
    out.replaceChildren(
      r.blocked ? el("p", "alert bad", r.answer) : el("p", "answer", r.answer),
      r.in_scope ? sources(r.sources) : (!r.blocked ? el("p", "muted", t("ask.no_kb")) : null));
  } catch (err) { out.replaceChildren(el("p", "alert bad", t("ask.failed", { msg: err.message }))); }
  btn.disabled = false;
});

// ------------------------------------------------------------------ receipts
function renderExpenses() {
  const box = $("#rc-list");
  $("#rc-csv").disabled = !expenses.length;
  if (!expenses.length) { box.replaceChildren(el("p", "muted", t("rc.empty"))); return; }
  const cur = expenses[expenses.length - 1].home_currency;
  const rows = expenses.map((x) => [x.date || "—", x.merchant_translated || x.merchant, tz(x.category), money(x.total_cny), money(x.total_home, x.home_currency)]);
  const sumCny = expenses.reduce((s, x) => s + x.total_cny, 0);
  const sumHome = expenses.filter((x) => x.home_currency === cur).reduce((s, x) => s + x.total_home, 0);
  rows.push({ cls: "total", cells: [t("total"), "", "", money(sumCny), money(sumHome, cur)] });
  const head = en() ? ["Date", "Merchant", "Category", "RMB", "Home currency"] : ["日期", "商户", "类别", "人民币", "本币"];
  box.replaceChildren(table(null, head, rows, [3, 4]));
}
$("#rc-file").addEventListener("change", (e) => {
  const file = e.target.files[0], out = $("#rc-out");
  if (!file) return;
  if (file.size > 5 * 1024 * 1024) { out.replaceChildren(el("p", "alert bad", t("rc.too_big"))); return; }
  const reader = new FileReader();
  reader.onload = async () => {
    const [meta, b64] = String(reader.result).split(",");
    const media = (meta.match(/^data:([^;]+);base64$/) || [])[1] || file.type;
    out.replaceChildren(el("p", "muted", t("rc.loading")));
    try {
      const r = await postJSON("/api/receipt", { image_b64: b64, media_type: media, language: $("#rc-lang").value, home_currency: $("#rc-cur").value });
      if (!r.is_receipt) { out.replaceChildren(el("p", "alert warn", r.message)); return; }
      expenses.push(r);
      renderExpenses();
      out.replaceChildren(el("div", "option",
        el("div", "option-head", el("strong", null, r.merchant_translated || r.merchant), badge(tz(r.category), "gray")),
        el("div", "muted", `${r.merchant} · ${r.date || t("rc.no_date")}`),
        el("ul", "plain", r.items.map((i) => el("li", null, `${i.name_translated || i.name} (${i.name}): ${money(i.amount, r.currency)}`))),
        el("div", "price", `${money(r.total, r.currency)} ≈ ${money(r.total_home, r.home_currency)}`),
        el("div", "muted", r.fx_note)));
    } catch (err) { out.replaceChildren(el("p", "alert bad", t("rc.failed", { msg: err.message }))); }
    e.target.value = "";
  };
  reader.readAsDataURL(file);
});
$("#rc-csv").addEventListener("click", () => {
  // Prefix cells that start with = + - @ so spreadsheet apps don't run them as formulas.
  const cell = (v) => { let s = String(v ?? ""); if (/^[=+\-@\t\r]/.test(s)) s = "'" + s; return '"' + s.replace(/"/g, '""') + '"'; };
  const head = ["date", "merchant", "merchant_translated", "category", "amount", "currency", "amount_cny", "amount_home", "home_currency"];
  const lines = [head.map(cell).join(",")].concat(expenses.map((x) =>
    [x.date, x.merchant, x.merchant_translated, x.category, x.total, x.currency, x.total_cny, x.total_home, x.home_currency].map(cell).join(",")));
  const blob = new Blob(["\ufeff" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const a = el("a");
  a.href = URL.createObjectURL(blob);
  a.download = "expenses.csv";
  document.body.append(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
});

// ------------------------------------------------------------------ language switch
function renderAll() {
  applyStatic();
  renderChips();
  renderSteps();
  setSubmit();
  renderResultArea();
  renderExpenses();
  if (lastNotice) notice(t(lastNotice[0], lastNotice[1]), lastNotice[2]);
  const ms = $("#elapsed").dataset.ms;
  if (ms) $("#elapsed").textContent = t("plan.done", { s: (ms / 1000).toFixed(1) });
  if (lastProfile) showProfile(...lastProfile);
}
function setLang(lang) {
  if (!LANGS.includes(lang) || lang === LANG) return;
  LANG = lang;
  localStorage.setItem("uiLang", lang);
  renderAll();
}
for (const btn of document.querySelectorAll(".lang-btn")) btn.addEventListener("click", () => setLang(btn.dataset.lang));

// ------------------------------------------------------------------ init
renderAll();
const savedProfile = localStorage.getItem("profileId");
if (savedProfile) { $("#profile").value = savedProfile; showProfile(savedProfile, true); }
api("/api/health").then((h) => {
  if (!h.token_present) showNotice("err.no_token", null, "warn");
}).catch(() => showNotice("err.no_backend", null, "bad"));
