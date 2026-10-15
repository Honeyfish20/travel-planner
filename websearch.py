"""Web search through MCP: Exa (hosted MCP) and Bocha 博查 (remote MCP or REST API).

- Exa: https://mcp.exa.ai/mcp, tool `web_search_exa`. Works without a key at a
  low rate limit; set EXA_API_KEY for higher limits.
- Bocha: the official bocha-search-mcp server is a thin wrapper around
  https://api.bochaai.com/v1/web-search. Set BOCHA_MCP_URL to use a remote
  Bocha MCP server (tool `bocha_web_search`), or BOCHA_API_KEY to call the same
  API directly. Without either, Bocha is reported as "not configured".
- WEB_SEARCH=off disables all outbound search (offline demo / tests).

Search results are untrusted third-party content: callers must treat them
as data only. Queries contain only city names and trip type, never traveller
details.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

from mcp_client import MCPClient, MCPError, USER_AGENT

logger = logging.getLogger(__name__)

EXA_MCP_URL = "https://mcp.exa.ai/mcp"
BOCHA_API_URL = "https://api.bochaai.com/v1/web-search"
TIMEOUT = 25
CACHE_TTL = 3600
SNIPPET_CHARS = 400


class ProviderUnavailable(RuntimeError):
    """Provider is not configured (e.g. missing API key)."""


def _env(name: str) -> Optional[str]:
    value = os.environ.get(name, "").strip()
    return value or None


def enabled() -> bool:
    return os.environ.get("WEB_SEARCH", "on").lower() != "off"


def status() -> Dict[str, dict]:
    bocha_mode = "MCP" if _env("BOCHA_MCP_URL") else ("REST" if _env("BOCHA_API_KEY") else None)
    return {
        "exa": {"configured": enabled(), "mode": "MCP", "key": bool(_env("EXA_API_KEY"))},
        "bocha": {"configured": enabled() and bool(bocha_mode), "mode": bocha_mode},
    }


def _clean(text: str, limit: int = SNIPPET_CHARS) -> str:
    text = re.sub(r"\s+", " ", re.sub(r"(?m)^\s*\.\.\.\s*$", " ", text or "")).strip()
    return text[:limit]


def _valid_url(url: str) -> bool:
    return bool(re.match(r"^https?://[^\s]+$", url or ""))


# ------------------------------------------------------------------ Exa (MCP)
_exa_client: Optional[MCPClient] = None
_exa_lock = threading.Lock()


def _exa() -> MCPClient:
    global _exa_client
    with _exa_lock:
        if _exa_client is None:
            url = _env("EXA_MCP_URL") or EXA_MCP_URL
            key = _env("EXA_API_KEY")
            if key:
                url += ("&" if "?" in url else "?") + "exaApiKey=" + urllib.parse.quote(key)
            _exa_client = MCPClient(url, timeout=TIMEOUT)
        return _exa_client


def parse_exa_text(text: str) -> List[dict]:
    """Parse Exa's 'Title: / URL: / Published: / Highlights:' text blocks."""
    results = []
    for chunk in re.split(r"(?m)^Title: ", text or "")[1:]:
        title = chunk.split("\n", 1)[0].strip()
        url = (re.search(r"(?m)^URL: (\S+)", chunk) or [None, ""])[1]
        published = (re.search(r"(?m)^Published: (.+)$", chunk) or [None, ""])[1].strip()
        body = chunk.split("Highlights:", 1)[1] if "Highlights:" in chunk else chunk.split("\n", 1)[-1]
        body = re.sub(r"(?m)^(URL|Published|Author): .*$", "", body)
        if _valid_url(url):
            results.append({"title": title[:200], "url": url, "snippet": _clean(body),
                            "published": "" if published in ("N/A", "") else published[:10]})
    return results


def exa_search(query: str, count: int) -> List[dict]:
    return parse_exa_text(_exa().call_tool("web_search_exa", {"query": query, "numResults": count}))


# ------------------------------------------------------------------ Bocha (MCP or REST)
def parse_bocha_text(text: str) -> List[dict]:
    """Parse the official bocha-search-mcp output ('Title: / URL: / Description: ...')."""
    results = []
    for chunk in re.split(r"(?m)^Title: ", text or "")[1:]:
        get = lambda key: (re.search(rf"(?m)^{key}: (.*)$", chunk) or [None, ""])[1].strip()  # noqa: E731
        url = get("URL")
        if _valid_url(url):
            results.append({"title": chunk.split("\n", 1)[0].strip()[:200], "url": url,
                            "snippet": _clean(get("Description")), "published": get("Published date")[:10]})
    return results


def parse_bocha_json(body: dict) -> List[dict]:
    data = body.get("data", body) if isinstance(body, dict) else {}
    pages = ((data or {}).get("webPages") or {}).get("value") or []
    return [{"title": str(p.get("name") or "")[:200], "url": p.get("url", ""),
             "snippet": _clean(p.get("summary") or p.get("snippet") or ""),
             "published": str(p.get("datePublished") or "")[:10]}
            for p in pages if _valid_url(p.get("url", ""))]


def bocha_search(query: str, count: int) -> List[dict]:
    key, mcp_url = _env("BOCHA_API_KEY"), _env("BOCHA_MCP_URL")
    if mcp_url:
        headers = {"Authorization": f"Bearer {key}"} if key else None
        text = MCPClient(mcp_url, headers=headers, timeout=TIMEOUT).call_tool(
            "bocha_web_search", {"query": query, "freshness": "oneYear", "count": count})
        return parse_bocha_text(text)
    if not key:
        raise ProviderUnavailable("未配置 BOCHA_API_KEY 或 BOCHA_MCP_URL")
    payload = json.dumps({"query": query, "summary": True, "freshness": "oneYear", "count": count}).encode("utf-8")
    req = urllib.request.Request(BOCHA_API_URL, data=payload, method="POST", headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return parse_bocha_json(json.loads(r.read().decode("utf-8")))
    except urllib.error.HTTPError as e:
        raise MCPError(f"Bocha HTTP {e.code}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise MCPError(f"Bocha request failed: {e}") from e


PROVIDERS = {"exa": exa_search, "bocha": bocha_search}
PROVIDER_NAMES = {"exa": "Exa", "bocha": "博查"}

# ------------------------------------------------------------------ fan-out with cache
_cache: Dict[Tuple[str, str, int], Tuple[float, List[dict]]] = {}
_cache_lock = threading.Lock()


def _cached(provider: str, query: str, count: int) -> List[dict]:
    key = (provider, query, count)
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL:
            return hit[1]
    results = PROVIDERS[provider](query, count)
    with _cache_lock:
        _cache[key] = (time.time(), results)
    return results


def search_all(plan: List[Tuple[str, str]], count: int = 5) -> Tuple[List[dict], Dict[str, dict]]:
    """Run [(provider, query), ...] in parallel.

    Returns (numbered, de-duplicated results, per-provider status).
    """
    statuses: Dict[str, dict] = {p: {"name": PROVIDER_NAMES[p], "ok": False, "count": 0, "error": None, "queries": []}
                                 for p in dict.fromkeys(p for p, _ in plan)}
    if not enabled():
        for s in statuses.values():
            s["error"] = "WEB_SEARCH=off"
        return [], statuses

    def run(item):
        provider, query = item
        try:
            return item, _cached(provider, query, count), None
        except (ProviderUnavailable, MCPError) as e:
            return item, [], str(e)
        except Exception as e:  # never let search break planning
            logger.exception("search failed: %s", provider)
            return item, [], f"{type(e).__name__}: {e}"

    with ThreadPoolExecutor(max_workers=max(1, len(plan))) as pool:
        outcomes = list(pool.map(run, plan))

    results, seen = [], set()
    for (provider, query), items, error in outcomes:
        st = statuses[provider]
        st["queries"].append(query)
        if error:
            st["error"] = st["error"] or error
        else:
            st["ok"] = True
        for it in items:
            if it["url"] in seen:
                continue
            seen.add(it["url"])
            st["count"] += 1
            results.append({"n": len(results) + 1, "provider": PROVIDER_NAMES[provider], **it})
    return results, statuses
