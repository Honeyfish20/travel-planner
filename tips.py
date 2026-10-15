"""Inbound travel reminders built from the final itinerary (rules, deterministic).

1. network_timeline — when and where the visitor's connection changes (landing,
   hotel Wi-Fi, high-speed rail, out-of-town sights, departure), what is
   affected, what to do, and links to Trip.com's official guides.
2. cash_advice — how much RMB small change to bring, broken down by day and
   place with a short reason for each amount, plus a note-denomination split.

Compliance: only roaming / eSIM preparation and offline readiness are
suggested; no cross-border access tools are recommended.
"""
from __future__ import annotations

import math
from collections import OrderedDict
from typing import Dict, List, Optional

import data
import knowledge

# ------------------------------------------------------------------ Trip.com official guides
GUIDES_CHECKED = "2026-10-11"
TRIP_GUIDES: Dict[str, Dict[str, tuple]] = {
    "esim": {
        "en": ("China eSIM guide — Trip.com", "https://www.trip.com/guide/phone/china-esim.html"),
        "ja": ("中国eSIMおすすめ比較 — Trip.com", "https://jp.trip.com/guide/phone/%E4%B8%AD%E5%9B%BD+eSIM.html"),
        "es": ("Internet en China: eSIM, SIM y WiFi — Trip.com", "https://es.trip.com/guide/phone/china-wifi.html"),
        "fr": ("Guide du Wi-Fi en Chine — Trip.com", "https://fr.trip.com/guide/phone/wi-fi-en-chine.html"),
    },
    "esim_setup": {
        "ja": ("中国eSIMの使い方・設定ガイド — Trip.com", "https://jp.trip.com/guide/phone/esim+%E4%B8%AD%E5%9B%BD+%E4%BD%BF%E3%81%84%E6%96%B9.html"),
    },
    "travel_tips": {
        "en": ("China Travel Tips 2026: Apps, Costs & Attractions — Trip.com", "https://www.trip.com/guide/info/china-travel-tips.html"),
        "es": ("Guía de viaje a China — Trip.com", "https://es.trip.com/guide/info/guia-viaje-china.html"),
    },
    "visa_transit": {
        "en": ("China 24/240-Hour Visa-Free Transit Guide — Trip.com", "https://www.trip.com/guide/info/china-visa-free-transit.html"),
    },
    "alipay": {
        "ja": ("アリペイ（Alipay）の使い方完全ガイド — Trip.com", "https://jp.trip.com/guide/china/%E3%82%A2%E3%83%AA%E3%83%9A%E3%82%A4.html"),
    },
}


def guide_links(keys, language: str) -> List[dict]:
    """Trip.com guide links in the visitor's language, falling back to English."""
    out = []
    for key in keys:
        options = TRIP_GUIDES.get(key, {})
        for lang in dict.fromkeys((language, "en")):
            if lang in options:
                title, url = options[lang]
                out.append({"key": key, "title": title, "url": url, "lang": lang, "checked": GUIDES_CHECKED})
                break
    return out


# Attractions outside the city centre: weaker mobile signal, more cash-only stalls.
REMOTE_POIS = {"八达岭长城", "都江堰", "秦始皇帝陵博物院（兵马俑）", "上海迪士尼乐园", "北京环球度假区"}


def _items(itin: dict, kind: str):
    for d in itin["days"]:
        for i in d["items"]:
            if (kind == "poi" and i.get("poi")) or (kind == "meal" and i.get("restaurant")):
                yield d, i


def network_timeline(req: dict, transport: dict, hotel: dict, itin: dict) -> Optional[dict]:
    if not req["is_inbound"]:
        return None
    lang = req["language"]
    out, back = transport["outbound"], transport["return"]
    events: List[dict] = []

    def add(when, place, impact_zh, impact_en, action_zh, action_en, links=(), when_en=None, place_en=None):
        events.append({"when": when, "when_en": when_en or when, "place": place, "place_en": place_en or place,
                       "impact_zh": impact_zh, "impact_en": impact_en,
                       "action_zh": action_zh, "action_en": action_en, "links": guide_links(links, lang)})

    add("出发前", req["origin"],
        "入境后本国 SIM 卡如未开通漫游将无法上网；境内网络下部分境外应用可能无法正常使用。",
        "Without roaming your home SIM has no data in China; some overseas apps may not work on local networks.",
        "开通本国运营商国际漫游，或购买并提前安装支持中国大陆的旅行 eSIM；下载离线翻译包，保存酒店中英文地址和电子票。",
        "Turn on international roaming or install a China travel eSIM before you leave; download offline translation and save your hotel address and e-tickets.",
        ("esim", "esim_setup", "travel_tips"), "Before departure", data.CITIES[req["origin"]]["en"])
    add(f"{out['arrive'][5:]} 抵达", out["to_hub"],
        "落地后手机需要切换到漫游或 eSIM 线路，切换前无法使用打车、地图和支付。",
        "After landing your phone must switch to the roaming / eSIM line; ride-hailing, maps and payments won't work until it does.",
        "下机后打开数据漫游或切换到 eSIM 线路，先确认能打开携程 App 和支付 App，再出关打车。",
        "Turn on data roaming or switch to the eSIM line right after landing, and check that Trip.com and your payment app open before leaving the airport.",
        ("esim",), f"{out['arrive'][5:]} arrival")
    if hotel["hotel"]:
        add(f"{req['depart_date'][5:]} 入住", hotel["hotel"]["name"],
            "连接酒店 Wi-Fi 后走境内网络，部分境外社交、地图、邮箱应用可能无法使用；携程、微信、支付宝等不受影响。",
            "On hotel Wi-Fi you use the local network: some overseas social, map and email apps may not work; Trip.com, WeChat and Alipay work normally.",
            "需要使用境外应用时关闭 Wi-Fi、改用漫游或 eSIM 数据；行程、订单和求助卡在携程 App 内查看。",
            "Switch Wi-Fi off and use your roaming / eSIM data for overseas apps; keep your itinerary, orders and help cards in the Trip.com app.",
            ("travel_tips",), f"{req['depart_date'][5:]} hotel check-in")
    rail_legs = [o for o in (out, back) if o["mode"] == "rail"]
    if rail_legs:
        add(f"{rail_legs[0]['depart'][5:]} 乘高铁", rail_legs[0]["from_hub"],
            "高铁途经隧道和山区时信号会时断时续，可能打不开电子票或支付页面。",
            "Signal drops in tunnels and mountains on high-speed rail, so e-tickets or payment pages may not load.",
            "上车前截图或离线保存车票信息，进出站凭护照。",
            "Screenshot or save your ticket offline before boarding; use your passport at the gates.",
            when_en=f"{rail_legs[0]['depart'][5:]} high-speed rail")
    for d, i in _items(itin, "poi"):
        if i["poi"]["name"] in REMOTE_POIS:
            add(f"{d['date'][5:]} {i.get('time') or ''}".strip(), i["poi"]["name"],
                "郊区景区人多、信号可能较弱，扫码购物和打车可能失败。",
                "Out-of-town sights can be crowded with weak signal; QR payments and ride-hailing may fail.",
                "提前下载离线地图，准备少量现金，约好返程车辆或集合时间。",
                "Download offline maps, carry some cash and arrange your return ride or meeting time in advance.",
                when_en=f"{d['date'][5:]} {i.get('time') or ''}".strip(), place_en=i["poi"]["name_en"])
    add("行程中分享", req["destination"],
        "用酒店 Wi-Fi 发布境外社交平台可能失败。",
        "Posting to overseas social platforms over hotel Wi-Fi may fail.",
        "通过手机系统分享面板，用自己的漫游或 eSIM 数据发布；也可以生成图片分享给在中国的同伴。",
        "Use your phone's share sheet over your own roaming / eSIM data, or share an image with companions in China.",
        when_en="Sharing during the trip", place_en=data.CITIES[req["destination"]]["en"])
    add(f"{back['depart'][5:]} 返程", back["from_hub"],
        "旅行 eSIM 套餐可能在离境前到期。",
        "Your travel eSIM plan may expire before you leave.",
        "确认套餐有效期覆盖到登机，必要时在携程 App 内续期。",
        "Make sure the plan lasts until boarding and top it up in the Trip.com app if needed.",
        ("esim",), f"{back['depart'][5:]} departure")
    return {"events": events, "guides": guide_links(("esim", "esim_setup", "travel_tips", "visa_transit", "alipay"), lang),
            "checked": GUIDES_CHECKED}


# ------------------------------------------------------------------ RMB small change
_POI_CASH = {  # category: (yuan per person, reason zh, reason en)
    "城市漫步": (30, "老街和夜市的小吃摊、手作摊多为个人收款码，扫码失败或不收境外卡时需要现金",
             "Street-food and craft stalls in old streets and night markets often use personal QR codes; cash helps if a scan fails"),
    "寺庙": (10, "香烛、许愿牌、小额随喜多用现金", "Incense, wish cards and small donations are usually paid in cash"),
    "自然风光": (10, "景区小卖部、储物柜、小游船可能只收现金", "Kiosks, lockers and small boats at scenic spots may take cash only"),
    "皇家园林": (10, "园内小卖部、租赁讲解器押金可能需要现金", "Kiosks and audio-guide deposits may require cash"),
    "历史古迹": (10, "景区周边小摊和存包处可能只收现金", "Stalls and left-luggage counters near the site may take cash only"),
    "动物园": (10, "园内投喂、小卖部可能只收现金", "Animal-feeding and kiosks inside may take cash only"),
    "主题乐园": (0, "", ""),
    "博物馆": (0, "", ""),
}
_REMOTE_CASH = 50          # per group
_SNACK_ADULT = 15          # per person per day: water / snacks
_SNACK_CHILD = 10
_MEAL_CAP = 200            # cash-only restaurant: cover up to this much
_BUFFER = 200              # per group
_BUFFER_EXTRA = 100        # with children or seniors


def _round_up(x: float, step: int = 50) -> int:
    return int(math.ceil(x / step) * step)


def _denominations(total: int) -> List[dict]:
    """About 30 % (¥100–300) in ¥10 / ¥20 notes — vendors often can't change ¥100."""
    small = min(300, max(100, _round_up(total * 0.3, 10)))
    n20 = int(small * 0.6 // 20)
    n10 = int((small - n20 * 20) // 10)
    rest = total - n20 * 20 - n10 * 10
    n50 = 1 if rest % 100 else (2 if rest >= 200 else 0)
    n100 = max(0, (rest - n50 * 50) // 100)
    remain = rest - n50 * 50 - n100 * 100
    n10 += max(0, remain) // 10
    return [{"note": v, "count": c} for v, c in ((100, n100), (50, n50), (20, n20), (10, n10)) if c]


def cash_advice(req: dict, bundle: dict, ground: dict, itin: dict) -> Optional[dict]:
    if not req["is_inbound"]:
        return None
    members = req["members"]
    party = len(members)
    adults = sum(1 for m in members if m["age"] is None or m["age"] >= 12)
    kids = sum(1 for m in members if m["age"] is not None and 3 <= m["age"] < 12)
    seniors = sum(1 for m in members if m["age"] is not None and m["age"] >= 65)
    days: "OrderedDict[str, List[dict]]" = OrderedDict((d["date"], []) for d in itin["days"])

    def add(day: str, place: str, place_en: str, amount: float, reason: str, reason_en: str) -> None:
        if amount > 0:
            days[day].append({"place": place, "place_en": place_en, "amount": int(round(amount)), "reason": reason, "reason_en": reason_en})

    snack = adults * _SNACK_ADULT + kids * _SNACK_CHILD
    for d in itin["days"]:
        add(d["date"], "全天", "All day", snack, f"{party} 人的饮用水和零食；路边小店、自动售货机偶尔只收现金或不支持境外卡",
            f"Water and snacks for {party}; small shops and vending machines sometimes take cash only or reject foreign cards")
    for d, i in _items(itin, "poi"):
        p = i["poi"]
        per, reason, reason_en = _POI_CASH.get(p["category"], (0, "", ""))
        add(d["date"], p["name"], p["name_en"], per * party, reason, reason_en)
        if p["name"] in REMOTE_POIS:
            add(d["date"], p["name"], p["name_en"], _REMOTE_CASH, "郊区景区信号可能较弱，扫码易失败；景区接驳车和周边小摊常收现金",
                "Out-of-town site with weak signal so QR payments may fail; shuttles and nearby stalls often take cash")
    for d, i in _items(itin, "meal"):
        r = i["restaurant"]
        if not r["foreign_card"]:
            meal = sum(r["price_pp"] * data.meal_factor(m["age"]) for m in members)
            add(d["date"], r["name"], r["name"], min(meal, _MEAL_CAP), "该餐厅不收境外银行卡，若扫码失败需要现金结账",
                "This restaurant doesn't accept foreign cards; pay cash if the QR payment fails")
    first, last = itin["days"][0]["date"], itin["days"][-1]["date"]
    for key, day, label, label_en in (("arrival", first, "抵达接送", "Arrival transfer"), ("departure", last, "离开接送", "Departure transfer")):
        t = ground[key]
        if t["mode"] == "出租车":
            add(day, label, label_en, ground[f"{key}_cny"], "出租车多数可扫码，但偶尔只收现金，准备好车费更稳妥",
                "Most taxis accept QR payment but some take cash only; keep the fare in cash")
        elif t["per_person"]:
            add(day, label, label_en, 10 * party, "地铁和机场快线可刷支付码，少数自助售票机只收现金",
                "Metro and airport express accept QR codes; a few ticket machines take cash only")
    buffer = _BUFFER + (_BUFFER_EXTRA if kids or seniors else 0)
    add(first, "应急备用", "Emergency reserve", buffer, "手机没电、网络不通或支付被风控时，用于打车、吃饭等应急开销",
        "For taxis or meals if your phone dies, there's no signal or a payment is blocked")

    breakdown = [{"date": day, "items": items, "subtotal": sum(x["amount"] for x in items)} for day, items in days.items()]
    raw = sum(b["subtotal"] for b in breakdown)
    total = min(max(_round_up(raw), 300), 5000)
    home = req["home_currency"]
    reasons = [
        "大多数商户支持支付宝、微信扫码，现金只用于小摊、少数出租车、郊区景区和应急。",
        "小商户常找不开 100 元，约 3 成（最多 300 元）准备成 10 元和 20 元。",
        "可在机场或银行 ATM 用境外银行卡取现，也可在机场兑换点兑换；剩余现金可留作下次使用。",
    ]
    reasons_en = [
        "Most merchants accept Alipay and WeChat Pay; cash is only for stalls, some taxis, out-of-town sites and emergencies.",
        "Small vendors often can't change ¥100, so keep about 30 % (up to ¥300) in ¥10 and ¥20 notes.",
        "Withdraw at airport or bank ATMs with your foreign card, or exchange at the airport; keep any leftover for next time.",
    ]
    return {
        "total_cny": total,
        "raw_cny": raw,
        "home_currency": home,
        "total_home": knowledge.from_cny(total, home) if home != "CNY" else None,
        "denominations": _denominations(total),
        "breakdown": breakdown,
        "reasons": reasons,
        "reasons_en": reasons_en,
        "fx_note": knowledge.FX_NOTE,
    }
