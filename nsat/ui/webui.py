# -*- coding: utf-8 -*-
"""WebUI：workflow.UI 在网页端的实现.

每次需要用户交互时，把「询问事件」放进 job 队列，阻塞等待前端响应。
"""

from __future__ import annotations

import os
import queue
import threading
from typing import Any

from ..permissions import PermissionDecision
from .. import workflow


class Job:
    """一个在后台线程里跑的工作单元（run / build / ask 等）."""

    def __init__(self, job_id: str, kind: str, target: str, options: dict[str, Any] | None = None):
        self.id = job_id
        self.kind = kind
        self.target = target
        self.options = options or {}
        self.events: queue.Queue = queue.Queue()
        self.pending_event = threading.Event()
        self.pending_type: str | None = None
        self.pending_response: dict[str, Any] | None = None
        self.done = False
        self.error: str | None = None
        self.thread: threading.Thread | None = None
        self._history: list[dict[str, Any]] | None = None

    # ---- 事件 ----

    def emit(self, payload: dict[str, Any]) -> None:
        self.events.put(payload)

    def ask(self, payload: dict[str, Any]) -> dict[str, Any]:
        """发出询问事件并阻塞等待前端响应."""
        self.emit(payload)
        self.pending_type = payload.get("type")
        self.pending_response = None
        self.pending_event.clear()
        if not self.pending_event.wait(timeout=900):
            raise TimeoutError("等待用户响应超时")
        resp = self.pending_response or {}
        self.pending_type = None
        return resp

    def respond(self, data: dict[str, Any]) -> None:
        self.pending_response = data
        self.pending_event.set()

    # ---- 辅助 ----

    def history(self) -> list[dict[str, Any]]:
        if self._history is None:
            from ..prompts import ASSISTANT_SYSTEM_PROMPT
            self._history = [{"role": "system", "content": ASSISTANT_SYSTEM_PROMPT}]
        return self._history


class Tee:
    """把 print 输出同时送进事件队列，前端控制台实时显示."""

    def __init__(self, job: Job):
        self.job = job
        self._buf = ""

    def write(self, text: str) -> None:
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line:
                self.job.emit({"type": "log", "text": line})
        if text and not text.endswith("\n"):
            pass  # 等换行再发，避免半行

    def flush(self) -> None:
        if self._buf:
            self.job.emit({"type": "log", "text": self._buf})
            self._buf = ""


class WebUI(workflow.UI):
    """网页端 UI 载体."""

    def __init__(self, job: Job):
        self.job = job

    def input(self, prompt: str) -> str:
        r = self.job.ask({"type": "ask_input", "prompt": prompt})
        return str(r.get("text", ""))

    def choose_language(self, options: list[str]) -> str:
        r = self.job.ask({"type": "ask_language", "options": options})
        lang = str(r.get("language", "")).strip()
        return lang if lang in options else (options[0] if options else "python")

    def choose_entry(self, options: list[str]) -> str:
        r = self.job.ask({"type": "ask_entry", "options": options})
        entry = str(r.get("entry", "")).strip()
        return entry if entry in options else (options[0] if options else "")

    def handle_logic_issues(self, issues) -> str:
        data = [
            {
                "line": it.line,
                "concern": it.concern,
                "suggestion": it.suggestion,
                "severity": it.severity,
            }
            for it in issues
        ]
        r = self.job.ask({"type": "ask_logic_issues", "issues": data})
        return str(r.get("decision", "proceed"))

    def provide_file(self, fname: str) -> tuple[bool, str | None]:
        r = self.job.ask({"type": "ask_provide_file", "fname": fname})
        path = str(r.get("path", "")).strip()
        if not path:
            return False, None
        if not os.path.isfile(path):
            return False, None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return True, f.read()
        except OSError:
            return False, None

    def next_instruction(self) -> str | None:
        r = self.job.ask({"type": "ask_next", "prompt": "输入下一轮修改意见"})
        instr = r.get("instruction")
        if instr is None:
            return None
        instr = str(instr).strip()
        if not instr:
            return None
        low = instr.lower()
        if low.startswith(("/exit", "/quit")):
            return None
        return instr

    def ask_permission(self, operation: str, path: str) -> PermissionDecision:
        r = self.job.ask(
            {"type": "ask_permission", "operation": operation, "path": path}
        )
        return PermissionDecision(
            allowed=bool(r.get("allowed", False)),
            remember=bool(r.get("remember", False)),
        )


def run_job(job: Job) -> None:
    """在 job 线程里执行，捕获 print 输出到事件流."""
    from .. import config as _config
    from .. import logging as nsatlog
    from ..ai import create_provider

    old_stdout = None
    nsatlog.log_app(f"job开始 kind={job.kind} target={job.target}")
    try:
        import sys

        old_stdout = sys.stdout
        sys.stdout = Tee(job)
        cfg = _config.load_config()
        provider = create_provider(cfg)

        if job.kind == "run":
            target = job.target
            options = job.options
            if options.get("inline"):
                entry = workflow.resolve_entry_file(target, WebUI(job))
                workflow.run_project(cfg, provider, entry, WebUI(job), target_lang=options.get("lang"))
            elif os.path.isdir(target):
                workflow.run_project_folder(cfg, provider, target, WebUI(job), target_lang=options.get("lang"))
            else:
                workflow.run_project(cfg, provider, target, WebUI(job), target_lang=options.get("lang"))
        elif job.kind == "build":
            target = job.target
            options = job.options
            if options.get("inline"):
                entry = workflow.resolve_entry_file(target, WebUI(job))
                out_dir = options.get("out") or workflow.default_out_dir(entry)
                workflow.final_build(cfg, provider, entry, out_dir, WebUI(job), target_lang=options.get("lang"))
            elif os.path.isdir(target):
                workflow.final_build_folder(cfg, provider, target, options.get("out"), WebUI(job), target_lang=options.get("lang"))
            else:
                out_dir = options.get("out") or workflow.default_out_dir(target)
                workflow.final_build(cfg, provider, target, out_dir, WebUI(job), target_lang=options.get("lang"))
        elif job.kind == "check":
            _run_check(job)
        elif job.kind == "review":
            workflow.review(cfg, provider, job.target, WebUI(job))
        elif job.kind == "ask":
            _run_ask_turn(job, cfg, provider)

    except Exception as e:  # noqa: BLE001 - 后台任务全部转成错误事件
        job.error = str(e)
        job.emit({"type": "error", "message": str(e)})
        nsatlog.log_app(f"job出错 kind={job.kind} error={e}")
    finally:
        if old_stdout is not None:
            sys.stdout = old_stdout
        job.done = True
        job.emit({"type": "done"})
        nsatlog.log_app(f"job结束 kind={job.kind} ok={job.error is None}")


def _run_check(job: Job) -> None:
    from ..parser import validate
    from ..errors import ParseError

    try:
        with open(job.target, "r", encoding="utf-8") as f:
            text = f.read()
        validate(text, path=job.target)
        job.emit({"type": "check_result", "ok": True, "issues": []})
    except ParseError as e:
        job.emit({
            "type": "check_result",
            "ok": False,
            "issues": [{"line": e.line, "message": str(e)}],
        })
    except OSError as e:
        job.emit({"type": "check_result", "ok": False, "issues": [{"line": None, "message": str(e)}]})


def _run_ask_turn(job: Job, cfg, provider) -> None:
    """AI 助手单轮对话（带工具 + 权限）."""
    from ..permissions import PermissionManager
    from ..tools import run_tool_loop
    from ..tools.file_tools import ToolContext
    from ..errors import AIError

    perm_cfg = cfg.get("permissions", {})
    ui = WebUI(job)
    permission = PermissionManager(mode=perm_cfg.get("mode", "ask"), ask_fn=ui.ask_permission)
    ctx = ToolContext(
        root=os.path.abspath(job.target),
        permission=permission,
        allow_run_command=bool(perm_cfg.get("allow_run_command", False)),
    )
    messages = job.history()
    message = job.options.get("message", "")
    messages.append({"role": "user", "content": message})
    try:
        run_tool_loop(provider, messages, ctx, permission)
        reply = messages[-1].get("content", "")
    except AIError:
        resp = provider.chat(messages, tools=None)
        reply = resp.get("content", "")
        messages.append({"role": "assistant", "content": reply})
    job.emit({"type": "assistant_reply", "text": reply})