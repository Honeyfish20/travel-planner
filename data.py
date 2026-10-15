"""Mock travel inventory and pricing rules (demo data only).

Inventory is generated deterministically from (route, date) so the same query
always returns the same options. In production, replace the search_* functions
with Trip.Biz search APIs or MCP tools. Times are not converted between time
zones, and child/senior prices follow simplified demo rules.
"""
from __future__ import annotations

import hashlib
import math
import random
import re
from datetime import date, datetime, time, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

CITIES: Dict[str, dict] = {
    "上海": {"en": "Shanghai", "code": "SHA", "airport": "上海浦东国际机场 (PVG)", "station": "上海虹桥站", "country": "CN", "lat": 31.23, "lon": 121.47, "hotel_cap": 900, "fx": 1.0},
    "北京": {"en": "Beijing", "code": "BJS", "airport": "北京首都国际机场 (PEK)", "station": "北京南站", "country": "CN", "lat": 39.90, "lon": 116.40, "hotel_cap": 1000, "fx": 1.0},
    "深圳": {"en": "Shenzhen", "code": "SZX", "airport": "深圳宝安国际机场 (SZX)", "station": "深圳北站", "country": "CN", "lat": 22.54, "lon": 114.06, "hotel_cap": 800, "fx": 1.0},
    "成都": {"en": "Chengdu", "code": "CTU", "airport": "成都天府国际机场 (TFU)", "station": "成都东站", "country": "CN", "lat": 30.57, "lon": 104.07, "hotel_cap": 700, "fx": 1.0},
    "杭州": {"en": "Hangzhou", "code": "HGH", "airport": "杭州萧山国际机场 (HGH)", "station": "杭州东站", "country": "CN", "lat": 30.27, "lon": 120.16, "hotel_cap": 700, "fx": 1.0},
    "西安": {"en": "Xi'an", "code": "XIY", "airport": "西安咸阳国际机场 (XIY)", "station": "西安北站", "country": "CN", "lat": 34.34, "lon": 108.94, "hotel_cap": 650, "fx": 1.0},
    "香港": {"en": "Hong Kong", "code": "HKG", "airport": "香港国际机场 (HKG)", "station": None, "country": "HK", "lat": 22.32, "lon": 114.17, "hotel_cap": 1500, "fx": 1.8},
    "新加坡": {"en": "Singapore", "code": "SIN", "airport": "新加坡樟宜机场 (SIN)", "station": None, "country": "SG", "lat": 1.35, "lon": 103.82, "hotel_cap": 1600, "fx": 2.0},
    "东京": {"en": "Tokyo", "code": "TYO", "airport": "东京羽田机场 (HND)", "station": None, "country": "JP", "lat": 35.68, "lon": 139.69, "hotel_cap": 1500, "fx": 2.2},
    "首尔": {"en": "Seoul", "code": "SEL", "airport": "首尔仁川国际机场 (ICN)", "station": None, "country": "KR", "lat": 37.57, "lon": 126.98, "hotel_cap": 1300, "fx": 1.9},
    "伦敦": {"en": "London", "code": "LON", "airport": "伦敦希思罗机场 (LHR)", "station": None, "country": "GB", "lat": 51.51, "lon": -0.13, "hotel_cap": 2000, "fx": 3.0},
    "纽约": {"en": "New York", "code": "NYC", "airport": "纽约肯尼迪国际机场 (JFK)", "station": None, "country": "US", "lat": 40.71, "lon": -74.01, "hotel_cap": 2200, "fx": 3.2},
}

POLICY = {
    "business_class_min_hours": 6.0,   # 飞行时长 ≥ 6 小时才可订公务舱
    "lowest_fare_tolerance": 0.20,     # 票价不高于同舱位当日最低价的 120%
    "advance_days_domestic": 3,        # 国内行程至少提前 3 天预订
    "advance_days_international": 7,   # 国际行程至少提前 7 天预订
    "preferred_airlines": {"MU", "CA", "SQ", "CX"},
}

MIN_FLIGHT_KM = 450   # 更短的航线没有航班，只能坐高铁
MAX_RAIL_KM = 1500    # 更长的国内线路不提供高铁

_ALIASES: Dict[str, str] = {}
for _cn, _c in CITIES.items():
    for _k in (_cn, _c["en"], _c["code"]):
        _ALIASES[_k.lower().replace(" ", "")] = _cn
_ALIASES.update({"hk": "香港", "sg": "新加坡", "pvg": "上海", "pek": "北京", "hnd": "东京", "lhr": "伦敦",
                 "icn": "首尔", "jfk": "纽约", "xian": "西安", "nyc": "纽约"})
# 繁体 / 日文 / 韩文写法
_ALIASES.update({
    "東京": "东京", "とうきょう": "东京", "トウキョウ": "东京", "도쿄": "东京",
    "ペキン": "北京", "베이징": "北京",
    "シャンハイ": "上海", "상하이": "上海",
    "杭州市": "杭州", "ハンジョウ": "杭州", "항저우": "杭州",
    "シーアン": "西安", "시안": "西安",
    "チェンドゥ": "成都", "청두": "成都",
    "シンセン": "深圳", "선전": "深圳",
    "ホンコン": "香港", "홍콩": "香港",
    "シンガポール": "新加坡", "싱가포르": "新加坡",
    "首爾": "首尔", "ソウル": "首尔", "서울": "首尔",
    "倫敦": "伦敦", "ロンドン": "伦敦", "런던": "伦敦",
    "紐約": "纽约", "ニューヨーク": "纽约", "뉴욕": "纽约",
})


def normalize_city(name) -> Optional[str]:
    """Map '上海市' / 'Shanghai' / 'SHA' etc. to the canonical Chinese name."""
    if not name:
        return None
    key = str(name).strip().lower().replace(" ", "")
    for suffix in ("特别行政区", "市"):
        if key.endswith(suffix):
            key = key[: -len(suffix)]
    return _ALIASES.get(key)


def is_mainland(city: str) -> bool:
    return CITIES[city]["country"] == "CN"


def is_domestic(a: str, b: str) -> bool:
    return is_mainland(a) and is_mainland(b)


def distance_km(a: str, b: str) -> float:
    ca, cb = CITIES[a], CITIES[b]
    lat1, lon1, lat2, lon2 = map(math.radians, (ca["lat"], ca["lon"], cb["lat"], cb["lon"]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def _rng(*parts: str) -> random.Random:
    seed = int(hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12], 16)
    return random.Random(seed)


# ------------------------------------------------------------------ intercity transport
_AIRLINES_DOMESTIC = (("中国东方航空", "MU"), ("中国国际航空", "CA"), ("中国南方航空", "CZ"), ("海南航空", "HU"), ("春秋航空", "9C"))
_AIRLINES_INTL = (("中国东方航空", "MU"), ("中国国际航空", "CA"), ("新加坡航空", "SQ"), ("国泰航空", "CX"), ("全日空", "NH"), ("英国航空", "BA"))


def search_flights(origin: str, dest: str, day: date) -> List[dict]:
    """Economy + business fares for six departures; empty for routes under MIN_FLIGHT_KM."""
    dist = distance_km(origin, dest)
    if dist < MIN_FLIGHT_KM:
        return []
    rng = _rng("flight", origin, dest, day.isoformat())
    domestic = is_domestic(origin, dest)
    airlines = _AIRLINES_DOMESTIC if domestic else _AIRLINES_INTL
    base = 0.75 * dist + 350 if domestic else 0.9 * dist + 900
    results = []
    for i, hour in enumerate((7, 9, 11, 14, 17, 20)):
        name, code = rng.choice(airlines)
        number = f"{code}{5000 + i * 37 + rng.randint(0, 30)}"
        dep = datetime.combine(day, time(hour, rng.choice((0, 15, 30, 45))))
        stops = 1 if (not domestic and dist > 7000 and rng.random() < 0.4) else 0
        duration = round(dist / 780 + 0.6 + stops * 2.5, 1)
        arr = dep + timedelta(hours=duration)
        factor = rng.uniform(0.8, 1.35)
        for cabin, cabin_code, mult in (("经济舱", "Y", 1.0), ("公务舱", "C", 3.2)):
            results.append({
                "id": f"{number}-{cabin_code}-{day:%m%d}",
                "mode": "flight",
                "number": number,
                "carrier": name,
                "carrier_code": code,
                "cabin": cabin,
                "depart": dep.strftime("%Y-%m-%d %H:%M"),
                "arrive": arr.strftime("%Y-%m-%d %H:%M"),
                "duration_h": duration,
                "stops": stops,
                "from_hub": CITIES[origin]["airport"],
                "to_hub": CITIES[dest]["airport"],
                "price_cny": int(round(base * mult * factor, -1)),
                "preferred": code in POLICY["preferred_airlines"],
            })
    return results


def search_rail(origin: str, dest: str, day: date) -> List[dict]:
    """High-speed rail (二等座 / 一等座) for mainland routes up to MAX_RAIL_KM."""
    if not is_domestic(origin, dest):
        return []
    dist = distance_km(origin, dest)
    if dist > MAX_RAIL_KM:
        return []
    rng = _rng("rail", origin, dest, day.isoformat())
    hours = round(dist / 280 + 0.3, 1)
    trains = []
    for i, hour in enumerate((7, 9, 11, 14, 17, 19)):
        number = f"G{rng.randint(1, 99) * 10 + i}"
        dep = datetime.combine(day, time(hour, rng.choice((0, 10, 30, 40))))
        for cabin, code, rate in (("二等座", "2", 0.48), ("一等座", "1", 0.78)):
            trains.append({
                "id": f"{number}-{code}-{day:%m%d}",
                "mode": "rail",
                "number": number,
                "carrier": "中国铁路",
                "carrier_code": "CR",
                "cabin": cabin,
                "depart": dep.strftime("%Y-%m-%d %H:%M"),
                "arrive": (dep + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M"),
                "duration_h": hours,
                "stops": 0,
                "from_hub": CITIES[origin]["station"],
                "to_hub": CITIES[dest]["station"],
                "price_cny": int(round(max(dist, 120) * rate, -1)),
                "preferred": True,
            })
    return trains


# ------------------------------------------------------------------ hotels & transfers
_HOTEL_BRANDS = (
    # 品牌, 星级, 价格系数, 协议酒店, 家庭房, 儿童设施
    ("全季酒店", 3, 0.45, True, False, False),
    ("亚朵酒店", 4, 0.70, True, True, False),
    ("希尔顿酒店", 5, 0.95, True, True, True),
    ("万豪酒店", 5, 1.15, False, True, False),
    ("洲际酒店", 5, 1.40, False, True, True),
)
_AREAS = (("市中心", 0.5, 1.5), ("中央商务区", 1.5, 4.0), ("景区附近", 2.0, 6.0), ("会展中心", 5.0, 12.0), ("机场/车站附近", 15.0, 30.0))


def search_hotels(city: str) -> List[dict]:
    rng = _rng("hotel", city)
    cap = CITIES[city]["hotel_cap"]
    hotels = []
    for k, (brand, stars, factor, preferred, family_room, kids) in enumerate(_HOTEL_BRANDS):
        area, lo, hi = _AREAS[k % len(_AREAS)]
        nightly = int(round(cap * factor * rng.uniform(0.92, 1.08), -1))
        hotels.append({
            "id": f"H-{CITIES[city]['code']}-{k + 1}",
            "name": f"{city}{area}{brand}",
            "brand": brand,
            "stars": stars,
            "area": area,
            "nightly_cny": nightly,                      # 标准间（2 人）
            "family_room": family_room,                  # 家庭房（最多 4 人）
            "family_room_cny": int(round(nightly * 1.4, -1)) if family_room else None,
            "accessible": stars >= 4 or rng.random() < 0.5,
            "kids_facilities": kids,
            "english_service": stars >= 4,
            "distance_to_center_km": round(rng.uniform(lo, hi), 1),
            "preferred": preferred,
            "breakfast": rng.random() < 0.6,
        })
    return hotels


def search_transfers(city: str) -> List[dict]:
    fx, code = CITIES[city]["fx"], CITIES[city]["code"]
    return [
        {"id": f"T-{code}-METRO", "mode": "地铁/机场快线", "duration_min": 55, "price_cny": int(round(35 * fx)), "per_person": True, "capacity": None, "preferred": False, "child_seat": False, "prepay": False},
        {"id": f"T-{code}-TAXI", "mode": "出租车", "duration_min": 40, "price_cny": int(round(180 * fx, -1)), "per_person": False, "capacity": 4, "preferred": False, "child_seat": False, "prepay": False},
        {"id": f"T-{code}-CAR", "mode": "企业协议专车", "duration_min": 40, "price_cny": int(round(260 * fx, -1)), "per_person": False, "capacity": 4, "preferred": True, "child_seat": False, "prepay": True},
        {"id": f"T-{code}-VAN", "mode": "7座商务车（可预约儿童座椅）", "duration_min": 45, "price_cny": int(round(320 * fx, -1)), "per_person": False, "capacity": 6, "preferred": False, "child_seat": True, "prepay": True},
    ]


# ------------------------------------------------------------------ attractions
# (名称, 英文名, 类别, 室内, 步行公里, 可推婴儿车, 适合老人, 最低年龄, 亲子指数0-3, 时长h, 成人价, 儿童价, 长者价, 最佳时段, 可预付)
_POIS: Dict[str, Tuple[tuple, ...]] = {
    "上海": (
        ("上海迪士尼乐园", "Shanghai Disneyland", "主题乐园", False, 8.0, True, False, 0, 3, 8, 599, 450, 450, "全天", True),
        ("外滩", "The Bund", "城市漫步", False, 2.0, True, True, 0, 1, 1.5, 0, 0, 0, "晚上", False),
        ("上海自然博物馆", "Shanghai Natural History Museum", "博物馆", True, 1.5, True, True, 0, 3, 3, 30, 15, 0, "上午", True),
        ("上海科技馆", "Shanghai Science and Technology Museum", "博物馆", True, 2.0, True, True, 0, 3, 3, 45, 20, 0, "上午", True),
        ("豫园", "Yu Garden", "古典园林", False, 1.5, False, True, 0, 1, 2, 40, 20, 20, "上午", True),
        ("东方明珠", "Oriental Pearl Tower", "观光", True, 1.0, True, True, 0, 2, 2, 199, 100, 100, "下午", True),
    ),
    "北京": (
        ("故宫博物院", "The Palace Museum", "历史古迹", False, 4.0, True, True, 0, 1, 4, 60, 30, 30, "上午", True),
        ("八达岭长城", "Badaling Great Wall", "历史古迹", False, 3.0, False, False, 6, 1, 4, 40, 20, 20, "上午", True),
        ("颐和园", "Summer Palace", "皇家园林", False, 3.0, True, True, 0, 1, 3, 30, 15, 15, "上午", True),
        ("中国科学技术馆", "China Science and Technology Museum", "博物馆", True, 2.0, True, True, 0, 3, 3, 30, 15, 0, "上午", True),
        ("天坛公园", "Temple of Heaven", "历史古迹", False, 2.0, True, True, 0, 1, 2, 15, 8, 0, "下午", True),
        ("北京环球度假区", "Universal Beijing Resort", "主题乐园", False, 8.0, True, False, 0, 3, 8, 638, 478, 478, "全天", True),
    ),
    "杭州": (
        ("西湖（游船+环湖）", "West Lake (boat tour)", "自然风光", False, 2.0, True, True, 0, 2, 3, 55, 28, 28, "上午", True),
        ("灵隐寺", "Lingyin Temple", "寺庙", False, 2.0, False, True, 0, 1, 2, 75, 40, 40, "上午", True),
        ("杭州动物园", "Hangzhou Zoo", "动物园", False, 2.5, True, True, 0, 3, 2.5, 20, 10, 0, "上午", True),
        ("浙江自然博物院", "Zhejiang Museum of Natural History", "博物馆", True, 1.5, True, True, 0, 3, 2.5, 0, 0, 0, "下午", False),
        ("宋城", "Songcheng Park", "主题演出", False, 2.5, True, True, 0, 2, 4, 310, 200, 200, "下午", True),
        ("西溪国家湿地公园", "Xixi National Wetland Park", "自然风光", False, 2.0, True, True, 0, 2, 3, 80, 40, 40, "下午", True),
    ),
    "西安": (
        ("秦始皇帝陵博物院（兵马俑）", "Terracotta Warriors Museum", "历史古迹", True, 2.5, True, True, 0, 1, 3, 120, 60, 60, "上午", True),
        ("西安城墙", "Xi'an City Wall", "历史古迹", False, 4.0, False, True, 0, 1, 2, 54, 27, 27, "下午", True),
        ("陕西历史博物馆", "Shaanxi History Museum", "博物馆", True, 2.0, True, True, 0, 2, 3, 0, 0, 0, "上午", False),
        ("大唐不夜城", "Datang Everbright City", "城市漫步", False, 2.0, True, True, 0, 2, 2, 0, 0, 0, "晚上", False),
        ("大雁塔", "Giant Wild Goose Pagoda", "寺庙", False, 1.0, False, True, 0, 1, 1.5, 40, 20, 20, "下午", True),
    ),
    "成都": (
        ("成都大熊猫繁育研究基地", "Chengdu Research Base of Giant Panda Breeding", "动物园", False, 3.0, True, True, 0, 3, 3, 55, 28, 28, "上午", True),
        ("宽窄巷子", "Kuanzhai Alley", "城市漫步", False, 1.5, True, True, 0, 1, 2, 0, 0, 0, "下午", False),
        ("成都博物馆", "Chengdu Museum", "博物馆", True, 1.5, True, True, 0, 2, 2.5, 0, 0, 0, "下午", False),
        ("都江堰", "Dujiangyan Irrigation System", "历史古迹", False, 3.5, False, True, 0, 1, 3, 80, 40, 40, "上午", True),
        ("锦里古街", "Jinli Ancient Street", "城市漫步", False, 1.0, True, True, 0, 1, 1.5, 0, 0, 0, "晚上", False),
    ),
    "香港": (
        ("香港迪士尼乐园", "Hong Kong Disneyland", "主题乐园", False, 7.0, True, False, 0, 3, 8, 680, 500, 100, "全天", True),
        ("香港海洋公园", "Ocean Park Hong Kong", "主题乐园", False, 6.0, True, True, 0, 3, 6, 450, 230, 0, "全天", True),
        ("太平山顶", "Victoria Peak", "观光", False, 1.5, True, True, 0, 2, 2, 100, 50, 50, "晚上", True),
        ("香港科学馆", "Hong Kong Science Museum", "博物馆", True, 1.0, True, True, 0, 3, 2.5, 20, 10, 10, "下午", True),
        ("天星小轮", "Star Ferry", "城市漫步", False, 0.5, True, True, 0, 2, 1, 5, 3, 0, "晚上", False),
    ),
    "新加坡": (
        ("新加坡动物园", "Singapore Zoo", "动物园", False, 4.0, True, True, 0, 3, 4, 320, 220, 220, "上午", True),
        ("滨海湾花园", "Gardens by the Bay", "自然风光", True, 2.0, True, True, 0, 2, 3, 110, 70, 70, "下午", True),
        ("新加坡环球影城", "Universal Studios Singapore", "主题乐园", False, 7.0, True, False, 0, 3, 8, 480, 360, 360, "全天", True),
        ("新加坡科学中心", "Science Centre Singapore", "博物馆", True, 1.5, True, True, 0, 3, 3, 90, 60, 60, "上午", True),
        ("鱼尾狮公园", "Merlion Park", "城市漫步", False, 1.0, True, True, 0, 1, 1, 0, 0, 0, "晚上", False),
    ),
    "东京": (
        ("上野动物园", "Ueno Zoo", "动物园", False, 3.0, True, True, 0, 3, 3, 30, 0, 15, "上午", True),
        ("东京迪士尼乐园", "Tokyo Disneyland", "主题乐园", False, 7.0, True, False, 0, 3, 8, 480, 290, 480, "全天", True),
        ("浅草寺", "Senso-ji Temple", "寺庙", False, 1.5, True, True, 0, 1, 1.5, 0, 0, 0, "上午", False),
        ("teamLab Planets", "teamLab Planets", "艺术展", True, 1.0, False, True, 0, 2, 2, 190, 0, 190, "下午", True),
        ("东京塔", "Tokyo Tower", "观光", True, 0.5, True, True, 0, 2, 1.5, 70, 40, 70, "晚上", True),
    ),
}

_POI_KEYS = ("name", "name_en", "category", "indoor", "walk_km", "stroller_ok", "senior_ok", "min_age", "kid_score",
             "duration_h", "price_adult", "price_child", "price_senior", "best_time", "prepay")


def search_pois(city: str) -> List[dict]:
    code = CITIES[city]["code"]
    return [{"id": f"P-{code}-{k + 1}", **dict(zip(_POI_KEYS, row))} for k, row in enumerate(_POIS.get(city, ()))]


# ------------------------------------------------------------------ partner coupons (demo)
# kind: percent（门票按比例优惠，value=优惠百分比）/ amount（立减金额）；scope: person / order；
# audience: all / family / inbound。仅在携程预付门票时可用。
COUPONS: Dict[str, dict] = {
    "上海迪士尼乐园": {"code": "TRIP-SHDL-FAM50", "partner": "上海迪士尼度假区", "kind": "amount", "value": 50, "scope": "person", "audience": "family", "min_people": 3, "cap": 300, "valid_until": "2026-12-31", "terms": "家庭（3 人及以上）预付门票每人立减 50 元，每单最高 300 元"},
    "上海自然博物馆": {"code": "TRIP-SNHM-10", "partner": "上海自然博物馆", "kind": "percent", "value": 10, "scope": "order", "audience": "all", "min_people": 1, "cap": None, "valid_until": "2026-12-31", "terms": "预付门票 9 折"},
    "东方明珠": {"code": "TRIP-OPT-INB20", "partner": "东方明珠广播电视塔", "kind": "amount", "value": 20, "scope": "person", "audience": "inbound", "min_people": 1, "cap": None, "valid_until": "2026-12-31", "terms": "入境游客凭护照预付门票每人立减 20 元"},
    "故宫博物院": {"code": "TRIP-PM-INB10", "partner": "故宫博物院（合作讲解服务）", "kind": "amount", "value": 10, "scope": "person", "audience": "inbound", "min_people": 1, "cap": None, "valid_until": "2026-12-31", "terms": "入境游客预付门票加英文讲解器每人立减 10 元"},
    "北京环球度假区": {"code": "TRIP-UBR-FAM60", "partner": "北京环球度假区", "kind": "amount", "value": 60, "scope": "person", "audience": "family", "min_people": 3, "cap": 360, "valid_until": "2026-12-31", "terms": "家庭（3 人及以上）预付门票每人立减 60 元，每单最高 360 元"},
    "宋城": {"code": "TRIP-SC-15", "partner": "杭州宋城", "kind": "percent", "value": 15, "scope": "order", "audience": "all", "min_people": 2, "cap": None, "valid_until": "2026-12-31", "terms": "2 人及以上预付门票 85 折"},
    "西湖（游船+环湖）": {"code": "TRIP-WL-BOAT10", "partner": "西湖游船", "kind": "amount", "value": 10, "scope": "person", "audience": "all", "min_people": 1, "cap": None, "valid_until": "2026-12-31", "terms": "预付游船票每人立减 10 元"},
    "秦始皇帝陵博物院（兵马俑）": {"code": "TRIP-TW-INB15", "partner": "秦始皇帝陵博物院（合作接驳）", "kind": "amount", "value": 15, "scope": "person", "audience": "inbound", "min_people": 1, "cap": None, "valid_until": "2026-12-31", "terms": "入境游客预付门票加接驳车每人立减 15 元"},
    "成都大熊猫繁育研究基地": {"code": "TRIP-PANDA-10", "partner": "成都大熊猫繁育研究基地", "kind": "percent", "value": 10, "scope": "order", "audience": "all", "min_people": 1, "cap": None, "valid_until": "2026-12-31", "terms": "预付门票 9 折"},
    "香港海洋公园": {"code": "TRIP-OPHK-FAM", "partner": "香港海洋公园", "kind": "percent", "value": 12, "scope": "order", "audience": "family", "min_people": 3, "cap": None, "valid_until": "2026-12-31", "terms": "家庭（3 人及以上）预付门票 88 折"},
    "新加坡动物园": {"code": "TRIP-SGZOO-10", "partner": "新加坡动物园", "kind": "percent", "value": 10, "scope": "order", "audience": "all", "min_people": 1, "cap": None, "valid_until": "2026-12-31", "terms": "预付门票 9 折"},
    "东京塔": {"code": "TRIP-TT-10", "partner": "东京塔", "kind": "percent", "value": 10, "scope": "order", "audience": "all", "min_people": 1, "cap": None, "valid_until": "2026-12-31", "terms": "预付门票 9 折"},
}


# ------------------------------------------------------------------ restaurants & allergens
ALLERGENS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    # 标准名: (英文名, 识别关键词：中 / 英 / 日 / 韩)。英文关键词按单词开头匹配，避免 "shellfish" 被识别成 "fish"；
    # 韩文只用多字词，避免 "땅콩"（花生）里的 "콩" 被识别成大豆。
    "花生": ("peanuts", ("花生", "peanut", "ピーナッツ", "落花生", "땅콩")),
    "坚果": ("tree nuts", ("坚果", "核桃", "腰果", "杏仁", "榛子", "nut", "walnut", "cashew", "almond", "hazelnut", "ナッツ", "くるみ", "견과", "호두")),
    "贝类": ("shellfish", ("贝类", "贝壳", "蛤", "牡蛎", "生蚝", "扇贝", "shellfish", "clam", "oyster", "scallop", "mussel", "貝", "조개", "패류")),
    "甲壳类": ("crustaceans (shrimp, crab)", ("甲壳", "虾", "蟹", "shrimp", "prawn", "crab", "lobster", "crustacean", "えび", "エビ", "かに", "カニ", "새우", "꽃게", "갑각류")),
    "鱼": ("fish", ("鱼", "fish", "魚", "생선")),
    "牛奶": ("milk / dairy", ("牛奶", "乳制品", "奶制品", "乳糖", "milk", "dairy", "lactose", "牛乳", "乳製品", "우유", "유제품")),
    "鸡蛋": ("eggs", ("鸡蛋", "蛋类", "蛋", "egg", "卵", "たまご", "タマゴ", "계란", "달걀")),
    "小麦": ("wheat / gluten", ("小麦", "麸质", "面筋", "gluten", "wheat", "グルテン", "밀가루", "글루텐")),
    "大豆": ("soy", ("大豆", "黄豆", "豆制品", "soy", "대두", "콩류")),
    "芝麻": ("sesame", ("芝麻", "sesame", "ごま", "ゴマ", "胡麻", "참깨")),
}


def _kw_match(keyword: str, text: str) -> bool:
    if keyword.isascii():
        return re.search(r"\b" + re.escape(keyword), text) is not None
    return keyword in text


def normalize_allergies(values: Iterable) -> Tuple[List[str], List[str]]:
    """Return (canonical allergens, unrecognised entries that need human review)."""
    found, unknown = set(), []
    for value in values:
        text = str(value).strip().lower()
        if not text:
            continue
        hits = {canon for canon, (_, kws) in ALLERGENS.items() if any(_kw_match(kw, text) for kw in kws)}
        if hits:
            found |= hits
        else:
            unknown.append(str(value).strip())
    order = list(ALLERGENS)
    return sorted(found, key=order.index), unknown


# (名称后缀, 菜系, 含有过敏原, 儿童餐, 人均, 收境外卡, 英文菜单, 清真, 素食, 儿童座椅)
_RESTAURANT_TEMPLATES = (
    ("家常菜馆", "中式家常菜", ("花生", "大豆", "小麦", "芝麻"), True, 90, False, False, False, False, True),
    ("海鲜酒家", "海鲜", ("贝类", "甲壳类", "鱼", "大豆"), False, 220, True, True, False, False, True),
    ("亲子主题餐厅", "西式简餐", ("牛奶", "鸡蛋", "小麦"), True, 130, True, True, False, False, True),
    ("素食馆", "素食", ("大豆", "小麦", "坚果"), True, 85, True, True, False, True, True),
    ("清真餐厅", "清真菜", ("小麦", "鸡蛋", "芝麻"), True, 75, False, False, True, False, False),
    ("面馆", "面食小吃", ("小麦", "鸡蛋", "大豆"), True, 45, False, False, False, False, False),
)
_STREETS = ("人民路", "中山路", "新天地", "文化街", "滨江路", "和平路")


def search_restaurants(city: str) -> List[dict]:
    code, mainland = CITIES[city]["code"], is_mainland(city)
    fx = CITIES[city]["fx"]
    out = []
    for k, (suffix, cuisine, allergens, kid_menu, price, card, en_menu, halal, veg, high_chair) in enumerate(_RESTAURANT_TEMPLATES):
        out.append({
            "id": f"R-{code}-{k + 1}",
            "name": f"{city}{_STREETS[k]}{suffix}",
            "cuisine": cuisine,
            "allergens": list(allergens),
            "kid_menu": kid_menu,
            "high_chair": high_chair,
            "price_pp": int(round(price * (fx if not mainland else 1.0), -1)),
            "foreign_card": card or not mainland,
            "english_menu": en_menu or not mainland,
            "halal": halal,
            "vegetarian": veg,
        })
    return out


# ------------------------------------------------------------------ age-based pricing (demo rules)
def transport_fare(option: dict, age: Optional[int], domestic: bool) -> int:
    """Flight: <2 岁 10%，2–11 岁国内 50% / 国际 75%。高铁：<6 岁免票，6–14 岁半价。"""
    price = option["price_cny"]
    if age is None:
        return price
    if option["mode"] == "flight":
        if age < 2:
            return int(round(price * 0.1, -1))
        if age < 12:
            return int(round(price * (0.5 if domestic else 0.75), -1))
        return price
    if age < 6:
        return 0
    if age < 15:
        return int(round(price * 0.5, -1))
    return price


def poi_price(poi: dict, age: Optional[int]) -> int:
    """<6 岁免票，6–17 岁儿童票，60 岁以上长者票。"""
    if age is None or 18 <= age < 60:
        return poi["price_adult"]
    if age < 6:
        return 0
    if age < 18:
        return poi["price_child"]
    return poi["price_senior"]


def meal_factor(age: Optional[int]) -> float:
    """<3 岁不计餐费，3–11 岁按半份估算。"""
    if age is None or age >= 12:
        return 1.0
    return 0.0 if age < 3 else 0.5
