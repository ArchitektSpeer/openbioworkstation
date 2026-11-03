# 多模型工厂真实执行记录

日期：2026-11-03 UTC。原始日志与 SQLite 状态保存在本机 `.factory/`，未公开完整会话或账号信息。

任务：修复目录文件预览忽略 preview_n 的实际问题。GitHub Issue：[1](https://github.com/ArchitektSpeer/openbioworkstation/issues/1)。

| 阶段 | CLI / 请求模型 | 结果 |
| --- | --- | --- |
| requirements | claude / claude-opus-5-5 | quota |
| requirements | codex / gpt-6.1-sol | success |
| plan | codex / gpt-6.1-sol | success |
| implement | qodercn / Qwen3.8-Flash | success |
| implement | qodercn / Qwen3.8-Flash | failed |
| implement | qodercn / Qwen3.8-Flash | success |
| review | codex / gpt-6.1-sol | success |
| review | codex / gpt-6.1-sol | success |

Claude Opus 首选实际返回周额度耗尽（HTTP 429），通知 11 月 4 日 14:00 UTC 恢复；需求阶段按配置改由 Sol 完成。Sol 产出任务计划，Qwen 完成代码与回归测试，Sol 对实现进行独立复审。Qoder 文件写入最初受到 CLI 权限模式限制；调整为接受工作区文件编辑后恢复同一任务。没有开启 YOLO。

首次实现阶段仅返回方案而未写文件，质量门禁实际失败，未标记完成。恢复后 Ruff 与 21 项该分支测试通过。首次复审缺少测试证据，因此被拒绝；补充检查的绝对解释器路径、退出码和日志后重新复审通过。

工厂自身测试包含调度状态机替身测试与真实本地子进程测试，不能把这些替身视为模型接入证据。实际模型证据对应上表 SQLite calls 和逐次 result.json。

CLI 版本：Codex 0.166.0；Claude Code 2.1.314；Qoder CN 1.1.81；OpenCode 2.2.5。OpenCode 的模型目录和适配器已核验，本样例没有调用 OpenCode 推理。低风险样例没有调用 Astra；随后对工厂调度器的恢复与发布边界进行了真实 Astra 后端审查，其指出的问题已加入修复和回归检查。

部分 CLI 未返回实际服务端模型 ID 或美元费用，分别记录为 unknown；不把订阅消耗推断为零费用。

真实样例草稿 PR：[#2](https://github.com/ArchitektSpeer/openbioworkstation/pull/2)。

未执行生产或预发布部署；本仓库尚未配置预发布托管与健康检查目标。

## 工厂源码验收

调度器的恢复、Git 暂存区范围、终态解析与发布边界经过实际 `gpt-6-astra` CLI 审查；修复发现后最终返回 `approved: true, findings: []`。工厂测试共 39 项，通过；包含真实本地子进程与模拟模型响应的确定性状态机测试。

最终审查所覆盖源码 SHA-256：

- `software_factory/engine.py`：`75551330cd55bb32779c43bebcbc3457276df1d518926cc0b05b754fcc1b761c`
- `software_factory/adapters.py`：`f494016d212236a9580d30484702481a6d8b382c1fd93fd9f9cc6f35015d97d6`
- `software_factory/storage.py`：`0d688915ef9aeaf6ede7d0969fa3f7f65e8c63c6b413484d750282a7e1028166`
