"""Constraint agent (rules): turn traveller profiles into hard planning constraints.

Hard constraints (allergies, stroller access, walking limits, minimum age,
diet) are applied by filtering candidates BEFORE the LLM sees them and are
re-checked afterwards, so a model slip can never put a peanut restaurant or a
long-walk attraction into a family plan.
"""
from __future__ import annotations

import math
from typing import Dict, List, Tuple

import data

DEFAULT_WALK_KM = {"wheelchair": 2.0, "limited": 3.0}
STROLLER_WALK_KM = 5.0
SENIOR_AGE = 65
NAP_WINDOW = "12:30-14:30"
DIET_NAMES = {"halal": "清真", "vegetarian": "素食"}


def member_label(m: dict) -> str:
    return f"{m['role']}（{m['age']} 岁）" if m["age"] is not None else m["role"]


def derive(req: dict) -> dict:
    members = req["members"]
    business = req["is_business"]
    ages = [m["age"] for m in members if m["age"] is not None]
    youngest = min(ages) if ages else None
    stroller = [m for m in members if m["age"] is not None and m["age"] < 3]
    nappers = [m for m in members if m["age"] is not None and m["age"] < 6]
    seniors = [m for m in members if (m["age"] is not None and m["age"] >= SENIOR_AGE) or m["mobility"] != "normal"]
    wheelchair = any(m["mobility"] == "wheelchair" for m in members)
    rules: List[str] = ["不安排 00:00–06:00 抵达的红眼班次"]

    max_walk = None
    if not business:
        limits = [(m["max_walk_km"] or DEFAULT_WALK_KM.get(m["mobility"]), m) for m in members]
        limits = [(v, m) for v, m in limits if v]
        if stroller:
            limits.append((STROLLER_WALK_KM, stroller[0]))
        if limits:
            max_walk, who = min(limits, key=lambda x: x[0])
            rules.append(f"{member_label(who)}每天步行不超过 {max_walk:g} 公里：排除步行量大的景点，并控制每天步行总量")
    if stroller:
        rules.append(f"{member_label(stroller[0])}需要婴儿车：只安排婴儿车可通行的景点")
    nap = None
    if nappers and not business:
        nap = NAP_WINDOW
        rules.append(f"{member_label(nappers[0])}需要午休：每天 {NAP_WINDOW.replace('-', '–')} 留出回酒店或安静休息的时间")
    avoid_early_late = bool(seniors or nappers) and not business
    if avoid_early_late:
        who = (seniors or nappers)[0]
        rules.append(f"{member_label(who)}同行：不安排早于 07:00 出发或晚于 22:00 抵达的班次")
    if seniors and not business:
        rules.append(f"{member_label(seniors[0])}同行：排除不适合老人或行动不便者的景点")
    if wheelchair:
        rules.append("有轮椅出行人：酒店须有无障碍设施")

    max_pois = None
    if not business:
        max_pois = 2 if (stroller or wheelchair) else (3 if req["is_family"] else 4)
        if req["pace"] == "relaxed":
            max_pois = max(1, max_pois - 1)
        elif req["pace"] == "packed" and not (stroller or wheelchair):
            max_pois += 1
        rules.append(f"每天最多安排 {max_pois} 个景点，抵达日和离开日最多 1 个")

    allergens, unknown = data.normalize_allergies(a for m in members for a in m["allergies"])
    if allergens:
        rules.append("过敏原：" + "、".join(allergens) + "（排除含这些食材的餐厅，并生成双语过敏提示卡）")
    if unknown:
        rules.append("以下过敏信息无法自动识别，需人工确认：" + "、".join(unknown))
    diets = sorted({m["diet"] for m in members} - {"none"})
    if diets:
        rules.append("饮食要求：" + "、".join(DIET_NAMES[d] for d in diets) + "（只推荐符合要求的餐厅）")

    party = len(members)
    occupants = sum(1 for m in members if m["age"] is None or m["age"] >= 6)
    kids = any(a < 12 for a in ages)
    family_room = req["is_family"] and kids and party <= 4
    rooms_standard = max(1, math.ceil(occupants / 2))
    if family_room:
        rules.append(f"{party} 人含儿童：优先 1 间家庭房")
    elif party > 1:
        rules.append(f"需要标准间 {rooms_standard} 间（6 岁以下儿童与大人同住）")
    child_seat = any(a < 6 for a in ages)
    if child_seat and not business:
        rules.append("有 6 岁以下儿童：接送优先预约带儿童座椅的车辆")
    if req["is_inbound"]:
        rules.append("入境游客：酒店须提供英文服务，优先有英文菜单、可刷境外卡的餐厅")

    return {
        "rules": rules,
        "party_size": party,
        "youngest_age": youngest,
        "stroller": bool(stroller),
        "nap_window": nap,
        "senior_or_limited": bool(seniors),
        "wheelchair": wheelchair,
        "avoid_early_late": avoid_early_late,
        "max_walk_km": max_walk,
        "max_pois": max_pois,
        "allergens": allergens,
        "unknown_allergies": unknown,
        "diets": diets,
        "family_room": family_room,
        "rooms_standard": rooms_standard,
        "child_seat": child_seat and not business,
        "kids": kids,
        "english_service": req["is_inbound"],
    }


def filter_pois(pois: List[dict], cons: dict) -> Tuple[List[dict], List[dict]]:
    allowed, excluded = [], []
    for p in pois:
        reasons = []
        if cons["youngest_age"] is not None and p["min_age"] > cons["youngest_age"]:
            reasons.append(f"适龄 {p['min_age']} 岁以上，同行最小 {cons['youngest_age']} 岁")
        if (cons["stroller"] or cons["wheelchair"]) and not p["stroller_ok"]:
            reasons.append("婴儿车/轮椅不便通行")
        if cons["senior_or_limited"] and not p["senior_ok"]:
            reasons.append("不适合老人或行动不便者")
        if cons["max_walk_km"] and p["walk_km"] > cons["max_walk_km"]:
            reasons.append(f"步行约 {p['walk_km']:g} 公里，超过每天 {cons['max_walk_km']:g} 公里上限")
        (excluded if reasons else allowed).append({**p, "excluded_reason": "；".join(reasons)} if reasons else p)
    return allowed, [{"id": p["id"], "name": p["name"], "reason": p["excluded_reason"]} for p in excluded]


def filter_restaurants(restaurants: List[dict], cons: dict) -> Tuple[List[dict], List[dict]]:
    allowed, excluded = [], []
    for r in restaurants:
        reasons = []
        bad = set(r["allergens"]) & set(cons["allergens"])
        if bad:
            reasons.append("含过敏原：" + "、".join(a for a in cons["allergens"] if a in bad))
        if "halal" in cons["diets"] and not r["halal"]:
            reasons.append("非清真")
        if "vegetarian" in cons["diets"] and not r["vegetarian"]:
            reasons.append("非素食")
        if reasons:
            excluded.append({"id": r["id"], "name": r["name"], "reason": "；".join(reasons)})
        else:
            allowed.append(r)
    return allowed, excluded


def diet_cards(cons: dict) -> List[Dict[str, str]]:
    """Bilingual cards to show restaurant staff (deterministic text, not model output)."""
    cards = []
    if cons["allergens"]:
        zh = "、".join(cons["allergens"])
        en = ", ".join(data.ALLERGENS[a][0] for a in cons["allergens"])
        cards.append({
            "title": "过敏提示卡 Allergy card",
            "zh": f"我们中有人对以下食物过敏：{zh}。请不要在菜品、酱料和烹饪用油中使用这些食材，谢谢！",
            "en": f"Someone in our party is allergic to: {en}. Please do not use these ingredients in any dish, sauce or cooking oil. Thank you!",
        })
    if "halal" in cons["diets"]:
        cards.append({"title": "清真饮食 Halal", "zh": "我们只吃清真食品，请推荐清真菜品，谢谢！", "en": "We only eat halal food. Please recommend halal dishes. Thank you!"})
    if "vegetarian" in cons["diets"]:
        cards.append({"title": "素食 Vegetarian", "zh": "我们吃素，请不要放肉、海鲜、鸡精和动物油，谢谢！", "en": "We are vegetarian: no meat, seafood, chicken stock or animal fat, please. Thank you!"})
    return cards
