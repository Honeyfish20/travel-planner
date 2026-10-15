"""LLM client for an Anthropic-compatible Messages API.

Configured entirely through environment variables:
    ADA_TOKEN      API key (sent as the x-api-key header)          — required
    ADA_BASE_URL   gateway base URL; unset = Anthropic's public API — optional
    ADA_MODEL      model id                                         — optional

Request: POST {ADA_BASE_URL}/v1/messages with anthropic-version: 2023-06-01.

Notes:
- Some gateways reject `temperature` for newer models, so it is never sent.
- `content` may be a plain string or a list of Anthropic content blocks
  (e.g. an image block plus a text block for receipt recognition).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import List, Optional, Union

import anthropic

logger = logging.getLogger(__name__)

ADA_BASE_URL = os.environ.get("ADA_BASE_URL") or None  # None → SDK default (api.anthropic.com)
ADA_MODEL = os.environ.get("ADA_MODEL", "claude-sonnet-5")
ADA_VERSION = os.environ.get("ADA_ANTHROPIC_VERSION", "2023-06-01")
ADA_TIMEOUT = float(os.environ.get("ADA_TIMEOUT", "120"))
# claude-sonnet-5 may think adaptively; thinking tokens count against
# max_tokens and can leave no room for the JSON answer. Every call here is a
# short structured choice, so thinking is disabled by default (also ~3x faster).
# Set ADA_THINKING=adaptive to let the model decide.
ADA_THINKING = os.environ.get("ADA_THINKING", "disabled")

Content = Union[str, List[dict]]


class AdaError(RuntimeError):
    """Raised for Ada configuration problems or unusable model output."""


_client: Optional[anthropic.Anthropic] = None
_client_lock = threading.Lock()


def get_client() -> anthropic.Anthropic:
    """Return a shared Anthropic SDK client pointed at the configured gateway."""
    global _client
    with _client_lock:
        if _client is None:
            token = os.environ.get("ADA_TOKEN")
            if not token:
                raise AdaError("ADA_TOKEN 未设置：请先执行 export ADA_TOKEN=<your-ada-token>")
            _client = anthropic.Anthropic(
                api_key=token,  # sent as the x-api-key header
                base_url=ADA_BASE_URL,
                default_headers={"anthropic-version": ADA_VERSION},
                timeout=ADA_TIMEOUT,
                max_retries=2,
            )
        return _client


def _complete_raw(system: str, content: Content, max_tokens: int):
    kwargs = dict(model=ADA_MODEL, max_tokens=max_tokens, system=system,
                  messages=[{"role": "user", "content": content}])
    if ADA_THINKING == "disabled":
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    resp = get_client().messages.create(**kwargs)
    text = "\n".join(b.text for b in resp.content if getattr(b, "text", None)).strip()
    return text, getattr(resp, "stop_reason", None)


def complete(system: str, content: Content, max_tokens: int = 1024) -> str:
    """Single-turn completion; returns the concatenated text blocks."""
    return _complete_raw(system, content, max_tokens)[0]


def extract_json(text: str) -> dict:
    """Pull the outermost JSON object out of a model reply (tolerates ``` fences)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in model output")
    obj = json.loads(text[start : end + 1])
    if not isinstance(obj, dict):
        raise ValueError("model output JSON is not an object")
    return obj


_RETRY_HINT = "注意：只输出一个合法的 JSON 对象，不要包含解释或 Markdown。"


def _with_hint(content: Content) -> Content:
    if isinstance(content, str):
        return content + "\n\n" + _RETRY_HINT
    return list(content) + [{"type": "text", "text": _RETRY_HINT}]


def complete_json(system: str, content: Content, max_tokens: int = 1024) -> dict:
    """Completion that must return a JSON object; retries once on bad JSON.

    A reply cut off by max_tokens is not retried (the retry would be cut off
    the same way); the caller gets an AdaError and can fall back.
    """
    text, stop = _complete_raw(system, content, max_tokens)
    if stop == "max_tokens":
        logger.warning("model output truncated at max_tokens=%s (%s chars)", max_tokens, len(text))
        raise AdaError(f"模型输出超过 {max_tokens} tokens 被截断")
    try:
        return extract_json(text)
    except ValueError as first:
        logger.warning("model returned invalid JSON, retrying once: %s", first)
        retry, _ = _complete_raw(system, _with_hint(content), max_tokens)
        try:
            return extract_json(retry)
        except ValueError as e:
            raise AdaError(f"模型未返回合法 JSON：{e}") from e
