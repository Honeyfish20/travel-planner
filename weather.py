"""Weather agent: multi-day and intra-day weather analysis for itinerary planning.

Data source per trip day (no API key needed):
  1. Open-Meteo forecast API — up to 16 days ahead, hourly.
  2. Open-Meteo archive API — same dates last year, used as a *reference* when
     the day is beyond the forecast range.
  3. Deterministic demo climate — when the network is unavailable or WEATHER=off.

Each day is split into five time blocks (早上 / 上午 / 午间 / 下午 / 晚上). A block
is marked unsuitable for outdoor sightseeing on rain, snow, thunderstorm,
heat (feels-like ≥ 33 °C) or strong wind; the itinerary agent schedules indoor
attractions there, and the rule check swaps any outdoor attraction that still
lands in a bad block. Weather data by Open-Meteo.com (CC BY 4.0).
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from typing import Dict, List, Optional

import data

logger = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_DAYS = 16
TIMEOUT = 12
CACHE_TTL = 1800
ATTRIBUTION = "Weather data by Open-Meteo.com (CC BY 4.0)"
HOURLY_FORECAST = "temperature_2m,apparent_temperature,precipitation_probability,precipitation,weather_code,wind_speed_10m,uv_index"
HOURLY_ARCHIVE = "temperature_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m"

RAIN_PROB = 60       # %
RAIN_MM = 1.0        # mm within a block
HOT_FEELS = 33.0     # °C feels-like
COLD_FEELS = 3.0
WIND_KMH = 38.0
UV_HIGH = 8.0

BLOCKS = (("morning", "早上", "Early morning", "07:00", "10:00"), ("forenoon", "上午", "Morning", "10:00", "12:00"),
          ("noon", "午间", "Midday", "12:00", "15:00"), ("afternoon", "下午", "Afternoon", "15:00", "18:00"),
          ("evening", "晚上", "Evening", "18:00", "21:00"))
SOURCE_LABELS = {"forecast": "实时预报", "archive": "去年同期参考", "demo": "演示数据"}
SOURCE_LABELS_EN = {"forecast": "Live forecast", "archive": "Last-year reference", "demo": "Demo data"}

_WMO = {
    0: ("晴", "☀️"), 1: ("晴间多云", "🌤️"), 2: ("多云", "⛅"), 3: ("阴", "☁️"), 45: ("雾", "🌫️"), 48: ("雾", "🌫️"),
    51: ("毛毛雨", "🌦️"), 53: ("毛毛雨", "🌦️"), 55: ("毛毛雨", "🌦️"), 56: ("冻毛毛雨", "🌧️"), 57: ("冻毛毛雨", "🌧️"),
    61: ("小雨", "🌧️"), 63: ("中雨", "🌧️"), 65: ("大雨", "🌧️"), 66: ("冻雨", "🌧️"), 67: ("冻雨", "🌧️"),
    71: ("小雪", "🌨️"), 73: ("中雪", "🌨️"), 75: ("大雪", "❄️"), 77: ("雪粒", "🌨️"),
    80: ("阵雨", "🌦️"), 81: ("阵雨", "🌦️"), 82: ("强阵雨", "⛈️"), 85: ("阵雪", "🌨️"), 86: ("强阵雪", "❄️"),
    95: ("雷阵雨", "⛈️"), 96: ("雷阵雨伴冰雹", "⛈️"), 99: ("雷阵雨伴冰雹", "⛈️"),
}
WET = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}
LIGHT_WET = {51, 53, 61, 80}   # drizzle / slight rain / slight showers: outdoors OK with an umbrella
SNOW = {71, 73, 75, 77, 85, 86}
STORM = {95, 96, 99}
BAD_TAGS = {"rain", "snow", "storm", "hot", "wind"}
TAG_TEXT = {"rain": "降雨", "light_rain": "小雨", "snow": "降雪", "storm": "雷暴", "hot": "高温", "cold": "低温", "wind": "大风", "uv": "紫外线强"}
TAG_TEXT_EN = {"rain": "rain", "light_rain": "light rain", "snow": "snow", "storm": "thunderstorm", "hot": "heat",
               "cold": "cold", "wind": "strong wind", "uv": "strong UV"}
_WMO_EN = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Fog",
    51: "Drizzle", 53: "Drizzle", 55: "Drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Showers", 81: "Showers", 82: "Heavy showers", 85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with hail",
}


def describe(code: int):
    return _WMO.get(int(code or 0), ("未知", "🌡️"))


def describe_en(code: int) -> str:
    return _WMO_EN.get(int(code or 0), "Unknown")


# ------------------------------------------------------------------ fetching
_cache: Dict[str, tuple] = {}
_cache_lock = threading.Lock()


def _fetch_json(url: str, params: dict) -> dict:
    full = url + "?" + urllib.parse.urlencode(params)
    with _cache_lock:
        hit = _cache.get(full)
        if hit and time.time() - hit[0] < CACHE_TTL:
            return hit[1]
    req = urllib.request.Request(full, headers={"User-Agent": "travel-planner/3.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        body = json.loads(r.read().decode("utf-8"))
    if body.get("error"):
        raise ValueError(body.get("reason") or "Open-Meteo error")
    with _cache_lock:
        _cache[full] = (time.time(), body)
    return body


def _rows(body: dict, shift_years: int = 0) -> Dict[str, List[dict]]:
    """Hourly arrays → {YYYY-MM-DD: [hour rows]}, optionally shifting the year forward."""
    h = body.get("hourly") or {}
    times = h.get("time") or []
    out: Dict[str, List[dict]] = {}
    for i, ts in enumerate(times):
        day, hour = ts[:10], int(ts[11:13])
        if shift_years:
            day = f"{int(day[:4]) + shift_years}{day[4:]}"
        col = lambda k: (h.get(k) or [None] * len(times))[i]  # noqa: E731
        precip = col("precipitation") or 0.0
        prob = col("precipitation_probability")
        if prob is None:  # archive has no probability: derive it from measured rain
            prob = 85 if precip >= 0.5 else (45 if precip >= 0.1 else 5)
        out.setdefault(day, []).append({
            "hour": hour, "temp": col("temperature_2m"), "feels": col("apparent_temperature"),
            "prob": prob, "precip": precip, "code": col("weather_code") or 0,
            "wind": col("wind_speed_10m") or 0.0, "uv": col("uv_index") or 0.0,
        })
    return out


def _shift_year(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # Feb 29
        return d.replace(year=d.year + years, day=28)


def _demo_rows(city: str, day: date) -> List[dict]:
    """Plausible but synthetic hourly weather (deterministic per city and date)."""
    c = data.CITIES[city]
    rng = data._rng("weather", city, day.isoformat())
    lat = c["lat"]
    season = math.cos((day.timetuple().tm_yday - 200) / 365 * 2 * math.pi) * (1 if lat >= 0 else -1)
    amplitude = 0 if abs(lat) < 10 else 8 + abs(lat) / 6
    mean = 27 - max(0, abs(lat) - 20) * 0.6 + amplitude * season + rng.uniform(-2, 2)
    rain_start = rng.choice((None, None, 8, 13, 16)) if abs(lat) >= 10 else rng.choice((None, 14, 15, 16))
    rows = []
    for hour in range(24):
        temp = round(mean + 4.5 * math.sin((hour - 9) / 24 * 2 * math.pi), 1)
        raining = rain_start is not None and rain_start <= hour < rain_start + 3
        rows.append({"hour": hour, "temp": temp, "feels": round(temp + (2 if mean > 26 else -1), 1),
                     "prob": 75 if raining else rng.choice((5, 10, 15, 20)), "precip": 1.2 if raining else 0.0,
                     "code": 63 if raining else rng.choice((0, 1, 2, 3)), "wind": round(rng.uniform(5, 20), 1),
                     "uv": max(0.0, round(7 * math.sin((hour - 6) / 12 * math.pi), 1)) if 6 <= hour <= 18 else 0.0})
    return rows


def _collect(city: str, dates: List[date], today: date) -> Dict[str, tuple]:
    """Return {date_iso: (source, rows)} using forecast → archive → demo."""
    c = data.CITIES[city]
    loc = {"latitude": c["lat"], "longitude": c["lon"], "timezone": "auto"}
    out: Dict[str, tuple] = {}
    if os.environ.get("WEATHER", "on").lower() == "off":
        return {d.isoformat(): ("demo", _demo_rows(city, d)) for d in dates}
    horizon = today + timedelta(days=FORECAST_DAYS - 1)
    near = [d for d in dates if d <= horizon]
    far = [d for d in dates if d > horizon]
    if near:
        try:
            body = _fetch_json(FORECAST_URL, {**loc, "hourly": HOURLY_FORECAST,
                                              "start_date": near[0].isoformat(), "end_date": near[-1].isoformat()})
            rows = _rows(body)
            out.update({d.isoformat(): ("forecast", rows[d.isoformat()]) for d in near if rows.get(d.isoformat())})
        except Exception as e:  # network, HTTP or bad data → fall through
            logger.warning("weather forecast failed for %s: %s", city, e)
    if far:
        try:
            start, end = _shift_year(far[0], -1), _shift_year(far[-1], -1)
            body = _fetch_json(ARCHIVE_URL, {**loc, "hourly": HOURLY_ARCHIVE, "start_date": start.isoformat(), "end_date": end.isoformat()})
            rows = _rows(body, shift_years=1)
            out.update({d.isoformat(): ("archive", rows[d.isoformat()]) for d in far if rows.get(d.isoformat())})
        except Exception as e:
            logger.warning("weather archive failed for %s: %s", city, e)
    for d in dates:
        out.setdefault(d.isoformat(), ("demo", _demo_rows(city, d)))
    return out


# ------------------------------------------------------------------ analysis
def _round(x) -> Optional[float]:
    return None if x is None else round(float(x), 1)


def _block(rows: List[dict], key: str, label: str, label_en: str, start: str, end: str) -> dict:
    h0, h1 = int(start[:2]), int(end[:2])
    sel = [r for r in rows if h0 <= r["hour"] < h1 and r["temp"] is not None] or rows
    temps = [r["temp"] for r in sel]
    feels = [r["feels"] if r["feels"] is not None else r["temp"] for r in sel]
    code = max((int(r["code"]) for r in sel), default=0)
    precip = sum(r["precip"] for r in sel)
    prob = max(int(r["prob"] or 0) for r in sel)
    wind = max(r["wind"] for r in sel)
    uv = max(r["uv"] for r in sel)
    tags = []
    if code in STORM:
        tags.append("storm")
    if prob >= RAIN_PROB or precip >= RAIN_MM or (code in WET and code not in LIGHT_WET):
        tags.append("rain")
    elif code in LIGHT_WET or prob >= 40:
        tags.append("light_rain")
    if code in SNOW:
        tags.append("snow")
    if max(feels) >= HOT_FEELS:
        tags.append("hot")
    if min(feels) <= COLD_FEELS:
        tags.append("cold")
    if wind >= WIND_KMH:
        tags.append("wind")
    if uv >= UV_HIGH:
        tags.append("uv")
    ok = not (BAD_TAGS & set(tags))
    text, icon = describe(code)
    if ok:
        extras = [("light_rain", "，带好雨伞", ", bring an umbrella"), ("uv", "，注意防晒", ", use sun protection"),
                  ("cold", "，注意保暖", ", dress warmly")]
        advice = "适合户外" + "".join(zh for k, zh, _ in extras if k in tags)
        advice_en = "Good for outdoors" + "".join(en for k, _, en in extras if k in tags)
    else:
        bad = [t for t in tags if t in BAD_TAGS]
        advice = "建议室内：" + "、".join(TAG_TEXT[t] for t in bad)
        advice_en = "Indoors recommended: " + ", ".join(TAG_TEXT_EN[t] for t in bad)
        if "rain" in tags:
            advice += f"（降雨概率 {prob}%）"
            advice_en += f" ({prob}% chance of rain)"
    return {"key": key, "label": label, "label_en": label_en, "start": start, "end": end, "temp": _round(sum(temps) / len(temps)),
            "feels_max": _round(max(feels)), "feels_min": _round(min(feels)), "precip_prob": prob,
            "precip_mm": _round(precip), "code": code, "text": text, "text_en": describe_en(code), "icon": icon, "wind": _round(wind),
            "uv": _round(uv), "tags": tags, "outdoor_ok": ok, "advice": advice, "advice_en": advice_en}


def _clothing(feels_mean: float):
    """(zh, en) clothing advice for the mean daytime feels-like temperature."""
    if feels_mean >= 28:
        return "短袖、透气衣物，带遮阳帽", "Short sleeves, breathable clothes and a sun hat"
    if feels_mean >= 20:
        return "薄长袖或短袖，早晚加一件薄外套", "Light layers; a thin jacket for mornings and evenings"
    if feels_mean >= 12:
        return "长袖加外套或卫衣", "Long sleeves with a jacket or hoodie"
    if feels_mean >= 5:
        return "毛衣加厚外套", "A sweater and a warm coat"
    return "羽绒服、帽子和手套", "A down jacket, hat and gloves"


def _day(day_iso: str, source: str, rows: List[dict], cons: Optional[dict]) -> dict:
    valid = [r for r in rows if r["temp"] is not None]
    blocks = [_block(valid, *b) for b in BLOCKS]
    temps = [r["temp"] for r in valid]
    feels = [r["feels"] if r["feels"] is not None else r["temp"] for r in valid if 7 <= r["hour"] < 21] or temps
    code = max((int(r["code"]) for r in valid if 7 <= r["hour"] < 21), default=0)
    text, icon = describe(code)
    bad = [b for b in blocks if not b["outdoor_ok"]]
    t_max, t_min = max(temps), min(temps)
    tips = []  # (zh, en) pairs
    tags = {t for b in blocks for t in b["tags"]}
    kids = bool(cons and cons.get("kids"))
    seniors = bool(cons and cons.get("senior_or_limited"))
    if tags & {"rain", "storm", "light_rain"}:
        tips.append(("带伞或雨衣" + ("，给孩子准备雨衣和备用衣物" if kids else ""),
                     "Bring an umbrella or raincoat" + (", plus rain gear and spare clothes for the kids" if kids else "")))
        if seniors:
            tips.append(("雨天路滑，老人穿防滑鞋，尽量乘车到景点门口",
                         "Paths get slippery: non-slip shoes for older travellers, and take a car to the entrance"))
    if "hot" in tags:
        tips.append(("高温时段多补水、避免长时间暴晒" + ("，老人和孩子午间尽量待在室内" if kids or seniors else ""),
                     "Drink plenty and avoid long sun exposure in the heat" + ("; keep kids and older travellers indoors at midday" if kids or seniors else "")))
    if "uv" in tags:
        tips.append(("紫外线强：涂防晒霜、戴帽子和太阳镜", "Strong UV: sunscreen, a hat and sunglasses"))
    if "cold" in tags or t_min <= 5:
        tips.append(("早晚气温低，注意保暖", "Cold mornings and evenings: dress warmly"))
    if t_max - t_min >= 10:
        tips.append((f"昼夜温差约 {t_max - t_min:.0f}°C，建议分层穿衣", f"About {t_max - t_min:.0f}°C between day and night: dress in layers"))
    if "wind" in tags:
        tips.append(("风大：户外高处和游船可能停运，出发前确认", "Strong wind: viewpoints and boats may close, check before you go"))
    text_en = describe_en(code)
    rng = f"{t_min:.0f}–{t_max:.0f}°C"
    if not bad:
        summary, summary_en = f"{text}，{rng}，全天适合户外", f"{text_en}, {rng}, good for outdoors all day"
    elif len(bad) >= 4:
        summary = f"{text}，{rng}，大部分时段不适合户外，以室内景点为主"
        summary_en = f"{text_en}, {rng}, mostly not suitable for outdoors — plan indoor sights"
    else:
        summary = f"{text}，{rng}，" + "、".join(b["label"] for b in bad) + "建议室内，其余时段适合户外"
        summary_en = f"{text_en}, {rng}; " + ", ".join(b["label_en"].lower() for b in bad) + " better indoors, other times fine outdoors"
    clothing, clothing_en = _clothing(sum(feels) / len(feels))
    return {"date": day_iso, "source": source, "source_label": SOURCE_LABELS[source], "source_label_en": SOURCE_LABELS_EN[source],
            "code": code, "text": text, "text_en": text_en, "icon": icon,
            "t_max": _round(t_max), "t_min": _round(t_min),
            "precip_prob_max": max(int(r["prob"] or 0) for r in valid), "precip_mm": _round(sum(r["precip"] for r in valid)),
            "uv_max": _round(max(r["uv"] for r in valid)), "blocks": blocks, "bad_blocks": len(bad),
            "rainy_day": len(bad) >= 3, "summary": summary, "summary_en": summary_en,
            "clothing": clothing, "clothing_en": clothing_en,
            "tips": [zh for zh, _ in tips], "tips_en": [en for _, en in tips]}


def weather_agent(req: dict, cons: Optional[dict] = None, today: Optional[date] = None) -> dict:
    today = today or date.today()
    start = date.fromisoformat(req["depart_date"])
    dates = [start + timedelta(days=i) for i in range(req["nights"] + 1)]
    collected = _collect(req["destination"], dates, today)
    days = [_day(d.isoformat(), *collected[d.isoformat()], cons) for d in dates]
    sources = sorted({d["source"] for d in days}, key=list(SOURCE_LABELS).index)
    alerts, alerts_en = [], []
    for d in days:
        storm = [b for b in d["blocks"] if "storm" in b["tags"]]
        hot = [b for b in d["blocks"] if "hot" in b["tags"]]
        if storm:
            alerts.append(f"{d['date']} {'、'.join(b['label'] for b in storm)}可能有雷暴，户外活动和游船请以现场通知为准")
            alerts_en.append(f"{d['date']} possible thunderstorms ({', '.join(b['label_en'].lower() for b in storm)}); outdoor activities and boats may be suspended")
        if len(hot) >= 2:
            feels = max(b["feels_max"] for b in d["blocks"])
            alerts.append(f"{d['date']} {'、'.join(b['label'] for b in hot)}体感 {feels:.0f}°C，注意防暑")
            alerts_en.append(f"{d['date']} feels like {feels:.0f}°C ({', '.join(b['label_en'].lower() for b in hot)}); beware of heat")
        if d["precip_mm"] and d["precip_mm"] >= 20:
            alerts.append(f"{d['date']} 预计降雨约 {d['precip_mm']:.0f} mm，可能影响交通，预留出行时间")
            alerts_en.append(f"{d['date']} about {d['precip_mm']:.0f} mm of rain expected; allow extra travel time")
    note = {"forecast": "", "archive": "部分日期超出 16 天预报范围，按去年同期天气参考，出发前请再次查看预报。",
            "demo": "未能获取实时天气，以下为演示数据。"}
    note_en = {"forecast": "", "archive": "Some dates are beyond the 16-day forecast; last year's weather is shown for reference. Check the forecast again before you go.",
               "demo": "Live weather unavailable; demo data shown."}
    return {
        "city": req["destination"],
        "city_en": data.CITIES[req["destination"]]["en"],
        "sources": sources,
        "source_label": " + ".join(SOURCE_LABELS[s] for s in sources),
        "source_label_en": " + ".join(SOURCE_LABELS_EN[s] for s in sources),
        "note": " ".join(note[s] for s in sources if note[s]),
        "note_en": " ".join(note_en[s] for s in sources if note_en[s]),
        "days": days,
        "alerts": alerts,
        "alerts_en": alerts_en,
        "attribution": ATTRIBUTION if any(s != "demo" for s in sources) else "",
    }


def block_at(day: Optional[dict], hhmm: str) -> Optional[dict]:
    """Return the weather block covering HH:MM (nearest block outside 07–21)."""
    if not day or not hhmm or len(hhmm) < 5 or ":" not in hhmm:
        return None
    for b in day["blocks"]:
        if b["start"] <= hhmm[:5] < b["end"]:
            return b
    return day["blocks"][0] if hhmm[:5] < day["blocks"][0]["start"] else day["blocks"][-1]


def prompt_brief(w: dict) -> List[dict]:
    """Compact per-day weather for the itinerary prompt."""
    return [{"date": d["date"], "summary": d["summary"],
             "blocks": [{"time": f"{b['start']}-{b['end']}", "weather": b["text"], "temp": b["temp"],
                         "rain_prob": b["precip_prob"], "outdoor_ok": b["outdoor_ok"]} for b in d["blocks"]]}
            for d in w["days"]]
