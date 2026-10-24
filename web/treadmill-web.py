#!/usr/bin/env python3
"""
阳台跑步机 Web 面板 —— 反向代理服务

用途：
  ESPHome 的 web_server 只能返回内置的空壳页面，无法托管自定义 HTML。
  本服务在 5095 上提供自定义页面，并把 API 请求转发到 ESP32。

路由：
  GET  /             -> /opt/treadmill-web/index.html（自定义页面）
  GET  /events       -> 转发 ESP32 的 SSE 日志流
  *    /sensor/...   -> 转发 ESP32 REST
  *    /button/...   -> 转发 ESP32 REST
  *    /number/...   -> 转发 ESP32 REST
  GET  /health       -> 健康检查

运行：
  ESP_HOST=192.168.1.50 PORT=8099 python3 treadmill-web.py
"""

import http.server
import socketserver
import urllib.request
import urllib.error
import os
import sys
import json
import socket

LISTEN_PORT = int(os.environ.get("PORT", "8099"))
ESP_HOST = os.environ.get("ESP_HOST", "esphome-device.local")  # 改成你的 ESP32 地址
ESP_PORT = int(os.environ.get("ESP_PORT", "80"))
WEB_ROOT = os.environ.get("WEB_ROOT", os.path.expanduser("~/treadmill-web"))

ESP_BASE = f"http://{ESP_HOST}:{ESP_PORT}"

# Home Assistant（用于查询历史数据）
HA_HOST = os.environ.get("HA_HOST", "192.168.199.109")
HA_PORT = int(os.environ.get("HA_PORT", "8123"))
HA_TOKEN_FILE = os.environ.get("HA_TOKEN_FILE", "/tmp/ha_token")
HA_BASE = f"http://{HA_HOST}:{HA_PORT}"


def ha_token():
    try:
        with open(HA_TOKEN_FILE) as f:
            return f.read().strip()
    except Exception:
        return ""

# 需要转发到 ESP32 的路径前缀
PROXY_PREFIXES = ("/sensor/", "/button/", "/number/", "/binary_sensor/",
                  "/switch/", "/select/", "/text_sensor/", "/events", "/light/")

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        # 只记错误，避免刷屏
        if args and str(args[1] if len(args) > 1 else "").startswith(("4", "5")):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ---------- 转发 ----------
    def _proxy(self, method):
        url = ESP_BASE + self.path
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else None

        req = urllib.request.Request(url, data=body, method=method)
        ct = self.headers.get("Content-Type")
        if ct:
            req.add_header("Content-Type", ct)

        try:
            resp = urllib.request.urlopen(req, timeout=60)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        except Exception as e:
            self.send_error(502, "ESP32 不可达: %s" % e)
            return

        # SSE 流式转发
        if "text/event-stream" in (resp.headers.get("Content-Type") or ""):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            try:
                while True:
                    chunk = resp.read1(4096) if hasattr(resp, "read1") else resp.read(4096)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        data = resp.read()
        self.send_response(resp.status)
        ctype = resp.headers.get("Content-Type")
        if ctype:
            self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    # ---------- 静态 ----------
    def _serve_file(self, path):
        root = os.path.realpath(WEB_ROOT)
        target = os.path.realpath(os.path.join(root, path.lstrip("/")))
        # 防目录穿越
        if not target.startswith(root):
            self.send_error(403)
            return
        if os.path.isdir(target):
            target = os.path.join(target, "index.html")
        if not os.path.isfile(target):
            self.send_error(404)
            return
        ext = os.path.splitext(target)[1].lower()
        with open(target, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    # ---------- 入口 ----------
    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/health":
            body = json.dumps({"ok": True, "esp": ESP_BASE}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if p.startswith("/ha/history"):
            self._ha_history()
            return
        if p.startswith(PROXY_PREFIXES):
            self._proxy("GET")
            return
        self._serve_file(p)

    def _ha_history(self):
        """转发 Home Assistant 的历史查询。
        前端调用：/ha/history?entity=sensor.xxx&start=2026-10-24T00:00:00+00:00
        """
        import urllib.parse
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        entity = qs.get("entity", [""])[0]
        start = qs.get("start", [""])[0]
        if not entity or not start:
            self.send_error(400, "need entity & start")
            return
        token = ha_token()
        if not token:
            self.send_error(500, "HA token missing")
            return
        url = (f"{HA_BASE}/api/history/period/{start}"
               f"?filter_entity_id={entity}&minimal_response&no_attributes")
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
        except Exception as e:
            self.send_error(502, "HA error: %s" % e)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        p = self.path.split("?")[0]
        if p.startswith(PROXY_PREFIXES):
            self._proxy("POST")
            return
        self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    if not os.path.isfile(os.path.join(WEB_ROOT, "index.html")):
        sys.stderr.write("警告: %s/index.html 不存在\n" % WEB_ROOT)

    srv = ThreadingServer(("0.0.0.0", LISTEN_PORT), Handler)
    sys.stderr.write("跑步机面板: http://0.0.0.0:%d/  ->  ESP32 %s\n"
                     % (LISTEN_PORT, ESP_BASE))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
