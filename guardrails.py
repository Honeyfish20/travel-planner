"""Payment-safety guardrails (deterministic, run outside the model).

- find_sensitive: blocks questions containing card numbers (Luhn-valid) or
  CVV / password / PIN / verification codes, so they never reach the model.
- redact: scrubs the same data from model output; aggressive mode also hides
  any long digit run (phone numbers, passport-like numbers) for share content.
"""
from __future__ import annotations

import re
from typing import List

BLOCK_MESSAGE = ("为了你的资金安全，请不要发送银行卡号、CVV 安全码、支付密码或验证码，本助手不需要这些信息。"
                 " For your safety, never share card numbers, CVV, passwords or verification codes — this assistant never needs them.")

_CARD_RE = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")
_SECRET_RE = re.compile(
    r"(cvv2?|cvc|cvn|security code|安全码|支付密码|交易密码|验证码|密码|password|passcode|pin)\s*(?:码|号|是|为|:|：|=|is)?\s*\d{3,8}",
    re.IGNORECASE,
)
_LONG_DIGITS_RE = re.compile(r"(?<![\d.])\+?\d(?: ?\d){7,}(?![\d.])")


def _luhn_ok(digits: str) -> bool:
    total, double = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if double:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        double = not double
    return total % 10 == 0


def _is_card(match: str) -> bool:
    digits = re.sub(r"\D", "", match)
    return 13 <= len(digits) <= 19 and _luhn_ok(digits)


def find_sensitive(text: str) -> List[str]:
    reasons = []
    if any(_is_card(m.group(0)) for m in _CARD_RE.finditer(text)):
        reasons.append("疑似银行卡号 card number")
    if _SECRET_RE.search(text):
        reasons.append("疑似安全码或密码 CVV / password / code")
    return reasons


def redact_text(text: str, aggressive: bool = False) -> str:
    text = _SECRET_RE.sub("[敏感信息已隐藏]", text)
    if aggressive:  # share content: hide every long number (phone, passport, card)
        return _LONG_DIGITS_RE.sub("[号码已隐藏]", text)
    return _CARD_RE.sub(lambda m: "[卡号已隐藏]" if _is_card(m.group(0)) else m.group(0), text)


def redact(obj, aggressive: bool = False):
    """Recursively redact every string inside dicts / lists."""
    if isinstance(obj, str):
        return redact_text(obj, aggressive)
    if isinstance(obj, list):
        return [redact(v, aggressive) for v in obj]
    if isinstance(obj, dict):
        return {k: redact(v, aggressive) for k, v in obj.items()}
    return obj
