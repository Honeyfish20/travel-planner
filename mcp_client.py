"""Minimal MCP client for remote servers (Streamable HTTP transport), stdlib only.

Flow: initialize → notifications/initialized → tools/call. Responses may be
plain JSON or a Server-Sent Events stream; both are handled. If the server
drops the session (HTTP 400/404), the client re-initialises once and retries.
"""
from __future__ import annotations

import itertools
import json
import threading
import urllib.error
import urllib.request
from typing import Optional

PROTOCOL_VERSION = "2025-03-26"
USER_AGENT = "travel-planner/3.0"


class MCPError(RuntimeError):
    """Transport, protocol or tool error from an MCP server."""


def parse_response(body: str, content_type: str, want_id) -> dict:
    """Return the JSON-RPC message answering `want_id` from a JSON or SSE body."""
    if "text/event-stream" not in content_type:
        try:
            return json.loads(body) if body.strip() else {}
        except ValueError as e:
            raise MCPError(f"invalid JSON from MCP server: {e}") from e
    messages, data_lines = [], []
    for line in body.splitlines() + [""]:
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif not line.strip() and data_lines:  # blank line ends an event
            try:
                messages.append(json.loads("\n".join(data_lines)))
            except ValueError:
                pass
            data_lines = []
    for msg in messages:
        if isinstance(msg, dict) and msg.get("id") == want_id:
            return msg
    return messages[-1] if messages else {}


class MCPClient:
    def __init__(self, url: str, headers: Optional[dict] = None, timeout: float = 30):
        self.url, self.timeout = url, timeout
        self.headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                        "User-Agent": USER_AGENT, **(headers or {})}
        self.session_id: Optional[str] = None
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._ready = False

    def _post(self, payload: dict, expect_response: bool = True) -> Optional[dict]:
        headers = dict(self.headers)
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                self.session_id = r.headers.get("Mcp-Session-Id") or self.session_id
                body = r.read().decode("utf-8", "replace")
                content_type = r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            raise MCPError(f"HTTP {e.code}") from e
        except (urllib.error.URLError, OSError) as e:  # includes timeouts
            raise MCPError(f"connection failed: {e}") from e
        return parse_response(body, content_type, payload.get("id")) if expect_response else None

    def _initialize(self) -> None:
        with self._lock:
            if self._ready:
                return
            self.session_id = None
            msg = self._post({"jsonrpc": "2.0", "id": next(self._ids), "method": "initialize", "params": {
                "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                "clientInfo": {"name": "travel-planner", "version": "3.0"}}})
            if msg and "error" in msg:
                raise MCPError(f"initialize failed: {msg['error']}")
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_response=False)
            self._ready = True

    def call_tool(self, name: str, arguments: dict) -> str:
        """Call a tool and return its text content."""
        for attempt in (1, 2):
            self._initialize()
            try:
                msg = self._post({"jsonrpc": "2.0", "id": next(self._ids), "method": "tools/call",
                                  "params": {"name": name, "arguments": arguments}})
                break
            except MCPError as e:
                if attempt == 1 and str(e) in ("HTTP 400", "HTTP 404"):  # session expired
                    with self._lock:
                        self._ready = False
                    continue
                raise
        if not msg:
            raise MCPError("empty response")
        if "error" in msg:
            raise MCPError(f"tool error: {msg['error'].get('message', msg['error'])}")
        result = msg.get("result") or {}
        text = "\n".join(c.get("text", "") for c in result.get("content") or [] if c.get("type") == "text")
        if result.get("isError"):
            raise MCPError(text[:300] or "tool returned an error")
        return text
