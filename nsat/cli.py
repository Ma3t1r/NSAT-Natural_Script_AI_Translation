# -*- coding: utf-8 -*-
"""CLI 入口：init / check / run / build / review / ask."""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from . import config as _config
from . import workflow
from .ai import create_provider
from .errors import ConfigError, NSATError, ParseError
from .langs import KNOWN_LANGUAGES
from .parser import validate
from .permissions import PermissionDecision

# Windows 控制台 UTF-8 兜底
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


class ConsoleUI(workflow.UI):
    def input(self, prompt: str) -> str:
        try:
            line = input(prompt)
            # PowerShell 以 UTF-8 管道喂数据时会在流开头写 BOM，剥掉它
            return line[1:] if line.startswith("\ufeff") else line
        except EOFError:
            return ""

    def choose_language(self, options: list[str]) -> str:
        all_opts = list(dict.fromkeys(options + KNOWN_LANGUAGES))
        print("未从首行识别到目标语言，请选择：")
        for i, name in enumerate(all_opts, 1):
            print(f"  {i}. {name}")
        while True:
            raw = self.input("请输入序号或语言名：").strip().lower()
            if raw.isdigit():
                idx = int(raw)
                if 1 <= idx <= len(all_opts):
                    return all_opts[idx - 1]
            elif raw:
                for name in all_opts:
                    if name == raw or raw in name:
                        return name
            if not raw:
                raise NSATError("未选择目标语言，已取消")
            print("无效选择，请重试。")

    def choose_entry(self, options: list[str]) -> str:
        print("检测到多个可能的入口文件，请选择：")
        for i, rel in enumerate(options, 1):
            print(f"  {i}. {rel}")
        while True:
            raw = self.input("请输入序号或文件名：").strip()
            if raw.isdigit():
                idx = int(raw)
                if 1 <= idx <= len(options):
                    return options[idx - 1]
            elif raw:
                for rel in options:
                    if raw == rel or raw in rel:
                        return rel
            if not raw:
                raise NSATError("未选择入口文件，已取消")
            print("无效输入。")

    def handle_logic_issues(self, issues: list) -> str:
        print("\n==== AI 检测到可疑逻辑问题 ====")
        for it in issues:
            print(f"  {it}")
        print("===============================")
        while True:
            raw = self.input(
                "如何处理？[回车]=按 AI 翻译继续  f=让 AI 按建议修复  d=我自己给方案  e=我自己改 NSAT  q=退出\n> "
            ).strip().lower()
            if raw == "":
                return "proceed"
            if raw in ("f", "fix"):
                return "refix"
            if raw in ("d", "diy", "custom"):
                return "custom"
            if raw in ("e", "edit"):
                return "manual"
            if raw in ("q", "quit"):
                return "quit"
            print("无效输入。")

    def provide_file(self, fname: str) -> tuple[bool, str | None]:
        cwd = os.getcwd()
        print(f"AI 需要文件 {fname}，但项目里没找到。")
        print(f"输入文件路径即可，支持三种写法：")
        print(f"  1) 绝对路径，如 {os.path.join('C:', '项目', fname)}")
        print(f"  2) 相对当前目录的路径（当前目录={cwd}）")
        print(f"  3) 仅文件名（将自动在项目根下查找）")
        raw = self.input("输入文件路径（回车跳过）：").strip()
        if not raw:
            return False, None
        cand = raw if os.path.isabs(raw) else os.path.join(cwd, raw)
        if not os.path.isfile(cand):
            print(f"文件不存在: {raw}")
            return False, None
        try:
            with open(cand, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError as e:
            print(f"读取失败: {e}")
            return False, None
        return True, content

    def next_instruction(self) -> str | None:
        while True:
            raw = self.input(
                "输入下一轮修改意见，或 /help 查看命令（直接回车结束）: "
            ).strip()
            if not raw:
                return None
            if raw.startswith("/"):
                if self._handle_command(raw) == "exit":
                    return None
                continue  # 帮助/未知命令已打印，重新询问
            return raw

    def _handle_command(self, raw: str) -> str:
        parts = raw.split()
        name = parts[0].lower()
        if name in ("/exit", "/quit", "/q"):
            return "exit"
        if name == "/help":
            print("可用命令：")
            print("  /exit, /quit    退出本次迭代")
            print("  /help           显示本帮助")
            print("其他输入都会被当作对程序的修改意见。")
            return "help"
        print(f"未知命令 {name}，输入 /help 查看可用命令。")
        return "help"

    def ask_permission(self, operation: str, path: str) -> PermissionDecision:
        while True:
            raw = self.input(
                f"AI 请求「{operation}」{path}？  [y]=允许  n=拒绝  a=本会话都允许  r=本会话都拒绝\n> "
            ).strip().lower()
            if raw in ("y", "yes"):
                return PermissionDecision(allowed=True)
            if raw in ("n", "no", ""):
                return PermissionDecision(allowed=False)
            if raw in ("a", "allow"):
                return PermissionDecision(allowed=True, remember=True)
            if raw in ("r", "deny"):
                return PermissionDecision(allowed=False, remember=True)
            print("无效输入，输入 y/n/a/r。")


# ---------------------------------------------------------------- 子命令

def cmd_init(args: argparse.Namespace) -> None:
    cfg = _config.DEFAULT_CONFIG
    print("NSAT 配置向导")
    print("（直接回车使用默认值；要退出按 Ctrl+C）")
    try:
        provider = input("AI 提供商 [deepseek/openai/anthropic/custom，默认 deepseek]: ").strip() or "deepseek"
        if provider not in ("deepseek", "openai", "anthropic", "custom"):
            print(f"未知提供商 {provider}，使用 deepseek")
            provider = "deepseek"
        cfg["ai"]["provider"] = provider
        cfg["ai"]["model"] = input(f"模型名 [默认 {cfg['ai']['model']}]: ").strip() or cfg["ai"]["model"]
        if provider == "custom":
            base = input("base_url（OpenAI 兼容地址）: ").strip()
            if base:
                cfg["ai"]["base_url"] = base
        key = input("API Key（留空则用环境变量 NSAT_API_KEY）: ").strip()
        if key:
            cfg["ai"]["api_key"] = key
        mode = input("逻辑错误处理模式 [ask/ignore/auto_fix，默认 ask]: ").strip() or "ask"
        if mode in ("ask", "ignore", "auto_fix"):
            cfg["logic_errors"]["mode"] = mode
        perm = input("文件操作权限 [ask/allow_all/deny_all，默认 ask]: ").strip() or "ask"
        if perm in ("ask", "allow_all", "deny_all"):
            cfg["permissions"]["mode"] = perm
    except EOFError:
        print()
        print("已取消。")
        return
    path = _config.save_config(cfg)
    print(f"已生成 {path}。")
    if not key:
        print("提示：请设置环境变量 NSAT_API_KEY 后使用。")


def cmd_check(args: argparse.Namespace) -> None:
    try:
        _ensure_exists(args.file)
        if os.path.isdir(args.file):
            raise NSATError(f"check 需要一个 .nsat 文件，收到的是文件夹：{args.file}")
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()
        nfile = validate(text, path=args.file)
    except ParseError as e:
        print(f"[校验失败] {e}")
        sys.exit(1)
    except NSATError as e:
        print(f"[错误] {e}")
        sys.exit(1)
    except OSError as e:
        print(f"[错误] {e}")
        sys.exit(1)
    lang = detect_language_quiet(nfile.header)
    print(f"[校验通过] {args.file}")
    if nfile.header.strip():
        print(f"[首行声明] {nfile.header.strip()}" + (f"  → 识别语言: {lang}" if lang else "（未能识别语言，运行时将询问）"))
    else:
        print("[首行声明] （空白，运行时将询问目标语言）")


def detect_language_quiet(header: str) -> str | None:
    from .langs import detect_language
    return detect_language(header)


def _load_provider():
    cfg = _config.load_config()
    _config.check_provider(cfg)
    return cfg, create_provider(cfg)


def _ensure_exists(path: str) -> None:
    if not os.path.exists(path):
        raise NSATError(f"找不到文件或文件夹：{path}")


def cmd_run(args: argparse.Namespace) -> None:
    try:
        _ensure_exists(args.file)
        cfg, provider = _load_provider()
        ui = ConsoleUI()
        if args.inline:
            entry = workflow.resolve_entry_file(args.file, ui)
            workflow.run_project(cfg, provider, entry, ui, target_lang=args.lang)
        elif os.path.isdir(args.file):
            workflow.run_project_folder(cfg, provider, args.file, ui, target_lang=args.lang)
        else:
            workflow.run_project(cfg, provider, args.file, ui, target_lang=args.lang)
    except NSATError as e:
        print(f"[错误] {e}")
        sys.exit(1)


def cmd_build(args: argparse.Namespace) -> None:
    try:
        _ensure_exists(args.entry)
        cfg, provider = _load_provider()
        ui = ConsoleUI()
        if args.inline:
            entry = workflow.resolve_entry_file(args.entry, ui)
            out_dir = args.out or workflow.default_out_dir(entry)
            workflow.final_build(cfg, provider, entry, out_dir, ui, target_lang=args.lang)
        elif os.path.isdir(args.entry):
            workflow.final_build_folder(cfg, provider, args.entry, args.out, ui, target_lang=args.lang)
        else:
            out_dir = args.out or workflow.default_out_dir(args.entry)
            workflow.final_build(cfg, provider, args.entry, out_dir, ui, target_lang=args.lang)
    except NSATError as e:
        print(f"[错误] {e}")
        sys.exit(1)


def cmd_review(args: argparse.Namespace) -> None:
    try:
        _ensure_exists(args.file)
        if os.path.isdir(args.file):
            raise NSATError(f"review 需要一个 .nsat 文件，收到的是文件夹：{args.file}")
        cfg, provider = _load_provider()
        ui = ConsoleUI()
        workflow.review(cfg, provider, args.file, ui)
    except NSATError as e:
        print(f"[错误] {e}")
        sys.exit(1)


def cmd_ask(args: argparse.Namespace) -> None:
    try:
        cfg, provider = _load_provider()
        ui = ConsoleUI()
        root = args.project or os.getcwd()
        workflow.assistant_chat(cfg, provider, root, ui)
    except NSATError as e:
        print(f"[错误] {e}")
        sys.exit(1)


def cmd_ui(args: argparse.Namespace) -> None:
    from .ui.app import launch

    root = args.project or os.getcwd()
    launch(project_root=root, browser_only=args.browser)


def cmd_open(args: argparse.Namespace) -> None:
    """双击 .nsat 文件时打开桌面 UI 并定位到该文件."""
    from .ui.app import launch

    path = os.path.abspath(args.file)
    if not os.path.exists(path):
        print(f"[错误] 找不到文件：{path}")
        sys.exit(1)
    root = args.project or (os.path.dirname(path) if os.path.isfile(path) else path)
    launch(project_root=root, browser_only=args.browser, open_file=path)


def cmd_assoc(args: argparse.Namespace) -> None:
    """注册 .nsat 文件关联 + 图标（HKCU，无需管理员）."""
    from .winassoc import register_assoc

    ok, msg = register_assoc()
    if ok:
        print(msg)
        print("现在双击任意 .nsat 文件即可用 NSAT Studio 打开。")
    else:
        print(f"[错误] {msg}")
        sys.exit(1)


def cmd_install_ui(args: argparse.Namespace) -> None:
    import subprocess
    import sys as _sys

    pkgs = ["pywebview"]
    print(f"安装 UI 依赖: {', '.join(pkgs)}")
    rc = subprocess.call([_sys.executable, "-m", "pip", "install", *pkgs])
    if rc == 0:
        print("完成。运行 `nsat ui` 启动桌面界面。")
    else:
        print("安装失败，请手动执行: pip install pywebview")
        sys.exit(1)


# ---------------------------------------------------------------- 主入口

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nsat", description="NSAT 自然语言编译器（实验版）")
    parser.add_argument("--version", action="version", version=f"nsat {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="生成 nsatconfig.json")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("check", help="本地语法校验（不调 AI）")
    p.add_argument("file")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("run", help="临时测试：翻译→运行→迭代（支持 .nsat 文件或文件夹）")
    p.add_argument("file")
    p.add_argument("--lang", help="强制目标语言（跳过首行识别）")
    p.add_argument("--inline", action="store_true", help="文件夹时用单文件内联模式（不拆模块）")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("build", help="最终编译：翻译→调用目标语言编译器（支持 .nsat 文件或文件夹）")
    p.add_argument("entry")
    p.add_argument("-o", "--out", help="输出目录（默认入口同目录下 dist）")
    p.add_argument("--lang", help="强制目标语言")
    p.add_argument("--inline", action="store_true", help="文件夹时用单文件内联模式（不拆模块）")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("review", help="只评审逻辑问题")
    p.add_argument("file")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("ask", help="AI 助手对话（项目级问答 + 文件工具）")
    p.add_argument("--project", help="项目根目录（默认当前目录）")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("ui", help="启动桌面界面（PyWebview，未安装时回退浏览器）")
    p.add_argument("--project", help="默认打开的项目根目录")
    p.add_argument("--browser", action="store_true", help="直接用浏览器打开，不用桌面窗口")
    p.set_defaults(func=cmd_ui)

    p = sub.add_parser("open", help="用桌面 UI 打开一个 .nsat 文件（文件关联调用）")
    p.add_argument("file")
    p.add_argument("--project", help="项目根目录（默认文件所在目录）")
    p.add_argument("--browser", action="store_true", help="用浏览器模式")
    p.set_defaults(func=cmd_open)

    p = sub.add_parser("assoc", help="注册 .nsat 文件关联与图标（HKCU）")
    p.set_defaults(func=cmd_assoc)

    p = sub.add_parser("install-ui", help="安装桌面 UI 依赖（pywebview）")
    p.set_defaults(func=cmd_install_ui)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()