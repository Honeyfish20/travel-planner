"""Inbound-travel knowledge base (demo content).

Visa, payment and connectivity answers must come only from these entries, and
the UI shows each entry's source and update date. The content is illustrative:
before production, sync it from official sources and have it reviewed, because
these policies change often. Deliberately no fee percentages, transaction
limits or visa-free day counts — those must come from live official data.
"""
from __future__ import annotations

import json
from typing import Dict, Iterable, List, Optional

KB_UPDATED = "2026-10-01（演示）"

KNOWLEDGE: List[dict] = [
    {"id": "VISA-1", "topic": "visa", "title": "入境签证与免签政策",
     "content": "外国游客入境中国大陆一般需要办理签证；中国对部分国家实行单方面免签入境和过境免签政策。适用国家、可停留天数、可停留区域和入境口岸会调整，出行前请以国家移民管理局和中国驻当地使领馆的最新公告为准。",
     "source": "国家移民管理局", "url": "https://www.nia.gov.cn"},
    {"id": "VISA-2", "topic": "visa", "title": "过境免签的基本条件",
     "content": "过境免签要求持有效国际旅行证件，以及已确定日期和座位、前往第三国（地区）的联程客票，并从规定口岸入境、在规定区域内停留。从本国出发经中国大陆再返回本国，一般不属于过境。具体条件以国家移民管理局公告为准。",
     "source": "国家移民管理局", "url": "https://www.nia.gov.cn"},
    {"id": "STAY-1", "topic": "stay", "title": "外国人住宿登记",
     "content": "外国人入住酒店时，由酒店办理住宿登记。住在亲友家等非酒店住所时，需在抵达后 24 小时内（农村地区 72 小时内）到当地公安机关办理住宿登记。",
     "source": "《中华人民共和国出境入境管理法》", "url": None},
    {"id": "PAY-1", "topic": "payment", "title": "开通支付宝",
     "content": "建议入境前下载支付宝，用手机号注册，按提示完成护照实名认证，并绑定境外 Visa、Mastercard 等银行卡，之后可以在多数商户扫码付款。出发前完成开通，并试付一笔小额。",
     "source": "支付宝官方 App 与公告", "url": None},
    {"id": "PAY-2", "topic": "payment", "title": "开通微信支付",
     "content": "建议入境前下载微信并注册，在“我 → 服务 → 钱包”中绑定境外银行卡并完成实名认证，之后可以扫码付款。",
     "source": "微信支付官方 App 与公告", "url": None},
    {"id": "PAY-3", "topic": "payment", "title": "手续费、限额与提前预付",
     "content": "使用境外银行卡付款时，单笔超过一定金额可能收取手续费，单笔和累计金额也有限额，具体以支付宝、微信支付 App 内展示和官方公告为准。酒店、交通、门票、包车等大额项目，建议提前在携程用境外银行卡预付，减少现场付款。",
     "source": "支付宝、微信支付官方公告；携程预订规则", "url": None},
    {"id": "PAY-4", "topic": "payment", "title": "准备少量现金",
     "content": "大多数商户支持扫码付款，但个别小摊、出租车或偏远地区可能只收现金，建议准备少量人民币现金。机场和主要银行的 ATM 通常支持境外银行卡取现，可能收取手续费。",
     "source": "携程入境游服务指引", "url": None},
    {"id": "PAY-5", "topic": "payment", "title": "绑卡或付款失败怎么办",
     "content": "常见原因：银行卡未开通境外或网上交易、发卡行风控拦截、需要短信或 3D 安全验证、实名信息与护照不一致。可以依次尝试：在银行 App 中开通境外交易并确认卡未冻结；按提示完成验证；核对姓名与护照完全一致；换一张其他卡组织的银行卡；联系发卡行解除拦截；暂时改用现金，或在携程预付。",
     "source": "携程入境游服务指引", "url": None},
    {"id": "PAY-6", "topic": "payment", "title": "支付安全",
     "content": "任何情况下都不要把银行卡号、CVV 安全码、支付密码或短信验证码告诉他人或 AI 助手。携程客服和本助手都不会索要这些信息。",
     "source": "携程安全提示", "url": None},
    {"id": "NET-1", "topic": "connectivity", "title": "手机网络",
     "content": "出发前开通本国运营商的国际漫游，或购买支持中国大陆的旅行 eSIM（先确认手机支持 eSIM）。抵达后连接酒店或机场 Wi-Fi 时，部分境外应用可能无法正常使用。",
     "source": "携程入境游服务指引", "url": None},
    {"id": "NET-2", "topic": "connectivity", "title": "离线准备",
     "content": "入境前下载离线翻译包，把酒店中英文地址卡、电子票和行程保存到手机本地。携程的行程、订单和求助卡在境内网络下可以正常使用。",
     "source": "携程入境游服务指引", "url": None},
    {"id": "NET-3", "topic": "connectivity", "title": "分享照片和游记",
     "content": "分享照片和游记时，使用手机系统自带的分享功能，通过你自己的网络发布到常用的社交平台；也可以生成链接或图片，分享给在中国的同伴。",
     "source": "携程入境游服务指引", "url": None},
    {"id": "DOC-1", "topic": "documents", "title": "随身携带护照",
     "content": "入住酒店、购买和乘坐火车、进入部分景点都需要出示护照，请随身携带。火车票实行实名制，用护照购票，进站时出示护照。",
     "source": "中国铁路实名制购票规定", "url": None},
    {"id": "TAXI-1", "topic": "transport", "title": "打车",
     "content": "主要城市可以使用打车 App，部分 App 提供英文界面并支持境外银行卡，以 App 内实际支持为准。上车后可以把酒店中文地址卡给司机看。",
     "source": "携程入境游服务指引", "url": None},
    {"id": "EMG-1", "topic": "emergency", "title": "紧急求助",
     "content": "在中国大陆，报警拨打 110，急救拨打 120，火警拨打 119。护照遗失等问题，请联系本国驻华使领馆。",
     "source": "中国大陆紧急电话", "url": None},
]
_EN = {
    "VISA-1": "Foreign visitors usually need a visa to enter mainland China. China offers unilateral visa-free entry and visa-free transit for some countries. Eligible countries, length of stay, permitted areas and ports of entry change, so check the latest notices from the National Immigration Administration and the Chinese embassy or consulate before you travel.",
    "VISA-2": "Visa-free transit requires a valid travel document and a confirmed onward ticket (date and seat) to a third country or region, entry through a designated port, and staying within the permitted area. Travelling from your home country through mainland China and back home is generally not transit. See National Immigration Administration notices for details.",
    "STAY-1": "Hotels register foreign guests at check-in. If you stay with friends or family instead, register with the local police within 24 hours of arrival (72 hours in rural areas).",
    "PAY-1": "Before arrival, download Alipay, register with your phone number, verify your identity with your passport and link a foreign Visa or Mastercard card. You can then pay by scanning QR codes at most merchants. Finish setup before you leave and try a small test payment.",
    "PAY-2": "Before arrival, download WeChat and register, then go to Me → Services → Wallet to link a foreign bank card and verify your identity. You can then pay by scanning QR codes.",
    "PAY-3": "Paying with a foreign card may incur a fee above a certain amount, and there are per-transaction and cumulative limits; see the Alipay and WeChat Pay apps and official notices. Prepay large items such as hotels, transport, tickets and private cars on Trip.com with your foreign card to reduce on-site payments.",
    "PAY-4": "Most merchants accept QR-code payments, but some street stalls, taxis or remote areas may accept cash only, so carry a small amount of RMB cash. ATMs at airports and major banks usually accept foreign cards, possibly with a fee.",
    "PAY-5": "Common causes: the card is not enabled for overseas or online transactions, the issuer's fraud check blocked it, SMS or 3-D Secure verification is required, or your name does not match your passport. Try in order: enable overseas transactions in your bank app and make sure the card is not frozen; complete the verification; check the name matches your passport exactly; try a card from another network; contact your card issuer to lift the block; meanwhile use cash or prepay on Trip.com.",
    "PAY-6": "Never share your card number, CVV, payment password or verification codes with anyone, including AI assistants. Trip.com customer service and this assistant will never ask for them.",
    "NET-1": "Before you leave, turn on international roaming with your home carrier or buy a travel eSIM that covers mainland China (check that your phone supports eSIM). On hotel or airport Wi-Fi some overseas apps may not work properly.",
    "NET-2": "Before arrival, download offline translation packs and save your hotel address card (Chinese and English), e-tickets and itinerary on your phone. Trip.com itineraries, orders and help cards work on local networks in China.",
    "NET-3": "To share photos and travel notes, use your phone's built-in share sheet and post through your own network to your usual social platforms. You can also create a link or image to share with companions in China.",
    "DOC-1": "Carry your passport: you need it to check in at hotels, buy and board trains and enter some attractions. Train tickets are real-name: buy them with your passport and show it at the station.",
    "TAXI-1": "Ride-hailing apps work in major cities; some offer an English interface and accept foreign cards, depending on the app. Show the driver your hotel's Chinese address card.",
    "EMG-1": "In mainland China call 110 for police, 120 for an ambulance and 119 for fire. For a lost passport, contact your country's embassy or consulate in China.",
}
for _k in KNOWLEDGE:
    _k["en"] = _EN[_k["id"]]
_BY_ID = {k["id"]: k for k in KNOWLEDGE}

OUT_OF_SCOPE = {
    "zh": "知识库中没有这个问题的可靠信息，请查询官方渠道或联系携程客服。",
    "en": "The knowledge base has no verified information on this. Please check official sources or contact Trip.com customer service.",
    "ja": "ナレッジベースに確認済みの情報がありません。公式情報をご確認いただくか、Trip.com カスタマーサービスにお問い合わせください。",
    "ko": "지식 베이스에 확인된 정보가 없습니다. 공식 채널을 확인하시거나 Trip.com 고객센터에 문의해 주세요.",
}


def kb_for_prompt(topics: Optional[Iterable[str]] = None) -> str:
    wanted = set(topics) if topics else None
    rows = [{"id": k["id"], "title": k["title"], "content": k["content"]} for k in KNOWLEDGE if wanted is None or k["topic"] in wanted]
    return json.dumps(rows, ensure_ascii=False, indent=1)


def valid_sources(ids) -> List[dict]:
    """Resolve cited ids to source records; unknown ids are dropped."""
    out, seen = [], set()
    for i in ids if isinstance(ids, list) else []:
        k = _BY_ID.get(str(i))
        if k and k["id"] not in seen:
            seen.add(k["id"])
            out.append({"id": k["id"], "title": k["title"], "source": k["source"], "url": k["url"], "updated": KB_UPDATED})
    return out


# ------------------------------------------------------------------ currency (demo rates)
FX_NOTE = "演示汇率，仅供估算 Demo rates, estimates only"
FX_DEMO: Dict[str, float] = {  # 1 unit of currency = x CNY
    "CNY": 1.0, "USD": 7.1, "EUR": 7.7, "GBP": 9.0, "JPY": 0.047, "KRW": 0.0052,
    "SGD": 5.4, "HKD": 0.91, "AUD": 4.7, "CAD": 5.2,
}


def to_cny(amount: float, currency: str) -> float:
    return amount * FX_DEMO.get(currency, 1.0)


def from_cny(amount_cny: float, currency: str) -> float:
    rate = FX_DEMO.get(currency, 1.0)
    return round(amount_cny / rate, 0 if currency in ("JPY", "KRW") else 2)


# ------------------------------------------------------------------ bilingual cards (fixed text)
PAYMENT_PHRASES = [
    {"zh": "请问可以用境外银行卡付款吗？", "en": "Can I pay with a foreign bank card?"},
    {"zh": "我用支付宝 / 微信扫码付款。", "en": "I'll pay by scanning with Alipay / WeChat Pay."},
    {"zh": "请出示收款码，我来扫。", "en": "Please show me your payment QR code and I'll scan it."},
    {"zh": "付款没有成功，可以用现金吗？", "en": "The payment failed. Can I pay in cash?"},
    {"zh": "请给我开一张小票，谢谢。", "en": "Could I have a receipt, please?"},
]

EMERGENCY_CARD = {
    "title": "紧急求助卡 Emergency card",
    "zh": "我需要帮助。报警 110 · 急救 120 · 火警 119。请帮我联系我国驻华使领馆。",
    "en": "I need help. Police 110 · Ambulance 120 · Fire 119. Please help me contact my embassy or consulate.",
}
