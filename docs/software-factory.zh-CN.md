# 本地多模型软件工厂

这是 `docs/codex-multi-model-auto-factory-bilingual.md` 的首版落地实现，独立于生信工作流运行器。它组织软件开发，不代替 Snakemake，也不自动执行生产部署。

## 执行方式

在仓库 Python 环境安装 `requirements-dev.txt`，并分别安装、登录 Codex、Claude Code、Qoder CN、OpenCode。订阅、模型目录及限额由各服务决定。先运行：

```bash
.venv/bin/python -m software_factory doctor
.venv/bin/python -m software_factory create examples/factory/directory-preview.json
.venv/bin/python -m software_factory run directory-preview
.venv/bin/python -m software_factory status directory-preview
```

`doctor` 只检查版本、登录信息和目录，不调用模型验证推理额度。结果在 `.factory/discovery.json`，不读取或输出密钥。模型别名映射和调用预算在 `config/factory-routes.yaml`。其中 Sol=`gpt-6.1-sol`、Astra=`gpt-6-astra`、Opus=`claude-opus-5-5`，Qoder 使用实际目录中的 `Qwen3.8-Flash`/`GLM-5.3-Flash`，OpenCode 使用 `opencode-go/deepseek-v4.1-flash`。目录列出模型不等于账号有额度。

也可在 create 时加 `--issue ArchitektSpeer/openbioworkstation#1` 从 GitHub 读取标题和正文；允许文件、验收和检查命令仍来自本地可信任务文件，不从 Issue 正文执行命令。

任务按以下阶段执行：

1. Opus 生成 PRD；不可用时按路由使用 Sol。
2. Sol 输出带依赖和验收标准的任务计划。
3. 按任务 route 选择常规执行模型，在独立 Git worktree 内修改指定文件。
4. 用任务提交者明确提供的 argv 检查命令执行本地质量门禁；CLI 声称完成不作为验收证据。
5. 由不同于实现模型的候选独立审查完整差异。CLI 未报告实际模型身份时要求不同提供商，并明确记录判断依据，不能称为服务端模型身份认证。超出审查大小预算时停止，不能静默截断。
6. 通过后状态为 `ready_for_pr`。显式运行下列命令才推送分支并创建草稿 PR：

```bash
.venv/bin/python -m software_factory publish directory-preview
```

publish 不合并、不部署，重复调用复用已经创建的 PR。通过 `gh` 使用已有 GitHub 登录；不把凭据传入质量检查。

## 任务包与恢复

每个任务保留 `.factory/tasks/<id>/task.json`、`acceptance.md`、`checkpoint.md`、PRD、计划、检查结果、独立审查及逐次调用日志。工作区为 `.factory/worktrees/<id>`，分支为 `codex/factory-<id>`。SQLite `.factory/state.sqlite3` 保存任务阶段、模型、版本、调用状态、耗时、可获得的费用及事件。

任务从创建时的 Git 提交启动；不会自动复制主工作区未提交的修改。若希望包含当前改动，先自行形成明确的基准提交再创建任务，或指定已有 `base_ref`。不自动覆盖、提交或丢弃主工作区草稿。

阶段完成后可再次 `run <id>` 接续，已完成任务不会重复调用模型。中断状态可检查日志及 worktree 后使用 `run <id> --recover`。如果发现仍未结束的调用，调度器停止，避免启动第二个会产生副作用的进程。确认原进程已经结束并检查部分修改后，才能显式执行：

```bash
.venv/bin/python -m software_factory abandon-call <id> <call-id>
.venv/bin/python -m software_factory run <id> --recover
```

该命令不会把旧调用标成成功，只记录人工确认放弃；原调用仍消耗预算，已有 Worker 身份保持固定。提交阶段通过保存预期 Git tree 识别“提交已完成、数据库尚未更新”的崩溃边界。

## 路由和质量规则

- 只有 429、限额、临时故障、超时和明确不可用状态触发候选切换；401/403 停用对应适配器，必须修复登录后显式恢复。
- 遵守可信 `Retry-After`；Claude 结构化限额错误附带明确 UTC 重置通知时使用该时间。无可信重置时间才使用策略中的保守冷却。恢复后实际调用就是小任务探测，不后台频繁轮询。
- 代码或测试失败保留原模型进行有限修复。修复次数持久化，最多 3 次，重新 run 不会清零。达到上限停止并请求升级分析；不会降低检查要求。
- 写调用中断且留下修改时停止，固定原 Worker，避免备用模型盲目重做副作用。
- Worker 不允许自行提交或编辑允许文件之外的内容。质量检查绑定准确的源文件摘要；检查通过后内容有变化则拒绝提交，不能沿用旧证据。计划、审查调用若修改 worktree 也会被拒绝。
- 生产、密钥、权限、付费操作和其他非低风险任务在调用模型前进入 `approval_required`。本版不提供自动高风险审批或部署命令。

## 权限与预算

Codex 使用 read-only/workspace-write sandbox。Claude/Qoder 限制为 Read/Glob/Grep，写阶段额外允许 Edit/Write，并采用 CLI 的接受工作区文件编辑模式；不会开启 YOLO 或跳过权限检查。OpenCode 沿用其本机正常权限，读取阶段指定 plan agent；它不是 OS 级隔离，不能据此处理任意不可信代码。质量检查是任务提交者明确配置的命令，也不是沙箱。

默认每任务最多 10 次模型调用、每天最多 30 次，单次超时 180 秒；每天与每任务的已报告费用另有熔断阈值。调用数量在派发前以 SQLite 事务预留，失败也计数。费用仅记录 CLI 返回数据，缺失时为 unknown；这些阈值不是对未报告费用或单次推理费用的严格美元上限，订阅额度也不等于免费无限量。需要严格计费控制时应另接服务商原生预算机制。

## 当前边界

首版串行调度，完成单任务闭环后再增加并发；配置大于 1 会明确拒绝，最大设计上限为 3。计划中的子任务作为同一个受限 Worker 任务执行，跨 Issue 依赖通过 `dependencies` 指定；尚无通用分布式 DAG 执行器。

未提供生产发布、预发布托管或持续监控，因为当前仓库没有相应托管目标或健康检查契约。自动化改进建议仍须审查后纳入，不允许 Worker 自行改变工厂规则。测试用替身只验证调度状态机；真实模型日志单独保存在本机，不把测试替身当作服务已接入的证据。

## 官方接口参考

- [Codex 非交互调用](https://learn.chatgpt.com/docs/non-interactive-mode)
- [Claude Code CLI](https://code.claude.com/docs/en/cli-reference)
- [Qoder CN 脚本模式](https://docs.qoder.cn/cli/run-in-scripts)、[文件编辑权限](https://docs.qoder.cn/cli/permissions)
- [OpenCode CLI](https://opencode.ai/docs/cli/)
