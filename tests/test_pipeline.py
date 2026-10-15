"""Offline tests: the Ada model is replaced by a deterministic fake.

Run:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["WEATHER"] = "off"      # deterministic demo weather, no network
os.environ["WEB_SEARCH"] = "off"   # no Exa / Bocha calls

import ada_client  # noqa: E402
import agents  # noqa: E402
import constraints  # noqa: E402
import data  # noqa: E402
import guardrails  # noqa: E402
import memory  # noqa: E402
import orchestrator  # noqa: E402
import server  # noqa: E402

TODAY = date.today()


def _ids(text: str, prefix: str):
    return re.findall(r'"id": "(' + re.escape(prefix) + r'[^"]*)"', text)


def make_fake(intake: dict, itinerary=None, inbound=None, bad_ids=False, ask=None, share=None, receipt=None, calls=None, trending=None):
    """Fake Ada: answers per ROLE; picks the cheapest-listed candidate ids."""

    def fake(system: str, content, max_tokens: int = 1024) -> dict:
        role = re.search(r"ROLE: (\w+)", system).group(1)
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        if calls is not None:
            calls.append(role)
        if role == "intake":
            return intake
        if bad_ids and role in ("transport", "hotel", "ground"):
            return {"outbound_id": "X", "return_id": "Y", "hotel_id": "Z", "arrival_transfer_id": "Q", "departure_transfer_id": "Q", "reason": "测试"}
        if role == "transport":
            out_part, back_part = text.split("返程候选")
            return {"outbound_id": re.findall(r'"id": "([^"]+)"', out_part.split("去程候选")[1])[0],
                    "return_id": re.findall(r'"id": "([^"]+)"', back_part)[0], "reason": "测试"}
        if role == "hotel":
            return {"hotel_id": _ids(text, "H-")[0], "reason": "测试"}
        if role == "ground":
            t = _ids(text, "T-")
            return {"arrival_transfer_id": t[-1], "departure_transfer_id": t[-1], "reason": "测试"}
        if role == "inbound":
            return inbound or {"visa_note": "请查询官方公告", "visa_source_ids": ["VISA-1"],
                               "checklist": [{"phase": "before", "task": "开通支付宝", "source_ids": ["PAY-1"]},
                                             {"phase": "before", "task": "编造的政策", "source_ids": ["FAKE-9"]}]}
        if role == "itinerary":
            if itinerary is not None:
                return itinerary(text)
            payload = json.loads(text)
            pois = [p["id"] for p in payload["候选景点"]]
            rests = [r["id"] for r in payload["候选餐厅"]]
            days = []
            for k, d in enumerate(payload["日期"]):
                items = [{"time": "12:00", "type": "meal", "ref_id": rests[0] if rests else None, "title": "午餐", "detail": ""}]
                if k < len(pois):
                    items.append({"time": "09:30", "type": "poi", "ref_id": pois[k], "title": "景点", "detail": ""})
                days.append({"date": d, "items": items})
            return {"title": "测试行程", "summary": "摘要", "days": days, "tips": ["提醒"]}
        if role == "ask":
            return ask or {"answer": "请在银行 App 开通境外交易。", "source_ids": ["PAY-5"], "in_scope": True}
        if role == "trending":
            return trending or {"ranking": [], "others": [], "insights": []}
        if role == "share":
            return share or {"title": "Trip", "post": "Great trip! Call me at +1 555 0100 1234", "caption": "Hi", "hashtags": ["China Trip", "#travel"]}
        if role == "receipt":
            return receipt or {"is_receipt": True, "merchant": "老王面馆", "merchant_translated": "Lao Wang Noodles", "date": "2026-10-20",
                               "currency": "CNY", "items": [{"name": "牛肉面", "name_translated": "Beef noodles", "amount": 38}], "total": 38, "category": "餐饮"}
        raise AssertionError(role)

    return fake


def intake_json(origin="上海", dest="新加坡", depart_in=10, nights=3, trip_type="business", members=None,
                described=True, budget=15000, currency="CNY", nationality=None, language="zh", pace="normal"):
    depart = TODAY + timedelta(days=depart_in)
    return {"trip_type": trip_type, "origin": origin, "destination": dest, "depart_date": depart.isoformat(),
            "return_date": (depart + timedelta(days=nights)).isoformat(), "travelers": len(members or [1]),
            "members_described": described, "members": members or [{"role": "我", "age": 35}],
            "purpose": "测试出行", "preferences": [], "pace": pace, "budget_amount": budget, "budget_currency": currency,
            "nationality": nationality, "language": language}


FAMILY = [
    {"role": "我", "age": 36}, {"role": "妻子", "age": 34},
    {"role": "孩子", "age": 5, "allergies": ["花生"]},
    {"role": "奶奶", "age": 70, "mobility": "limited", "max_walk_km": 2},
]


def run_plan(fake, profile_id=None):
    events = []
    with mock.patch.object(ada_client, "complete_json", fake):
        result = orchestrator.plan("测试需求", events.append, profile_id)
    return result, events


class TempMemory(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patch = mock.patch.object(memory, "MEMORY_DIR", Path(self._tmp.name))
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()


# ------------------------------------------------------------------ data & rules
class DataTests(unittest.TestCase):
    def test_normalize_city(self):
        self.assertEqual(data.normalize_city("上海市"), "上海")
        self.assertEqual(data.normalize_city("Hangzhou"), "杭州")
        self.assertEqual(data.normalize_city("香港特别行政区"), "香港")
        self.assertEqual(data.normalize_city("東京"), "东京")
        self.assertEqual(data.normalize_city("서울"), "首尔")
        self.assertIsNone(data.normalize_city("火星"))

    def test_multilingual_allergens(self):
        self.assertEqual(data.normalize_allergies(["卵"])[0], ["鸡蛋"])
        self.assertEqual(data.normalize_allergies(["땅콩"])[0], ["花生"])

    def test_short_route_has_rail_only(self):
        d = TODAY + timedelta(days=5)
        self.assertEqual(data.search_flights("上海", "杭州", d), [])
        self.assertTrue(data.search_rail("上海", "杭州", d))
        self.assertEqual(data.search_rail("上海", "新加坡", d), [])

    def test_allergy_normalization(self):
        found, unknown = data.normalize_allergies(["花生酱", "Shellfish", "芒果"])
        self.assertEqual(found, ["花生", "贝类"])  # shellfish must not also match fish
        self.assertEqual(unknown, ["芒果"])

    def test_age_pricing(self):
        flight = {"mode": "flight", "price_cny": 1000}
        rail = {"mode": "rail", "price_cny": 100}
        self.assertEqual(data.transport_fare(flight, 1, True), 100)
        self.assertEqual(data.transport_fare(flight, 8, True), 500)
        self.assertEqual(data.transport_fare(flight, 8, False), 750)
        self.assertEqual(data.transport_fare(rail, 4, True), 0)
        self.assertEqual(data.transport_fare(rail, 10, True), 50)
        poi = {"price_adult": 100, "price_child": 50, "price_senior": 30}
        self.assertEqual([data.poi_price(poi, a) for a in (3, 10, 40, 70)], [0, 50, 100, 30])


class GuardrailTests(unittest.TestCase):
    def test_detects_card_and_secrets(self):
        self.assertTrue(guardrails.find_sensitive("my card is 4111 1111 1111 1111"))
        self.assertTrue(guardrails.find_sensitive("CVV 123"))
        self.assertTrue(guardrails.find_sensitive("支付密码是 654321"))
        self.assertEqual(guardrails.find_sensitive("预算 15000 元，订单 1234567890123456"), [])  # not Luhn-valid

    def test_redact(self):
        self.assertNotIn("4111", guardrails.redact_text("card 4111-1111-1111-1111"))
        self.assertIn("[号码已隐藏]", guardrails.redact_text("call +86 138 1234 5678", aggressive=True))


class ConstraintTests(unittest.TestCase):
    def test_toddler_excludes_long_walk_and_no_stroller(self):
        req = {"members": [agents._norm_member({"role": "我", "age": 33}, 0), agents._norm_member({"role": "宝宝", "age": 1}, 1)],
               "is_business": False, "is_family": True, "is_inbound": False, "pace": "normal"}
        cons = constraints.derive(req)
        _, excluded = constraints.filter_pois(data.search_pois("上海"), cons)
        names = {e["name"] for e in excluded}
        self.assertIn("上海迪士尼乐园", names)  # 8 km walk > 5 km stroller limit
        self.assertIn("豫园", names)  # not stroller friendly
        self.assertEqual(cons["max_pois"], 2)
        self.assertEqual(cons["nap_window"], constraints.NAP_WINDOW)


# ------------------------------------------------------------------ pipeline
class PipelineTests(TempMemory):
    def test_business_trip(self):
        result, events = run_plan(make_fake(intake_json()))
        self.assertIsNotNone(result, events[-1])
        done = {e["agent"] for e in events if e["type"] == "step" and e["status"] in ("done", "skipped")}
        self.assertEqual(done, {"intake", "constraints", "transport", "hotel", "ground", "inbound", "weather", "trending", "itinerary", "check"})
        self.assertEqual(result["weather"]["sources"], ["demo"])
        self.assertEqual(result["trending"]["basis"], "builtin")
        self.assertIsNone(result["cash"])  # cash advice is for inbound visitors only
        self.assertIsNone(result["inbound"])
        out = result["transport"]["outbound"]
        self.assertEqual(out["cabin"], "经济舱")  # < 6 h: no business class
        self.assertGreaterEqual(int(out["arrive"][11:13]), 6)  # red-eye arrivals filtered
        rules = {c["rule"] for c in result["checks"]}
        self.assertIn("提前预订", rules)
        self.assertEqual(result["cost"]["total_cny"], sum(i["amount"] for i in result["cost"]["items"]))

    def test_family_trip_enforces_constraints(self):
        def itinerary(text):
            p = json.loads(text)
            pois = [x["id"] for x in p["候选景点"]]
            # candidates after filtering (grandma walks ≤ 2 km): 西湖, 灵隐寺, 自然博物院, 西溪
            return {"title": "家庭游", "summary": "", "tips": [], "days": [
                {"date": p["日期"][0], "items": [
                    {"time": "15:00", "type": "poi", "ref_id": pois[0], "title": "A"},
                    {"time": "17:00", "type": "poi", "ref_id": pois[3], "title": "D"},          # arrival day allows 1
                ]},
                {"date": p["日期"][1], "items": [
                    {"time": "09:00", "type": "poi", "ref_id": pois[1], "title": "B"},
                    {"time": "15:00", "type": "poi", "ref_id": pois[2], "title": "C"},          # 2.0 + 1.5 km > 2 km
                    {"time": "12:00", "type": "meal", "ref_id": "R-HGH-1", "title": "家常菜馆"},  # contains peanuts
                    {"time": "16:00", "type": "poi", "ref_id": "P-XXX-9", "title": "编造景点"},  # not a candidate
                ]},
                {"date": p["日期"][2], "items": [{"time": "10:00", "type": "poi", "ref_id": pois[0], "title": "A 重复"}]},
            ]}

        fake = make_fake(intake_json("上海", "杭州", nights=2, trip_type="family", members=FAMILY, budget=None), itinerary=itinerary)
        result, _ = run_plan(fake)
        self.assertEqual(result["transport"]["outbound"]["mode"], "rail")  # 165 km: no flights
        self.assertEqual(result["hotel"]["room_type"], "家庭房")
        self.assertTrue(result["ground"]["arrival"]["child_seat"])
        cons = result["constraints"]["constraints"]
        self.assertEqual(cons["allergens"], ["花生"])
        self.assertEqual(cons["max_pois"], 3)
        self.assertEqual(cons["max_walk_km"], 2)
        fixes = result["itinerary"]["fixes"]
        self.assertEqual(len(fixes), 5, fixes)  # cap, walking, peanut restaurant, invented POI, duplicate
        self.assertTrue(all(d["walk_km"] <= 2 for d in result["itinerary"]["days"]))
        walk = next(c for c in result["checks"] if c["rule"] == "每日步行")
        self.assertEqual(walk["status"], "pass")
        used_rests = [i["ref_id"] for d in result["itinerary"]["days"] for i in d["items"] if i["type"] == "meal"]
        self.assertNotIn("R-HGH-1", used_rests)
        excluded = {e["id"] for e in result["constraints"]["restaurants_excluded"]}
        self.assertIn("R-HGH-1", excluded)
        diet = next(c for c in result["checks"] if c["rule"] == "过敏与饮食")
        self.assertEqual(diet["status"], "pass")
        self.assertFalse(result["needs_approval"])  # approval is a business-only concept
        self.assertTrue(result["constraints"]["diet_cards"])
        # The 5-year-old rides high-speed rail free; grandma pays full fare.
        per = {p["member"]: p["transport"] for p in result["cost"]["per_member"]}
        self.assertEqual(per["孩子（5 岁）"], 0)

    def test_invalid_model_ids_fall_back(self):
        result, _ = run_plan(make_fake(intake_json(), bad_ids=True))
        self.assertIn("回退", result["transport"]["reason"])
        self.assertTrue(result["hotel"]["hotel"]["preferred"])

    def test_inbound_trip_grounding_and_payment_plan(self):
        fake = make_fake(intake_json("东京", "北京", depart_in=20, nights=3, trip_type="leisure",
                                     members=[{"role": "me", "age": 40}, {"role": "wife", "age": 38}],
                                     budget=3000, currency="USD", nationality="日本", language="ja"))
        result, _ = run_plan(fake)
        req = result["request"]
        self.assertTrue(req["is_inbound"])
        self.assertEqual(req["home_currency"], "JPY")
        self.assertEqual(req["budget_cny"], round(3000 * 7.1))
        inbound = result["inbound"]
        self.assertEqual([c["task"] for c in inbound["checklist"]], ["开通支付宝"])  # ungrounded item dropped
        self.assertTrue(inbound["payment_phrases"])
        self.assertTrue(result["hotel"]["hotel"]["english_service"])
        pp = result["payment_plan"]
        self.assertGreater(pp["prepay_total"], 0)
        self.assertGreaterEqual(pp["cash_suggest_cny"], 300)
        self.assertIsNotNone(result["cost"]["total_home"])

    def test_inbound_fallback_is_english(self):
        def broken_inbound(system, content, max_tokens=1024):
            if "ROLE: inbound" in system:
                raise ada_client.AdaError("truncated")
            return base(system, content, max_tokens)

        base = make_fake(intake_json("首尔", "上海", depart_in=20, nights=2, trip_type="leisure",
                                     members=[{"role": "me", "age": 30}], nationality="韩国", language="en"))
        result, _ = run_plan(broken_inbound)
        tasks = [c["task"] for c in result["inbound"]["checklist"]]
        self.assertTrue(tasks and all(t.isascii() or "→" in t for t in tasks), tasks)
        self.assertTrue(all(c["sources"] for c in result["inbound"]["checklist"]))
        self.assertEqual(result["request"]["home_currency"], "KRW")

    def test_multi_family_cost_split(self):
        members = [{"role": "我", "age": 40, "group": "我家"}, {"role": "孩子", "age": 8, "group": "我家"},
                   {"role": "王先生", "age": 41, "group": "王家"}, {"role": "王太太", "age": 39, "group": "王家"}]
        result, _ = run_plan(make_fake(intake_json("北京", "西安", nights=2, trip_type="family", members=members, budget=None)))
        split = result["cost"]["split"]
        self.assertEqual({s["group"] for s in split}, {"我家", "王家"})
        self.assertEqual(sum(s["total"] for s in split), result["cost"]["total_cny"])

    def test_memory_carries_family_over(self):
        first = make_fake(intake_json("上海", "杭州", nights=2, trip_type="family", members=FAMILY, budget=None))
        run_plan(first, profile_id="zhang-family")
        self.assertEqual(len(memory.get_profile("zhang-family")["members"]), 4)
        second = make_fake(intake_json("上海", "北京", nights=3, trip_type="family", members=[], described=False, budget=None))
        result, _ = run_plan(second, profile_id="zhang-family")
        req = result["request"]
        self.assertEqual(req["party_size"], 4)
        self.assertIn("档案", req["memory_note"])
        self.assertEqual(result["constraints"]["constraints"]["allergens"], ["花生"])

    def test_unknown_city_reports_error(self):
        result, events = run_plan(make_fake(intake_json(dest="火星")))
        self.assertIsNone(result)
        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("火星", events[-1]["message"])

    def test_itinerary_fallback_respects_caps(self):
        def broken(text):
            raise ada_client.AdaError("bad json")

        fake = make_fake(intake_json("上海", "杭州", nights=3, trip_type="family", members=FAMILY, budget=None), itinerary=broken)
        result, _ = run_plan(fake)
        itin = result["itinerary"]
        self.assertEqual(itin["generated_by"], "fallback")
        self.assertEqual(itin["fixes"], [])
        self.assertTrue(all(d["poi_count"] <= 3 for d in itin["days"]))


# ------------------------------------------------------------------ on-demand agents
class OnDemandTests(unittest.TestCase):
    def test_ask_blocks_sensitive_without_calling_model(self):
        calls = []
        with mock.patch.object(ada_client, "complete_json", make_fake({}, calls=calls)):
            res = agents.ask_agent("My card 4111 1111 1111 1111 was declined", "en")
        self.assertTrue(res["blocked"])
        self.assertEqual(calls, [])

    def test_ask_requires_valid_sources(self):
        with mock.patch.object(ada_client, "complete_json", make_fake({})):
            ok = agents.ask_agent("card declined?", "en")
        self.assertTrue(ok["in_scope"])
        self.assertEqual(ok["sources"][0]["id"], "PAY-5")
        bad = make_fake({}, ask={"answer": "免签 30 天", "source_ids": ["NOPE"], "in_scope": True})
        with mock.patch.object(ada_client, "complete_json", bad):
            res = agents.ask_agent("visa free days?", "en")
        self.assertFalse(res["in_scope"])
        self.assertNotIn("30", res["answer"])

    def test_receipt(self):
        img = base64.b64encode(b"\x89PNG fake").decode()
        with mock.patch.object(ada_client, "complete_json", make_fake({})):
            res = agents.receipt_agent(img, "image/png", "en", "USD")
        self.assertEqual(res["total_cny"], 38)
        self.assertEqual(res["total_home"], round(38 / 7.1, 2))
        with self.assertRaises(agents.PlanningError):
            agents.receipt_agent(img, "application/pdf")
        with self.assertRaises(agents.PlanningError):
            agents.receipt_agent("not base64!!", "image/png")


# ------------------------------------------------------------------ server
class ServerTests(TempMemory):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.make_server("127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    def _stream(self, q, profile=""):
        url = self.base + "/api/plan/stream?q=" + urllib.parse.quote(q) + "&profile=" + urllib.parse.quote(profile)
        with urllib.request.urlopen(url, timeout=30) as r:
            return [json.loads(line[6:]) for line in r.read().decode().splitlines() if line.startswith("data: ")]

    def test_index_and_health(self):
        with urllib.request.urlopen(self.base + "/") as r:
            page = r.read().decode()
        self.assertIn("行程规划", page)
        self.assertIn('class="lang-btn"', page)
        for path, marker in (("/i18n.js", "const I18N"), ("/app.js", "function renderResult")):
            with urllib.request.urlopen(self.base + path) as r:
                self.assertTrue(r.headers["Content-Type"].startswith("text/javascript"))
                self.assertIn(marker, r.read().decode())
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.base + "/server.py")
        self.assertEqual(ctx.exception.code, 404)
        with urllib.request.urlopen(self.base + "/api/health") as r:
            self.assertTrue(json.loads(r.read())["ok"])

    def test_stream_share_and_profile(self):
        fake = make_fake(intake_json("上海", "杭州", nights=2, trip_type="family", members=FAMILY, budget=None))
        with mock.patch.object(ada_client, "complete_json", fake):
            events = self._stream("带孩子和奶奶去杭州", "test-fam")
            self.assertEqual(events[-1]["type"], "result")
            plan_id = events[-1]["data"]["plan_id"]
            share = self._post("/api/share", {"plan_id": plan_id, "language": "en"})
        self.assertNotIn("+1 555 0100 1234", share["post"])
        self.assertEqual(share["hashtags"][0], "#ChinaTrip")
        with urllib.request.urlopen(self.base + "/api/profile?id=test-fam") as r:
            self.assertEqual(len(json.loads(r.read())["profile"]["members"]), 4)
        req = urllib.request.Request(self.base + "/api/profile?id=test-fam", method="DELETE")
        with urllib.request.urlopen(req) as r:
            self.assertTrue(json.loads(r.read())["deleted"])

    def test_ask_and_receipt_endpoints(self):
        with mock.patch.object(ada_client, "complete_json", make_fake({})):
            ask = self._post("/api/ask", {"question": "card declined", "language": "en"})
            rec = self._post("/api/receipt", {"image_b64": base64.b64encode(b"img").decode(), "media_type": "image/jpeg", "language": "en", "home_currency": "EUR"})
        self.assertTrue(ask["in_scope"])
        self.assertEqual(rec["home_currency"], "EUR")

    def test_bad_requests(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.base + "/api/plan/stream?q=")
        self.assertEqual(ctx.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.base + "/api/profile?id=" + urllib.parse.quote("../etc"))
        self.assertEqual(ctx.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post("/api/share", {"plan_id": "missing"})
        self.assertEqual(ctx.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post("/api/receipt", {"image_b64": "x", "media_type": "text/html"})
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
