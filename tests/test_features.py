"""Offline tests for weather, MCP web search, trending attractions, coupons and inbound tips.

Run:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["WEATHER"] = "off"
os.environ["WEB_SEARCH"] = "off"

import ada_client  # noqa: E402
import agents  # noqa: E402
import data  # noqa: E402
import mcp_client  # noqa: E402
import recommend  # noqa: E402
import tips  # noqa: E402
import weather  # noqa: E402
import websearch  # noqa: E402
from test_pipeline import FAMILY, TempMemory, intake_json, make_fake, run_plan  # noqa: E402

TODAY = date.today()


def rows(rain_hours=(), hot_hours=(), temp=22.0):
    """24 synthetic hourly rows."""
    return [{"hour": h, "temp": temp, "feels": 36.0 if h in hot_hours else temp, "prob": 85 if h in rain_hours else 10,
             "precip": 1.5 if h in rain_hours else 0.0, "code": 63 if h in rain_hours else 1, "wind": 10.0, "uv": 3.0}
            for h in range(24)]


def open_meteo_body(start: date, n_days: int, rain_hours=()):
    times, temp, prob, precip, code = [], [], [], [], []
    for i in range(n_days):
        for h in range(24):
            times.append(f"{(start + timedelta(days=i)).isoformat()}T{h:02d}:00")
            temp.append(20.0)
            prob.append(80 if h in rain_hours else 5)
            precip.append(2.0 if h in rain_hours else 0.0)
            code.append(61 if h in rain_hours else 0)
    n = len(times)
    return {"hourly": {"time": times, "temperature_2m": temp, "apparent_temperature": temp,
                       "precipitation_probability": prob, "precipitation": precip, "weather_code": code,
                       "wind_speed_10m": [8.0] * n, "uv_index": [4.0] * n}}


# ------------------------------------------------------------------ weather
class WeatherTests(unittest.TestCase):
    def test_blocks_flag_rain_and_heat(self):
        day = weather._day("2026-10-25", "forecast", rows(rain_hours=range(15, 18), hot_hours=range(12, 15)), None)
        ok = {b["key"]: b["outdoor_ok"] for b in day["blocks"]}
        self.assertEqual(ok, {"morning": True, "forenoon": True, "noon": False, "afternoon": False, "evening": True})
        self.assertIn("rain", day["blocks"][3]["tags"])
        self.assertIn("hot", day["blocks"][2]["tags"])
        self.assertTrue(any("伞" in t for t in day["tips"]))
        self.assertEqual(weather.block_at(day, "16:30")["key"], "afternoon")
        self.assertEqual(weather.block_at(day, "06:00")["key"], "morning")

    def test_light_drizzle_is_outdoor_ok_with_umbrella(self):
        r = rows()
        for x in r:
            if 10 <= x["hour"] < 12:
                x.update(code=51, prob=25, precip=0.1)
        block = weather._day("2026-10-25", "forecast", r, None)["blocks"][1]
        self.assertTrue(block["outdoor_ok"])
        self.assertIn("light_rain", block["tags"])
        self.assertIn("雨伞", block["advice"])

    def test_forecast_archive_and_demo_sources(self):
        start = TODAY + timedelta(days=14)
        req = {"destination": "杭州", "depart_date": start.isoformat(), "nights": 4}
        calls = []

        def fake_fetch(url, params):
            calls.append((url, params["start_date"], params["end_date"]))
            s = date.fromisoformat(params["start_date"])
            n = (date.fromisoformat(params["end_date"]) - s).days + 1
            return open_meteo_body(s, n)

        with mock.patch.dict(os.environ, {"WEATHER": "on"}), mock.patch.object(weather, "_fetch_json", fake_fetch):
            report = weather.weather_agent(req, today=TODAY)
        self.assertEqual([d["source"] for d in report["days"]], ["forecast", "forecast", "archive", "archive", "archive"])
        self.assertEqual(calls[0][0], weather.FORECAST_URL)
        self.assertEqual(calls[1][0], weather.ARCHIVE_URL)
        self.assertEqual(calls[1][1], weather._shift_year(start + timedelta(days=2), -1).isoformat())  # last year
        self.assertIn("去年同期", report["note"])

        def down(url, params):
            raise OSError("network down")

        with mock.patch.dict(os.environ, {"WEATHER": "on"}), mock.patch.object(weather, "_fetch_json", down):
            report = weather.weather_agent(req, today=TODAY)
        self.assertEqual(report["sources"], ["demo"])


class WeatherItineraryTests(TempMemory):
    def _plan(self, itinerary, weather_rows):
        req = intake_json("上海", "杭州", nights=2, trip_type="family", members=FAMILY, budget=None)

        def collect(city, dates, today):
            return {d.isoformat(): ("forecast", weather_rows(i)) for i, d in enumerate(dates)}

        with mock.patch.object(weather, "_collect", collect):
            return run_plan(make_fake(req, itinerary=itinerary))[0]

    @staticmethod
    def _itinerary_with(poi_name):
        def build(text):
            p = json.loads(text)
            pid = next(x["id"] for x in p["候选景点"] if x["name"] == poi_name)
            return {"title": "t", "summary": "", "tips": [], "days": [
                {"date": p["日期"][0], "items": []},
                {"date": p["日期"][1], "items": [{"time": "15:30", "type": "poi", "ref_id": pid, "title": poi_name}]},
                {"date": p["日期"][2], "items": []}]}
        return build

    def test_outdoor_poi_in_rain_is_swapped_for_indoor(self):
        result = self._plan(self._itinerary_with("西湖（游船+环湖）"), lambda i: rows(rain_hours=range(14, 19)) if i == 1 else rows())
        itin = result["itinerary"]
        item = next(i for i in itin["days"][1]["items"] if i["type"] == "poi")
        self.assertTrue(item["poi"]["indoor"])
        self.assertTrue(item.get("weather_swapped"))
        self.assertEqual(len(itin["weather_fixes"]), 1)
        self.assertIn("降雨", itin["weather_fixes"][0])
        self.assertFalse(item["weather"]["outdoor_ok"])
        self.assertEqual(itin["days"][1]["weather"]["source_label"], "实时预报")
        check = next(c for c in result["checks"] if c["rule"] == "天气适配")
        self.assertEqual(check["status"], "pass")

    def test_outdoor_poi_in_good_weather_is_kept(self):
        result = self._plan(self._itinerary_with("西湖（游船+环湖）"), lambda i: rows())
        item = next(i for i in result["itinerary"]["days"][1]["items"] if i["type"] == "poi")
        self.assertEqual(item["poi"]["name"], "西湖（游船+环湖）")
        self.assertEqual(result["itinerary"]["weather_fixes"], [])

    def test_fallback_itinerary_puts_indoor_first_on_rainy_day(self):
        def broken(text):
            raise ada_client.AdaError("bad")

        result = self._plan(broken, lambda i: rows(rain_hours=range(7, 21)))
        pois = [i["poi"] for d in result["itinerary"]["days"] for i in d["items"] if i["type"] == "poi"]
        self.assertTrue(pois and pois[0]["indoor"])


# ------------------------------------------------------------------ MCP & web search
EXA_TEXT = """Title: Shanghai 4-Day Family Itinerary
URL: https://example.com/shanghai-family
Published: 2026-05-01
Author: N/A
Highlights:
Sunrise stroll along The Bund. Dinosaur galleries at the Shanghai Natural History Museum.
...
Title: Bad entry without url
Highlights: nothing
Title: Disney tips
URL: https://example.com/disney
Published: N/A
Highlights:
Shanghai Disneyland with kids: arrive early."""

BOCHA_TEXT = """Title: 上海亲子游攻略
URL: https://example.cn/a
Description: 上海迪士尼乐园和上海自然博物馆最受欢迎
Published date: 2026-06-01T00:00:00
Site name: 示例"""


class _FakeMCP(BaseHTTPRequestHandler):
    sessions = set()

    def log_message(self, *a):
        pass

    def do_POST(self):
        msg = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        sid = self.headers.get("Mcp-Session-Id")
        if msg["method"] == "initialize":
            sid = f"s{len(self.sessions) + 1}"
            self.sessions.add(sid)
            return self._sse({"jsonrpc": "2.0", "id": msg["id"], "result": {"protocolVersion": "2025-03-26"}}, sid)
        if sid not in self.sessions:
            self.send_response(404)
            self.end_headers()
            return
        if msg["method"] == "notifications/initialized":
            self.send_response(202)
            self.end_headers()
            return
        args = msg["params"]["arguments"]
        text = EXA_TEXT if msg["params"]["name"] == "web_search_exa" else BOCHA_TEXT
        self._sse({"jsonrpc": "2.0", "id": msg["id"], "result": {"content": [{"type": "text", "text": text + f"\n<!--{args['query']}-->"}]}}, sid)

    def _sse(self, payload, sid):
        body = ("event: message\ndata: " + json.dumps({"jsonrpc": "2.0", "method": "notifications/progress"}) + "\n\n"
                "event: message\ndata: " + json.dumps(payload) + "\n\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Mcp-Session-Id", sid)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _FakeMCP)
        cls.url = f"http://127.0.0.1:{cls.httpd.server_address[1]}/mcp"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_mcp_client_sse_and_session_recovery(self):
        client = mcp_client.MCPClient(self.url)
        self.assertIn("Shanghai 4-Day", client.call_tool("web_search_exa", {"query": "q1"}))
        _FakeMCP.sessions.clear()  # server forgets the session → client must re-initialise
        self.assertIn("q2", client.call_tool("web_search_exa", {"query": "q2"}))

    def test_parsers(self):
        exa = websearch.parse_exa_text(EXA_TEXT)
        self.assertEqual([r["url"] for r in exa], ["https://example.com/shanghai-family", "https://example.com/disney"])
        self.assertEqual(exa[1]["published"], "")
        self.assertIn("Natural History Museum", exa[0]["snippet"])
        self.assertEqual(websearch.parse_bocha_text(BOCHA_TEXT)[0]["published"], "2026-06-01")
        body = {"code": 200, "data": {"webPages": {"value": [{"name": "A", "url": "https://x.cn", "summary": "s", "datePublished": "2026-01-02"},
                                                              {"name": "bad", "url": "javascript:alert(1)"}]}}}
        self.assertEqual([r["url"] for r in websearch.parse_bocha_json(body)], ["https://x.cn"])

    def test_search_all_via_mcp_with_dedupe_and_status(self):
        env = {"WEB_SEARCH": "on", "EXA_MCP_URL": self.url, "BOCHA_MCP_URL": self.url}
        with mock.patch.dict(os.environ, env), mock.patch.object(websearch, "_exa_client", None):
            websearch._cache.clear()
            results, st = websearch.search_all([("exa", "q1"), ("exa", "q1b"), ("bocha", "q2")])
        self.assertTrue(st["exa"]["ok"] and st["bocha"]["ok"])
        self.assertEqual(len({r["url"] for r in results}), len(results))  # de-duplicated
        self.assertEqual([r["n"] for r in results], list(range(1, len(results) + 1)))

    def test_bocha_not_configured_is_reported(self):
        with mock.patch.dict(os.environ, {"WEB_SEARCH": "on"}, clear=False):
            os.environ.pop("BOCHA_API_KEY", None)
            os.environ.pop("BOCHA_MCP_URL", None)
            with mock.patch.dict(websearch.PROVIDERS, {"exa": lambda q, c: [{"title": "t", "url": "https://a", "snippet": "", "published": ""}]}):
                websearch._cache.clear()
                results, st = websearch.search_all([("exa", "q"), ("bocha", "q")])
        self.assertTrue(st["exa"]["ok"])
        self.assertFalse(st["bocha"]["ok"])
        self.assertIn("BOCHA_API_KEY", st["bocha"]["error"])
        self.assertEqual(len(results), 1)


# ------------------------------------------------------------------ trending & coupons
def _req(trip_type="family", members=FAMILY, dest="杭州", inbound=False, language="zh"):
    origin = "北京" if dest == "上海" else "上海"
    fake = make_fake(intake_json(origin, dest, nights=2, trip_type=trip_type, members=members, budget=None,
                                 nationality="美国" if inbound else None, language=language))
    with mock.patch.object(ada_client, "complete_json", fake):
        req = agents.intake("x")
    return req, agents.constraint_agent(req)


class TrendingTests(unittest.TestCase):
    RESULTS = [
        {"n": 1, "provider": "Exa", "title": "Hangzhou family trip", "url": "https://e.com/1", "snippet": "West Lake boat tour, then Songcheng show", "published": ""},
        {"n": 2, "provider": "博查", "title": "杭州亲子游", "url": "https://b.cn/2", "snippet": "西湖、宋城、杭州动物园最受欢迎；还有河坊街", "published": ""},
    ]

    def test_web_based_ranking_validates_ids_and_sources(self):
        req, bundle = _req()
        llm = {"ranking": [{"poi_id": "P-HGH-5", "sources": [2, 99], "reason": "演出受欢迎"},
                           {"poi_id": "P-HGH-1", "sources": [1, 2], "reason": "必去"},
                           {"poi_id": "P-NOPE", "sources": [1]}],
               "others": [{"name": "河坊街", "sources": [2], "note": "老街"}, {"name": "编造地点", "sources": [7]}],
               "insights": ["先游西湖再看演出"]}
        with mock.patch.object(websearch, "search_all", return_value=(self.RESULTS, {"exa": {"name": "Exa", "ok": True}})), \
             mock.patch.object(ada_client, "complete_json", make_fake({}, trending=llm)):
            res = recommend.trending_agent(req, bundle)
        self.assertEqual(res["basis"], "web")
        names = [h["poi"]["name"] for h in res["hot"]]
        self.assertEqual(names[:2], ["宋城", "西湖（游船+环湖）"])
        songcheng = res["hot"][0]
        self.assertFalse(songcheng["allowed"])  # grandma's 2 km walking limit excludes 宋城 (2.5 km)
        self.assertIn("步行", songcheng["excluded_reason"])
        self.assertNotIn("P-HGH-5", res["hot_rank"])
        self.assertEqual([s["n"] for s in songcheng["sources"]], [2])  # invalid source 99 dropped
        self.assertEqual([o["name"] for o in res["others"]], ["河坊街"])
        self.assertEqual(res["insights"], ["先游西湖再看演出"])
        west = res["hot"][1]
        self.assertTrue(west["coupon"]["eligible"])
        self.assertEqual(west["coupon"]["saving_cny"], 10 * 3)  # ¥10/person × 3 paying (the 5-year-old is free)

    def test_builtin_fallback_without_results(self):
        req, bundle = _req()
        res = recommend.trending_agent(req, bundle)  # WEB_SEARCH=off
        self.assertEqual(res["basis"], "builtin")
        self.assertTrue(res["hot"])
        self.assertFalse(res["providers"]["exa"]["ok"])

    def test_coupon_eligibility(self):
        req, _ = _req(trip_type="leisure", members=[{"role": "我", "age": 30}], dest="上海")
        pois = {p["name"]: p for p in data.search_pois("上海")}
        self.assertIn("入境", recommend.coupon_offer(pois["东方明珠"], req)["ineligible_reason"])
        self.assertIn("家庭", recommend.coupon_offer(pois["上海迪士尼乐园"], req)["ineligible_reason"])
        nhm = recommend.coupon_offer(pois["上海自然博物馆"], req)
        self.assertTrue(nhm["eligible"])
        self.assertEqual(nhm["saving_cny"], 3)  # 10 % of ¥30
        self.assertEqual(nhm["label"], "门票 9 折")
        self.assertIsNone(recommend.coupon_offer(pois["外滩"], req))


# ------------------------------------------------------------------ inbound tips (cash & network)
class InboundTipsTests(TempMemory):
    def test_inbound_plan_has_cash_network_and_coupons(self):
        def itinerary(text):
            p = json.loads(text)
            ids = {x["name"]: x["id"] for x in p["候选景点"]}
            rests = {x["name"]: x["id"] for x in p["候选餐厅"]}
            noodle = next(v for k, v in rests.items() if "面馆" in k)
            return {"title": "t", "summary": "", "tips": [], "days": [
                {"date": p["日期"][0], "items": [{"time": "16:00", "type": "poi", "ref_id": ids["故宫博物院"], "title": "故宫"}]},
                {"date": p["日期"][1], "items": [{"time": "09:00", "type": "poi", "ref_id": ids["八达岭长城"], "title": "长城"},
                                                 {"time": "12:00", "type": "meal", "ref_id": noodle, "title": "面馆"}]},
                {"date": p["日期"][2], "items": []}]}

        req = intake_json("东京", "北京", depart_in=10, nights=2, trip_type="leisure",
                          members=[{"role": "me", "age": 40}, {"role": "wife", "age": 38}],
                          nationality="日本", language="ja", budget=None)
        # Pin dry weather: otherwise the date-dependent demo weather may swap the outdoor Palace Museum for an indoor sight.
        dry = lambda city, dates, today: {d.isoformat(): ("forecast", rows()) for d in dates}  # noqa: E731
        with mock.patch.object(weather, "_collect", dry):
            result, _ = run_plan(make_fake(req, itinerary=itinerary))
        cash = result["cash"]
        self.assertEqual(cash["total_cny"] % 50, 0)
        self.assertGreaterEqual(cash["total_cny"], 300)
        self.assertEqual(sum(d["note"] * d["count"] for d in cash["denominations"]), cash["total_cny"])
        places = [x["place"] for d in cash["breakdown"] for x in d["items"]]
        self.assertIn("八达岭长城", places)  # remote site
        self.assertTrue(any("面馆" in p for p in places))  # cash-only restaurant
        self.assertTrue(all(x["reason"] for d in cash["breakdown"] for x in d["items"]))
        self.assertEqual(cash["home_currency"], "JPY")

        net = result["network"]
        urls = [l["url"] for e in net["events"] for l in e["links"]] + [g["url"] for g in net["guides"]]
        self.assertTrue(urls and all(u.startswith("https://") and "trip.com/" in u for u in urls))
        self.assertTrue(any(u.startswith("https://jp.trip.com/") for u in urls))  # Japanese guides for a Japanese visitor
        self.assertTrue(any("八达岭" in e["place"] for e in net["events"]))
        self.assertEqual(result["payment_plan"]["cash_suggest_cny"], cash["total_cny"])

        coupons = {c["poi_name"]: c for c in result["cost"]["coupons"]}
        self.assertTrue(coupons["故宫博物院"]["eligible"])  # inbound-only coupon
        self.assertEqual(result["cost"]["coupon_savings_cny"], 20)
        self.assertEqual(result["cost"]["total_after_coupons_cny"], result["cost"]["total_cny"] - 20)

    def test_guide_links_fall_back_to_english(self):
        links = tips.guide_links(["esim", "visa_transit"], "ko")
        self.assertEqual([l["lang"] for l in links], ["en", "en"])


if __name__ == "__main__":
    unittest.main()
