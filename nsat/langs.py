# -*- coding: utf-8 -*-
"""目标语言识别：从 NSAT 首行声明做关键词匹配."""

from __future__ import annotations

# 语言别名表（小写匹配）。顺序即优先级。
LANG_ALIASES: dict[str, list[str]] = {
    "python": ["python", "py"],
    "go": ["go", "golang"],
    "rust": ["rust", "rs"],
    "c": ["c", "c语言", "c 语言"],
    "cpp": ["c++", "cpp", "cplusplus"],
    "java": ["java"],
    "javascript": ["javascript", "js", "node"],
    "typescript": ["typescript", "ts"],
    "csharp": ["c#", "csharp", "cs", "dotnet"],
    "php": ["php"],
    "ruby": ["ruby"],
    "swift": ["swift"],
    "kotlin": ["kotlin"],
    "shell": ["shell", "bash", "sh"],
    "lua": ["lua"],
}

KNOWN_LANGUAGES = sorted(LANG_ALIASES.keys())


def register_language(name: str, aliases: list[str], ext: str) -> None:
    """插件注册自定义语言."""
    global KNOWN_LANGUAGES
    LANG_ALIASES[name] = [a.lower() for a in aliases]
    LANG_EXTENSIONS[name] = ext
    KNOWN_LANGUAGES = sorted(LANG_ALIASES.keys())

# 目标语言 → 文件扩展名
LANG_EXTENSIONS: dict[str, str] = {
    "python": "py",
    "go": "go",
    "rust": "rs",
    "c": "c",
    "cpp": "cpp",
    "java": "java",
    "javascript": "js",
    "typescript": "ts",
    "csharp": "cs",
    "php": "php",
    "ruby": "rb",
    "swift": "swift",
    "kotlin": "kt",
    "shell": "sh",
    "lua": "lua",
}


def detect_language(declaration_line: str) -> str | None:
    """从首行声明识别目标语言。

    唯一命中返回语言名；无法识别或产生歧义返回 None。
    """
    text = declaration_line.strip().lower()
    if not text:
        return None
    hits = [lang for lang, aliases in LANG_ALIASES.items() if any(a in text for a in aliases)]
    if len(hits) == 1:
        return hits[0]
    return None


def describe_options() -> str:
    return ", ".join(KNOWN_LANGUAGES)