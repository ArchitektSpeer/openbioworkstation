# 与 Agent 协作开展生物信息学分析

**简体中文** | [English](agent-workflow.en.md) · [返回首页](../README.md)

本教程介绍通过 MCP 与 Agent 协作完成计算分析的方法。研究者提出问题、确定实验设计和解释结论；Agent 将操作落实为可检查的工具调用、工作流与运行记录。这里的“实验”指计算实验，不涉及湿实验设备控制。

## 1. 研究者与 Agent 的分工

| 阶段 | 研究者 | Agent 与工作站 |
|---|---|---|
| 问题与设计 | 确定对照、重复、混杂因素和分析终点 | 整理样本表，列出缺失信息与可行流程 |
| 数据与方法 | 确认数据来源、参考版本及参数依据 | 检查文件，检索可用工具，构建节点与连线 |
| 执行与检查 | 检查生成命令、工具定义和关键中间结果 | 先 dry-run，再执行，查询状态与日志 |
| 分析与解释 | 判断统计假设、效应量和结论边界 | 汇总证据、异常、参数与可复核的结果表 |

Agent 生成的文字不是执行证据。报告应引用实际 `run_id`、日志、文件及统计输出；不得将合成测试成功等同于真实样本的科学有效性。

## 2. 安装和创建独立工作区

先按 [首页](../README.md) 安装 Python 依赖。以下练习只需 SeqKit，可建立最小工具环境；已有 common-tools 环境包含 SeqKit 时跳过安装：

```bash
conda create -y --solver libmamba --override-channels \
  -c conda-forge -c bioconda --strict-channel-priority \
  -p ~/.cache/biows/common-tools seqkit
mkdir -p ~/biows/projects/agent-seqkit/inputs
```

`BIOWS_COMMON_ENV` 可指定另一个包含 Conda 包元数据与可执行文件的环境；仅在系统 PATH 安装 SeqKit 不足以注册 `local:` 节点。创建两个各 4 bp 的合成读段：

```bash
printf '@r1\nACGT\n+\nIIII\n@r2\nTGCA\n+\nIIII\n' \
  > ~/biows/projects/agent-seqkit/inputs/reads.fastq
```

使用新的练习目录，避免覆盖已有同名文件。此练习不需要测序下载，也不用于评价真实样本的质量或变异。

## 3. 将 Agent 连接至 MCP

以下为通用 stdio 配置示例，具体客户端的配置文件位置与字段要求请按其说明设置。将所有路径替换为本机绝对路径，`~` 不应用于 JSON 示例：

```json
{
  "mcpServers": {
    "openbioworkstation": {
      "command": "/absolute/path/openbioworkstation/.venv/bin/python",
      "args": ["-m", "mcp_server.bio_mcp", "--workspace", "/absolute/path/biows/projects/agent-seqkit"],
      "env": {"PYTHONPATH": "/absolute/path/openbioworkstation"}
    }
  }
}
```

如果使用自定义 `BIOWS_COMMON_ENV`，也将其传入服务进程的 `env`。客户端通常自行启动 stdio 服务，无需另外在终端启动同一服务。连接后先检查工具列表是否包含下列 9 项：

| 工具 | 用途 |
|---|---|
| `search_bio_tools` | 按关键词和格式检索工具 |
| `add_node` | 添加输入、工具或输出节点 |
| `connect_nodes` | 使用稳定节点 ID 连接端口 |
| `compile_and_run_async` | 编译运行快照并发起异步执行 |
| `get_run_status` | 查询保存的运行状态与日志尾部 |
| `inspect_output_file` | 检查节点输出或工作区内文件 |
| `auto_wrap_bioconda_pkg` | 提取帮助并提交手写或生成的工具定义 |
| `wrap_tool` | 发起后台按需封装任务 |
| `get_wrap_job` | 查询封装任务 |

stdio 接口测试与具体 Agent 客户端集成是不同验证层级。本教程附带的脚本使用 MCP Python 客户端，不代表 Claude Desktop 等客户端已经验证。标准 MCP 服务不注册 `demo` 专用工具，因此不要直接连接包含演示专用节点的 `demo_workspace`。

可同时打开同一个标准工作区：

```bash
.venv/bin/python -m ui.workstation_window --workspace ~/biows/projects/agent-seqkit
```

共享的是本地会话文件。Agent 修改期间先保存界面修改；发生 revision 冲突时重新加载会话并核对，避免反复保存旧版本。当前 MCP 没有读取完整画布、修改已有节点参数或删除节点的高层接口；这类操作使用界面或经检查的脚本，不要臆造工具名。

## 4. 可直接交给 Agent 的练习提示词

```text
请使用 openbioworkstation MCP，在已配置的全新工作区中完成合成 FASTQ 的序列统计。
输入：工作区 inputs/reads.fastq；数据包含两个 4 bp 读段。
先检索并确认 local:seqkit/stats 可用，不要下载新数据或自动封装替代工具。
创建 FASTQ 输入 → SeqKit stats → 输出节点，使用工具返回的 node_id 和端口名连线。
先以 dry_run=true 编译，等待该 run_id 成功，再以 dry_run=false、cores=2 执行。
轮询每次运行状态直至终态；成功后检查 TSV，核对 num_seqs=2、sum_len=8。
报告实际 run_id、输出路径、检查结果与错误；不要把 dry-run 成功写成分析已完成。
本任务是计算流程练习，不产生生物学结论。
```

## 5. 实际工具调用顺序

下列为工具名及 JSON 参数示意，不是终端命令。将 `<INPUT_ID>` 等占位符替换为对应 `add_node` 返回的 `node_id`，不要使用会话内部字典键。

```text
search_bio_tools({"query":"seqkit","input_format":"FASTQ","output_format":"TSV","limit":10})
add_node({"tool_id_or_kind":"fastq_input","properties":{"path_r1":"/absolute/path/biows/projects/agent-seqkit/inputs/reads.fastq"}})
add_node({"tool_id_or_kind":"local:seqkit/stats"})
add_node({"tool_id_or_kind":"output"})
connect_nodes({"from_node":"<INPUT_ID>","from_port":"reads","to_node":"<TOOL_ID>","to_port":"reads"})
connect_nodes({"from_node":"<TOOL_ID>","from_port":"stats","to_node":"<OUTPUT_ID>","to_port":"files"})
compile_and_run_async({"mode":"all","cores":2,"dry_run":true})
get_run_status({"run_id":"<DRY_RUN_ID>","log_tail":30})
```

确认 dry-run 的 `state` 为 `success` 后执行：

```text
compile_and_run_async({"mode":"all","cores":2,"dry_run":false})
get_run_status({"run_id":"<RUN_ID>","log_tail":30})
inspect_output_file({"node_id_or_path":"<TOOL_ID>"})
```

运行启动返回 `run_id` 不等于已完成。等待 `success`，或在 `failed` / `cancelled` 时报告原因。真实执行成功后，TSV 应有一行数据，`num_seqs=2`、`sum_len=8`。不要凭空填写输出文件名，使用返回的检查信息定位文件。快速预览有记录上限，需要时进一步读取完整统计表。

如需验证相同调用，无需配置交互式 Agent 客户端，可运行配套脚本；它自动创建合成文件，要求工作区内不存在既有会话或同名输入：

```bash
.venv/bin/python -m examples.agent_seqkit \
  --workspace ~/biows/projects/agent-seqkit-script
```

2026-11-01 本机验证：该脚本通过真实 MCP stdio 服务完成工具检索、3 节点/2 连线、Snakemake dry-run、实际运行和 TSV 数值检查（2 条序列、8 bp）。验证范围是这条合成 SeqKit 链路，不覆盖所有工具或外部 Agent 客户端。

## 6. 迁移到真实生物信息学研究

以短读长比对为例，先建立样本表，至少包含样本 ID、处理组、独立生物学重复、批次、R1/R2 路径、数据来源及校验和。将待检验假设、对照和排除标准写入分析计划，再让 Agent 组织流程。

```text
FASTQ → fastp → BWA MEM → SAMtools view → sort → index → 输出
                       ↑
FASTA → BWA index ──────┘
```

检索本机节点 `local:fastp`、`local:bwa/index`、`local:bwa/mem`、`local:samtools/view`、`local:samtools/sort` 和 `local:samtools/index`。安装相应软件后再使用。FASTQ 输入节点通过 `path_r1`、`path_r2` 表示双端数据；FASTA 使用 `fasta_reference` 和 `path` 属性。以检索结果和 `add_node` 返回的端口为准，先检查一个样本再复制样本链。当前不支持多样本通配符展开。

比对完成不能直接推出差异表达、RNA 编辑或变异的结论。后续计数、过滤、建模和多重检验须采用与研究问题相符的方法，明确区分工作站执行节点与外部分析脚本。记录样本量、效应量、不确定性、阈值和敏感性分析；未检出显著差异不等同于等效。

可给 Agent 的研究提示词模板：

```text
研究问题：[填写问题与预设终点]
样本表：[路径；包含分组、重复、批次和文件]
参考：[物种、组装版本、注释版本与校验和]
预设方法：[工具、版本、参数、过滤和统计模型]
执行约束：[核心数、输入许可目录、输出工作区]
请先核查缺失信息及工具可用性，再构建并 dry-run 单样本链。
执行后按 run_id 汇总输入、参数、日志、输出校验和与异常。
将生物学解释与软件运行证据分开；没有实际运行的步骤明确标为未执行。
```

## 7. 失败处理和可复核记录

- 检索不到 `local:` 节点：检查 Conda 包元数据、可执行文件和服务进程的 `BIOWS_COMMON_ENV`；重启 MCP 后重试检索。
- `connect_nodes` 返回 `ok=false`：检查端口方向、格式、输入是否已连接及是否构成环。
- `step` 模式用于重跑目标节点，需已有上游结果；首次分析先用 `all` 或 `until`。调用时将目标稳定 ID 传给 `target_node`。
- 自动封装仅在确有需要时使用 `wrap_tool` 并轮询 `get_wrap_job`；生成定义默认未审核。检查 shell、输入输出与试运行结果后，再按项目流程标记审核状态。
- 外部 Agent 可能按客户端策略发送提示词及工具返回数据；本地执行不等于外部模型不接收预览内容。按所用客户端设置管理数据范围。

保存 `session.json`、`runs/<run_id>/` 中的会话快照、Snakefile、manifest、status 和日志，另外导出环境版本、输入/参考校验和、分析计划和最终结果。不要把 API 密钥写入报告。

## 8. 已有研究与展示材料

[研究展示附件](../promo/research/README.md)包含已有 WSMV 研究介绍、案例稿件、软件操作展示及小麦叶绿体 RNA 编辑探索性报告。它们是保留的原始成品，不是本教程重新执行得到的研究结果，也不代表经过同行评审。本教程提供独立的合成练习，避免依赖完整案例数据。
