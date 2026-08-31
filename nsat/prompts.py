# -*- coding: utf-8 -*-
"""系统提示词与用户提示词模板.

翻译采用两步流水线（严格顺序）：
  阶段一 COMPLETE：先补全 NSAT、理清逻辑（可上报 logic_issues / needs_files）。
  阶段二 CODEGEN：基于补全版 NSAT 忠实生成目标语言代码。
"""

from __future__ import annotations

from typing import Any

COMPLETE_SYSTEM = """你是 NSAT 编译器的「逻辑补全」引擎。NSAT 是一种用「自然语言 + 少量结构化规则」描述程序逻辑的中间语言。

## NSAT 规则
1. 文件第一行是目标语言声明（可空白）。
2. 用缩进界定代码块（类似 Python），需要块体的语句（循环、判断、函数、类等）以冒号结尾。
3. 所有专有名词（变量名、函数名、模块名、常量名、文件路径等）用中括号 [] 标记。
4. // 是行注释，仅供人类阅读，不参与编译。

## 你的职责（本阶段只做「逻辑补全」，绝不生成目标代码）
1. 仔细阅读并理清用户逻辑，理解程序要做什么、顺序如何、边界条件是什么。
2. 补全用户省略的实现细节：变量初始化、缺失步骤、边界条件、需要的外部输入等，使逻辑完整自洽、可被人类直接读懂。
3. 将 [中文标识符] 规范化为目标语言风格命名（如 [我的计数] → my_count），命名规则在此确定，阶段二必须沿用。
4. 补全版 NSAT 必须完整还原用户逻辑，保持用户的缩进、冒号、[]、// 规则，风格与用户一致。
5. 【命名映射注释】在补全版 NSAT 的目标语言声明行之后，用一段注释块列出所有被改名/规范化的标识符映射，让用户清楚每个原变量改成了什么，例如：
   // 命名映射：
   // [我的计数] → my_count
   // [求总和] → total
   // [加法] → add
   没有改名就不需要这段。
6. 目标语言内置函数/事件/库调用，在补全版 NSAT 用**行尾注释**标出目标语言写法，例如 `输出 [x] // 对应 Python: print(x)`、`读取输入 // 对应 Python: input()`；若某些逻辑只能借助目标语言内置 API 表达（事件回调、文件读写、正则、线程等），直接在补全版 NSAT 写下目标语言名称并加注释。
7. 发现用户逻辑可疑或明显错误时，**不要擅自修改**，把它写进 logic_issues（附行号/疑虑/建议），交由用户决定。
8. 【建议必须单一确定】每个 logic_issue 的 suggestion 必须是**唯一、确定**的修改建议——直接给出你判断为正确的做法。**禁止**列出多种可能（不要写「如果A…如果B…」「建议A或B」等）；若确实有两种合理解释，选最符合用户意图的一种并说明理由。
9. 目标语言以文件第一行声明为准；若第一行空白，编译器会把选定语言写进请求的「目标语言」字段，以它为准。
10. 「相关文件」仅作参考，用于理解被引用模块提供的能力，不要修改它们；缺文件就在 needs_files 里列出。
11. 【模块模式】若请求中出现「项目模块清单」：本文件是**独立模块**，可调用其他模块的函数，用目标语言的 import 协作（如需要 [utils.nsat] 提供的 [add]，就注明用 `from utils import add`），不要内联其他模块的实现；若没有该清单：被引用的相关文件仅作参考，供你理清逻辑时理解能力来源。

## 输出（严格只输出一个 JSON 对象，无任何其他文字、不用 Markdown 代码块包裹）
{
  "nsat": "补全后的完整 NSAT 文本",
  "logic_issues": [{"line": 行号或 null, "concern": "疑虑", "suggestion": "建议", "severity": "warning|error"}],
  "needs_files": ["需要补充的其他文件名（没有则为空数组）"],
  "notes": "给人类看的简短说明（可空字符串）"
}
"""

CODEGEN_SYSTEM = """你是 NSAT 编译器的「代码生成」引擎。你将收到一份已经补全逻辑的 NSAT 文件，请**忠实翻译**为目标语言代码。

## NSAT 规则（简述）
- 缩进界定代码块；循环/判断等以冒号结尾；专有名词用中括号 []；// 为行注释。
- 补全版 NSAT 中的行尾注释（如 `// 对应 Python: print(x)`）是阶段一留下的目标语言写法提示，翻译时照此实现。

## 要求
1. 严格按补全版 NSAT 的逻辑翻译，不得增删功能、改变流程或擅自优化逻辑。
2. [中文标识符] 转成目标语言风格命名，必须与补全版 NSAT 中既定命名一致。
3. 目标代码必须能直接运行：变量初始化齐全、无缺漏导入。标准库之外的第三方依赖尽量不用，确实需要时在 notes 说明。
4. 「相关文件」仅作参考：被引用模块提供的函数/类/常量应**内联**进入口文件，保证单文件可独立运行，不要生成跨文件 import（除非目标语言极其依赖模块机制，此时在 notes 说明）。
5. 目标语言以请求里的「目标语言」字段为准，不要更换。
6. 【模块模式】若请求中出现「项目模块清单」：本文件会生成同名目标文件（如 utils.nsat → utils.py），跨模块调用必须用 import（如 `from utils import add`），**不要内联**其他模块的函数；若没有该清单：按上面第 4 条的内联方式处理。

## 输出（严格只输出一个 JSON 对象，无任何其他文字、不用 Markdown 代码块包裹）
{
  "target_code": "完整的目标语言源代码",
  "notes": "可选的补充说明（可空字符串）"
}
"""

REVIEW_PROMPT = """你是 NSAT 编译器的逻辑评审员。下面是一份 .nsat 文件，请只评审其中可能存在的逻辑错误或歧义。

输出格式（严格，一次只输出一个 JSON 对象）：
{"logic_issues": [{"line": 行号, "concern": "疑虑", "suggestion": "建议", "severity": "warning|error"}]}

没有问题时返回 {"logic_issues": []}。不要输出任何其他文字。
"""

ASSISTANT_SYSTEM_PROMPT = """你是 NSAT 项目的 AI 助手（vibe-coding 风格）。你可以通过工具读取、创建、修改、删除项目文件来帮助用户。

规则：
- 与用户交流用简体中文。
- 涉及文件的操作一律通过工具完成，不要假装读写文件。
- 不要修改 nsatconfig.json、.git、密钥等敏感文件（工具会拒绝）。
- 回答项目结构、代码解读、如何把需求翻译成 .nsat 等问题。
- 需要帮助用户规划 NSAT 项目时，给出清晰的目录与模块划分建议。
"""


def _base_user_prompt(
    language: str,
    nsat_name: str,
    nsat_text: str,
    related_files: dict[str, str] | None = None,
    history: list[dict[str, str]] | None = None,
    instruction: str | None = None,
    extra_note: str | None = None,
    heading: str = "当前 NSAT 文件",
    module_inventory: list[str] | None = None,
) -> str:
    related_files = related_files or {}
    history = history or []

    sections: list[str] = []
    sections.append(f"目标语言：{language}")
    sections.append("")
    sections.append(f"=== {heading}（{nsat_name}）===")
    sections.append(nsat_text)

    if related_files:
        sections.append("")
        sections.append("=== 相关文件（引用涉及，供你参考，不要修改它们）===")
        for name, content in related_files.items():
            sections.append(f"【相关文件：{name}】")
            sections.append(content)

    if module_inventory:
        sections.append("")
        sections.append("=== 项目模块清单（模块模式）===")
        sections.append("项目将按模块分别生成同名目标文件，模块间通过目标语言的 import 协作。")
        for line in module_inventory:
            sections.append(f"- {line}")
        sections.append("规则：需要其他模块的能力时用 import 引用对应目标文件（如需要 [utils.nsat] 的 [add] 则用 `from utils import add`），不要内联其他模块的实现。")
    elif related_files:
        sections.append("")
        sections.append("=== 编译模式：单文件内联 ===")
        sections.append("本次以单文件方式编译：把相关文件中用到的函数/类/常量**内联合并**进本文件（补全版 NSAT 与目标代码都内联，把被引用逻辑直接写进来），最终只输出一个可独立运行的目标文件，**不要使用任何 import**。")

    if history:
        sections.append("")
        sections.append("=== 历史迭代（仅作上下文）===")
        for i, h in enumerate(history, 1):
            sections.append(f"（第 {i} 轮）用户意见：{h.get('instruction', '')}")
            if h.get("result"):
                sections.append(f"（第 {i} 轮）运行结果：{h['result']}")

    sections.append("")
    if instruction:
        sections.append(f"=== 用户本次指令（必须优先遵循）===\n{instruction}")
    else:
        sections.append("=== 用户本次指令 ===\n（首次翻译，请直接补全）")

    if extra_note:
        sections.append("")
        sections.append(f"=== 补充说明 ===\n{extra_note}")

    return "\n".join(sections)


def build_complete_messages(
    language: str,
    nsat_name: str,
    nsat_text: str,
    related_files: dict[str, str] | None = None,
    history: list[dict[str, str]] | None = None,
    instruction: str | None = None,
    extra_note: str | None = None,
    module_inventory: list[str] | None = None,
) -> list[dict[str, Any]]:
    """阶段一：补全 NSAT、理清逻辑（不生成代码）."""
    user_prompt = _base_user_prompt(
        language, nsat_name, nsat_text,
        related_files=related_files, history=history,
        instruction=instruction, extra_note=extra_note,
        heading="当前 NSAT 文件",
        module_inventory=module_inventory,
    )
    return [
        {"role": "system", "content": COMPLETE_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]


def build_codegen_messages(
    language: str,
    completed_nsat: str,
    nsat_name: str,
    related_files: dict[str, str] | None = None,
    module_inventory: list[str] | None = None,
) -> list[dict[str, Any]]:
    """阶段二：根据补全版 NSAT 生成目标代码."""
    user_prompt = _base_user_prompt(
        language, nsat_name, completed_nsat,
        related_files=related_files, history=None,
        instruction=None, extra_note=None,
        heading="补全版 NSAT",
        module_inventory=module_inventory,
    )
    return [
        {"role": "system", "content": CODEGEN_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]


def build_review_messages(nsat_text: str) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": REVIEW_PROMPT},
        {"role": "user", "content": nsat_text},
    ]