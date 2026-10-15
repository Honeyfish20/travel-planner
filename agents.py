"""Agents for business, family and inbound trip planning.

LLM agents (Ada claude-sonnet-5): intake, transport, hotel, ground, inbound,
itinerary, plus on-demand ask / share / receipt.
Rule agents (deterministic): constraints, check (policy + constraint
verification + cost + payment plan).

Design rules:
- Hard constraints are applied to candidates before the model sees them, and
  the model's itinerary is re-checked afterwards (`_enforce`).
- The model only picks ids from candidate lists; unknown ids fall back to a
  deterministic choice.
- Visa / payment / connectivity answers come only from the knowledge base and
  must cite valid sources; card numbers and passwords are blocked or redacted.
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import math
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import ada_client
import constraints
import data
import guardrails
import knowledge
import memory
import recommend
import tips
import weather

logger = logging.getLogger(__name__)


class PlanningError(Exception):
    """User-facing error (unsupported city, missing date, bad upload, ...)."""


WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
LANG_NAMES = {"zh": "简体中文", "en": "English", "ja": "日本語", "ko": "한국어"}
CHINA_NAMES = {"中国", "中国大陆", "china", "prc", "中华人民共和国"}
NATIONALITY_CURRENCY = {
    "美国": "USD", "英国": "GBP", "日本": "JPY", "韩国": "KRW", "新加坡": "SGD", "德国": "EUR", "法国": "EUR",
    "意大利": "EUR", "西班牙": "EUR", "荷兰": "EUR", "澳大利亚": "AUD", "加拿大": "CAD", "中国香港": "HKD", "香港": "HKD",
}
TRIP_TYPES = {"business", "family", "leisure"}
MOBILITY = {"normal", "limited", "wheelchair"}
DIETS = {"none", "halal", "vegetarian"}
PACES = {"relaxed", "normal", "packed"}
ITEM_TYPES = {"transport", "hotel", "poi", "meal", "rest", "work", "free"}
MAX_NIGHTS = 14
MAX_MEMBERS = 12
MAX_RECEIPT_BYTES = 5 * 1024 * 1024
ITINERARY_MAX_TOKENS = 8000
RECEIPT_MEDIA = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def _today() -> date:
    return date.today()


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)


def _parse_date(value) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _num(value, lo, hi, cast=float):
    try:
        x = cast(value)
    except (TypeError, ValueError):
        return None
    return x if lo <= x <= hi else None


def _lang_name(code: str) -> str:
    return LANG_NAMES.get(code, LANG_NAMES["zh"])


def _hour(ts: str) -> int:
    return int(ts[11:13])


def _req_brief(req: dict) -> dict:
    keys = ("trip_type", "origin", "destination", "depart_date", "return_date", "nights", "purpose",
            "preferences", "pace", "budget_cny", "is_inbound", "language")
    brief = {k: req[k] for k in keys}
    brief["members"] = [constraints.member_label(m) for m in req["members"]]
    return brief


# ================================================================== intake
INTAKE_PROMPT = """ROLE: intake
你是出行需求解析 Agent，支持商务出行、家庭游和入境游（外国游客来中国）。把用户的需求解析成结构化 JSON。
今天是 {today}。支持的城市：{cities}。
规则：
- 相对日期（“下周三”“后天”）按今天换算成具体日期；无法确定的字段填 null。
- 城市用支持列表中的中文名；不在列表中的城市原样填写。
- trip_type：出差、拜访客户、开会为 business；带孩子或老人、全家出行为 family；其他旅游为 leisure。
- members：列出每位出行人。用户明确提到同行人（如“带孩子和奶奶”）时 members_described=true；只说“全家”“我们”而没说明是谁时 members_described=false，members 留空。
  - role 用简短中文称呼（我、妻子、孩子、奶奶、同事等）；age 为整数或 null。
  - mobility：normal / limited（老人行动较慢、腿脚不便）/ wheelchair。
  - max_walk_km：用户明确说明每天步行上限时填数字，否则 null。
  - allergies：过敏食物列表，尽量使用标准中文名：花生、坚果、贝类、甲壳类、鱼、牛奶、鸡蛋、小麦、大豆、芝麻；其他过敏原原样填写。diet：none / halal / vegetarian。
  - group：多个家庭一起出行并要分摊费用时，填所属家庭名称（如“我家”“王家”），否则 null。
- pace：节奏轻松为 relaxed，紧凑为 packed，否则 normal。
- budget_amount 和 budget_currency：预算金额与币种（CNY、USD、EUR、GBP、JPY、KRW、SGD、HKD、AUD、CAD）。
- nationality：出行人国籍（中文国名），未提及时填 null；language：用户使用的语言 zh / en / ja / ko。
只输出一个 JSON 对象，例如：
{"trip_type": "family", "origin": "上海", "destination": "杭州", "depart_date": "YYYY-MM-DD", "return_date": "YYYY-MM-DD", "travelers": 3, "members_described": true, "members": [{"role": "孩子", "age": 5, "mobility": "normal", "max_walk_km": null, "allergies": ["花生"], "diet": "none", "group": null}], "purpose": "家庭旅游", "preferences": [], "pace": "normal", "budget_amount": null, "budget_currency": "CNY", "nationality": null, "language": "zh"}"""

_FILL_DEFAULTS = {"age": None, "mobility": "normal", "max_walk_km": None, "allergies": [], "diet": "none", "group": None}


def _norm_member(m, i: int) -> dict:
    m = m if isinstance(m, dict) else {}
    allergies = m.get("allergies") or []
    if isinstance(allergies, str):
        allergies = [allergies]
    return {
        "role": str(m.get("role") or f"出行人{i + 1}")[:20],
        "age": _num(m.get("age"), 0, 110, int),
        "mobility": m.get("mobility") if m.get("mobility") in MOBILITY else "normal",
        "max_walk_km": _num(m.get("max_walk_km"), 0.5, 30),
        "allergies": [str(a).strip()[:20] for a in allergies if str(a).strip()][:8],
        "diet": m.get("diet") if m.get("diet") in DIETS else "none",
        "group": str(m["group"])[:20] if m.get("group") else None,
    }


def _merge_members(parsed: List[dict], stored: List[dict]):
    """Fill missing details of mentioned members from memory, matched by role."""
    used, out = set(), []
    for m in parsed:
        idx = next((i for i, s in enumerate(stored) if i not in used and s["role"] == m["role"]), None)
        if idx is None:
            out.append(m)
            continue
        used.add(idx)
        merged = dict(m)
        for key, default in _FILL_DEFAULTS.items():
            if merged[key] == default and stored[idx].get(key) not in (None, [], "normal", "none"):
                merged[key] = stored[idx][key]
        out.append(merged)
    return out, len(used)


def intake(query: str, profile_id: Optional[str] = None) -> dict:
    today = _today()
    supported = "、".join(data.CITIES)
    system = (INTAKE_PROMPT
              .replace("{today}", f"{today.isoformat()}（{WEEKDAYS[today.weekday()]}）")
              .replace("{cities}", supported))
    raw = ada_client.complete_json(system, query, max_tokens=900)

    origin, dest = data.normalize_city(raw.get("origin")), data.normalize_city(raw.get("destination"))
    if not origin:
        raise PlanningError(f"无法识别出发城市「{raw.get('origin') or '未提供'}」。演示数据支持：{supported}")
    if not dest:
        raise PlanningError(f"无法识别目的城市「{raw.get('destination') or '未提供'}」。演示数据支持：{supported}")
    if origin == dest:
        raise PlanningError("出发城市与目的城市相同")
    depart = _parse_date(raw.get("depart_date"))
    if not depart:
        raise PlanningError("没有识别到出发日期，请在需求中说明，例如“10月20日出发”")
    if depart < today:
        raise PlanningError(f"出发日期 {depart} 早于今天 {today}")
    ret = _parse_date(raw.get("return_date")) or depart + timedelta(days=2)
    if ret < depart:
        raise PlanningError("返程日期早于出发日期")
    if (ret - depart).days > MAX_NIGHTS:
        raise PlanningError(f"演示版最多规划 {MAX_NIGHTS} 晚，请拆分行程")

    raw_members = raw.get("members") if isinstance(raw.get("members"), list) else []
    members = [_norm_member(m, i) for i, m in enumerate(raw_members[:MAX_MEMBERS])]
    stored = memory.get_profile(profile_id) if profile_id else None
    memory_note = None
    if stored:
        saved = [_norm_member(m, i) for i, m in enumerate(stored.get("members") or [])]
        if saved and (not raw.get("members_described") or not members):
            members, memory_note = saved, f"已从档案带入 {len(saved)} 位出行人"
        elif saved:
            members, n = _merge_members(members, saved)
            if n:
                memory_note = f"已从档案补全 {n} 位出行人的信息"
    travelers = _num(raw.get("travelers"), 1, MAX_MEMBERS, int) or 1
    while len(members) < travelers:
        members.append(_norm_member({"role": "我"} if not members else {}, len(members)))
    if not members:
        members = [_norm_member({"role": "我"}, 0)]

    groups = list(dict.fromkeys(m["group"] for m in members if m["group"]))
    if groups:
        for m in members:
            m["group"] = m["group"] or groups[0]

    language = raw.get("language") if raw.get("language") in LANG_NAMES else ((stored or {}).get("language") or "zh")
    nationality = raw.get("nationality") or (stored or {}).get("nationality")
    foreign = bool(nationality and str(nationality).strip().lower() not in CHINA_NAMES) or language != "zh"
    is_inbound = data.is_mainland(dest) and foreign
    home_currency = (NATIONALITY_CURRENCY.get(str(nationality or "")) or (stored or {}).get("home_currency")
                     or ("USD" if foreign else "CNY"))

    budget_amount = _num(raw.get("budget_amount"), 1, 1e8)
    budget_currency = str(raw.get("budget_currency") or "CNY").upper()
    if budget_currency not in knowledge.FX_DEMO:
        budget_currency = "CNY"
    budget_cny = round(knowledge.to_cny(budget_amount, budget_currency)) if budget_amount else None

    trip_type = raw.get("trip_type") if raw.get("trip_type") in TRIP_TYPES else "leisure"
    has_dependants = any(m["age"] is not None and (m["age"] < 18 or m["age"] >= 65) for m in members)
    if trip_type == "leisure" and len(members) > 1 and has_dependants:
        trip_type = "family"
    prefs = raw.get("preferences") or []
    if isinstance(prefs, str):
        prefs = [prefs]

    return {
        "query": query,
        "trip_type": trip_type,
        "is_business": trip_type == "business",
        "is_family": trip_type == "family",
        "is_inbound": is_inbound,
        "origin": origin,
        "destination": dest,
        "depart_date": depart.isoformat(),
        "return_date": ret.isoformat(),
        "nights": (ret - depart).days,
        "members": members,
        "party_size": len(members),
        "groups": groups,
        "purpose": str(raw.get("purpose") or ("商务出行" if trip_type == "business" else "旅游")),
        "preferences": [str(p) for p in prefs][:8],
        "pace": raw.get("pace") if raw.get("pace") in PACES else "normal",
        "budget_cny": budget_cny,
        "budget_original": {"amount": budget_amount, "currency": budget_currency} if budget_amount else None,
        "nationality": nationality,
        "language": language,
        "home_currency": home_currency,
        "domestic": data.is_domestic(origin, dest),
        "distance_km": round(data.distance_km(origin, dest)),
        "profile_id": profile_id,
        "memory_note": memory_note,
    }


# ================================================================== constraints (rules)
def constraint_agent(req: dict) -> dict:
    cons = constraints.derive(req)
    pois, pois_excluded = constraints.filter_pois(data.search_pois(req["destination"]), cons)
    rests, rests_excluded = constraints.filter_restaurants(data.search_restaurants(req["destination"]), cons)
    return {
        "constraints": cons,
        "pois": pois,
        "pois_excluded": pois_excluded,
        "restaurants": rests,
        "restaurants_excluded": rests_excluded,
        "diet_cards": constraints.diet_cards(cons),
    }


# ================================================================== transport
TRANSPORT_PROMPT = """ROLE: transport
你是城际交通 Agent，从候选的航班和高铁中为出行人选择一个去程和一个返程。
候选已经按出行政策和同行人约束过滤（例如去掉了红眼班次、过早或过晚的班次）。
选择原则：
{rules}
只输出 JSON：{"outbound_id": "...", "return_id": "...", "reason": "不超过80字的理由，使用{language}"}"""
_TRANSPORT_BUSINESS = ("1. 票价不超过同交通方式、同舱位最低价的 {limit}%，尽量接近最低价；2. 兼顾出行目的（如上午有会议，选早班或前一天抵达）；"
                       "3. 同等条件下优先协议航司和直飞；4. 距离较近时，高铁通常比飞机门到门更省时。")
_TRANSPORT_LEISURE = ("1. 优先门到门时间短、换乘少的方式，距离较近时优先高铁；2. 有老人或幼儿同行时选择白天、时间宽松的班次；"
                      "3. 满足以上条件时控制全家总价；4. 抵达时间要给当天的安排留出余地。")


def _transport_allowed(opt: dict, req: dict) -> bool:
    if opt["mode"] == "rail":
        return opt["cabin"] == "二等座" or not req["is_business"]
    if opt["cabin"] == "公务舱":
        return req["is_business"] and opt["duration_h"] >= data.POLICY["business_class_min_hours"]
    return True


def _time_ok(opt: dict, cons: dict) -> bool:
    if _hour(opt["arrive"]) < 6:  # red-eye arrival
        return False
    if cons["avoid_early_late"] and (_hour(opt["depart"]) < 7 or _hour(opt["arrive"]) >= 22):
        return False
    return True


def _lowest(options: List[dict]) -> dict:
    out: Dict[str, int] = {}
    for o in options:
        key = f"{o['mode']}:{o['cabin']}"
        out[key] = min(out.get(key, o["price_cny"]), o["price_cny"])
    return out


def _option_brief(o: dict) -> dict:
    keys = ("id", "mode", "number", "carrier", "cabin", "depart", "arrive", "duration_h", "stops", "price_cny", "preferred")
    return {k: o[k] for k in keys}


def party_fare(opt: dict, req: dict) -> int:
    return sum(data.transport_fare(opt, m["age"], req["domestic"]) for m in req["members"])


def transport_agent(req: dict, cons: dict) -> dict:
    depart, ret = date.fromisoformat(req["depart_date"]), date.fromisoformat(req["return_date"])
    o, d = req["origin"], req["destination"]
    out_all = data.search_flights(o, d, depart) + data.search_rail(o, d, depart)
    back_all = data.search_flights(d, o, ret) + data.search_rail(d, o, ret)
    if not out_all or not back_all:
        raise PlanningError(f"{o} 与 {d} 之间没有可用的航班或高铁（演示数据）")

    filtered_out = 0

    def eligible(options: List[dict], leg: str) -> List[dict]:
        nonlocal filtered_out
        base = [x for x in options if _transport_allowed(x, req)]
        timed = [x for x in base if _time_ok(x, cons)]
        if leg == "return" and req["nights"] == 0:
            timed = [x for x in timed if _hour(x["depart"]) >= 17] or timed
        filtered_out += len(base) - len(timed)
        pool = timed or base
        picked = []
        for mode in ("rail", "flight"):
            picked += sorted((x for x in pool if x["mode"] == mode), key=lambda x: x["price_cny"])[:6]
        return picked

    out_c, back_c = eligible(out_all, "outbound"), eligible(back_all, "return")
    rules = _TRANSPORT_BUSINESS if req["is_business"] else _TRANSPORT_LEISURE
    system = (TRANSPORT_PROMPT.replace("{rules}", rules)
              .replace("{limit}", str(int((1 + data.POLICY["lowest_fare_tolerance"]) * 100)))
              .replace("{language}", _lang_name(req["language"])))
    user = ("出行需求：\n" + _dumps(_req_brief(req)) + "\n\n约束：\n" + _dumps(cons["rules"])
            + "\n\n去程候选：\n" + _dumps([_option_brief(x) for x in out_c])
            + "\n\n返程候选：\n" + _dumps([_option_brief(x) for x in back_c]))
    choice = ada_client.complete_json(system, user, max_tokens=400)

    outbound = {x["id"]: x for x in out_c}.get(choice.get("outbound_id"))
    inbound = {x["id"]: x for x in back_c}.get(choice.get("return_id"))
    reason = str(choice.get("reason") or "")
    if not outbound or not inbound:
        cheapest = lambda xs: min(xs, key=lambda x: party_fare(x, req))  # noqa: E731
        outbound, inbound = outbound or cheapest(out_c), inbound or cheapest(back_c)
        reason = (reason + "（部分班次编号无效，已回退为总价最低的班次）").strip()
    return {
        "outbound": outbound,
        "return": inbound,
        "party_fare": {"outbound": party_fare(outbound, req), "return": party_fare(inbound, req)},
        "reason": reason,
        "lowest_fare": {"outbound": _lowest(out_all), "return": _lowest(back_all)},
        "candidates": len(out_c) + len(back_c),
        "filtered_out": filtered_out,
    }


# ================================================================== hotel
HOTEL_PROMPT = """ROLE: hotel
你是酒店 Agent，从候选酒店中选择一家。候选已按同行人约束过滤（家庭房、无障碍、英文服务等）。
{rules}
只输出 JSON：{"hotel_id": "...", "reason": "不超过80字的理由，使用{language}"}"""
_HOTEL_BUSINESS = "公司住宿标准：{city} 标准间每晚不超过 {cap} 元。优先标准内的协议酒店（preferred=true）；按出行目的选位置（会议优先市中心或中央商务区，展会优先会展中心）。"
_HOTEL_LEISURE = "选择原则：1. 有儿童时优先有儿童设施的酒店，有老人时优先交通方便的位置；2. 游玩为主优先景区附近或市中心；3. 满足条件时控制价格；4. 不要无理由选择最贵的酒店。"


def hotel_agent(req: dict, cons: dict) -> dict:
    city = req["destination"]
    cap = data.CITIES[city]["hotel_cap"] if req["is_business"] else None
    if req["nights"] == 0:
        return {"hotel": None, "room_type": None, "rooms": 0, "nightly_cny": 0, "nights": 0, "total_cny": 0,
                "cap_cny": cap, "relaxed": False, "reason": "当天往返，无需住宿"}

    cands = data.search_hotels(city)
    use_family = cons["family_room"] and any(h["family_room"] for h in cands)

    def ok(h: dict) -> bool:
        if cons["wheelchair"] and not h["accessible"]:
            return False
        if cons["english_service"] and not h["english_service"]:
            return False
        return h["family_room"] or not use_family

    pool = [h for h in cands if ok(h)]
    relaxed = not pool
    pool = pool or cands
    room_price = lambda h: h["family_room_cny"] if use_family and h["family_room"] else h["nightly_cny"]  # noqa: E731
    rules = (_HOTEL_BUSINESS.replace("{city}", city).replace("{cap}", str(cap))) if req["is_business"] else _HOTEL_LEISURE
    system = HOTEL_PROMPT.replace("{rules}", rules).replace("{language}", _lang_name(req["language"]))
    room_type = "家庭房" if use_family else "标准间"
    user = ("出行需求：\n" + _dumps(_req_brief(req)) + f"\n\n房型：{room_type}"
            + "\n\n候选酒店：\n" + _dumps([{**h, "room_cny": room_price(h)} for h in pool]))
    choice = ada_client.complete_json(system, user, max_tokens=300)

    hotel = {h["id"]: h for h in pool}.get(choice.get("hotel_id"))
    reason = str(choice.get("reason") or "")
    if not hotel:
        if req["is_business"]:
            within = [h for h in pool if h["nightly_cny"] <= cap] or pool
            hotel = min(within, key=lambda h: (not h["preferred"], h["nightly_cny"]))
        else:
            hotel = min(pool, key=lambda h: (cons["kids"] and not h["kids_facilities"], room_price(h)))
        reason = (reason + "（酒店编号无效，已按规则回退）").strip()
    rooms = 1 if use_family else cons["rooms_standard"]
    nightly = room_price(hotel)
    return {"hotel": hotel, "room_type": room_type, "rooms": rooms, "nightly_cny": nightly, "nights": req["nights"],
            "total_cny": nightly * rooms * req["nights"], "cap_cny": cap, "relaxed": relaxed, "reason": reason}


# ================================================================== ground transfers
GROUND_PROMPT = """ROLE: ground
你是接送 Agent，为目的地 {city} 选择抵达时（机场或车站→酒店）和离开时（酒店→机场或车站）的接送方式。候选已按人数、儿童座椅和无障碍要求过滤。
原则：多人同行、有老人幼儿或行李多时优先专车或商务车；单人且时间宽裕可以选地铁或机场快线；商务出行优先企业协议专车；入境游客优先可在携程预付（prepay=true）的方式。
只输出 JSON：{"arrival_transfer_id": "...", "departure_transfer_id": "...", "reason": "不超过80字的理由，使用{language}"}"""


def ground_agent(req: dict, cons: dict) -> dict:
    city = req["destination"]
    party = cons["party_size"]
    transfers = data.search_transfers(city)

    def ok(t: dict) -> bool:
        if cons["child_seat"] and not t["child_seat"]:
            return False
        if cons["wheelchair"] and t["per_person"]:
            return False
        return t["per_person"] or t["capacity"] >= min(party, 6)

    pool = [t for t in transfers if ok(t)] or transfers
    system = GROUND_PROMPT.replace("{city}", city).replace("{language}", _lang_name(req["language"]))
    user = "出行需求：\n" + _dumps(_req_brief(req)) + "\n\n接送方式候选：\n" + _dumps(pool)
    choice = ada_client.complete_json(system, user, max_tokens=300)

    by_id = {t["id"]: t for t in pool}
    default = next((t for t in pool if t["preferred"]), pool[0])
    arrival = by_id.get(choice.get("arrival_transfer_id")) or default
    departure = by_id.get(choice.get("departure_transfer_id")) or default

    def cost(t: dict) -> int:
        return t["price_cny"] * (party if t["per_person"] else math.ceil(party / t["capacity"]))

    return {"arrival": arrival, "departure": departure, "arrival_cny": cost(arrival), "departure_cny": cost(departure),
            "reason": str(choice.get("reason") or "")}


# ================================================================== inbound readiness
INBOUND_PROMPT = """ROLE: inbound
你是入境游助手 Agent，帮外国游客为这次中国行程做准备。
- 只能使用「知识库」中的信息，并在 source_ids 中引用对应条目的 id；不要补充知识库以外的政策细节，不要给出具体的免签天数、手续费比例或限额数字。
- 结合游客情况生成个性化清单：phase 为 before（入境前）、arrival（抵达当天）或 during（行程中）；最多 10 条，每条 task 不超过 60 字（英文不超过 35 词）。
- 不要索要或提及具体的银行卡号、密码、验证码。
- 使用{language}输出。
只输出 JSON：{"visa_note": "...", "visa_source_ids": ["VISA-1"], "checklist": [{"phase": "before", "task": "...", "source_ids": ["PAY-1"]}]}"""
_PHASES = ("before", "arrival", "during")
INBOUND_MAX_TOKENS = 3000
_FALLBACK_PLAN = (("before", "PAY-1"), ("before", "PAY-2"), ("before", "NET-1"), ("before", "NET-2"), ("before", "PAY-4"),
                  ("arrival", "DOC-1"), ("during", "PAY-5"), ("during", "EMG-1"))


def _fallback_checklist(language: str) -> List[dict]:
    """Rule-based checklist straight from the KB; English text for non-Chinese visitors."""
    by_id = {k["id"]: k for k in knowledge.KNOWLEDGE}
    key = "content" if language == "zh" else "en"
    return [{"phase": p, "task": by_id[kid][key], "sources": knowledge.valid_sources([kid])} for p, kid in _FALLBACK_PLAN]


def inbound_agent(req: dict, cons: dict) -> Optional[dict]:
    if not req["is_inbound"]:
        return None
    info = {
        "国籍": req["nationality"], "语言": req["language"], "本币": req["home_currency"],
        "人数": req["party_size"], "有儿童": cons["kids"], "有老人或行动不便者": cons["senior_or_limited"],
        "行程": {"出发地": req["origin"], "目的地": req["destination"], "日期": f"{req['depart_date']} 至 {req['return_date']}"},
    }
    system = INBOUND_PROMPT.replace("{language}", _lang_name(req["language"]))
    user = "游客与行程：\n" + _dumps(info) + "\n\n知识库：\n" + knowledge.kb_for_prompt()
    try:
        raw = ada_client.complete_json(system, user, max_tokens=INBOUND_MAX_TOKENS)
        checklist = []
        for item in raw.get("checklist") or []:
            if not isinstance(item, dict):
                continue
            sources = knowledge.valid_sources(item.get("source_ids"))
            if sources and item.get("task"):  # drop anything not grounded in the KB
                phase = item.get("phase") if item.get("phase") in _PHASES else "before"
                checklist.append({"phase": phase, "task": str(item["task"]), "sources": sources})
        visa_sources = knowledge.valid_sources(raw.get("visa_source_ids"))
        visa_note = str(raw.get("visa_note") or "") if visa_sources else ""
    except (ada_client.AdaError, ValueError) as e:
        logger.warning("inbound model output unusable, using knowledge-base fallback: %s", e)
        checklist, visa_note, visa_sources = [], "", []
    if not checklist:
        checklist = _fallback_checklist(req["language"])
    if not visa_note:
        visa_note = knowledge.KNOWLEDGE[0]["content" if req["language"] == "zh" else "en"]
        visa_sources = knowledge.valid_sources(["VISA-1"])
    return guardrails.redact({
        "visa_note": visa_note,
        "visa_sources": visa_sources,
        "checklist": checklist,
        "payment_phrases": knowledge.PAYMENT_PHRASES,
        "emergency_card": knowledge.EMERGENCY_CARD,
        "kb_updated": knowledge.KB_UPDATED,
    })


# ================================================================== itinerary
ITINERARY_PROMPT = """ROLE: itinerary
你是行程编排 Agent。根据已确定的交通、酒店、接送，【已按同行人约束过滤】的候选景点和餐厅，以及逐日分时段天气，生成逐日行程。
硬性规则：
- 景点只能从「候选景点」中选择，餐厅只能从「候选餐厅」中选择，并填写对应的 ref_id；不要编造其他景点或餐厅。
- 每天景点数不超过 max_pois_per_day，抵达日和离开日最多 1 个；同一景点不要重复安排。
- 天气：「天气」给出每天 5 个时段（早上、上午、午间、下午、晚上）及 outdoor_ok。outdoor_ok=false 的时段（降雨、雷暴、高温、大风）只安排室内景点（indoor=true）、用餐或休息；户外景点放在 outdoor_ok=true 的时段；高温天把户外景点放在早上或傍晚；整天不适合户外时以室内景点为主。
- 热门与优惠：hot_rank 越小越受相似游客欢迎，coupon=true 表示有合作优惠券；在满足约束和天气的前提下优先安排。
- 如果给出了 nap_window，每天在该时段安排 type=rest 的午休，不要在午休时段安排景点。
- 商务出行以工作时段（type=work）为主，景点最多在空闲时间安排 1 个。
- 交通：出发前往机场或车站（国内航班提前 2 小时，国际航班提前 3 小时，高铁提前 1 小时）、航班或高铁、接送、入住和退房。
- 午餐和晚餐尽量从候选餐厅中安排（type=meal），可以重复使用同一家餐厅。
- 时间用 24 小时制 HH:MM；title、detail、summary 和 tips 使用{language}。
- 输出要精简：每天不超过 8 个条目，title 不超过 20 字，detail 不超过 30 字（可以写天气相关的安排理由，没有必要可留空）；景点、餐厅和天气详情系统会自动补充。
- summary 用一两句话说明天气对行程的影响；tips 给出 3–5 条，每条不超过 40 字，结合同行人情况和天气。
只输出 JSON：
{"title": "...", "summary": "不超过100字", "days": [{"date": "YYYY-MM-DD", "items": [{"time": "HH:MM", "type": "transport|hotel|poi|meal|rest|work|free", "ref_id": "P-... 或 R-... 或 null", "title": "...", "detail": "..."}]}], "tips": ["..."]}"""

_POI_BRIEF = ("id", "name", "name_en", "category", "indoor", "walk_km", "duration_h", "kid_score", "best_time")
_REST_BRIEF = ("id", "name", "cuisine", "kid_menu", "high_chair", "price_pp", "english_menu", "foreign_card", "halal", "vegetarian")


def _brief(obj: dict, keys) -> dict:
    return {k: obj[k] for k in keys}


def _normalize_itinerary(raw: dict, default_title: str) -> dict:
    days = []
    for d in raw.get("days") or []:
        if not isinstance(d, dict):
            continue
        items = []
        for i in d.get("items") or []:
            if not isinstance(i, dict):
                continue
            ref = i.get("ref_id")
            items.append({
                "time": str(i.get("time") or ""),
                "type": i.get("type") if i.get("type") in ITEM_TYPES else "free",
                "ref_id": str(ref) if ref else None,
                "title": str(i.get("title") or ""),
                "detail": str(i.get("detail") or ""),
            })
        days.append({"date": str(d.get("date") or ""), "items": items})
    if not days:
        raise ValueError("itinerary has no days")
    return {"title": str(raw.get("title") or default_title), "summary": str(raw.get("summary") or ""),
            "days": days, "tips": [str(t) for t in (raw.get("tips") or []) if t][:6], "generated_by": "model"}


def _day_cap(index: int, n_days: int, cons: dict, req: dict) -> int:
    if req["is_business"] or index == 0 or index == n_days - 1:
        return 1
    return cons["max_pois"] or 1


def _enforce(itin: dict, bundle: dict, req: dict) -> List[str]:
    """Re-check the model's itinerary against the hard constraints; returns fix notes."""
    cons = bundle["constraints"]
    pois = {p["id"]: p for p in bundle["pois"]}
    rests = {r["id"]: r for r in bundle["restaurants"]}
    excluded = {e["id"]: e["reason"] for e in bundle["pois_excluded"] + bundle["restaurants_excluded"]}
    fixes, used = [], set()
    n_days = len(itin["days"])
    for idx, day in enumerate(itin["days"]):
        cap, count, walk, kept = _day_cap(idx, n_days, cons, req), 0, 0.0, []
        for item in day["items"]:
            ref = item["ref_id"] or ""
            if item["type"] == "poi" or ref.startswith("P-"):
                poi = pois.get(ref)
                if not poi:
                    fixes.append(f"{day['date']} 移除「{item['title']}」：{excluded.get(ref, '不在候选景点中')}")
                    continue
                if ref in used:
                    fixes.append(f"{day['date']} 移除重复安排的「{poi['name']}」")
                    continue
                if count >= cap:
                    fixes.append(f"{day['date']} 移除「{poi['name']}」：超过当天 {cap} 个景点的上限")
                    continue
                limit = cons["max_walk_km"]
                if limit and count and walk + poi["walk_km"] > limit:
                    fixes.append(f"{day['date']} 移除「{poi['name']}」：当天步行将超过 {limit:g} 公里")
                    continue
                count, walk = count + 1, walk + poi["walk_km"]
                used.add(ref)
                item.update(type="poi", poi=_brief(poi, _POI_BRIEF))
            elif ref.startswith("R-"):
                rest = rests.get(ref)
                if not rest:
                    fixes.append(f"{day['date']} 移除餐厅「{item['title']}」：{excluded.get(ref, '不在候选餐厅中')}")
                    continue
                item.update(type="meal", restaurant=_brief(rest, _REST_BRIEF))
            kept.append(item)
        day.update(items=kept, poi_count=count, walk_km=round(walk, 1))
    return fixes


def _hot_key(hot_rank: Dict[str, int]):
    return lambda p: hot_rank.get(p["id"], 99)


def _block_weather(b: dict) -> dict:
    return {k: b[k] for k in ("label", "label_en", "icon", "text", "text_en", "temp", "precip_prob", "outdoor_ok", "advice", "advice_en", "tags")}


def _weather_adjust(itin: dict, bundle: dict, wx_report: dict, hot_rank: Dict[str, int]):
    """Attach weather to every item; swap outdoor POIs in bad time blocks for unused indoor ones."""
    cons = bundle["constraints"]
    by_date = {d["date"]: d for d in wx_report["days"]}
    used = {i["ref_id"] for d in itin["days"] for i in d["items"] if i["type"] == "poi"}
    indoor = sorted((p for p in bundle["pois"] if p["indoor"] and p["id"] not in used), key=_hot_key(hot_rank))
    fixes, conflicts = [], []
    for day in itin["days"]:
        wd = by_date.get(day["date"])
        day["weather"] = wd and {k: wd[k] for k in ("icon", "text", "text_en", "t_min", "t_max", "summary", "summary_en", "clothing", "clothing_en",
                                                    "source_label", "source_label_en", "precip_prob_max", "tips", "tips_en")}
        for item in day["items"]:
            blk = weather.block_at(wd, item["time"])
            if blk:
                item["weather"] = _block_weather(blk)
            if item["type"] != "poi" or not blk or blk["outdoor_ok"] or item["poi"]["indoor"]:
                continue
            poi = item["poi"]
            why = blk["label"] + "、".join(weather.TAG_TEXT[t] for t in blk["tags"] if t in weather.BAD_TAGS)
            if "rain" in blk["tags"]:
                why += f"（降雨概率 {blk['precip_prob']}%）"
            limit = cons["max_walk_km"]
            alt = next((p for p in indoor if not limit or day["walk_km"] - poi["walk_km"] + p["walk_km"] <= limit), None)
            if alt:
                indoor.remove(alt)
                fixes.append(f"{day['date']} {item['time']} {why}：把户外的「{poi['name']}」换成室内的「{alt['name']}」")
                day["walk_km"] = round(day["walk_km"] - poi["walk_km"] + alt["walk_km"], 1)
                item.update(ref_id=alt["id"], title=alt["name"], detail=f"因天气调整，原计划：{poi['name']}",
                            poi=_brief(alt, _POI_BRIEF), weather_swapped=True)
            else:
                conflicts.append(f"{day['date']} {item['time']}「{poi['name']}」是户外景点，{why}，没有可替换的室内景点，请备好雨具或调整时间")
    return fixes, conflicts


def _fallback_itinerary(req: dict, bundle: dict, transport: dict, hotel: dict, ground: dict, title: str,
                        wx_report: dict, hot_rank: Dict[str, int]) -> dict:
    cons = bundle["constraints"]
    base = (lambda p: (-p["kid_score"], p["walk_km"])) if cons["kids"] else (lambda p: (p["walk_km"], -p["kid_score"]))
    pois = sorted(bundle["pois"], key=lambda p: (hot_rank.get(p["id"], 99), *base(p)))
    rest = bundle["restaurants"][0] if bundle["restaurants"] else None
    out, back, h = transport["outbound"], transport["return"], hotel["hotel"]
    start = date.fromisoformat(req["depart_date"])
    n_days, days, remaining = req["nights"] + 1, [], list(pois)
    limit = cons["max_walk_km"]
    wdays = {d["date"]: d for d in wx_report["days"]}
    for idx in range(n_days):
        day_iso = (start + timedelta(days=idx)).isoformat()
        wd = wdays.get(day_iso)
        items = []
        if idx == 0:
            items += [{"time": out["depart"][11:], "type": "transport", "ref_id": None, "title": f"{out['number']} {req['origin']} → {req['destination']}", "detail": f"{out['from_hub']} → {out['to_hub']}"},
                      {"time": out["arrive"][11:], "type": "transport", "ref_id": None, "title": f"接站/接机：{ground['arrival']['mode']}", "detail": ""}]
            if h:
                items.append({"time": "", "type": "hotel", "ref_id": None, "title": f"入住 {h['name']}", "detail": f"{hotel['room_type']} × {hotel['rooms']}"})
        slots = ["15:00", "16:30"] if idx == 0 else ["09:30", "15:00", "16:30", "10:30", "17:30"]
        if wd:  # put good-weather slots first so outdoor sights land there
            slots.sort(key=lambda s: not (weather.block_at(wd, s) or {"outdoor_ok": True})["outdoor_ok"])
        pool = sorted(remaining, key=lambda p: (not p["indoor"]) if wd and wd["rainy_day"] else 0)
        cap, walk, picked = _day_cap(idx, n_days, cons, req), 0.0, []
        for p in pool:
            if len(picked) >= min(cap, len(slots)):
                break
            if limit and picked and walk + p["walk_km"] > limit:
                continue
            picked.append(p)
            walk += p["walk_km"]
            remaining.remove(p)
        for k, p in enumerate(picked):
            items.append({"time": slots[k], "type": "poi", "ref_id": p["id"], "title": p["name"], "detail": f"约 {p['duration_h']:g} 小时"})
        if rest and 0 < idx < n_days - 1:
            items.append({"time": "12:00", "type": "meal", "ref_id": rest["id"], "title": f"午餐：{rest['name']}", "detail": rest["cuisine"]})
        if cons["nap_window"] and 0 < idx < n_days - 1:
            items.append({"time": "12:30", "type": "rest", "ref_id": None, "title": "回酒店午休", "detail": cons["nap_window"]})
        if idx == n_days - 1:
            if h:
                items.append({"time": "", "type": "hotel", "ref_id": None, "title": "退房", "detail": ""})
            items.append({"time": back["depart"][11:], "type": "transport", "ref_id": None, "title": f"{back['number']} 返程", "detail": f"{ground['departure']['mode']}前往{back['from_hub']}"})
        items.sort(key=lambda i: i["time"] or "99")
        days.append({"date": day_iso, "items": items})
    return {"title": title, "summary": "模型行程生成失败，以下是系统按已选资源、约束和天气生成的基础行程。", "days": days, "tips": [], "generated_by": "fallback"}


def itinerary_agent(req: dict, bundle: dict, transport: dict, hotel: dict, ground: dict,
                    wx_report: dict, trending: Optional[dict] = None) -> dict:
    cons = bundle["constraints"]
    hot_rank = (trending or {}).get("hot_rank") or {}
    start = date.fromisoformat(req["depart_date"])
    dates = [(start + timedelta(days=i)).isoformat() for i in range(req["nights"] + 1)]
    title = f"{req['origin']} → {req['destination']} · {req['purpose']}"
    candidates = [{**_brief(p, _POI_BRIEF), "hot_rank": hot_rank.get(p["id"]), "coupon": p["name"] in data.COUPONS}
                  for p in sorted(bundle["pois"], key=_hot_key(hot_rank))]
    payload = {
        "需求": _req_brief(req),
        "约束": {"rules": cons["rules"], "max_pois_per_day": cons["max_pois"] or 1, "nap_window": cons["nap_window"]},
        "日期": dates,
        "天气": weather.prompt_brief(wx_report),
        "去程": _option_brief(transport["outbound"]) | {"from_hub": transport["outbound"]["from_hub"], "to_hub": transport["outbound"]["to_hub"]},
        "返程": _option_brief(transport["return"]) | {"from_hub": transport["return"]["from_hub"], "to_hub": transport["return"]["to_hub"]},
        "酒店": hotel["hotel"] and {"name": hotel["hotel"]["name"], "area": hotel["hotel"]["area"], "room_type": hotel["room_type"], "rooms": hotel["rooms"]},
        "接送": {"arrival": ground["arrival"]["mode"], "departure": ground["departure"]["mode"]},
        "候选景点": candidates,
        "候选餐厅": [_brief(r, _REST_BRIEF) for r in bundle["restaurants"]],
    }
    system = ITINERARY_PROMPT.replace("{language}", _lang_name(req["language"]))
    try:
        raw = ada_client.complete_json(system, _dumps(payload), max_tokens=ITINERARY_MAX_TOKENS)
        itin = _normalize_itinerary(raw, title)
    except (ada_client.AdaError, ValueError) as e:
        logger.warning("itinerary model output unusable, using rule-based fallback: %s", e)
        itin = _fallback_itinerary(req, bundle, transport, hotel, ground, title, wx_report, hot_rank)
        itin["fallback_reason"] = str(e)
    itin["fixes"] = _enforce(itin, bundle, req)
    itin["weather_fixes"], itin["weather_conflicts"] = _weather_adjust(itin, bundle, wx_report, hot_rank)
    used = {i["ref_id"] for d in itin["days"] for i in d["items"] if i["type"] == "poi"}
    itin["rain_backup"] = [_brief(p, _POI_BRIEF) for p in bundle["pois"] if p["indoor"] and p["id"] not in used][:3]
    return itin


# ================================================================== cost, payment plan, checks (rules)
def _itinerary_pois(itin: dict) -> List[dict]:
    return [i["poi"] for d in itin["days"] for i in d["items"] if i["type"] == "poi" and i.get("poi")]


def compute_cost(req: dict, bundle: dict, transport: dict, hotel: dict, ground: dict, itin: dict) -> dict:
    pois = {p["id"]: p for p in bundle["pois"]}
    rests = {r["id"]: r for r in bundle["restaurants"]}
    poi_ids = [p["id"] for p in _itinerary_pois(itin)]
    meal_ids = [i["ref_id"] for d in itin["days"] for i in d["items"] if i.get("restaurant")]
    per_member = []
    for m in req["members"]:
        per_member.append({
            "member": constraints.member_label(m),
            "group": m["group"],
            "transport": sum(data.transport_fare(transport[k], m["age"], req["domestic"]) for k in ("outbound", "return")),
            "tickets": sum(data.poi_price(pois[p], m["age"]) for p in poi_ids),
            "meals": int(round(sum(rests[r]["price_pp"] * data.meal_factor(m["age"]) for r in meal_ids), -1)),
        })
    transfers = ground["arrival_cny"] + ground["departure_cny"]
    items = [
        {"key": "transport", "label": f"城际交通（往返 × {req['party_size']} 人）", "amount": sum(p["transport"] for p in per_member)},
        {"key": "hotel", "label": f"酒店 {hotel['nights']} 晚 × {hotel['rooms']} 间（{hotel['room_type']}）" if hotel["hotel"] else "酒店（无需住宿）", "amount": hotel["total_cny"]},
        {"key": "transfer", "label": "接送（抵达 + 离开）", "amount": transfers},
        {"key": "tickets", "label": f"景点门票（{len(poi_ids)} 个景点）", "amount": sum(p["tickets"] for p in per_member)},
        {"key": "meals", "label": f"餐饮估算（{len(meal_ids)} 餐）", "amount": sum(p["meals"] for p in per_member)},
    ]
    total = sum(i["amount"] for i in items)
    coupons = [c for c in (recommend.coupon_offer(pois[p], req) for p in poi_ids) if c]
    savings = sum(c["saving_cny"] for c in coupons)

    split = []
    if len(req["groups"]) > 1:
        shared = hotel["total_cny"] + transfers
        for g in req["groups"]:
            mine = [p for p in per_member if p["group"] == g]
            personal = sum(p["transport"] + p["tickets"] + p["meals"] for p in mine)
            share = int(round(shared * len(mine) / len(per_member)))
            split.append({"group": g, "members": len(mine), "personal": personal, "shared": share, "total": personal + share})
        split[-1]["total"] += total - sum(s["total"] for s in split)  # absorb rounding

    home = req["home_currency"]
    net = total - savings
    return {
        "items": items,
        "total_cny": total,
        "coupons": coupons,
        "coupon_savings_cny": savings,
        "total_after_coupons_cny": net,
        "per_member": per_member,
        "split": split,
        "budget_cny": req["budget_cny"],
        "within_budget": None if req["budget_cny"] is None else net <= req["budget_cny"],
        "home_currency": home,
        "total_home": knowledge.from_cny(net, home) if home != "CNY" else None,
        "fx_note": knowledge.FX_NOTE,
    }


def payment_plan(req: dict, bundle: dict, ground: dict, itin: dict, cost: dict, cash: Optional[dict]) -> dict:
    """Split spending into 'prepay on Trip.com' vs 'pay on site'."""
    pois = {p["id"]: p for p in bundle["pois"]}
    coupon_by_poi = {c["poi_id"]: c for c in cost["coupons"] if c["eligible"]}
    prepay = [{"item": "城际交通（往返）", "item_en": "Intercity transport (return)", "amount": cost["items"][0]["amount"]}]
    if cost["items"][1]["amount"]:
        prepay.append({"item": cost["items"][1]["label"], "item_en": "Hotel", "amount": cost["items"][1]["amount"]})
    onsite = []
    for key, label, label_en in (("arrival", "接站/接机", "Arrival transfer"), ("departure", "送站/送机", "Departure transfer")):
        t, amount = ground[key], ground[f"{key}_cny"]
        (prepay if t["prepay"] else onsite).append({"item": f"{label}：{t['mode']}", "item_en": label_en, "amount": amount,
                                                    "method": "扫码支付", "method_key": "qr"})
    for d in itin["days"]:
        for i in d["items"]:
            if i["type"] == "poi" and i.get("poi"):
                p = pois[i["poi"]["id"]]
                amount = sum(data.poi_price(p, m["age"]) for m in req["members"])
                if not amount:
                    continue
                c = coupon_by_poi.get(p["id"])
                if p["prepay"]:
                    prepay.append({"item": f"门票：{p['name']}", "item_en": f"Ticket: {p['name_en']}", "amount": amount - (c["saving_cny"] if c else 0),
                                   "coupon": c and f"{c['label']}（{c['code']}）", "coupon_code": c and c["code"]})
                else:
                    onsite.append({"item": f"门票：{p['name']}", "item_en": f"Ticket: {p['name_en']}", "amount": amount,
                                   "method": "扫码支付", "method_key": "qr"})
            elif i.get("restaurant"):
                r = i["restaurant"]
                amount = int(round(sum(r["price_pp"] * data.meal_factor(m["age"]) for m in req["members"]), -1))
                onsite.append({"item": f"{d['date'][5:]} {r['name']}", "item_en": f"{d['date'][5:]} {r['name']}", "amount": amount,
                               "method": "扫码 / 境外卡" if r["foreign_card"] else "仅扫码或现金",
                               "method_key": "qr_card" if r["foreign_card"] else "qr_cash"})
    return {
        "prepay": prepay,
        "prepay_total": sum(p["amount"] for p in prepay),
        "onsite": onsite,
        "onsite_total": sum(o["amount"] for o in onsite),
        "cash_suggest_cny": cash["total_cny"] if cash else None,
        "home_currency": req["home_currency"],
        "note": "门票、酒店、交通和可预付的接送建议提前在携程用境外银行卡支付（合作景点优惠券在预付时使用）；现场优先使用支付宝或微信支付扫码，并准备少量现金。",
        "note_en": "Prepay tickets, hotel, transport and transfers on Trip.com with your foreign card (partner coupons apply when prepaying); on site, pay with Alipay or WeChat Pay QR codes and keep a little cash.",
    }


def _business_checks(req: dict, transport: dict, hotel: dict, add) -> bool:
    p, tol = data.POLICY, data.POLICY["lowest_fare_tolerance"]
    for key, name in (("outbound", "去程"), ("return", "返程")):
        o = transport[key]
        if o["mode"] == "flight" and o["cabin"] == "公务舱" and o["duration_h"] < p["business_class_min_hours"]:
            add(f"{name}舱位", "fail", f"{o['number']} 飞行 {o['duration_h']} 小时，不足 {p['business_class_min_hours']:g} 小时，不可订公务舱")
        elif o["mode"] == "rail" and o["cabin"] != "二等座":
            add(f"{name}舱位", "warn", f"{o['number']} 为{o['cabin']}，商务出行高铁标准为二等座")
        else:
            add(f"{name}舱位", "pass", f"{o['number']} {o['cabin']}，符合舱位标准")
        lowest = transport["lowest_fare"][key].get(f"{o['mode']}:{o['cabin']}", o["price_cny"])
        if o["price_cny"] > lowest * (1 + tol):
            add(f"{name}最低价", "warn", f"票价 {o['price_cny']} 元，高于同类最低价 {lowest} 元的 {int(tol * 100)}% 容差，需填写超标理由")
        else:
            add(f"{name}最低价", "pass", f"票价 {o['price_cny']} 元，在最低价 {lowest} 元的 {int(tol * 100)}% 容差内")
    days_ahead = (date.fromisoformat(req["depart_date"]) - _today()).days
    need = p["advance_days_domestic"] if req["domestic"] else p["advance_days_international"]
    late = days_ahead < need
    add("提前预订", "warn" if late else "pass",
        f"提前 {days_ahead} 天预订，{'低于' if late else '满足'}{'国内' if req['domestic'] else '国际'}行程 {need} 天要求" + ("，需要审批" if late else ""))
    if hotel["hotel"]:
        h, cap = hotel["hotel"], hotel["cap_cny"]
        if h["nightly_cny"] > cap:
            add("住宿标准", "fail", f"{h['name']} 每晚 {h['nightly_cny']} 元，超出{req['destination']}标准 {cap} 元，需要审批")
        else:
            add("住宿标准", "pass", f"每晚 {h['nightly_cny']} 元，在{req['destination']}标准 {cap} 元以内")
    non_pref = [transport[k]["carrier"] for k in ("outbound", "return") if not transport[k]["preferred"]]
    if hotel["hotel"] and not hotel["hotel"]["preferred"]:
        non_pref.append(hotel["hotel"]["name"])
    add("协议供应商", "warn" if non_pref else "pass",
        ("建议优先使用协议供应商，当前非协议：" + "、".join(dict.fromkeys(non_pref))) if non_pref else "交通与酒店均为协议供应商")
    return late


def _in_window(t: str, window: str) -> bool:
    if len(t) != 5 or ":" not in t:
        return False
    start, end = window.split("-")
    return start <= t < end


def check_agent(req: dict, bundle: dict, transport: dict, hotel: dict, ground: dict, itin: dict) -> dict:
    cons = bundle["constraints"]
    checks: List[dict] = []

    def add(rule: str, status: str, detail: str) -> None:
        checks.append({"rule": rule, "status": status, "detail": detail})

    late = _business_checks(req, transport, hotel, add) if req["is_business"] else False

    for key, name in (("outbound", "去程"), ("return", "返程")):
        o = transport[key]
        if _hour(o["arrive"]) < 6:
            add(f"{name}时间", "warn", f"{o['number']} {o['arrive'][11:]} 抵达，属于红眼班次（没有其他可选班次）")
        elif cons["avoid_early_late"] and (_hour(o["depart"]) < 7 or _hour(o["arrive"]) >= 22):
            add(f"{name}时间", "warn", f"{o['number']} {o['depart'][11:]} 出发、{o['arrive'][11:]} 抵达，对老人或儿童偏早或偏晚")
        else:
            add(f"{name}时间", "pass", f"{o['number']} {o['depart'][11:]} 出发、{o['arrive'][11:]} 抵达")

    days = itin["days"]
    if not req["is_business"]:
        if itin["fixes"]:
            add("景点与餐厅约束", "warn", f"模型安排中有 {len(itin['fixes'])} 处不符合约束，已自动移除：" + "；".join(itin["fixes"][:3]))
        else:
            excluded = "、".join(e["name"] for e in bundle["pois_excluded"]) or "无"
            add("景点与餐厅约束", "pass", f"所有安排均来自约束过滤后的候选；已排除的景点：{excluded}")
        add("每日景点数", "pass", f"每天不超过 {cons['max_pois']} 个，抵达日和离开日不超过 1 个")
        if cons["max_walk_km"]:
            over = [d for d in days if d["walk_km"] > cons["max_walk_km"]]
            add("每日步行", "warn" if over else "pass",
                ("；".join(f"{d['date']} 景点步行约 {d['walk_km']:g} 公里" for d in over) + f"，超过 {cons['max_walk_km']:g} 公里，建议景点间乘车")
                if over else f"每天景点步行均不超过 {cons['max_walk_km']:g} 公里")
        if cons["nap_window"]:
            clash = [f"{d['date']} {i['time']} {i['title']}" for d in days for i in d["items"] if i["type"] == "poi" and _in_window(i["time"], cons["nap_window"])]
            add("午休时段", "warn" if clash else "pass", ("以下景点与午休时段重叠：" + "；".join(clash)) if clash else f"{cons['nap_window']} 未安排景点")

    pois_planned = _itinerary_pois(itin)
    if pois_planned:
        wf, wc = itin.get("weather_fixes") or [], itin.get("weather_conflicts") or []
        if wc:
            add("天气适配", "warn", f"{len(wc)} 个户外景点落在不适合户外的时段：" + "；".join(wc[:2]))
        else:
            add("天气适配", "pass", f"户外景点都安排在适合户外的时段" + (f"；已按天气调整 {len(wf)} 处" if wf else ""))

    if cons["allergens"] or cons["diets"]:
        used = [i["restaurant"] for d in days for i in d["items"] if i.get("restaurant")]
        rests = {r["id"]: r for r in bundle["restaurants"]}
        bad = [r["name"] for r in used if set(rests[r["id"]]["allergens"]) & set(cons["allergens"])]
        want = "、".join(cons["allergens"] + [constraints.DIET_NAMES[x] for x in cons["diets"]])
        add("过敏与饮食", "fail" if bad else "pass",
            ("以下餐厅含过敏原：" + "、".join(bad)) if bad else f"推荐的 {len(used)} 餐均符合要求（{want}）；已排除 {len(bundle['restaurants_excluded'])} 家餐厅")
    if cons["unknown_allergies"]:
        add("过敏信息确认", "warn", "无法自动识别：" + "、".join(cons["unknown_allergies"]) + "，请人工确认餐厅食材")

    h = hotel["hotel"]
    if h:
        need = []
        if cons["family_room"]:
            need.append(("家庭房", hotel["room_type"] == "家庭房"))
        if cons["wheelchair"]:
            need.append(("无障碍设施", h["accessible"]))
        if cons["english_service"]:
            need.append(("英文服务", h["english_service"]))
        if need:
            missing = [n for n, ok in need if not ok]
            add("酒店设施", "warn" if missing else "pass",
                ("没有找到满足全部要求的酒店，缺少：" + "、".join(missing)) if missing else f"{h['name']} 满足：" + "、".join(n for n, _ in need))
    if cons["child_seat"]:
        ok = ground["arrival"]["child_seat"] and ground["departure"]["child_seat"]
        add("儿童座椅", "pass" if ok else "warn", "接送车辆可预约儿童座椅" if ok else "所选接送方式不提供儿童座椅")

    cost = compute_cost(req, bundle, transport, hotel, ground, itin)
    if cost["budget_cny"] is not None:
        net = cost["total_after_coupons_cny"]
        add("预算", "pass" if cost["within_budget"] else "warn",
            f"预计总费用 {net} 元（已扣优惠券），{'在' if cost['within_budget'] else '超出'}预算 {cost['budget_cny']} 元{'以内' if cost['within_budget'] else ''}")

    cash = tips.cash_advice(req, bundle, ground, itin)
    needs_approval = req["is_business"] and (late or any(c["status"] == "fail" for c in checks))
    return {
        "checks": checks,
        "needs_approval": needs_approval,
        "cost": cost,
        "cash": cash,
        "network": tips.network_timeline(req, transport, hotel, itin),
        "payment_plan": payment_plan(req, bundle, ground, itin, cost, cash) if req["is_inbound"] else None,
    }


# ================================================================== on-demand: Q&A
ASK_PROMPT = """ROLE: ask
你是面向外国游客的入境游助手，回答签证、支付、网络、证件、交通和紧急求助相关的问题。
- 只根据「知识库」回答，并在 source_ids 中引用所用条目的 id；知识库没有相关信息时，in_scope=false。
- 不要编造费率、限额、免签天数等具体数字。
- 绝不索要银行卡号、CVV、密码或验证码。
- 使用{language}回答，分步骤时用编号列表，不超过 200 字。
只输出 JSON：{"answer": "...", "source_ids": ["PAY-5"], "in_scope": true}"""


def ask_agent(question: str, language: str = "en") -> dict:
    question = (question or "").strip()
    language = language if language in LANG_NAMES else "en"
    if not question:
        raise PlanningError("问题不能为空")
    if guardrails.find_sensitive(question):
        return {"blocked": True, "in_scope": False, "answer": guardrails.BLOCK_MESSAGE, "sources": []}
    system = ASK_PROMPT.replace("{language}", _lang_name(language))
    raw = ada_client.complete_json(system, "知识库：\n" + knowledge.kb_for_prompt() + "\n\n游客问题：\n" + question, max_tokens=800)
    sources = knowledge.valid_sources(raw.get("source_ids"))
    in_scope = bool(raw.get("in_scope")) and bool(sources) and bool(raw.get("answer"))
    answer = guardrails.redact_text(str(raw["answer"])) if in_scope else knowledge.OUT_OF_SCOPE[language]
    return {"blocked": False, "in_scope": in_scope, "answer": answer, "sources": sources if in_scope else [], "kb_updated": knowledge.KB_UPDATED}


# ================================================================== on-demand: share content
SHARE_PROMPT = """ROLE: share
你是旅行分享文案 Agent，根据行程亮点为游客生成社交媒体分享内容，使用{language}。
内容：一段 80–150 字（英文约 60–120 词）的游记、一句照片配文、5–8 个话题标签。
不要包含：酒店名称、航班或车次号、具体时间、同行人的姓名、年龄和健康信息、证件号码或联系方式。
只输出 JSON：{"title": "...", "post": "...", "caption": "...", "hashtags": ["#..."]}"""


def share_agent(plan: dict, language: str) -> dict:
    language = language if language in LANG_NAMES else plan["request"]["language"]
    req, itin = plan["request"], plan["itinerary"]
    key = "name" if language == "zh" else "name_en"
    highlights = [i["poi"][key] for d in itin["days"] for i in d["items"] if i.get("poi")]
    payload = {
        "destination": req["destination"] if language == "zh" else data.CITIES[req["destination"]]["en"],
        "days": len(itin["days"]),
        "trip_type": req["trip_type"],
        "with_family": req["is_family"],
        "highlights": highlights,
    }
    raw = ada_client.complete_json(SHARE_PROMPT.replace("{language}", _lang_name(language)), _dumps(payload), max_tokens=800)
    tags = [("#" + str(t).lstrip("#")).replace(" ", "") for t in (raw.get("hashtags") or []) if str(t).strip("# ")][:8]
    return guardrails.redact({"title": str(raw.get("title") or ""), "post": str(raw.get("post") or ""),
                              "caption": str(raw.get("caption") or ""), "hashtags": tags, "language": language}, aggressive=True)


# ================================================================== on-demand: receipt recognition
RECEIPT_PROMPT = """ROLE: receipt
识别图片中的购物小票或发票：提取商户名称、日期、明细和总金额，并把商户名和明细翻译成{language}。
- 不是小票或无法识别时 is_receipt=false。
- 金额用数字；币种默认 CNY。
- 不要输出银行卡号、交易参考号等支付信息。
- category 取：餐饮、交通、购物、门票、住宿、其他。
只输出 JSON：{"is_receipt": true, "merchant": "原文", "merchant_translated": "...", "date": "YYYY-MM-DD 或 null", "currency": "CNY", "items": [{"name": "原文", "name_translated": "...", "amount": 12.5}], "total": 88.0, "category": "餐饮"}"""
RECEIPT_CATEGORIES = {"餐饮", "交通", "购物", "门票", "住宿", "其他"}


def receipt_agent(image_b64: str, media_type: str, language: str = "en", home_currency: str = "USD") -> dict:
    if media_type not in RECEIPT_MEDIA:
        raise PlanningError("仅支持 JPG、PNG、WebP、GIF 图片")
    try:
        raw_bytes = base64.b64decode(image_b64 or "", validate=True)
    except (binascii.Error, ValueError):
        raise PlanningError("图片数据不是合法的 base64")
    if not raw_bytes:
        raise PlanningError("图片为空")
    if len(raw_bytes) > MAX_RECEIPT_BYTES:
        raise PlanningError("图片不能超过 5 MB")
    language = language if language in LANG_NAMES else "en"
    home_currency = home_currency if home_currency in knowledge.FX_DEMO else "USD"
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
        {"type": "text", "text": "请识别这张小票。"},
    ]
    raw = ada_client.complete_json(RECEIPT_PROMPT.replace("{language}", _lang_name(language)), content, max_tokens=1500)
    if not raw.get("is_receipt"):
        return {"is_receipt": False, "message": "没有识别到小票，请换一张更清晰的照片。"}
    items = []
    for i in raw.get("items") or []:
        if isinstance(i, dict) and _num(i.get("amount"), 0, 1e7) is not None:
            items.append({"name": str(i.get("name") or ""), "name_translated": str(i.get("name_translated") or ""),
                          "amount": _num(i.get("amount"), 0, 1e7)})
    total = _num(raw.get("total"), 0, 1e7)
    if total is None:
        total = round(sum(i["amount"] for i in items), 2)
    currency = str(raw.get("currency") or "CNY").upper()
    currency = currency if currency in knowledge.FX_DEMO else "CNY"
    cny = round(knowledge.to_cny(total, currency), 2)
    return guardrails.redact({
        "is_receipt": True,
        "merchant": str(raw.get("merchant") or ""),
        "merchant_translated": str(raw.get("merchant_translated") or ""),
        "date": str(_parse_date(raw.get("date")) or ""),
        "category": raw.get("category") if raw.get("category") in RECEIPT_CATEGORIES else "其他",
        "items": items,
        "total": total,
        "currency": currency,
        "total_cny": cny,
        "home_currency": home_currency,
        "total_home": knowledge.from_cny(cny, home_currency),
        "fx_note": knowledge.FX_NOTE,
    })
