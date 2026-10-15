"""Local web server for the travel planner (Python standard library only).

Routes:
    GET    /                          → static/index.html
    GET    /api/health                → {"ok", "token_present", "model"}
    GET    /api/plan/stream?q=&profile=  → Server-Sent Events from orchestrator.plan
    GET    /api/profile?id=           → saved traveller profile
    DELETE /api/profile?id=           → delete a saved profile
    POST   /api/ask      {"question", "language"}                       → inbound Q&A (knowledge base only)
    POST   /api/share    {"plan_id", "language"}                        → share post / caption / hashtags
    POST   /api/receipt  {"image_b64", "media_type", "language", "home_currency"} → receipt recognition

Security: binds to 127.0.0.1 by default and has NO authentication. Anyone who
can reach the port can spend your Ada quota and read saved family profiles,
so do not expose it (HOST=0.0.0.0) on a shared network without adding auth.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import ada_client
import agents
import memory
import orchestrator
import websearch

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_QUERY_CHARS = 1000
MAX_BODY_BYTES = 8 * 1024 * 1024  # a 5 MB image is ~6.7 MB as base64


class Handler(BaseHTTPRequestHandler):
    server_version = "TravelPlanner/2.0"

    # ------------------------------------------------------------ routing
    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        url = urlparse(self.path)
        qs = parse_qs(url.query)
        if url.path in ("/", "/index.html"):
            self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        elif url.path in ("/i18n.js", "/app.js"):
            self._send_file(STATIC_DIR / url.path.lstrip("/"), "text/javascript; charset=utf-8")
        elif url.path == "/api/health":
            self._send_json(200, {"ok": True, "token_present": bool(os.environ.get("ADA_TOKEN")), "model": ada_client.ADA_MODEL,
                                  "weather": "off" if os.environ.get("WEATHER", "on").lower() == "off" else "open-meteo",
                                  "search": websearch.status()})
        elif url.path == "/api/plan/stream":
            self._stream_plan(qs.get("q", [""])[0], qs.get("profile", [""])[0].strip() or None)
        elif url.path == "/api/profile":
            pid = qs.get("id", [""])[0].strip()
            if not memory.valid_id(pid):
                return self._send_json(400, {"error": "档案 ID 只能包含字母、数字、汉字、下划线和短横线，最长 32 个字符"})
            profile = memory.get_profile(pid)
            self._send_json(200 if profile else 404, {"id": pid, "profile": profile})
        else:
            self._send_json(404, {"error": "not found"})

    def do_DELETE(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if url.path != "/api/profile":
            return self._send_json(404, {"error": "not found"})
        pid = parse_qs(url.query).get("id", [""])[0].strip()
        if not memory.valid_id(pid):
            return self._send_json(400, {"error": "invalid profile id"})
        self._send_json(200, {"deleted": memory.delete_profile(pid)})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        handlers = {"/api/ask": self._ask, "/api/share": self._share, "/api/receipt": self._receipt}
        if path not in handlers:
            return self._send_json(404, {"error": "not found"})
        body = self._read_json()
        if body is None:
            return
        try:
            self._send_json(200, handlers[path](body))
        except agents.PlanningError as e:
            self._send_json(400, {"error": str(e)})
        except ada_client.AdaError as e:
            self._send_json(502, {"error": str(e)})
        except Exception as e:  # model / network failures
            logger.exception("request failed: %s", path)
            self._send_json(502, {"error": f"{type(e).__name__}: {e}"})

    # ------------------------------------------------------------ POST handlers
    def _ask(self, body: dict) -> dict:
        question = str(body.get("question") or "")
        if len(question) > MAX_QUERY_CHARS:
            raise agents.PlanningError(f"问题不超过 {MAX_QUERY_CHARS} 字")
        return agents.ask_agent(question, str(body.get("language") or "en"))

    def _share(self, body: dict) -> dict:
        plan = orchestrator.get_plan(str(body.get("plan_id") or ""))
        if not plan:
            raise agents.PlanningError("找不到这份行程，请重新规划后再生成分享内容")
        return agents.share_agent(plan, str(body.get("language") or ""))

    def _receipt(self, body: dict) -> dict:
        return agents.receipt_agent(str(body.get("image_b64") or ""), str(body.get("media_type") or ""),
                                    str(body.get("language") or "en"), str(body.get("home_currency") or "USD"))

    # ------------------------------------------------------------ helpers
    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            self._send_json(400, {"error": "请求体为空"})
            return None
        if length > MAX_BODY_BYTES:
            self._send_json(413, {"error": "请求体过大（上限 8 MB）"})
            return None
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self._send_json(400, {"error": "请求体不是合法的 JSON"})
            return None
        if not isinstance(body, dict):
            self._send_json(400, {"error": "请求体必须是 JSON 对象"})
            return None
        return body

    def _send_file(self, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _stream_plan(self, query: str, profile_id) -> None:
        query = query.strip()
        if not query or len(query) > MAX_QUERY_CHARS:
            return self._send_json(400, {"error": f"q 不能为空且不超过 {MAX_QUERY_CHARS} 字"})
        if profile_id and not memory.valid_id(profile_id):
            return self._send_json(400, {"error": "档案 ID 格式不正确"})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        def emit(event: dict) -> None:
            data = f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")
            try:
                self.wfile.write(data)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass  # browser went away; let the pipeline finish quietly

        orchestrator.plan(query, emit, profile_id)


def make_server(host: str, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    if not os.environ.get("ADA_TOKEN"):
        print("警告：ADA_TOKEN 未设置，规划请求会失败。请先 export ADA_TOKEN=<your-ada-token>", file=sys.stderr)
    if host not in ("127.0.0.1", "localhost"):
        print(f"警告：服务监听在 {host}，没有任何鉴权，同网段的人都能使用你的 Ada 额度并读取家庭档案。", file=sys.stderr)
    httpd = make_server(host, port)
    print(f"行程规划服务已启动：http://{host}:{port}  (Ctrl+C 退出)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
