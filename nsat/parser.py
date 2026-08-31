# -*- coding: utf-8 -*-
"""NSAT 本地语法校验层。

不消耗 AI 的机械规则：
1. 首行目标语言声明（可为空白；不得以 // 开头）
2. 缩进界定代码块（空格/Tab 不混用，缩进层级合法，冒号行后必须缩进）
3. 冒号块起始标记
4. 方括号配对（不嵌套、不悬空），`//` 在 [] 内不算注释
5. `//` 行注释
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .errors import ParseError

# 半角/全角冒号
_COLON_CHARS = ":："
BOLD_COLON = "\uff1a"


@dataclass
class LineInfo:
    lineno: int            # 原始行号（1 基）
    raw: str               # 原始文本
    code: str              # 去除注释后的代码（保留缩进）
    indent: str            # 缩进字符串（"" 或 n * unit）
    level: int             # 缩进层级
    is_blank: bool = False
    ends_colon: bool = False
    comment: str = ""      # 提取出的注释文本

    @property
    def is_header(self) -> bool:
        return self.lineno == 1


@dataclass
class NSATFile:
    path: str = ""
    lines: list[LineInfo] = field(default_factory=list)
    header: str = ""       # 首行声明原文
    text: str = ""

    def to_text(self) -> str:
        return self.text


# ---------------------------------------------------------------- 底层工具

def split_comment(line: str) -> tuple[str, str]:
    """把一行拆成「代码 + 注释」。[] 内的 // 不算注释。

    返回 (code_part, comment_text)。
    """
    out: list[str] = []
    in_bracket = False
    i, n = 0, len(line)
    while i < n:
        ch = line[i]
        if ch == "[":
            in_bracket = True
            out.append(ch)
            i += 1
        elif ch == "]":
            in_bracket = False
            out.append(ch)
            i += 1
        elif not in_bracket and ch == "/" and i + 1 < n and line[i + 1] == "/":
            return "".join(out).rstrip(), line[i:]
        else:
            out.append(ch)
            i += 1
    return "".join(out).rstrip(), ""


def _check_brackets(code: str, lineno: int) -> None:
    """校验一行内方括号配对与不嵌套."""
    depth = 0
    for ch in code:
        if ch == "[":
            depth += 1
            if depth > 1:
                raise ParseError("[] 不允许嵌套", lineno)
        elif ch == "]":
            depth -= 1
            if depth < 0:
                raise ParseError("多余的 ]，缺少对应的 [", lineno)
    if depth > 0:
        raise ParseError("未闭合的 [，缺少对应的 ]", lineno)


def _match_unit(indent: str) -> str:
    """返回缩进单位：4 空格 或 1 个 Tab；不合法抛错."""
    if not indent:
        raise ValueError("empty indent")
    if "\t" in indent and " " in indent:
        raise ParseError("同一行内混用空格与 Tab，缩进只能使用 4 空格或 1 Tab")
    if indent[0] == "\t":
        if any(c != "\t" for c in indent):
            raise ParseError("缩进混用空格与 Tab，缩进只能使用 4 空格或 1 Tab")
        return "\t"
    if any(c != " " for c in indent):
        raise ParseError("缩进混用空格与 Tab，缩进只能使用 4 空格或 1 Tab")
    if len(indent) % 4 != 0:
        raise ParseError("缩进必须为 4 空格的整数倍（或使用 Tab）")
    return "    "


def _leading(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


# ---------------------------------------------------------------- 主入口

def parse(text: str, path: str = "") -> NSATFile:
    """解析并校验 NSAT 文本，返回结构化结果；失败抛 ParseError."""
    raw_lines = text.splitlines()
    nfile = NSATFile(path=path, text=text)

    if not raw_lines:
        raise ParseError("文件为空")

    # ---- 首行声明
    header = raw_lines[0].strip()
    if header.startswith("//"):
        raise ParseError("第一行必须是目标语言声明，不能以 // 注释开头")
    nfile.header = header

    unit: str | None = None
    infos: list[LineInfo] = []
    last_code: str | None = None  # 上一行代码（用于是否存在冒号等待块）
    last_line: LineInfo | None = None

    for idx, raw in enumerate(raw_lines, start=1):
        lineno = idx
        # 计算缩进（在去注释之前，注释不影响缩进层级）
        stripped = raw.strip()
        info = LineInfo(lineno=lineno, raw=raw, code="", indent="", level=0)
        if not stripped:
            info.is_blank = True
            infos.append(info)
            continue

        code, comment = split_comment(raw)
        if not code:
            # 整行都是注释
            info.code = code
            info.comment = comment
            infos.append(info)
            continue

        _check_brackets(code, lineno)
        leading = _leading(code)
        if leading:
            if unit is None:
                unit = _match_unit(leading)
            if unit == "\t":
                if any(c != "\t" for c in leading):
                    raise ParseError("缩进混用空格与 Tab（文件应统一使用 4 空格或 Tab）", lineno)
                level = len(leading)
            else:
                if len(leading) % 4 != 0 or any(c != " " for c in leading):
                    raise ParseError("缩进混用空格与 Tab（文件应统一使用 4 空格或 Tab）", lineno)
                level = len(leading) // 4
        else:
            level = 0

        info.code = code
        info.indent = leading
        info.level = level
        info.comment = comment

        norm_code = code.replace(BOLD_COLON, ":")
        info.ends_colon = norm_code.endswith(":")

        # ---- 块结构检查
        if last_line is not None and not last_line.is_blank:
            if last_line.ends_colon:
                if level <= last_line.level:
                    raise ParseError(
                        f"以冒号结尾的语句后缺少缩进块（{last_line.code!r} 之后应缩进）", lineno)
            else:
                if level > last_line.level:
                    raise ParseError(f"非冒号行 {last_line.code!r} 之后不能增加缩进", lineno)

        infos.append(info)
        last_line = info

    # 文件以冒号结尾
    was_colon = False
    for info in reversed(infos):
        if info.is_blank or not info.code:
            continue
        was_colon = info.ends_colon
        if was_colon:
            raise ParseError(f"以冒号结尾的语句 {info.code!r} 缺少块内容", info.lineno)
        break

    nfile.lines = infos
    return nfile


_RE_REF = re.compile(r"\[([^\[\]\s]+?\.nsat)\]", re.IGNORECASE)


def detect_references(text: str) -> list[str]:
    """提取文本中引用的其他 NSAT 模块文件名（去重、保持顺序）."""
    seen: list[str] = []
    for m in _RE_REF.findall(text):
        name = m.strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def validate(text: str, path: str = "") -> NSATFile:
    """校验入口：合法返回 NSATFile，不合法抛 ParseError."""
    return parse(text, path=path)