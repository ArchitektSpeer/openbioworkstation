# Agent 与可视化界面双向协作

外部 Agent 负责复杂流程、工具封装和修复；桌面画布用于观察、查看和修改配置。所有编辑使用同一配置校验，允许保存尚未完成的流程；执行时另行检查必需输入和可执行性。

## MCP 操作闭环

1. `get_workflow()` 读取磁盘上已保存的节点、稳定 `node_id`、连线及 `revision`。界面未保存的草稿不属于该结果；交给 Agent 前先保存。
2. `get_tool_schema(tool_id)` 获取端口、执行定义、默认参数和可编辑属性名。
3. 使用 `add_node`、`update_node`、`connect_nodes`、`disconnect_nodes` 和 `remove_node` 编辑。`update_node` 可修改 `properties`、`name` 和 `position`；删除节点也删除其连线。
4. 写操作传入最近读取的 `expected_revision`；若修订过期，重新读取并核对再修改。每次写操作内部也会检查读取后是否发生并发更新。
5. `compile_and_run_async` 启动运行；`get_run_status` 查询，`cancel_run` 发出取消请求后继续查询到终态。`list_runs` 可在新的 Agent 会话中找回运行。

例如：

```json
{"node_id":"<稳定ID>","properties":{"threads":4},"expected_revision":12}
```

这是 `update_node` 的参数示例。工具参数的属性名称使用 `get_tool_schema` 返回值（通常为 `param_<参数名>`）。属性必须已声明，节点 ID 与工具 ID 不可通过参数编辑替换。

## 未审核工具

用户及外部 Agent 可以管理未审核工具。`compile_and_run_async(..., allow_unreviewed=true)` 显式允许本次运行使用未审核定义；省略时沿用配置。桌面“运行 → 允许运行未审核工具”提供同样选择。该选择记录在运行 manifest 中，不改变工具审核标记。

封装命令及分析工具以本地用户权限执行，Conda 环境用于依赖管理。工作站不承诺执行隔离。用户应按自己的数据与环境要求选择 Agent 和工具定义。

## 界面同步与冲突

界面没有本地修改时自动加载外部更新；有未保存修改时提示用户选择，不静默覆盖。重新加载会替换当前画布，不累积重复节点。保存前与 MCP 使用相同校验，包括参数类型、线程数、路径许可、端口、重复连接及环。

切换工作区会同时切换保存服务和运行管理器；此前启动的运行仍按原有后台机制继续。

## 执行配置与历史结果

- 当前画布始终用于编辑后续运行。运行启动时保存执行会话、Snakefile、完整工具定义及本次是否允许未审核工具。
- “运行 → 查看本次运行配置快照”显示所选运行的只读配置；MCP 对应 `get_run_snapshot(run_id)`。
- 查看历史后，输出预览绑定所选 `run_id` 的 manifest，不再重新编译当前草稿。MCP 使用 `inspect_output_file(node_id_or_path=<节点ID>, run_id=<运行ID>)`。
- 成功运行保存所选节点产物的轻量身份记录（大小、修改时间和 inode；目录检查其成员）。发现变化或删除时拒绝作为旧结果打开，避免将新产物展示为历史结果。
- 当前未复制保存每次运行的全部大文件，身份检查也不是内容哈希验证。旧版运行、预演和未完成运行没有可验证产物记录；目录符号链接不提供历史验证。历史节点日志可能复用路径，因此查看所选运行自己的完整 Snakemake 日志。

## 验证

运行 `python -m pytest -q`、`ruff check .`、`python -m validation.mcp_stdio_client`、`python -m validation.ui_smoke`。stdio 验证使用真实 MCP 子进程；UI 检查为 offscreen，包括 Agent 修改到 UI、UI 修改到 Agent 和切换工作区保存。它们不等于真实研究分析验收。[Qoder 真实 MCP 推理记录](qoder-mcp-validation.zh-CN.md)另行验证了外部 Agent 客户端的实际构图、配置和运行。
