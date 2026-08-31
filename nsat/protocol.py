# -*- coding: utf-8 -*-
"""AI 返回的 JSON 信封协议解析与校验."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .errors import ProtocolError


@dataclass
class LogicIssue:
    line: int | None
    concern: str
    suggestion: str
    severity: str = "warning"

    def __str__(self) -> str:
        loc = f"第 {self.line} 行" if self.line else "全文"
        return f"[{self.severity}] {loc}: {self.concern}\n        建议: {self.suggestion}"


@dataclass
class Envelope:
    nsat: str = ""
    target_code: str = ""
    logic_issues: list[LogicIssue] = field(default_factory=list)
    needs_files: list[str] = field(default_factory=list)
    notes: str = ""


def extract_json(text: str) -> dict[str, Any]:
    """从 AI 回复中提取 JSON 对象（容忍代码块围栏与前后废话）."""
    if not text or not text.strip():
        raise ProtocolError("AI 返回内容为空")
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    s, e = t.find("{"), t.rfind("}")
    if s == -1 or e == -1 or e <= s:
        raise ProtocolError("AI 返回中未找到 JSON 对象")
    try:
        return json.loads(t[s : e + 1])
    except json.JSONDecodeError as err:
        raise ProtocolError(f"AI 返回的 JSON 解析失败: {err}")


def parse_envelope(text: str) -> Envelope:
    data = extract_json(text)
    issues = []
    for it in data.get("logic_issues") or []:
        if not isinstance(it, dict):
            continue
        issues.append(
            LogicIssue(
                line=it.get("line"),
                concern=str(it.get("concern", "")),
                suggestion=str(it.get("suggestion", "")),
                severity=str(it.get("severity", "warning")),
            )
        )
    env = Envelope(
        nsat=str(data.get("nsat", "")),
        target_code=str(data.get("target_code", "")),
        logic_issues=issues,
        needs_files=[str(x) for x in (data.get("needs_files") or [])],
        notes=str(data.get("notes", "")),
    )
    if not env.nsat and not env.target_code:
        # 允许仅 review 场景（只返回 logic_issues）
        if issues:
            return env
        raise ProtocolError("AI 返回信封缺少 nsat / target_code 字段")
    return env


def parse_review(text: str) -> list[LogicIssue]:
    data = extract_json(text)
    issues = []
    for it in data.get("logic_issues") or []:
        if not isinstance(it, dict):
            continue
        issues.append(
            LogicIssue(
                line=it.get("line"),
                concern=str(it.get("concern", "")),
                suggestion=str(it.get("suggestion", "")),
                severity=str(it.get("severity", "warning")),
            )
        )
    return issues


def parse_codegen(text: str) -> tuple[str, str]:
    """解析阶段二（代码生成）返回，返回 (target_code, notes)."""
    data = extract_json(text)
    code = str(data.get("target_code") or "").strip()
    if not code:
        raise ProtocolError("AI 返回的 target_code 为空")
    return code, str(data.get("notes", ""))