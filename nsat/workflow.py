# -*- coding: utf-8 -*-
"""NSAT 核心工作流：两步生成（先补全 NSAT → 再生成代码）、迭代测试、最终编译、AI 助手.

流程约定：
- 不做强制本地语法校验，NSAT 原样交给 AI。
- 阶段一：AI 补全 NSAT、理清逻辑（可能上报 logic_issues / needs_files）。
- 阶段二：基于补全版 NSAT 生成目标代码。
- 补全版 NSAT 与目标代码都写入 out/ 目录，用户的原始文件保持不动。
"""

from __future__ import annotations

import os
from typing import Any

from . import runner as _runner
from .ai.base import AIProvider
from .errors import AIError, NSATError, ProtocolError
from .langs import LANG_EXTENSIONS, detect_language
from .parser import detect_references
from .permissions import PermissionManager, PermissionDecision
from .prompts import (
    ASSISTANT_SYSTEM_PROMPT,
    build_codegen_messages,
    build_complete_messages,
    build_review_messages,
)
from .protocol import Envelope, parse_codegen, parse_envelope, parse_review


class UI:
    """交互载体抽象：CLI 用控制台，GUI 用对话框."""

    def input(self, prompt: str) -> str:
        raise NotImplementedError

    def choose_language(self, options: list[str]) -> str:
        raise NotImplementedError

    def choose_entry(self, options: list[str]) -> str:
        """多文件时选择入口文件（options 为绝对路径），返回选中项."""
        raise NotImplementedError

    def handle_logic_issues(self, issues: list) -> str:
        """返回 proceed / refix / custom / manual / quit."""
        raise NotImplementedError

    def provide_file(self, fname: str) -> tuple[bool, str | None]:
        """用户为 needs_files 提供文件内容。返回 (是否提供, 内容)."""
        raise NotImplementedError

    def next_instruction(self) -> str | None:
        """询问下一轮修改意见；返回 None 表示结束."""
        raise NotImplementedError

    def ask_permission(self, operation: str, path: str) -> PermissionDecision:
        raise NotImplementedError


# ---------------------------------------------------------------- 工具函数

def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def first_line(text: str) -> str:
    lines = text.splitlines()
    return lines[0].strip() if lines else ""


def default_out_dir(entry_path: str) -> str:
    """AI 编译输出目录：入口文件同名 + _out（如 fib.nsat → fib_out/）."""
    entry_path = os.path.abspath(entry_path)
    stem = os.path.splitext(os.path.basename(entry_path))[0]
    return os.path.join(os.path.dirname(entry_path), f"{stem}_out")


def _rel_key(path: str, base: str) -> str:
    return os.path.relpath(path, base).replace("\\", "/")


def gather_related_files(entry_path: str, depth: int) -> tuple[dict[str, str], list[str]]:
    """递归收集入口文件引用的其他文件。

    返回 (name->content, 缺失文件列表).
    """
    related: dict[str, str] = {}
    missing: list[str] = []
    seen: set[str] = set()
    entry_abs = os.path.abspath(entry_path)
    entry_dir = os.path.dirname(entry_abs)

    def walk(path: str, d: int) -> None:
        if d < 0 or path in seen:
            return
        seen.add(path)
        try:
            text = read_text(path)
        except OSError:
            return
        if path != entry_abs:  # 入口文件本身不注入
            related[_rel_key(path, entry_dir)] = text
        if d == 0:
            return
        for ref in detect_references(text):
            ref_path = os.path.join(os.path.dirname(path), ref)
            if os.path.isfile(ref_path):
                walk(os.path.abspath(ref_path), d - 1)
            else:
                missing.append(ref)

    walk(entry_abs, depth)
    return related, missing


def _find_file_in_dirs(name: str, dirs: list[str]) -> str | None:
    """在若干目录内按文件名查找（精确、再大小写不敏感递归）."""
    base = os.path.basename(name.replace("\\", "/"))
    for d in dirs:
        cand = os.path.join(d, base)
        if os.path.isfile(cand):
            return cand
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for root, _dirs, fns in os.walk(d):
            for fn in fns:
                if fn.lower() == base.lower():
                    return os.path.join(root, fn)
    return None


def _complete_nsat(
    provider: AIProvider,
    language: str,
    nsat_name: str,
    nsat_text: str,
    related: dict[str, str],
    history: list[dict[str, str]],
    instruction: str | None,
    ui: UI,
    nsat_dir: str,
    *,
    module_inventory: list[str] | None = None,
    search_dirs: list[str] | None = None,
) -> Envelope:
    """阶段一：补全 NSAT、理清逻辑；处理 needs_files 后重试."""
    search_dirs = search_dirs or [nsat_dir]
    extra_note: str | None = None
    for _ in range(3):
        messages = build_complete_messages(
            language=language,
            nsat_name=nsat_name,
            nsat_text=nsat_text,
            related_files=related,
            history=history,
            instruction=instruction,
            extra_note=extra_note,
            module_inventory=module_inventory,
        )
        reply = provider.complete_text(messages)
        env = parse_envelope(reply)
        if not env.needs_files:
            return env
        # 处理 needs_files：先自动匹配项目内文件，再询问用户
        added = False
        for fname in env.needs_files:
            resolved = _find_file_in_dirs(fname, search_dirs)
            if resolved:
                key = os.path.basename(fname.replace("\\", "/"))
                related[key] = read_text(resolved)
                added = True
                continue
            ok, content = ui.provide_file(fname)
            if ok and content is not None:
                related[os.path.basename(fname.replace("\\", "/"))] = content
                added = True
        if added:
            extra_note = f"已按你上次的 needs_files 请求补充文件：{', '.join(env.needs_files)}，请重新补全。"
            continue
        extra_note = "你上次请求的文件用户未提供，请忽略它们并基于现有信息继续。"
    raise ProtocolError("补全在 needs_files 循环中重试次数过多")


def _gen_code(
    provider: AIProvider,
    language: str,
    completed_nsat: str,
    nsat_name: str,
    related: dict[str, str],
    *,
    module_inventory: list[str] | None = None,
) -> str:
    """阶段二：基于补全版 NSAT 生成目标代码."""
    last_err: Exception | None = None
    for _ in range(2):
        messages = build_codegen_messages(
            language, completed_nsat, nsat_name,
            related_files=related, module_inventory=module_inventory,
        )
        try:
            reply = provider.complete_text(messages)
            code, notes = parse_codegen(reply)
            if notes:
                print(f"[代码生成说明] {notes}")
            return code
        except ProtocolError as e:
            last_err = e
    raise ProtocolError(f"代码生成返回解析失败: {last_err}")


def resolve_language(text: str, ui: UI) -> str:
    """根据首行判断目标语言；无法判断或空白时询问用户."""
    lang = detect_language(first_line(text))
    if lang:
        return lang
    return ui.choose_language(["python", "go", "rust"])


# ---------------------------------------------------------------- 命令

def run_project(
    cfg: dict[str, Any],
    provider: AIProvider,
    nsat_path: str,
    ui: UI,
    *,
    target_lang: str | None = None,
) -> None:
    """临时测试：两步生成 → 产物写入 out/ → 运行 → 迭代."""
    nsat_path = os.path.abspath(nsat_path)
    base_name = os.path.splitext(os.path.basename(nsat_path))[0]
    nsat_dir = os.path.dirname(nsat_path)
    out_dir = default_out_dir(nsat_path)

    current_text = read_text(nsat_path)
    language = target_lang or resolve_language(current_text, ui)
    src = "--lang 参数" if target_lang else ("首行声明" if first_line(current_text).strip() else "用户选择")
    print(f"[目标语言] {language}（来源：{src}）")

    history: list[dict[str, str]] = []
    instruction: str | None = None
    retry_fix = False

    while True:
        related, missing = gather_related_files(nsat_path, cfg.get("context", {}).get("follow_refs_depth", 3))
        if missing:
            print(f"[提示] 引用的文件未找到: {', '.join(missing)}（AI 会自行处理）")

        # 阶段一：补全 NSAT
        print("[阶段一] AI 补全 NSAT…")
        completed = _complete_nsat(
            provider, language, os.path.basename(nsat_path), current_text,
            related, history, instruction, ui, nsat_dir,
            search_dirs=[nsat_dir],
        )

        if not retry_fix:
            decision = _handle_logic_issues(completed, cfg.get("logic_errors", {}).get("mode", "ask"), ui)
            if decision == "quit":
                return
            if decision == "refix":
                instruction = "AI 检测到逻辑问题，请按你提出的建议修复后重新补全，其余保持不变。"
                current_text = completed.nsat
                retry_fix = True
                continue
            if decision == "custom":
                solution = ui.input("请输入你的解决方案（自然语言）：\n> ").strip()
                if solution:
                    instruction = f"用户自己给出了解决方案，请严格按它实现：{solution}"
                    current_text = completed.nsat
                    retry_fix = True
                    continue
                # 没输入内容则视为继续
            if decision == "manual":
                nsat_out = os.path.join(out_dir, f"{base_name}.nsat")
                write_text(nsat_out, completed.nsat)
                ui.input(f"已把 AI 补全版写出 {nsat_out}，请直接修改后按回车继续…")
                try:
                    current_text = read_text(nsat_out)
                except OSError:
                    ui.input("读取修改后的文件失败，按回车放弃本轮修改…")
                    current_text = completed.nsat
                instruction = None
                retry_fix = True
                continue

        retry_fix = False
        used_instruction = instruction
        instruction = None  # 单次指令用完后清空，防止重复应用

        # 写补全版 NSAT 到 out 目录
        nsat_out = os.path.join(out_dir, f"{base_name}.nsat")
        write_text(nsat_out, completed.nsat)
        print(f"[产物] {nsat_out}")

        # 阶段二：生成目标代码
        print("[阶段二] AI 生成目标代码…")
        target_code = _gen_code(provider, language, completed.nsat, f"{base_name}.nsat", related)
        ext = LANG_EXTENSIONS.get(language, "txt")
        target_out = os.path.join(out_dir, f"{base_name}.{ext}")
        write_text(target_out, target_code)
        print(f"[产物] {target_out}")

        # 运行
        run_cmd = " + ".join((cfg.get("targets", {}).get(language, {}).get("run") or [language]))
        print(f"[运行] {run_cmd} {target_out}")
        result = _runner.run_target(language, cfg, target_out, cwd=out_dir)
        print("---- 运行结果 ----")
        print(result.summary())
        print("------------------")
        history.append({"instruction": used_instruction or "(首次翻译)", "result": result.summary()})

        instr = ui.next_instruction()
        if instr is None:
            break
        instruction = instr
        current_text = completed.nsat  # 以补全版 NSAT 为基础继续迭代
        print()


def _handle_logic_issues(env: Envelope, mode: str, ui: UI) -> str:
    issues = env.logic_issues
    if not issues:
        return "proceed"
    if mode == "ignore":
        print("[逻辑检查] 已配置为忽略所有可疑逻辑问题")
        return "proceed"
    if mode == "auto_fix":
        print("[逻辑检查] auto_fix 模式：按 AI 翻译继续，可疑问题如下：")
        for it in issues:
            print(f"  {it}")
        return "proceed"
    return ui.handle_logic_issues(issues)


def review(cfg: dict[str, Any], provider: AIProvider, nsat_path: str, ui: UI) -> None:
    text = read_text(nsat_path)
    messages = build_review_messages(text)
    reply = provider.complete_text(messages)
    issues = parse_review(reply)
    if not issues:
        print("未发现明显逻辑问题。")
    for it in issues:
        print(it)


def final_build(
    cfg: dict[str, Any],
    provider: AIProvider,
    entry_path: str,
    out_dir: str,
    ui: UI,
    *,
    target_lang: str | None = None,
) -> None:
    """最终编译：两步生成 → 产物写入 out/ → 调用目标语言编译器."""
    entry_path = os.path.abspath(entry_path)
    base_name = os.path.splitext(os.path.basename(entry_path))[0]
    nsat_dir = os.path.dirname(entry_path)

    current_text = read_text(entry_path)
    language = target_lang or resolve_language(current_text, ui)
    src = "--lang 参数" if target_lang else ("首行声明" if first_line(current_text).strip() else "用户选择")
    print(f"[目标语言] {language}（来源：{src}）")

    related, missing = gather_related_files(entry_path, cfg.get("context", {}).get("follow_refs_depth", 99))
    if missing:
        print(f"[提示] 引用的文件未找到: {', '.join(missing)}")

    print("[阶段一] AI 补全 NSAT…")
    completed = _complete_nsat(
        provider, language, os.path.basename(entry_path), current_text,
        related, [], None, ui, nsat_dir,
        search_dirs=[nsat_dir],
    )
    if completed.logic_issues:
        print("[逻辑检查] 可疑问题（未阻止编译）：")
        for it in completed.logic_issues:
            print(f"  {it}")

    os.makedirs(out_dir, exist_ok=True)
    nsat_out = os.path.join(os.path.abspath(out_dir), f"{base_name}.nsat")
    write_text(nsat_out, completed.nsat)
    print(f"[产物] {nsat_out}")

    print("[阶段二] AI 生成目标代码…")
    target_code = _gen_code(provider, language, completed.nsat, f"{base_name}.nsat", related)
    ext = LANG_EXTENSIONS.get(language, "txt")
    target_out = os.path.join(os.path.abspath(out_dir), f"{base_name}.{ext}")
    write_text(target_out, target_code)
    print(f"[产物] {target_out}")

    result = _runner.compile_target(language, cfg, target_out, cwd=os.path.abspath(out_dir))
    print("---- 编译结果 ----")
    print(result.summary())
    print("------------------")
    if result.ok:
        print(f"[完成] 最终程序位于 {out_dir}")


# ---------------------------------------------------------------- 多文件（文件夹）模式

SKIP_DIRS = {"out", "dist", ".git", "__pycache__", ".idea"}


def _skip_dir(name: str) -> bool:
    return name in SKIP_DIRS or name.endswith("_out")


def _find_nsat_files(folder: str) -> dict[str, str]:
    """递归扫描文件夹，返回 {绝对路径: 相对名}."""
    folder = os.path.abspath(folder)
    found: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if not _skip_dir(d)]
        for fn in filenames:
            if fn.lower().endswith(".nsat"):
                p = os.path.abspath(os.path.join(dirpath, fn))
                found[p] = os.path.relpath(p, folder).replace("\\", "/")
    return found


def _build_graph(files: dict[str, str]) -> dict[str, set[str]]:
    """基于 [xxx.nsat] 引用建依赖图（边指向被引用文件）."""
    graph: dict[str, set[str]] = {}
    for abs_path in files:
        graph[abs_path] = set()
        try:
            text = read_text(abs_path)
        except OSError:
            continue
        base_dir = os.path.dirname(abs_path)
        for ref in detect_references(text):
            cand = os.path.abspath(os.path.join(base_dir, ref))
            if cand in files:
                graph[abs_path].add(cand)
                continue
            # 按文件名兜底匹配（同目录外）
            for other in files:
                if os.path.basename(other).lower() == os.path.basename(ref).lower():
                    graph[abs_path].add(other)
                    break
    return graph


def _find_entry(files: dict[str, str], graph: dict[str, set[str]], ui: UI) -> str:
    abs_list = list(files)
    incoming = {a: 0 for a in abs_list}
    for src, dsts in graph.items():
        for d in dsts:
            incoming[d] = incoming.get(d, 0) + 1
    candidates = [a for a in abs_list if incoming[a] == 0] or abs_list

    mainish = [a for a in candidates if os.path.basename(a).lower()
               in ("main.nsat", "入口.nsat", "entry.nsat", "index.nsat")]
    if len(mainish) == 1:
        return mainish[0]
    if len(candidates) == 1:
        return candidates[0]
    return _pick(candidates, files, ui)


def _pick(candidates: list[str], files: dict[str, str], ui: UI) -> str:
    display = [(a, files[a]) for a in candidates]
    selected = ui.choose_entry([rel for _, rel in display])
    for a, rel in display:
        if rel == selected:
            return a
    return candidates[0]


def _reachable(entry: str, graph: dict[str, set[str]]) -> set[str]:
    seen: set[str] = set()
    stack = [entry]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(graph.get(cur, set()) - seen)
    return seen


def _module_base_text(module_abs: str, out_dir: str) -> str:
    """模块当前文本：优先取 out/ 里的补全版，否则取原文件."""
    cand = os.path.join(out_dir, os.path.basename(module_abs))
    if os.path.isfile(cand):
        return read_text(cand)
    return read_text(module_abs)


def _gen_module(
    cfg: dict[str, Any],
    provider: AIProvider,
    module_abs: str,
    files: dict[str, str],
    out_dir: str,
    base_dir: str,
    language: str,
    ui: UI,
    *,
    history: list[dict[str, str]] | None = None,
    instruction: str | None = None,
    module_inventory: list[str] | None = None,
    nsat_dir: str | None = None,
) -> Envelope:
    """生成单个模块：阶段一补全 + 阶段二生成，产物写入 out/."""
    base_name = os.path.splitext(os.path.basename(module_abs))[0]
    nsat_dir = nsat_dir or os.path.dirname(module_abs)
    current_text = _module_base_text(module_abs, out_dir)

    # 兄弟模块上下文：优先用 out/ 里的补全版
    related: dict[str, str] = {}
    for other_abs in files:
        if other_abs == module_abs:
            continue
        other_out = os.path.join(out_dir, os.path.basename(other_abs))
        if os.path.isfile(other_out):
            related[os.path.basename(other_out)] = read_text(other_out)
        else:
            related[files[other_abs]] = read_text(other_abs)

    completed = _complete_nsat(
        provider, language, os.path.basename(module_abs), current_text,
        related, history or [], instruction, ui, nsat_dir,
        module_inventory=module_inventory,
        search_dirs=[base_dir, nsat_dir],
    )
    nsat_out = os.path.join(out_dir, f"{base_name}.nsat")
    write_text(nsat_out, completed.nsat)
    print(f"[产物] {nsat_out}")

    code = _gen_code(
        provider, language, completed.nsat, f"{base_name}.nsat",
        related, module_inventory=module_inventory,
    )
    ext = LANG_EXTENSIONS.get(language, "txt")
    target_out = os.path.join(out_dir, f"{base_name}.{ext}")
    write_text(target_out, code)
    print(f"[产物] {target_out}")
    return completed


def resolve_entry_file(target: str, ui: UI) -> str:
    """--inline 模式用：把文件/文件夹解析成单个入口文件的绝对路径."""
    target = os.path.abspath(target)
    if os.path.isfile(target):
        return target
    files = _find_nsat_files(target)
    if not files:
        raise NSATError(f"{target} 下没有找到 .nsat 文件")
    graph = _build_graph(files)
    return _find_entry(files, graph, ui)


def _resolve_project(
    cfg: dict[str, Any],
    target: str,
    ui: UI,
    *,
    target_lang: str | None = None,
) -> tuple[str, dict[str, str], dict[str, set[str]], str, str, str]:
    """解析入口与模块集合。

    返回 (base_dir, files, graph, entry_abs, out_dir, language)。
    files 包含文件夹内全部 .nsat（全部都会生成）。
    """
    target = os.path.abspath(target)
    if os.path.isfile(target):
        base_dir = os.path.dirname(target)
        files = {target: os.path.basename(target)}
        graph = _build_graph(files)
        entry_abs = target
        print(f"[入口] {os.path.basename(target)}")
    else:
        base_dir = target
        files = _find_nsat_files(target)
        if not files:
            raise NSATError(f"{target} 下没有找到 .nsat 文件")
        graph = _build_graph(files)
        entry_abs = _find_entry(files, graph, ui)
        print(f"[入口] {files[entry_abs]}（文件夹内共 {len(files)} 个 .nsat，全部生成）")
    out_dir = default_out_dir(entry_abs)
    os.makedirs(out_dir, exist_ok=True)

    language = target_lang or resolve_language(_module_base_text(entry_abs, out_dir), ui)
    src = "--lang 参数" if target_lang else ("首行声明" if first_line(_module_base_text(entry_abs, out_dir)).strip() else "用户选择")
    print(f"[目标语言] {language}（来源：{src}）")
    return base_dir, files, graph, entry_abs, out_dir, language


def run_project_folder(
    cfg: dict[str, Any],
    provider: AIProvider,
    target: str,
    ui: UI,
    *,
    target_lang: str | None = None,
) -> None:
    """文件夹 / 多文件模式：全量生成 → 跑入口 → 迭代."""
    base_dir, files, graph, entry_abs, out_dir, language = _resolve_project(
        cfg, target, ui, target_lang=target_lang)

    ext = LANG_EXTENSIONS.get(language, "txt")
    inventory = [
        f"{os.path.basename(f)} → {os.path.splitext(os.path.basename(f))[0]}.{ext}"
        for f in sorted(files)
    ]

    history: list[dict[str, str]] = []
    instruction: str | None = None
    retry_fix = False
    mode = cfg.get("logic_errors", {}).get("mode", "ask")

    while True:
        order = [f for f in files if f != entry_abs] + [entry_abs]
        entry_env = None
        for m in order:
            is_entry = (m == entry_abs)
            print(f"[生成模块] {os.path.basename(m)}")
            env = _gen_module(
                cfg, provider, m, files, out_dir, base_dir, language, ui,
                history=history if is_entry else None,
                instruction=instruction if is_entry else None,
                module_inventory=inventory,
            )
            if not is_entry:
                if env.logic_issues:
                    print(f"[逻辑检查 {os.path.basename(m)}] 可疑问题（不阻止，仅供查看）：")
                    for it in env.logic_issues:
                        print(f"  {it}")
                continue
            entry_env = env
            if not retry_fix:
                decision = _handle_logic_issues(env, mode, ui)
                if decision == "quit":
                    return
                if decision == "refix":
                    instruction = "AI 检测到逻辑问题，请按你提出的建议修复后重新补全入口，其余模块保持不变。"
                    retry_fix = True
                    break
                if decision == "custom":
                    solution = ui.input("请输入你的解决方案（自然语言）：\n> ").strip()
                    if solution:
                        instruction = f"用户自己给出了解决方案，请严格按它实现：{solution}"
                        retry_fix = True
                        break
                if decision == "manual":
                    entry_out = os.path.join(out_dir, os.path.basename(entry_abs))
                    write_text(entry_out, env.nsat)
                    ui.input(f"已把入口补全版写出 {entry_out}，请直接修改后按回车继续…")
                    retry_fix = True
                    break

        if retry_fix:
            retry_fix = False
            continue

        used_instruction = instruction
        instruction = None
        entry_target = os.path.join(out_dir, f"{os.path.splitext(os.path.basename(entry_abs))[0]}.{ext}")
        run_cmd = " + ".join((cfg.get("targets", {}).get(language, {}).get("run") or [language]))
        print(f"[运行] {run_cmd} {entry_target}")
        result = _runner.run_target(language, cfg, entry_target, cwd=out_dir)
        print("---- 运行结果 ----")
        print(result.summary())
        print("------------------")
        history.append({"instruction": used_instruction or "(首次翻译)", "result": result.summary()})

        instr = ui.next_instruction()
        if instr is None:
            break
        instruction = instr
        print()


def final_build_folder(
    cfg: dict[str, Any],
    provider: AIProvider,
    target: str,
    out_dir: str,
    ui: UI,
    *,
    target_lang: str | None = None,
) -> None:
    """文件夹模式最终编译：全量生成 → 编译入口."""
    base_dir, files, graph, entry_abs, _, language = _resolve_project(
        cfg, target, ui, target_lang=target_lang)

    ext = LANG_EXTENSIONS.get(language, "txt")
    inventory = [
        f"{os.path.basename(f)} → {os.path.splitext(os.path.basename(f))[0]}.{ext}"
        for f in sorted(files)
    ]
    out_dir = os.path.abspath(out_dir) if out_dir else default_out_dir(entry_abs)
    os.makedirs(out_dir, exist_ok=True)

    for m in sorted(files):
        print(f"[生成模块] {os.path.basename(m)}")
        _gen_module(
            cfg, provider, m, files, out_dir, base_dir, language, ui,
            module_inventory=inventory,
        )

    entry_name = os.path.splitext(os.path.basename(entry_abs))[0]
    entry_target = os.path.join(out_dir, f"{entry_name}.{ext}")
    result = _runner.compile_target(language, cfg, entry_target, cwd=out_dir)
    print("---- 编译结果 ----")
    print(result.summary())
    print("------------------")
    if result.ok:
        print(f"[完成] 最终程序位于 {out_dir}")


def assistant_chat(cfg: dict[str, Any], provider: AIProvider, root: str, ui: UI) -> None:
    """AI 助手对话：项目级问答 + 工具调用 + 权限."""
    from .tools import run_tool_loop

    perm_cfg = cfg.get("permissions", {})
    permission = PermissionManager(
        mode=perm_cfg.get("mode", "ask"), ask_fn=ui.ask_permission
    )
    from .tools.file_tools import ToolContext

    ctx = ToolContext(
        root=os.path.abspath(root),
        permission=permission,
        allow_run_command=bool(perm_cfg.get("allow_run_command", False)),
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": ASSISTANT_SYSTEM_PROMPT}
    ]
    print(f"AI 助手已就绪（项目根：{ctx.root}）。输入 exit 退出。")

    while True:
        try:
            text = ui.input("你> ")
        except EOFError:
            print()
            break
        text = text.strip()
        if not text:
            continue
        if text.lower() in ("exit", "quit", "退出", "q"):
            break
        messages.append({"role": "user", "content": text})
        try:
            run_tool_loop(provider, messages, ctx, permission)
        except AIError:
            # 降级：不支持工具调用的模型 → 纯文本对话
            try:
                reply = provider.chat(messages, tools=None)
            except AIError as e:
                print(f"[错误] {e}")
                messages.pop()
                continue
            messages.append({"role": "assistant", "content": reply.get("content", "")})
            print(f"AI> {reply.get('content', '')}")
            continue
        # run_tool_loop 已把最终 assistant 消息追加进 messages
        content = messages[-1].get("content", "")
        print(f"AI> {content}")