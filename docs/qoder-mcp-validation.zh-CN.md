# Qoder 真实 MCP 推理验证（2026-11-03）

使用已登录的 Qoder CN CLI 1.1.81，请求模型 `Qwen3.8-Flash`，通过 stdio MCP 完成真实工具调用。CLI 未报告服务端模型 ID，故实际 ID 记为 unknown；这里验证的是明确指定模型的真实 CLI 会话，不是模型身份认证。

## 验收结果

- 约 70.3 秒完成；实际发起 20 次 MCP 工具调用，全部成功，无工具错误。
- 模型读取空工作区、检索 SeqKit、读取工具及输入/输出节点 schema，创建 3 节点、2 连线。
- 模型使用 `update_node` 将工具重命名为 `Qoder SeqKit live`，线程数设为 2；保存后的 revision 为 6。
- 模型先预演，再实际执行 SeqKit 2.14.0，均等待到 success。
- 模型检查运行快照、历史及实际输出；独立验证器重新读取 TSV，确认 `num_seqs=2`、`sum_len=8`。
- 将同一工作区载入真实 Qt 窗口的 offscreen 渲染，确认节点、名称、线程参数及运行结果能在界面显示。

预演 ID：`6ecbf6f54c764aa4a59ccc994503c6fc`。

实际运行 ID：`84a4fd6b105c48e8bc6e46cdcf22cb07`。

工具调用分布：get_workflow ×3、get_tool_schema ×3、add_node ×3、connect_nodes ×2、compile_and_run_async ×2、get_run_status ×2；search_bio_tools、update_node、inspect_output_file、list_runs、get_run_snapshot 各1次。

## 证据与权限

`validation/qoder_mcp_check.py` 提供可重复的显式调用入口：

```bash
.venv/bin/python -m validation.qoder_mcp_check --model Qwen3.8-Flash
```

需要已登录 Qoder，且 SeqKit 已安装于工作站识别的 common-tools 环境。此脚本调用真实模型，**不在 CI 中自动执行**。

所有内置文件和 Shell 工具均禁用，仅放行本次工作区的指定 MCP 工具；不启用 YOLO，不改全局 MCP 配置。透明代理记录模型发出的 JSON-RPC 请求和真实服务响应。模型任务只给出目标和验收标准，由模型选择工具及参数；验证器只准备合成输入、记录通信并检查结果，不替模型构图或执行分析。

本机证据位于 `.factory/mcp-live/qoder-mcp-20261103T092637/`：`wire.jsonl`、Qoder 流式日志、`report.json`、`workspace/session.json`、运行快照、SeqKit TSV 和 `ui.png`。原始会话不随仓库公开。SQLite 记录真实 CLI 调用；其一次调用可能包含多个模型轮次与 MCP 调用，不等于一次底层 API 请求。

第一次真实测试暴露了输入节点类型无法发现的问题：模型反复猜测 input 等名称。该次失败日志保留，未记为成功。随后在 `get_workflow` 暴露内置节点类型，并让 `get_tool_schema` 支持其端口和属性，添加回归测试后，使用全新工作区重新验证通过。

这是两条合成读段的执行与客户端集成验证，不是研究数据分析验收或所有工具的兼容性证明。
