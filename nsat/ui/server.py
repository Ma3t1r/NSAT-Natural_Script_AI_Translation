# -*- coding: utf-8 -*-
"""NSAT UI 后端：静态文件 + REST API + SSE 事件流.

纯标准库实现（http.server + 线程），避免额外依赖。
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

from .. import config as _config
from .. import workflow
from .. import plugins as _plugins
from .webui import Job, run_job


def _static_dir() -> str:
    if getattr(sys, "frozen", False):  # PyInstaller 打包后
        return os.path.join(sys._MEIPASS, "nsat", "ui", "static")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


STATIC_DIR = _static_dir()

# ------------------------------------------------------------ 单实例控制
INSTANCE_PORT = 8798
_pending_open: dict[str, str | None] = {"path": None}
_instance_lock = threading.Lock()


def _instance_loop(sock: socket.socket) -> None:
    while True:
        try:
            conn, _ = sock.accept()
            data = conn.recv(8192)
            conn.close()
            if not data:
                continue
            try:
                msg = json.loads(data.decode("utf-8"))
                if msg.get("action") == "open" and msg.get("path"):
                    with _instance_lock:
                        _pending_open["path"] = msg["path"]
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        except OSError:
            break


def become_primary(open_file: str | None = None) -> bool:
    """尝试成为主实例。

    - 成功绑定控制端口 → 本进程是主实例，返回 True
    - 绑定失败且有实例在 → 发送打开请求，返回 False
    """
    global _instance_sock
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # 注意：Windows 上不能用 SO_REUSEADDR，否则允许重复绑定导致单实例失效
        s.bind(("127.0.0.1", INSTANCE_PORT))
        s.listen(5)
        _instance_sock = s
        threading.Thread(target=_instance_loop, args=(s,), daemon=True).start()
        return True
    except OSError:
        if notify_instance(open_file):
            return False
        return True


_instance_sock: socket.socket | None = None


def notify_instance(open_file: str | None = None) -> bool:
    """向已运行的主实例发送打开请求."""
    try:
        s = socket.create_connection(("127.0.0.1", INSTANCE_PORT), timeout=2)
        payload = json.dumps({"action": "open", "path": open_file or ""}).encode("utf-8")
        s.sendall(payload)
        s.close()
        return True
    except OSError:
        return False


def pop_pending_open() -> str | None:
    with _instance_lock:
        p = _pending_open["path"]
        _pending_open["path"] = None
        return p


def _list_drives() -> list[str]:
    if os.name != "nt":
        return []
    drives = []
    for d in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if os.path.exists(f"{d}:\\"):
            drives.append(f"{d}:\\")
    return drives


# ------------------------------------------------------------ 最近打开
_recent_lock = threading.Lock()
_RECENT_CAP = 12


def _recent_file() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "nsat", "recent.json")


def _load_recent() -> list[dict]:
    try:
        with open(_recent_file(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return []


def _save_recent(items: list[dict]) -> None:
    try:
        os.makedirs(os.path.dirname(_recent_file()), exist_ok=True)
        with open(_recent_file(), "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def record_recent(path: str, rtype: str = "folder") -> None:
    path = os.path.normpath(path)
    if not path:
        return
    with _recent_lock:
        items = _load_recent()
        items = [it for it in items if not (it.get("path") == path and it.get("type") == rtype)]
        items.insert(0, {"path": path, "type": rtype})
        _save_recent(items[:_RECENT_CAP])


def get_recent() -> list[dict]:
    with _recent_lock:
        return _load_recent()


# ------------------------------------------------------------ 会话记忆
_session_lock = threading.Lock()


def _session_file() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "nsat", "session.json")


def _load_session() -> dict:
    try:
        with open(_session_file(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save_session(data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_session_file()), exist_ok=True)
        with open(_session_file(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
_MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".map": "application/json",
}


def _send_json(handler: BaseHTTPRequestHandler, code: int, data) -> None:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length") or 0)
    raw = handler.rfile.read(length) if length else b"{}"
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return {}


def _query_param(handler: BaseHTTPRequestHandler, name: str, default: str = "") -> str:
    q = parse_qs(urlparse(handler.path).query)
    vals = q.get(name)
    return unquote(vals[0]) if vals else default


class JobStore:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, kind: str, target: str, options: dict | None = None) -> Job:
        with self._lock:
            jid = uuid.uuid4().hex[:12]
            job = Job(jid, kind, target, options)
            job.thread = threading.Thread(target=run_job, args=(job,), daemon=True)
            self._jobs[jid] = job
            return job

    def get(self, jid: str) -> Job | None:
        with self._lock:
            return self._jobs.get(jid)

    def start(self, job: Job) -> None:
        job.thread.start()


JOBS = JobStore()


def _list_project(root: str) -> list[dict]:
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        return []
    skip = {"out", "dist", ".git", "node_modules", "__pycache__", ".idea", ".venv", "venv"}
    out: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip and not d.endswith("_out")]
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace("\\", "/")
            out.append({"path": full, "rel": rel, "type": "nsat" if fn.lower().endswith(".nsat") else "other"})
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "NSAT/0.1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 安静
        pass

    # ------------------------------------------------------------ 路由

    def _route(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        try:
            if method == "GET" and path in ("/", "/index.html"):
                return self._serve_file("index.html")
            if method == "GET" and path.startswith("/static/"):
                return self._serve_file(path[len("/static/"):])
            if method == "GET" and path.startswith("/vendor/"):
                return self._serve_file(path.lstrip("/"))
            if path == "/api/health":
                return _send_json(self, 200, {"ok": True})
            if method == "GET" and path == "/api/config":
                return self._api_config_get()
            if method == "PUT" and path == "/api/config":
                return self._api_config_put(_read_body(self))
            if method == "GET" and path == "/api/project":
                return self._api_project(_query_param(self, "root"))
            if method == "GET" and path == "/api/read":
                return self._api_read(_query_param(self, "path"))
            if method == "POST" and path == "/api/save":
                return self._api_save(_read_body(self))
            if method == "GET" and path == "/api/settings":
                return self._api_settings_get()
            if method == "PUT" and path == "/api/settings":
                return self._api_settings_put(_read_body(self))
            if method == "GET" and path == "/api/browse":
                return self._api_browse(_query_param(self, "path"), _query_param(self, "mode", "folder"))
            if method == "GET" and path == "/api/recent":
                return _send_json(self, 200, {"ok": True, "items": get_recent()})
            if method == "POST" and path == "/api/recent":
                body = _read_body(self)
                record_recent(str(body.get("path", "")), str(body.get("type", "folder")))
                return _send_json(self, 200, {"ok": True})
            if method == "GET" and path == "/api/session":
                return _send_json(self, 200, {"ok": True, "session": _load_session()})
            if method == "POST" and path == "/api/session":
                body = _read_body(self)
                _save_session({"root": str(body.get("root", "") or ""), "files": list(body.get("files") or [])})
                return _send_json(self, 200, {"ok": True})
            if method == "POST" and path == "/api/mkdir":
                return self._api_mkdir(_read_body(self))
            if method == "POST" and path == "/api/delete":
                return self._api_delete(_read_body(self))
            if method == "POST" and path == "/api/rename":
                return self._api_rename(_read_body(self))
            if method == "POST" and path == "/api/assoc":
                return self._api_assoc()
            if method == "POST" and path == "/api/exit":
                return self._api_exit()
            if method == "GET" and path == "/api/instance/pending":
                return _send_json(self, 200, {"ok": True, "path": pop_pending_open()})
            if method == "POST" and path == "/api/run":
                return self._api_submit("run", _read_body(self))
            if method == "POST" and path == "/api/build":
                return self._api_submit("build", _read_body(self))
            if method == "POST" and path == "/api/check":
                return self._api_submit("check", _read_body(self))
            if method == "POST" and path == "/api/review":
                return self._api_submit("review", _read_body(self))
            if method == "POST" and path == "/api/ask":
                return self._api_submit("ask", _read_body(self))
            if method == "GET" and path.startswith("/api/jobs/"):
                rest = path[len("/api/jobs/"):]
                if "/stream" in rest:
                    return self._api_job_stream(rest.split("/")[0])
                if rest.endswith("/respond"):
                    return self._send_error(400, "respond 需要 POST")
                return self._api_job_status(rest)
            if method == "POST" and path.startswith("/api/jobs/") and path.endswith("/respond"):
                return self._api_job_respond(path[len("/api/jobs/"):-len("/respond")], _read_body(self))
            return self._send_error(404, f"未找到: {method} {path}")
        except Exception as e:  # noqa: BLE001
            return _send_json(self, 500, {"ok": False, "error": str(e)})

    # ------------------------------------------------------------ API

    def _api_config_get(self) -> None:
        cfg = _config.load_config()
        ai = dict(cfg.get("ai", {}))
        ai["api_key"] = "********" if ai.get("api_key") else ""
        cfg["ai"] = ai
        _send_json(self, 200, {"ok": True, **cfg})

    def _api_config_put(self, body: dict) -> None:
        cfg = _config.load_config()
        ai = body.get("ai") or {}
        for k in ("provider", "model", "base_url", "temperature", "max_tokens", "timeout"):
            if k in ai:
                cfg.setdefault("ai", {})[k] = ai[k]
        if ai.get("api_key") and ai["api_key"] not in ("", "********"):
            cfg["ai"]["api_key"] = ai["api_key"]
        for sec in ("logic_errors", "permissions", "context", "output", "ui"):
            if body.get(sec) is not None:
                cfg[sec] = body[sec]
        _config.save_config(cfg)
        _send_json(self, 200, {"ok": True})

    def _api_project(self, root: str) -> None:
        if not root:
            root = os.getcwd()
        files = _list_project(root)
        _send_json(self, 200, {"ok": True, "root": os.path.abspath(root), "files": files})

    def _api_read(self, path: str) -> None:
        if not path or not os.path.isfile(path):
            return _send_json(self, 404, {"ok": False, "error": "文件不存在"})
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError as e:
            return _send_json(self, 500, {"ok": False, "error": str(e)})
        _send_json(self, 200, {"ok": True, "content": content})

    def _api_save(self, body: dict) -> None:
        path = body.get("path", "")
        if not path:
            return _send_json(self, 400, {"ok": False, "error": "缺少 path"})
        try:
            workflow.write_text(path, str(body.get("content", "")))
        except OSError as e:
            return _send_json(self, 500, {"ok": False, "error": str(e)})
        _send_json(self, 200, {"ok": True})

    def _api_settings_get(self) -> None:
        cfg = _config.load_config()
        ai = dict(cfg.get("ai", {}))
        ai["api_key"] = "********" if ai.get("api_key") else ""
        cfg["ai"] = ai
        _send_json(self, 200, {"ok": True, **cfg})

    def _api_settings_put(self, body: dict) -> None:
        cfg = _config.load_config()
        ai = body.get("ai") or {}
        for k in ("provider", "model", "base_url", "temperature", "max_tokens", "timeout"):
            if k in ai:
                cfg.setdefault("ai", {})[k] = ai[k]
        # API Key：空/"********" 视为不变，__clear__ 表示清除
        if ai.get("api_key"):
            key = str(ai["api_key"])
            if key == "__clear__":
                cfg["ai"]["api_key"] = ""
            elif key != "********":
                cfg["ai"]["api_key"] = key
        for sec in ("logic_errors", "permissions", "context", "output", "ui"):
            if body.get(sec) is not None:
                cfg[sec] = body[sec]
        path = _config.save_user_config(cfg)
        _send_json(self, 200, {"ok": True, "path": path})

    def _api_assoc(self) -> None:
        from ..winassoc import register_assoc

        ok, msg = register_assoc()
        _send_json(self, 200 if ok else 500, {"ok": ok, "message": msg})

    def _api_browse(self, path: str, mode: str = "folder") -> None:
        """目录浏览：返回子目录/文件。空路径或盘符根 → 列出 Windows 盘符."""
        if not path or path.strip() in ("\\", "/"):
            drives = _list_drives()
            return _send_json(self, 200, {"ok": True, "path": "", "dirs": drives, "files": [], "parent": None})
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            return _send_json(self, 200, {"ok": True, "path": path, "dirs": [], "files": [], "parent": None})
        dirs: list[str] = []
        files: list[str] = []
        try:
            entries = sorted(os.listdir(path), key=str.lower)
        except OSError as e:
            return _send_json(self, 200, {"ok": False, "error": str(e)})
        for e in entries:
            full = os.path.join(path, e)
            try:
                if os.path.isdir(full):
                    dirs.append(e)
                elif os.path.isfile(full):
                    files.append(e)
            except OSError:
                continue
        parent = os.path.dirname(path)
        _send_json(self, 200, {"ok": True, "path": path, "dirs": dirs, "files": files, "parent": parent, "mode": mode})

    def _api_mkdir(self, body: dict) -> None:
        path = body.get("path", "")
        if not path:
            return _send_json(self, 400, {"ok": False, "error": "缺少 path"})
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as e:
            return _send_json(self, 500, {"ok": False, "error": str(e)})
        _send_json(self, 200, {"ok": True})

    def _api_delete(self, body: dict) -> None:
        path = body.get("path", "")
        if not path:
            return _send_json(self, 400, {"ok": False, "error": "缺少 path"})
        if os.path.isdir(path):
            try:
                if os.listdir(path):
                    return _send_json(self, 400, {"ok": False, "error": "文件夹非空，请先删除内容"})
                os.rmdir(path)
            except OSError as e:
                return _send_json(self, 500, {"ok": False, "error": str(e)})
        elif os.path.isfile(path):
            try:
                os.remove(path)
            except OSError as e:
                return _send_json(self, 500, {"ok": False, "error": str(e)})
        else:
            return _send_json(self, 404, {"ok": False, "error": "路径不存在"})
        _send_json(self, 200, {"ok": True})

    def _api_rename(self, body: dict) -> None:
        old = body.get("old", "")
        new = body.get("new", "")
        if not old or not new:
            return _send_json(self, 400, {"ok": False, "error": "缺少 old/new"})
        if not os.path.exists(old):
            return _send_json(self, 404, {"ok": False, "error": "路径不存在"})
        if os.path.exists(new):
            return _send_json(self, 400, {"ok": False, "error": "目标已存在"})
        try:
            os.rename(old, new)
        except OSError as e:
            return _send_json(self, 500, {"ok": False, "error": str(e)})
        _send_json(self, 200, {"ok": True})

    def _api_exit(self) -> None:
        _send_json(self, 200, {"ok": True})
        threading.Timer(0.3, lambda: os._exit(0)).start()

    def _api_submit(self, kind: str, body: dict) -> None:
        target = body.get("target", "")
        if not target:
            return _send_json(self, 400, {"ok": False, "error": "缺少 target"})
        options = {
            "inline": bool(body.get("inline")),
            "lang": body.get("lang"),
            "out": body.get("out"),
            "root": body.get("root"),
            "message": body.get("message", ""),
        }
        job = JOBS.create(kind, target, options)
        JOBS.start(job)
        _send_json(self, 200, {"ok": True, "job_id": job.id})

    def _api_job_status(self, jid: str) -> None:
        job = JOBS.get(jid)
        if not job:
            return _send_json(self, 404, {"ok": False, "error": "job 不存在"})
        _send_json(self, 200, {
            "ok": True,
            "job_id": job.id,
            "kind": job.kind,
            "done": job.done,
            "error": job.error,
            "pending_type": job.pending_type,
        })

    def _api_job_respond(self, jid: str, body: dict) -> None:
        job = JOBS.get(jid)
        if not job:
            return _send_json(self, 404, {"ok": False, "error": "job 不存在"})
        if not job.pending_event.is_set():
            job.respond(body)
            _send_json(self, 200, {"ok": True})
        else:
            _send_json(self, 409, {"ok": False, "error": "没有待响应的询问"})

    def _api_job_stream(self, jid: str) -> None:
        job = JOBS.get(jid)
        if not job:
            return self._send_error(404, "job 不存在")
        self.close_connection = True  # 流结束即断开，客户端能读到 EOF
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        # 直接用 connection.sendall 绕过 wfile 缓冲，保证即时送达
        try:
            while True:
                try:
                    payload = job.events.get(timeout=5)
                except Exception:
                    self.connection.sendall(b": keepalive\n\n")
                    continue
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.connection.sendall(b"data: " + data + b"\n\n")
                if payload.get("type") == "done":
                    break
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _serve_file(self, rel: str) -> None:
        rel = os.path.normpath(rel).lstrip("\\/")
        full = os.path.join(STATIC_DIR, rel)
        if not os.path.isfile(full) or ".." in rel:
            return self._send_error(404, "not found")
        try:
            with open(full, "rb") as f:
                data = f.read()
        except OSError:
            return self._send_error(404, "not found")
        ext = os.path.splitext(full)[1].lower()
        self.send_response(200)
        self.send_header("Content-Type", _MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _send_error(self, code: int, msg: str) -> None:
        _send_json(self, code, {"ok": False, "error": msg})

    # 方法分发
    do_GET = do_POST = do_PUT = do_DELETE = lambda self: self._route(self.command)


def create_server(host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    """创建并返回服务器（尚未 listen 的实例，需要外部 start）."""
    return ThreadingHTTPServer((host, port), Handler)


def run_server(host: str = "127.0.0.1", port: int = 8799) -> ThreadingHTTPServer:
    """在当前线程启动服务器（阻塞）。"""
    server = ThreadingHTTPServer((host, port), Handler)
    server.serve_forever()
    return server


def start_server(host: str = "127.0.0.1", port: int = 8799):
    """后台线程启动服务器，返回 (server, url)."""
    from .. import logging as nsatlog

    nsatlog.setup_logging()
    nsatlog.log_app(f"服务启动 host={host}")
    _plugins.load_plugins()
    server = ThreadingHTTPServer((host, 0), Handler)
    actual_port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, f"http://{host}:{actual_port}/"