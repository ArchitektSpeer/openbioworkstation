# Codex 多模型全自动软件工厂 / Codex Multi-Model Autonomous Software Factory

> **目标：** 以 GPT-6.1 Sol 为总调度，Claude Opus 5.5 理解需求并开发复杂前端，GPT-6 Astra 攻克复杂后端；Qoder CN 与 OpenCode 的廉价模型处理常规任务，限额后自动切换备用模型。  
> **Goal:** Use GPT-6.1 Sol for orchestration, Claude Opus 5.5 for requirements and complex frontend work, GPT-6 Astra for difficult backend work, and inexpensive Qoder CN/OpenCode models for routine tasks, with automatic failover at quota limits.

**定位：这是待搭建的工作流设计，不是已经运行的软件；模型 ID、权限及订阅可用性必须在本机核实。**  
**Status: This is an implementation blueprint, not a running system; verify model IDs, permissions, and subscription availability locally.**

## 1. 角色与二级模型 / Roles and Fallbacks

| 任务 Task | 第一选择 Primary | 第二选择 Fallback | 最后兜底 Last resort |
|---|---|---|---|
| **总调度 / Orchestration** | **GPT-6.1 Sol · Codex** | Claude Opus 5.5 | DeepSeek V4.1 Flash（只做低风险调度 / low-risk routing only） |
| **需求理解、PRD / Requirements** | **Claude Opus 5.5 · Claude Code** | GPT-6.1 Sol | Qwen3.8 Flash（草案需复核 / draft requires review） |
| **复杂前端 / Complex frontend** | **Claude Opus 5.5 · Claude Code** | GPT-6.1 Sol | DeepSeek V4.1 Flash（拆成小任务 / scoped tasks） |
| **复杂后端 / Complex backend** | **GPT-6 Astra · Codex/API** | GPT-6.1 Sol | DeepSeek V4.1 Flash（只处理非关键模块 / noncritical modules） |
| **测试、文档、Lint、简单 Bug / Tests, docs, lint, simple bugs** | **Qwen3.8 Flash · Qoder CN** | GLM-5.3 Flash · Qoder CN | DeepSeek V4.1 Flash · OpenCode |
| **常规代码、重构 / Routine coding and refactoring** | **DeepSeek V4.1 Flash · OpenCode** | Qwen3.8 Flash | GLM-5.3 Flash |
| **独立复审 / Independent review** | 与实现者不同的模型 / Different model from author | GPT-6.1 Sol 或 Opus 5.5 / or Opus 5.5 | 高风险任务暂停 / Hold high-risk tasks |

- **优先级是用户指定的策略，不代表经基准测试证明的能力排名。** / **These priorities reflect your preferred workflow, not a proven benchmark ranking.**
- **Astra 成本较高：只用于复杂后端、疑难并发、安全敏感设计；普通 CRUD 用廉价模型。** / **Astra is costly: reserve it for difficult backend, concurrency, and security-sensitive design; use cheaper models for ordinary CRUD.**
- **Qoder CN 的可选 CLI 模型不一定等于 Qoder IDE 列表；若找不到所列 Flash 型号，替换成账户实际可选型号。** / **Qoder CN CLI availability may differ from its IDE catalog; replace unavailable Flash models with models actually listed for your account.**

## 2. 自动执行闭环 / Autonomous Delivery Loop

```text
需求 / Request
  ↓
Opus：澄清需求 → PRD → 验收标准 / Requirements → PRD → acceptance criteria
  ↓
Sol：架构 → 任务 DAG → 风险分级 → 预算 → 模型路由
     Architecture → task DAG → risk → budget → routing
  ↓
调度器：独立 worktree + 任务包 / Scheduler: isolated worktree + task packet
  ├─ Opus：复杂 UI / Complex UI
  ├─ Astra：关键后端 / Critical backend
  └─ Qwen / GLM / DeepSeek：测试、文档、常规实现 / QA, docs, routine work
  ↓
本地 CI：类型 / Lint / 单测 / 集成 / E2E / 性能 / 安全
          Types / lint / unit / integration / E2E / performance / security
  ↓
失败：日志 → 修复 Agent → 最多 3 次 → 升级模型或停止
Failure: logs → repair agent → max 3 attempts → escalate or stop
  ↓
独立审查 → 自动草稿 PR → 预发布部署 → 监控
Independent review → draft PR → staging → monitoring
  ↓
复盘：重复错误 → 测试、Lint、Skill 提案 → 审核后纳入规则
Reflection: repeated failures → rule/test/Skill proposal → approved adoption
```

**原则：模型的自述“完成”不算完成；只有 CI 输出和验收证据才算完成。**  
**Rule: An agent claiming “done” is not completion; passing CI and acceptance evidence are required.**

## 3. 配额耗尽后的切换 / Quota-Aware Failover

1. **统一适配器：** 给 Codex、Claude Code、Qoder CN、OpenCode 分别实现 `run(prompt, worktree, timeout)`，统一返回状态、日志和产物。  
   **Common adapters:** Implement `run(prompt, worktree, timeout)` for Codex, Claude Code, Qoder CN, and OpenCode, returning normalized status, logs, and artifacts.
2. **只在可用性错误时切模型：** 限额、429、临时故障、超时 → `cooldown` → 下一候选模型；401/403 等凭证问题则停用该适配器并告警。  
   **Switch only for availability failures:** Quota, 429, transient errors, and timeouts → `cooldown` → next candidate; disable an adapter and alert on credential errors such as 401/403.
3. **代码或测试失败不等于限额：** 保留原模型进行有限修复，修复失败才转给更强的审查者。  
   **Code/test failures are not quota failures:** Allow bounded repair with the current model, then escalate to a stronger reviewer if needed.
4. **切换时传任务包，而非一大段聊天记录：** `task.json` + `acceptance.md` + `checkpoint.md` + Git commit + 失败日志；确保任务可恢复且不重复执行副作用。  
   **Transfer a task packet, not a long chat transcript:** `task.json` + `acceptance.md` + `checkpoint.md` + Git commit + failure logs; make work resumable and side effects idempotent.
5. **限额恢复：** 遵守服务商返回的 `Retry-After` 或可信重置时间；先小流量探测，再恢复主模型，不绕过服务商限制。  
   **Recovery:** Respect provider `Retry-After` or a confirmed reset time; probe gently before restoring the primary model, without circumventing usage limits.
6. **质量下限：** 备用模型无法满足复杂度或安全要求时暂停任务，不要以“自动化”为理由强行降级上线。  
   **Quality floor:** Pause when fallback models cannot satisfy task complexity or security requirements; never degrade just to preserve automation.

## 4. 调度规则示例 / Illustrative Routing Policy

> 下列 YAML 是**自定义调度器的设计配置**，不是 Codex、Claude Code 或 OpenCode 可直接识别的原生配置。  
> This YAML is a **design configuration for your own orchestrator**, not a native config file recognized directly by Codex, Claude Code, or OpenCode.

```yaml
orchestrator: codex-gpt-6.1-sol
max_parallel_jobs: 3
max_repair_attempts: 3
production_deploy: manual_approval
critical_changes: manual_approval

routes:
  requirements: [claude-opus-5.5, gpt-6.1-sol, qwen-flash]
  orchestration: [gpt-6.1-sol, claude-opus-5.5]
  frontend_complex: [claude-opus-5.5, gpt-6.1-sol, deepseek-flash]
  backend_complex: [gpt-6-astra, gpt-6.1-sol]
  routine_code: [deepseek-flash, qwen-flash, glm-flash]
  tests_docs_lint: [qwen-flash, glm-flash, deepseek-flash]

on_quota_error: try_next_available_model
on_test_failure: repair_then_escalate
on_auth_error: disable_provider_and_alert
cooldown: provider_retry_after_or_verified_reset
require_evidence: [typecheck, lint, unit_tests, build, relevant_e2e]
require_independent_review: true
```

## 5. pstack 方法如何接入 / Applying the pstack Methods

| Skill / 机制 Mechanism | 自动化用途 / Automated use |
|---|---|
| `poteto-mode` / `swarm` | 分解和并行调度；在本系统中由 Sol + 自定义调度器承担 / Task decomposition and parallelism, implemented here by Sol + orchestrator |
| `correct` | 同类 Bug 反复出现 → 提交新增测试、类型或 Lint 规则的 PR / Repeated bugs → propose test, type, or lint rules via PR |
| `create-verification-skill` | 为每个软件生成可复现的启动、操作及验收脚本 / Build reproducible launch, interaction, and acceptance checks |
| `create-formal-verification-skill` | 仅给状态机、支付流程等高价值逻辑做 TLA+ / Formal checks for high-value logic such as state machines and payments |
| `reflect` | 根据失败日志提出规则改进，不允许 Agent 自行削弱检查 / Suggest improved rules from failure logs; never silently weaken gates |
| 性能预算 / Performance budgets | 先 profiling，再约束热路径、内存、响应延迟、构建体积 / Profile first, then enforce hot-path, memory, latency, and bundle budgets |

**推荐：先把 `AGENTS.md`、测试和 CI 做扎实，再增加多 Agent 并行；Skill 是指导，不替代真实验证。**  
**Recommendation: Establish `AGENTS.md`, tests, and CI before adding agent parallelism; Skills guide behavior but cannot replace actual verification.**

## 6. 最小工程结构 / Minimum Project Layout

```text
software-factory/
├── AGENTS.md                     # 统一规范 / Shared rules
├── config/routes.yaml            # 模型优先级 / Model priorities
├── orchestrator/                 # 队列、恢复、预算 / Queue, recovery, budgets
├── adapters/                     # codex, claude, qodercn, opencode
├── skills/                       # verification, correct, reflect, performance
├── tasks/<id>/                   # task.json, acceptance.md, checkpoint.md
├── worktrees/                    # 独立任务工作区 / Isolated workspaces
└── .github/workflows/ci.yml      # 自动质量门 / Automated quality gates
```

**首版范围：** 1 个 Issue → Opus 生成 PRD → Sol 分配 → 1 个廉价执行模型改代码 → CI → 独立审查 → 草稿 PR；跑通后再开放最多 3 个并发任务。  
**MVP scope:** 1 Issue → Opus writes PRD → Sol routes → 1 low-cost worker edits code → CI → independent review → draft PR; only then increase to 3 concurrent jobs.

## 7. 本机 CLI 接入核验 / Verify Local CLI Integrations

```bash
# Codex：非交互调用 / Codex noninteractive run
codex exec "Summarize this repository and its tests"

# Claude Code：需求分析 / Claude Code requirements analysis
claude -p "Turn this feature request into a PRD and acceptance criteria" \
  --output-format json

# Qoder CN：先列出账户可用模型 / List available models first
qodercn --list-models
qodercn -p "Generate unit tests for this module" --output-format json

# OpenCode：列出提供商模型，再替换为真实 provider/model ID
# OpenCode: list models, then substitute the actual provider/model ID
opencode models
opencode run --model <provider/model-id> "Review these changes"
```

**注意：** `claude -p`、`qodercn -p`、`opencode run` 和 `codex exec` 支持脚本调用，但**订阅不等于 API 配额**；是否允许自动调用、可用时长、限额和认证方式以各 CLI 的官方规定及账户状态为准。  
**Note:** These tools offer scriptable CLI commands, but **subscriptions are not equivalent to API credits**; unattended usage, quotas, limits, and authentication depend on provider policies and your account.

## 8. 自动化边界 / Automation Boundaries

- **默认自动：** 低风险编码、测试、修复、文档、草稿 PR、预发布部署。 / **Automatic by default:** Low-risk coding, tests, repairs, docs, draft PRs, staging deployments.
- **必须审批：** 正式生产发布、密钥操作、权限提升、付费行为、不可逆数据库迁移。 / **Approval required:** Production releases, secret operations, privilege escalation, purchases, irreversible migrations.
- **必须可追踪：** 每个任务记录模型、版本、提交、失败原因、尝试次数、耗时和 API 成本（若可获取）。 / **Auditable:** Record model, version, commit, failure reason, attempts, duration, and API cost where available.
- **成本控制：** 设置每日预算、每任务预算、最大调用次数与熔断；不要把订阅额度误算为免费无限量。 / **Cost control:** Enforce daily/per-task budgets, call limits, and circuit breakers; never assume subscriptions provide unlimited free usage.

## 9. 给 Sol 的启动指令 / Bootstrap Instruction for Sol

> 用 Python 实现一套本地优先的多模型任务调度器，接入 Codex、Claude Code、Qoder CN 和 OpenCode 的非交互 CLI；按第 1 节角色路由，按第 3 节检测配额并自动切换，使用独立 Git worktree、可恢复任务包、SQLite 状态、限次修复、独立审查、GitHub 草稿 PR 与 CI 门禁。先实现一个真实端到端样例，运行测试并展示日志；不要跳过权限审核，不要声称未经测试的流程已经可用。  
> Build a local-first Python multi-model orchestrator using Codex, Claude Code, Qoder CN, and OpenCode noninteractive CLIs. Route by Section 1, handle quotas and fallback by Section 3, and use isolated Git worktrees, resumable task packets, SQLite state, bounded repair, independent review, GitHub draft PRs, and CI gates. Implement and test one real end-to-end example first, showing logs. Respect permission boundaries and do not claim untested flows work.

## 参考 / Sources

- [Codex noninteractive CLI](https://learn.chatgpt.com/docs/non-interactive-mode)
- [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference)
- [Qoder CN script mode](https://docs.qoder.cn/cli/run-in-scripts) · [Model listing](https://docs.qoder.cn/cli/models)
- [OpenCode CLI](https://docs.opencode.ai/docs/cli/) · [Model selection](https://opencode.ai/v2/docs/models/)
- [pstack open-source Skills](https://github.com/cursor/plugins/tree/main/pstack)

*版本 / Version: 2026-11-03 · 模型名称与服务配额可能变化，请以实际 CLI 检测结果为准。 / Model names and provider quotas may change; rely on live CLI discovery.*
