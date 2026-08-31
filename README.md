# NSAT — 自然语言编程工作台

> ⚠️ 警告：本项目的绝大部分文件甚至包括 README 文件都是 AI 创作，本人（Ma3t1r）只是用AI帮助还原一下自己的想法，其做出来的成品会存在很多BUG，漏洞等安全问题，软件仅供参考！
> 此项目欢迎各位志同道合者一起完善，欢迎加入我们交流群1109955255共同交流！

用自然语言（中文优先）描述程序逻辑，AI 负责补全逻辑并编译成目标语言（Python / Go / Rust / C++ / Java…）。提供 CLI 与桌面应用（VSCode 风格 UI），支持单文件 / 多文件工程、逻辑审查、迭代测试、插件扩展。

## 核心思路

- **人写逻辑，AI 写代码**：用「自然语言 + 少量结构化规则」写 `.nsat` 文件，不直接面对目标语言语法。
- **两阶段生成**：AI 先补全 NSAT、理清逻辑（可上报逻辑疑点交你决定），再基于补全版忠实翻译为目标代码。
- **维护 NSAT，测试目标代码**：迭代时改 `.nsat`，目标代码每次重新生成。
- **你的原始文件永远不动**：AI 补全版与目标代码都写入 `out/` 目录。

## 特性

- 📝 **NSAT 语言**：缩进定块、`[]` 标记专有名词、`//` 注释、首行声明目标语言
- 🧠 **AI 翻译引擎**：DeepSeek / OpenAI / Anthropic / 任意 OpenAI 兼容接口
- 🖥️ **桌面 UI**（PyWebview + CodeMirror 6，VSCode 风格）：文件树、多标签编辑器、右键菜单、终端输出、设置窗口、AI 助手、单实例、会话记忆
- 📦 **单文件 / 多文件工程**：多文件按模块生成同名目标文件并用 import 协作；单文件模式把相关函数内联成一个文件
- 🔍 **逻辑审查**：AI 检测可疑逻辑，询问「继续 / AI 修复 / 自己给方案 / 自己改」
- 🔌 **插件系统**：往 `plugins/` 放 `.py` 即可注册新语言 / 新 AI 工具
- 📦 **打包成 exe**：一键构建独立 Windows 应用（PyInstaller）

## NSAT 语言规则

```nsat
我想把这个文件编译成 Python

// 计算 1 到 n 的和
将 [n] 初始化为 100
将 [total] 初始化为 0
循环 [i] 从 [1] 到 [n]：
    将 [total] 加上 [i]
输出 [total] // 对应 Python: print(total)
```

| 规则 | 说明 |
| --- | --- |
| 第一行 | 目标语言声明（自然语言）；空白则由你选择 |
| 缩进 | 界定代码块（类似 Python，4 空格或 Tab） |
| 冒号 | 循环 / 判断等块语句以 `:` 结尾 |
| `[]` | 专有名词（变量 / 函数 / 模块名） |
| `//` | 行注释 |
| 文件引用 | `引用文件 [utils.nsat]`（多文件工程） |

## 安装与使用

### 作为 CLI（开发模式）

```bash
pip install -e .            # 或仅用 requests：pip install requests
export NSAT_API_KEY="sk-..."   # Windows: $env:NSAT_API_KEY="sk-..."
nsat init                    # 生成配置
nsat check examples/fib.nsat # 本地校验
nsat run examples/fib.nsat   # 补全 → 生成 → 运行 → 迭代
nsat build examples/hello.nsat -o dist
nsat review examples/fib.nsat
nsat ask --project .         # 终端 AI 助手
```

### 桌面应用

```bash
pip install pywebview        # 桌面窗口依赖
nsat ui                      # 启动桌面 UI
nsat ui --project examples   # 指定默认项目
```

### 打包独立 exe（Windows）

```bash
python scripts/build_exe.py  # 产物在 dist\NSAT-Studio\NSAT-Studio.exe
python nsat_ui.pyw assoc     # 注册 .nsat 文件关联与图标（Windows）
```

## 配置

- **用户级设置**（API Key 等全局配置）：`%APPDATA%/nsat/settings.json`，也可在 UI「设置 → 打开设置」中配置，支持自动保存。
- **项目级配置**：`nsatconfig.json`（见 `nsatconfig.example.json`），可覆盖全局。
- API Key 也可用环境变量 `NSAT_API_KEY`（优先级最高）。

## 插件

`plugins/` 目录下的 `.py` 文件会被自动加载，可注册新语言或新 AI 工具：

```python
def register(ctx):
    ctx.register_language("lua", ["lua"], "lua")
    ctx.register_tool("read_json", "读取并解析 JSON", {...参数...}, impl=my_impl, operation="read")
```

## 目录结构

```
nsat/
├── cli.py         # 命令行
├── parser.py      # NSAT 本地校验
├── workflow.py    # 两阶段生成 / 迭代 / 多文件
├── prompts.py     # AI 提示词
├── protocol.py    # AI JSON 信封协议
├── runner.py      # 目标语言运行 / 编译
├── permissions.py # 权限系统
├── plugins.py     # 插件加载
├── logging.py     # 每日日志（log/，30 天自动清理）
├── ai/            # DeepSeek / OpenAI / Anthropic / 兼容接口
├── tools/         # AI 工具（读 / 写 / 改 / 删文件等）
└── ui/            # 桌面 UI（server + 前端 + PyWebview 入口）
examples/          # 示例 .nsat
tests/             # 单元测试
scripts/build_exe.py
```

## 开发

```bash
pip install -e ".[dev]"
python -m unittest discover -s tests
```

## License

GPLv3
