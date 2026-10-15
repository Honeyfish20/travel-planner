"""Orchestrator.

Pipeline:
    intake (LLM) → constraints (rules)
      → transport ∥ hotel ∥ ground ∥ inbound ∥ weather ∥ trending   (parallel)
         weather:  Open-Meteo forecast / last-year archive, per-day 5 time blocks
         trending: Exa + 博查 web search via MCP → LLM ranking → partner coupons
      → itinerary (LLM, weather-aware; re-checked by rules, outdoor POIs in bad weather swapped)
      → check (rules: policy, constraints, weather fit, cost + coupons, RMB cash, network timeline)

Events streamed to the browser as Server-Sent Events:
    {"type": "step", "agent": "...", "status": "running" | "done" | "skipped" | "error", ...}
    {"type": "result", "data": {...}, "elapsed_ms": 12345}
    {"type": "error", "message": "..."}
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

import agents
import data
import memory
import recommend
import weather

logger = logging.getLogger(__name__)

Emit = Callable[[dict], None]
TRIP_NAMES = {"business": "商务出行", "family": "家庭游", "leisure": "休闲游"}

_PLANS: "OrderedDict[str, dict]" = OrderedDict()
_PLANS_LOCK = threading.Lock()
MAX_CACHED_PLANS = 50


def get_plan(plan_id: str) -> Optional[dict]:
    with _PLANS_LOCK:
        return _PLANS.get(plan_id)


def _cache(plan: dict) -> None:
    with _PLANS_LOCK:
        _PLANS[plan["plan_id"]] = plan
        while len(_PLANS) > MAX_CACHED_PLANS:
            _PLANS.popitem(last=False)


def _summary(agent: str, res) -> str:
    if agent == "intake":
        tags = TRIP_NAMES[res["trip_type"]] + ("·入境游" if res["is_inbound"] else "")
        note = f"；{res['memory_note']}" if res["memory_note"] else ""
        return f"{tags}：{res['origin']}→{res['destination']} {res['depart_date'][5:]}~{res['return_date'][5:]}，{res['party_size']} 人{note}"
    if agent == "constraints":
        return f"{len(res['constraints']['rules'])} 条约束；排除 {len(res['pois_excluded'])} 个景点、{len(res['restaurants_excluded'])} 家餐厅"
    if agent == "transport":
        o, r = res["outbound"], res["return"]
        return f"去程 {o['number']}（{'高铁' if o['mode'] == 'rail' else '航班'}）/ 返程 {r['number']}"
    if agent == "hotel":
        return f"{res['hotel']['name']}（{res['room_type']} × {res['rooms']}）" if res["hotel"] else "无需住宿"
    if agent == "ground":
        return f"接 {res['arrival']['mode']} / 送 {res['departure']['mode']}"
    if agent == "inbound":
        return f"{len(res['checklist'])} 项入境准备，均附知识库来源"
    if agent == "weather":
        bad = sum(d["bad_blocks"] for d in res["days"])
        rng = f"{min(d['t_min'] for d in res['days']):.0f}–{max(d['t_max'] for d in res['days']):.0f}°C"
        return f"{res['source_label']}：{len(res['days'])} 天 {rng}，{bad} 个时段不宜户外"
    if agent == "trending":
        ok = [p["name"] for p in res["providers"].values() if p["ok"]]
        top = "、".join(h["poi"]["name"] for h in res["hot"][:3]) or "无景点数据"
        src = f"{'+'.join(ok)} {len(res['results'])} 条结果" if ok else "未获得检索结果，用内置热度"
        coupons = sum(1 for h in res["hot"] if h["coupon"] and h["coupon"]["eligible"])
        return f"{src}；热门：{top}；可用优惠券 {coupons} 张"
    if agent == "itinerary":
        fixes = f"，约束修正 {len(res['fixes'])} 处" if res["fixes"] else ""
        wx = f"，天气调整 {len(res['weather_fixes'])} 处" if res["weather_fixes"] else ""
        return f"{len(res['days'])} 天行程{fixes}{wx}"
    if agent == "check":
        counts = {s: sum(1 for c in res["checks"] if c["status"] == s) for s in ("pass", "warn", "fail")}
        cash = f"，建议现金 ¥{res['cash']['total_cny']}" if res["cash"] else ""
        return f"{counts['pass']} 通过 / {counts['warn']} 提醒 / {counts['fail']} 违规，总费用 ¥{res['cost']['total_after_coupons_cny']:,}{cash}"
    return "完成"


TRIP_NAMES_EN = {"business": "Business", "family": "Family", "leisure": "Leisure"}


def _summary_en(agent: str, res) -> str:
    """English step summary for the bilingual UI."""
    if agent == "intake":
        tags = TRIP_NAMES_EN[res["trip_type"]] + (" · inbound" if res["is_inbound"] else "")
        note = "; profile applied" if res["memory_note"] else ""
        o, d = (data.CITIES[c]["en"] for c in (res["origin"], res["destination"]))
        return f"{tags}: {o}→{d} {res['depart_date'][5:]}~{res['return_date'][5:]}, {res['party_size']} pax{note}"
    if agent == "constraints":
        return f"{len(res['constraints']['rules'])} rules; excluded {len(res['pois_excluded'])} attractions, {len(res['restaurants_excluded'])} restaurants"
    if agent == "transport":
        o, r = res["outbound"], res["return"]
        return f"Out {o['number']} ({'rail' if o['mode'] == 'rail' else 'flight'}) / back {r['number']}"
    if agent == "hotel":
        return f"{res['hotel']['name']} ({res['rooms']} room(s))" if res["hotel"] else "No hotel needed"
    if agent == "ground":
        return "Transfers booked for arrival and departure"
    if agent == "inbound":
        return f"{len(res['checklist'])} entry-prep items, all sourced"
    if agent == "weather":
        bad = sum(d["bad_blocks"] for d in res["days"])
        src = "+".join({"forecast": "forecast", "archive": "last-year reference", "demo": "demo"}[s] for s in res["sources"])
        rng = f"{min(d['t_min'] for d in res['days']):.0f}–{max(d['t_max'] for d in res['days']):.0f}°C"
        return f"{src}: {len(res['days'])} days {rng}, {bad} time slots not good for outdoors"
    if agent == "trending":
        ok = [{"博查": "Bocha"}.get(p["name"], p["name"]) for p in res["providers"].values() if p["ok"]]
        src = f"{'+'.join(ok)} {len(res['results'])} results" if ok else "no search results, built-in popularity"
        coupons = sum(1 for h in res["hot"] if h["coupon"] and h["coupon"]["eligible"])
        return f"{src}; top {min(3, len(res['hot']))} picked; {coupons} usable coupon(s)"
    if agent == "itinerary":
        fixes = f", {len(res['fixes'])} constraint fix(es)" if res["fixes"] else ""
        wx = f", {len(res['weather_fixes'])} weather swap(s)" if res["weather_fixes"] else ""
        return f"{len(res['days'])}-day itinerary{fixes}{wx}"
    if agent == "check":
        counts = {s: sum(1 for c in res["checks"] if c["status"] == s) for s in ("pass", "warn", "fail")}
        cash = f", cash ¥{res['cash']['total_cny']}" if res["cash"] else ""
        return f"{counts['pass']} pass / {counts['warn']} warn / {counts['fail']} fail, total ¥{res['cost']['total_after_coupons_cny']:,}{cash}"
    return "Done"


def plan(query: str, emit: Emit, profile_id: Optional[str] = None) -> Optional[dict]:
    """Run the full pipeline. Errors are reported via emit; returns None on failure."""
    lock = threading.Lock()

    def send(event: dict) -> None:
        with lock:
            emit(event)

    def step(agent: str, fn, *args):
        send({"type": "step", "agent": agent, "status": "running"})
        start = time.perf_counter()
        try:
            res = fn(*args)
        except Exception as e:
            send({"type": "step", "agent": agent, "status": "error", "message": str(e)})
            raise
        ms = int((time.perf_counter() - start) * 1000)
        if res is None:
            send({"type": "step", "agent": agent, "status": "skipped", "elapsed_ms": ms, "summary": "不适用", "summary_en": "Not applicable"})
        else:
            send({"type": "step", "agent": agent, "status": "done", "elapsed_ms": ms,
                  "summary": _summary(agent, res), "summary_en": _summary_en(agent, res)})
        return res

    t0 = time.perf_counter()
    try:
        req = step("intake", agents.intake, query, profile_id)
        bundle = step("constraints", agents.constraint_agent, req)
        cons = bundle["constraints"]
        parallel = (("transport", agents.transport_agent, (req, cons)), ("hotel", agents.hotel_agent, (req, cons)),
                    ("ground", agents.ground_agent, (req, cons)), ("inbound", agents.inbound_agent, (req, cons)),
                    ("weather", weather.weather_agent, (req, cons)), ("trending", recommend.trending_agent, (req, bundle)))
        with ThreadPoolExecutor(max_workers=len(parallel)) as pool:
            futures = {name: pool.submit(step, name, fn, *args) for name, fn, args in parallel}
            transport, hotel, ground, inbound, wx, trending = (futures[n].result() for n, _, _ in parallel)
        itinerary = step("itinerary", agents.itinerary_agent, req, bundle, transport, hotel, ground, wx, trending)
        check = step("check", agents.check_agent, req, bundle, transport, hotel, ground, itinerary)
    except agents.PlanningError as e:
        send({"type": "error", "message": str(e)})
        return None
    except Exception as e:  # model / network failures
        logger.exception("planning failed")
        send({"type": "error", "message": f"{type(e).__name__}: {e}"})
        return None

    saved = None
    if profile_id and memory.valid_id(profile_id):
        try:
            memory.save_profile(profile_id, req)
            saved = profile_id
        except OSError:
            logger.exception("failed to save profile")

    result = {
        "plan_id": uuid.uuid4().hex,
        "request": req,
        "constraints": bundle,
        "transport": transport,
        "hotel": hotel,
        "ground": ground,
        "inbound": inbound,
        "weather": wx,
        "trending": trending,
        "itinerary": itinerary,
        "checks": check["checks"],
        "needs_approval": check["needs_approval"],
        "cost": check["cost"],
        "cash": check["cash"],
        "network": check["network"],
        "payment_plan": check["payment_plan"],
        "profile_saved": saved,
    }
    _cache(result)
    send({"type": "result", "data": result, "elapsed_ms": int((time.perf_counter() - t0) * 1000)})
    return result
