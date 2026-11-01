# 项目传播文案 / Project communication copy

[素材目录 / Asset guide](README.md) · [中文教程](../docs/agent-workflow.zh-CN.md) · [English tutorial](../docs/agent-workflow.en.md)

## 一句话定位 / One-line description

面向本地生物信息学分析的可视化工作流与 Agent 协作平台。

A visual workflow platform for local bioinformatics analysis and agent-assisted operation.

## 简介 / Short description

OpenBioWorkstation 集成 NodeGraphQt、Snakemake 与 MCP，将流程构建、执行状态、文件检查和运行记录关联到同一本地工作区。研究者可与 Agent 协作组织计算分析，并检查实际运行证据。项目提供合成数据演示、Agent 协作教程及既有研究案例展示。

OpenBioWorkstation integrates NodeGraphQt, Snakemake and MCP to associate workflow construction, execution state, file inspection and run records in a shared local workspace. Researchers and agents can organize computational analyses while inspecting execution evidence. Synthetic demos, agent-collaboration tutorials and existing research case materials are provided.

## 社交平台短文 / Short social post

OpenBioWorkstation：用节点画布组织生信流程，由 Snakemake 执行，并通过 MCP 与 Agent 协作。现提供Agent 协作教程、可运行的合成数据示例及研究展示附件。Linux 单机，MIT 开源。

OpenBioWorkstation combines a visual bioinformatics canvas, Snakemake execution and MCP-based agent assistance. Includes an agent-collaboration guide, a runnable synthetic-data tutorial and research showcase PDFs. Linux desktop, single machine, MIT licensed.

## 技术社区 / Technical community

OpenBioWorkstation 是一个 Linux 桌面生物信息学工作流工具。图形界面与 MCP 使用同一本地会话；节点图被编译为 Snakefile，并保留运行快照、日志和状态。研究者可让 Agent 检索工具、连接端口、先 dry-run 再执行，并基于实际输出核对结果。配套教程使用两个合成 FASTQ 读段和本机 SeqKit，避免把复杂案例当作入门前提。

当前限制包括无多用户服务、无多样本通配符展开，以及工具定义需要逐项检查。MCP stdio 和教程链路已实测，具体 Agent 客户端仍需分别验证。研究附件包括 WSMV 案例稿件及小麦叶绿体 RNA 编辑探索性报告；这些材料不作为已发表或经同行评审的成果宣传，也不包含完整数据与代码归档。

OpenBioWorkstation is a Linux desktop bioinformatics workflow tool. Its graphical interface and MCP server share a local session. Graphs compile into Snakefiles, with retained execution snapshots, logs and state. Researchers can ask an agent to discover tools, connect ports, perform a dry run and inspect actual outputs. The companion tutorial uses two synthetic FASTQ reads and a local SeqKit node, without requiring a complete case study.

Limitations include no multi-user service or sample wildcard expansion, and tool definitions requiring individual review. MCP stdio and the tutorial workflow have been exercised; each end-user agent client requires separate verification. Research attachments include a WSMV case manuscript and an exploratory wheat chloroplast RNA-editing report. They are not presented as published or peer-reviewed findings, and do not constitute complete data/code archives.

## 演示讲解顺序 / Demonstration sequence

1. **问题 / Question**：介绍研究问题、样本设计和研究者与 Agent 的分工 / Introduce the question, sample design and division of responsibilities.
2. **构建 / Construction**：通过 MCP 检索 SeqKit，创建输入、工具及输出节点 / Discover SeqKit through MCP and create input, tool and output nodes.
3. **检查 / Inspection**：显示端口、输入预览和 dry-run 结果 / Inspect ports, input previews and dry-run results.
4. **执行 / Execution**：展示实际 run ID、状态、日志及 TSV / Show actual run IDs, states, logs and the TSV.
5. **扩展 / Extension**：解释如何迁移到真实样本，再展示既有研究附件 / Explain real-data extensions and present the existing research artifacts.

## 常见问题 / FAQ

**是否自动完成所有研究？ / Does it automate all research?**

不。工具调用可辅助流程操作；研究设计、参数合理性和结论解释仍需研究者负责。 / No. Tool calls assist operational work; researchers remain responsible for study design, justified parameters and interpretation.

**是否支持所有索引工具？ / Are all indexed tools executable?**

不。索引元数据、可生成命令、可执行定义及已验证流程属于不同层级，应以当前注册表、依赖和测试为准。 / No. Metadata entries, convertible commands, executable definitions and validated workflows are different levels of support.

**数据是否全部留在本地？ / Does all data remain local?**

工作流执行与文件存储在本地；依赖下载可能联网，外部 Agent 的提示词及工具返回数据由其客户端策略决定。 / Execution and storage are local; dependency retrieval may use the network, and external-agent prompts and tool results follow client policy.

**案例是否构成生物学发现证明？ / Do cases establish biological findings?**

案例仅展示特定分析过程及其既有报告。WSMV 阴性结果不证明等效，探索性报告的新颖性判断亦未为本次发布重新核查。 / Cases demonstrate particular analyses and their existing reports. The WSMV negative result does not establish equivalence, and exploratory novelty claims were not rechecked for this release.

**如何开始？ / Where should I start?**

先运行离线演示，再按Agent 协作教程完成 SeqKit 合成练习。 / Run the offline demo, then follow the agent-collaboration tutorial for the synthetic SeqKit exercise.

## 声明依据 / Claim basis

- 系统结构与功能 / Architecture and behavior: [README 中文](../README.md), [English](../README.en.md), [设计文档 / Design](../DESIGN.md).
- 当前 MCP 工具与参数 / Current MCP signatures: [服务实现 / Server](../mcp_server/bio_mcp.py).
- 合成练习及本机验证范围 / Synthetic exercise and verification scope: [教程 / Tutorial](../docs/agent-workflow.en.md), [脚本 / Script](../examples/agent_seqkit.py).
- 图像来源与既有视觉复核限制 / Image provenance and historical review limits: [素材目录 / Assets](README.md), [复核记录 / Review](review_log.md).
- 研究附件状态与限制 / Research status and limits: [研究展示 / Research showcase](research/README.md).

未新增性能、速度、用户规模或机构背书声明。 / No performance, speed, adoption or institutional endorsement claim is made.
