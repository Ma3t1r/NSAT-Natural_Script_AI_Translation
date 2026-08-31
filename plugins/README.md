# 插件目录

把 `.py` 插件文件放到这里（或 exe 旁的 `plugins/`、`%APPDATA%/nsat/plugins/`），应用启动时会自动加载。

示例 `my_plugin.py`：

```python
def register(ctx):
    # 注册一个新语言
    ctx.register_language("lua", ["lua"], "lua")

    # 注册一个新 AI 工具
    # ctx.register_tool("read_json", "读取并解析 JSON 文件",
    #                  {"type": "object", "properties": {"path": {"type": "string"}},
    #                   "required": ["path"]},
    #                  impl=my_impl, operation="read")
```

可用能力：

| 方法 | 说明 |
| --- | --- |
| `ctx.register_language(name, aliases, ext)` | 注册目标语言 |
| `ctx.register_tool(name, description, parameters, impl, operation)` | 注册 AI 可调用的文件工具（operation 为 read / write / edit / delete / run） |
