# OpenBioWorkstation 设计文档（DESIGN.md）

> 生物信息学可视化节点工作站：100% 复用开源组件 + 纯 Python 胶水层 + MCP 接入
>
> 公开实现与验证边界说明（原始内部需求稿不随仓库发布）
> 文档版本：v0.2（2026-10-30）——按实际代码修订，以本文为准；v0.1 的设想与实现不符之处见「附录 A 修订记录」。

---

## 0. 目录

1. 目标、非目标与完成度
2. 设计原则
3. 总体架构
4. 核心数据模型（接口契约）
5. 模块设计
   - 5.1 `glue/bio_inspector.py`
   - 5.2 工具注册表 `glue/wrapper_registry.py` 及适配器
   - 5.3 `glue/snakemake_bridge.py` 与运行监督进程
   - 5.4 `ui/workstation_window.py`
   - 5.5 `mcp_server/bio_mcp.py`
6. 关键流程（时序）
7. 文件格式类型系统
8. 目录与工作区布局
9. 并发、状态同步与一致性
10. 安全设计
11. 性能约束与预算
12. 依赖与版本锁定
13. 测试与验证
14. 交付里程碑与当前状态
15. 风险与待决问题
- 附录 A：v0.1 → v0.2 修订记录

---

## 1. 目标、非目标与完成度

### 1.1 目标

| 编号 | 目标 | 状态 |
| :--- | :--- | :--- |
| G1 | Linux 桌面「左输入 → 中间工具 → 右输出」节点连线工作台，端口带强类型格式标签 | ✅ 已实现并实测 |
| G2 | 画布编译为标准 `Snakefile`，由 Snakemake 负责 DAG 调度、缓存、断点续跑与环境隔离 | ✅ 已实现，真实 Snakemake 9.27 运行通过 |
| G3 | 「运行此步」「运行至此节点」「全量运行」，节点边框实时反映状态 | ✅ 已实现并实测 |
| G4 | 快速文件校验与前 5 条记录预览（FASTA/FASTQ/SAM/BAM/CRAM/VCF/BCF 等） | ✅ 14 种格式验证通过 |
| G5 | 多源适配器三阶段扩展：snakemake-wrappers（300~500）→ nf-core/modules + CWL（1,800+）→ Bioconda 长尾（12,000+） | ⚠️ 上游元数据已下载并建索引 15,447 条；Top-50 批次 50/50 已封装（46/46 合成数据冒烟通过并审核，4 个仅存活检查；11 个目录输出）；seqkit / fastp（smk + Conda）/ fastqc（目录）/ bcftools query（真实 VCF）/ samtools flagstat（真实 BAM）均已端到端验证；nf-core 86 个可生成 shell |
| G6 | 通过 MCP 暴露 7 个高层工具 | ✅ 7 个工具经 stdio 客户端验证；⚠️ 未在 Claude Code/Desktop 中实测 |

### 1.2 非目标（v1 明确不做）

- 不实现任何生信算法、文件解析器、DAG 调度器、哈希缓存、节点图渲染与序列化。
- 不自创工具描述规范：内部 `ToolSpec` 只是上游元数据的内存投影；自动封装定义沿用 snakemake-wrappers `meta.yaml` 结构并增加 `biows:` 扩展段。
- v1 不支持多样本通配符（`{sample}`）展开；多样本以多条并行的节点链表达。
- 不提供集群调度器配置界面；不做多用户/远程协作。

---

## 2. 设计原则

1. **零重复造轮子**：每个能力都能指出负责其核心逻辑的上游组件（见 §3.2）。胶水层只做「格式转换 + 分发 + 回调」。
2. **单一事实源**：
   - 图结构：工作区 `session.json`（NodeGraphQt 会话格式）。
   - 运行状态：Snakemake 本身（输出文件 + `.snakemake/` 元数据）；`runs/<run_id>/status.json` 是由日志解析得到的派生视图。
   - 工具定义：上游仓库元数据；内置定义在 `glue/builtins.py`，本机工具在 `glue/installed_tools.py`。
   - 前后端接口：`glue/models.py`、`glue/session_schema.py`、`glue/errors.py` 三个契约文件。
3. **UI 无关的胶水核心**：`glue/` 不依赖 Qt，UI 与 MCP 两个进程共用。
4. **懒加载**：启动只读索引缓存；节点类、Conda 环境、文件索引在首次需要时创建。
5. **安全默认**：子进程一律 argv 列表；写入 `Snakefile` 的值经 `repr()`；LLM 生成的定义默认「未审核」且默认禁止运行。

---

## 3. 总体架构

### 3.1 进程与分层

```
┌──────────────────────────────┐   ┌──────────────────────────────┐
│ 进程 A：桌面工作台 (PySide6)   │   │ 进程 B：MCP Server (stdio)    │
│ ui/workstation_window.py     │   │ mcp_server/bio_mcp.py        │
└──────────────┬───────────────┘   └──────────────┬───────────────┘
               │ import                           │ import
               ▼                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│ glue/（纯 Python，无 Qt）                                        │
│ bio_inspector  wrapper_registry(+builtins/installed_tools/       │
│ nf_converter/catalog_cache)  snakemake_bridge  session_store     │
└───────┬──────────────────┬─────────────────────┬───────────────┘
        ▼                  ▼                     │ Popen(start_new_session)
 pyfastx/pysam/cyvcf2  上游元数据目录              ▼
                                       进程 C：运行监督 glue.run_worker
                                       （每次运行一个，脱离 UI/MCP 存活）
                                                 │ Popen
                                                 ▼
                                       snakemake CLI → tool_runner / wrapper / conda
```

UI、MCP、运行监督三类进程只通过**工作区目录**共享状态（`session.json` + `session.meta.json` + `runs/<run_id>/`），不直接通信（§9）。

### 3.2 能力 → 上游组件对照

| 能力 | 上游组件 | 胶水层职责 |
| :--- | :--- | :--- |
| FASTA/FASTQ 校验、统计 | `pyfastx` | 扩展名分发、结果规整为 `InspectResult` |
| SAM/BAM/CRAM 校验、索引统计 | `pysam`（htslib） | 同上，索引存在性检查 |
| VCF/BCF 解析 | `cyvcf2`（htslib） | 同上 |
| 工具元数据 | snakemake-wrappers / nf-core modules / Bioconda recipes | 解析 → `ToolSpec`，建索引、检索 |
| DAG、缓存、断点、并行、环境 | Snakemake | 图 JSON → `Snakefile`；拼装 CLI；解析日志 |
| 环境隔离 | Conda / Apptainer | 透传 `--use-conda` / `--sdm conda apptainer` 与 `--conda-prefix` |
| CWL 执行 | `cwltool` | 生成 job JSON，经 `glue/cwl_runner.py` 调用 |
| 节点图编辑、序列化、菜单、属性面板 | NodeGraphQt | 节点类注册、端口格式拦截、菜单命令、状态着色 |
| MCP 协议 | `mcp` 官方 SDK（FastMCP 1.x） | 7 个工具函数 |

---

## 4. 核心数据模型（接口契约）

契约文件由前端维护，后端只读取/构造，不得增删字段。

### 4.1 `glue/models.py`

| 类型 | 关键字段 | 说明 |
| :--- | :--- | :--- |
| `PortSpec` | `name, formats, multiple, optional, pattern, description` | `name` 即 Snakefile 中 input/output 关键字 |
| `ParamSpec` | `name, default, description` | `default` 的类型决定画布字符串如何转换 |
| `ExecSpec` | `kind("wrapper"/"shell"/"cwl"), wrapper, shell, conda_env, container, cwl` | 执行方式 |
| `ToolSpec` | `tool_id, name, category, source, description, keywords, inputs, outputs, params, execution, threads, reviewed` | 字段名为 `execution`（避免遮蔽内建 `exec`） |
| `IndexEntry` | `tool_id, name, category, source, keywords, input_formats, output_formats, summary, reviewed, wrapped` | 检索用轻量条目；`wrapped=False` 表示 Bioconda 包尚未封装 |
| `SearchPage` | `total, items, next_offset` | 分页结果 |
| `InspectResult` | `path, format, valid, error, compressed, index, stats, preview, warnings, elapsed_ms` | 文件检查结果 |
| `CompileResult` | `snakefile_text, rule_of_node, outputs, log_paths, targets, warnings` | 键为 `bio_uid`，路径均为绝对路径 |
| `RunStatus` | `run_id, mode, target_uid, dry_run, state, node_states, progress, pid, log_path, started_at, finished_at, returncode, failed_rule` | 持久化为 `status.json` |
| `Config` | `workspace, data_dir, cache_dir, upstream_dir, conda_prefix, wrappers_version, cores, deploy, allowed_input_roots, allow_unreviewed, bioconda_channeldata_url` | `bioconda_channeldata_url` 目前未被使用（§15 Q4） |

`ToolSource` 在实现中额外出现 `local-installed`（本机工具）与 `local-demo`（离线演示）两个取值。

### 4.2 画布会话约定 `glue/session_schema.py`

- **节点的稳定标识是自定义属性 `bio_uid`**（8 位十六进制）。NodeGraphQt 每次加载都会用 `hex(id(obj))` 重新分配节点 id，`nodes` 字典的键只用于在同一份 JSON 内解析 `connections`，不能跨保存/加载引用。rule 名、MCP 的 `node_id`、`RunStatus.node_states` 的键一律使用 `bio_uid`。
- 节点类型：

| 节点 | `type_` | 端口 | 自定义属性 |
| :--- | :--- | :--- | :--- |
| FASTQ 输入 | `bio.input.FastqInputNode` | 输出 `reads`（FASTQ，multiple，值为 [R1] 或 [R1,R2]） | `bio_uid, path_r1, path_r2` |
| FASTA 参考 | `bio.input.FastaReferenceNode` | 输出 `fasta` | `bio_uid, path` |
| BAM 输入 | `bio.input.BamInputNode` | 输出 `bam` | `bio_uid, path` |
| VCF 输入 | `bio.input.VcfInputNode` | 输出 `vcf`（VCF/BCF） | `bio_uid, path` |
| 输出汇总 | `bio.output.BioOutputNode` | 输入 `files`（ANY，可多连） | `bio_uid, label` |
| 工具 | `bio.tool.T_<slug>_<sha1 前 6 位>` | 按 `ToolSpec` | `bio_uid, tool_id, threads, param_<name>` |

- 工具节点类型名带 `tool_id` 的短哈希，避免不同 `tool_id` 清洗后重名。
- 画布属性一律为字符串；`param_from_str()` 按 `ParamSpec.default` 的类型转换（空串取默认值，布尔接受 true/false/1/0/yes/no/on/off）。
- 连线沿用 NodeGraphQt 原生格式 `{"out": [key, port], "in": [key, port]}`。
- `session.meta.json` 记录 `revision`、`updated_by` 等，用于乐观并发（§9）。

### 4.3 运行目录 `runs/<run_id>/`

| 文件 | 内容 |
| :--- | :--- |
| `Snakefile` | 本次运行的编译快照 |
| `session.json` | 本次运行使用的画布快照 |
| `manifest.json` | Snakemake 命令 argv、`node_of_rule`、`outputs`、`warnings`、`planned_jobs`、`planned_jobs_kind` |
| `status.json` | `RunStatus`，由监督进程原子更新 |
| `snakemake.log` / `supervisor.log` | Snakemake 输出 / 监督进程输出 |
| `ready` / `cancel` | 启动握手标记 / 取消请求标记 |

---

## 5. 模块设计

### 5.1 `glue/bio_inspector.py`（119 行）

`inspect_bio_file(path, preview_n=5, full_stats=False) -> InspectResult`，函数本身不抛异常，错误写入 `valid=False, error`。

- 格式识别由 `glue/formats.detect_format()` 按扩展名完成（先剥离 `.gz/.bgz/.bgzf`）。
- FASTA/FASTQ：`pyfastx.Fastx` 流式读取；快速模式只读前 `preview_n` 条（统计键为 `sampled_records/sampled_bases`），完整模式读全文件（`records/total_bases`）。
- SAM/BAM/CRAM：`pysam.AlignmentFile`；有索引时给出比对统计，CRAM 快速模式只报告参考序列名，不再给出误导性的 mapped=0。
- VCF/BCF：`cyvcf2.VCF` 读头部与前若干条。
- HTML/JSON/TEXT/TSV/BED/GFF/GTF：按文本读取前若干行。
- 索引检查（仅存在性）：FASTA `.fai/.fxi/BWA 五件套`，FASTQ `.fxi`，BAM `.bai/.csi`，CRAM `.crai`，VCF `.tbi/.csi`，BCF `.csi`。
- 快速模式结果附带警告「快速预览只检查已读取的记录，不代表全文件」。

### 5.2 工具注册表

#### 5.2.1 适配器接口

每个适配器提供 `source`、`iter_index() -> Iterator[IndexEntry]`、`load_spec(tool_id) -> ToolSpec`。`ToolRegistry.from_config()` 依次加载：

| 顺序 | 适配器 | `tool_id` 前缀 | 来源 | 现状 |
| :--- | :--- | :--- | :--- | :--- |
| 1 | `InstalledToolsAdapter`（`glue/installed_tools.py`） | `local:` | 本机独立 Conda 环境 `~/.cache/biows/common-tools`（可用 `BIOWS_COMMON_ENV` 覆盖） | 8 个节点：fastp、bwa index/mem、samtools view/sort/index、bcftools stats、seqkit stats；只有对应包和可执行文件存在时才出现 |
| 2 | `SnakemakeWrapperAdapter` | `smk:` | 5 个内置定义（`glue/builtins.py`）+ `upstream_dir/snakemake-wrappers/bio/**/meta.yaml` | v5.0.0 已下载并索引 423 条（418 上游 + 5 内置） |
| 3 | `NfCoreModuleAdapter` | `nf:` / `cwl:` | `upstream_dir/nf-core-modules` 的 `meta.yml` + `main.nf`，以及其中的 `*.cwl` | 稀疏克隆已下载并索引 2,125 个模块；86 个可自动生成 shell |
| 4 | `BiocondaAutoWrapAdapter` | `conda:` / `auto:` | `upstream_dir/bioconda-recipes/recipes/*` 目录名或 `channeldata.json`；已封装定义在 `data_dir/auto_wrapped/<pkg>/<cmd>/meta.yaml` | channeldata 已索引 12,888 个包；按需封装 |

#### 5.2.2 `ToolRegistry`

- `build_index(refresh=False)`：逐适配器读取 `catalog_cache`（`cache_dir/catalog-<source>.json`，以上游 YAML/CWL 文件的路径、mtime、大小与 `.git` 引用计算指纹，指纹不变则直接复用），合并后写 `cache_dir/index.json`；内部加锁并整体替换，可在后台线程调用。
- `categories()`、`get(tool_id)`（按需加载并缓存 `ToolSpec`）。
- `search(query, input_format, output_format, category, limit, offset)`：先按格式/分类过滤；每个关键词按「名称完全相等 10 / 名称前缀 6 / 名称或关键词包含 4 / 摘要包含 1」打分，**所有关键词都必须命中**；未审核条目分数减半；`limit` 被限制在 1–50（UI 与 MCP 相同）。
- `mark_reviewed(tool_id)`：任意已索引工具均可审核；审核结果写入 `data_dir/reviewed.json`，建索引与加载时覆盖 `reviewed`。`auto:` 定义同时改写其 `meta.yaml` 中的 `biows.reviewed`。

#### 5.2.3 阶段一：snakemake-wrappers

- 内置 5 个已核对端口契约的定义：`smk:bio/fastp`、`smk:bio/bwa/index`、`smk:bio/bwa/mem`、`smk:bio/samtools/sort`、`smk:bio/samtools/index`，`reviewed=True`。
- 上游 wrapper：v5.0.0 已下载（423 条：418 上游 + 5 内置）。解析 `meta.yaml` 的 `input/output`：字典项的键作为端口名，非法标识符（如 `Runtime_log.txt`）归一化为 `file_N`；纯文本描述项命名为 `file_N`；格式由 `infer_formats()` 从通配符和描述文字推断，推断不出则为 `ANY`。这类定义一律 `reviewed=False`、分类 `Other`、只带一个 `extra` 参数。
- **未实现**：v0.1 设想的 `port_overrides.yaml` 覆盖文件；当前只有「内置 → 启发式」两级。

#### 5.2.4 阶段二：nf-core/modules 与 CWL

- 端口来自 nf-core `meta.yml`，兼容新旧两种结构；跳过 `meta`（map）元素，`pattern` 用 `expand_brace_glob()` 展开后映射为格式标签。
- 命令由 `glue/nf_converter.convert_script()` **保守转换**：只接受 `script:` 前仅有 `task.ext.args/prefix` 默认值的模块；脚本中出现 `${if`、`.collect`、`.join(`、`meta.`、`?:`、`->` 等无法静态求值的结构就放弃转换。转换失败的模块不生成 shell，只能检索、不能运行（需先提供经审核的自动封装定义）。
- 实测覆盖率：2,125 个模块中 86 个可自动生成 shell（约 4%），其余只能检索、不能直接运行。
- CWL：识别 `*.cwl` 的静态 `File`/`File[]` 端口和静态输出文件名。执行时编译器生成 job JSON（base64 内联到 Snakefile），由 `python -m glue.cwl_runner` 调用 `cwltool`。
  - 说明：Snakemake 9.27 文档中 `cwl:` 指令**仍然存在**（v0.1 写「已移除」是错误的）。实现选择自带 runner，是为了自行控制 job 生成和静态输出路径；改回原生 `cwl:` 指令列为待办（§15 Q5）。

#### 5.2.5 阶段三：Bioconda 自动封装

- 索引：`bioconda-recipes/recipes/` 存在时用其中的**目录名**生成 `conda:<pkg>` 条目；否则读取 `channeldata.json` 的 `packages`（实测 12,888 个包，摘要入索引）。不解析 recipe 的 `meta.yaml`，因为它们是 Jinja2 模板，`yaml.safe_load` 无法解析。
- 封装（`prepare` → `store_definition`）：
  1. 校验包名、命令名（正则白名单，禁止路径、空白和 shell 字符）。
  2. 若环境不存在，则执行 `conda create -p <conda_prefix>/biows-<pkg>`（超时 900 s）。
  3. `conda run` 依次尝试 `--help`、`-h`、`help`、无参数来抓取帮助文本（截断到 16 KB）。
  4. 校验提交的 YAML：`biows.inputs/outputs/params/shell`，至少一个输入和一个输出，shell 占位符只能引用已声明的端口和参数。
  5. 落盘为 `auto:<pkg>/<cmd>`，固定包版本，`reviewed: false`。
- 已实现基于 `channeldata.json` 的索引（§15 Q4）；下载与格式校验见 `glue.fetch_catalog`。
- 创建环境固定 `--override-channels -c conda-forge -c bioconda`，不依赖 defaults 渠道；可执行文件由配置 `conda_bin` 指定。
- 多子命令工具用 `binary` 参数接入：工具 ID 使用独立命令名（如 `auto:samtools/samtools-faidx`），环境与可执行文件仍为 `samtools`。
- 目录类输出用 `directory: true` 标记：编译器生成 `directory(<path>)` 输出，下游可把它作为目录输入；文件预览对目录返回 `DIRECTORY` 与条目列表。
- 额外依赖：清单可声明 `dependencies`（如 `python=3.11`），写入 `environment.yaml` 并在建环境时一并求解，用于上游包的 Python 兼容性。
- 批量封装：`python -m glue.wrap_batch --manifest tool_packs/top50.yaml`，清单见 `tool_packs/top50.yaml`，可重复执行并复用已有环境。
- 运行期：Snakemake 子进程注入 `CONDA_DEFAULT_CHANNELS=""` 与隔离 `CONDARC`，避免 conda 26 默认渠道 ToS 阻塞环境创建；`conda_bin` 所在目录加入子进程 PATH。seqkit 已验证「画布 → Snakemake」端到端运行（2/2 步，输出正确）。

### 5.3 `glue/snakemake_bridge.py` 与运行监督

#### 5.3.1 编译器 `compile_session(session, registry, workdir, *, allow_unreviewed=False, allowed_input_roots=()) -> CompileResult`

纯函数，不写任何文件。

1. 校验：`bio_uid` 合法且唯一；未知节点类型报错；未审核工具在 `allow_unreviewed=False` 时报错。
2. 连线校验：端口存在且方向正确，格式兼容（`formats_compatible`），无重复连线，非 multiple 端口只能有一个上游；使用 `graphlib` 检测环（只做静态校验，调度仍交给 Snakemake）。
3. 输入节点不生成 rule；其路径必须位于工作区或 `allowed_input_roots` 内（解析符号链接后判断）且文件存在。
4. 工具节点生成一条 rule：
   - rule 名：`n_<清洗后的 spec.name>_<bio_uid>`。中文名称会清洗成下划线，例如 `n_BWA_MEM______c7000006`。
   - 输入：上游只有一个工具时写 `rules.<rule>.output.<port>`，否则写绝对路径字面量。
   - 输出：`<workdir>/results/<rule>/<port><扩展名>`；multiple 端口按上游 multiple 输入的文件数编号为 `_1`、`_2`；`BWA_INDEX` 用 `multiext(...)`；CWL 用其静态输出文件名。
   - `params`（`repr()`）、`threads`、`log: logs/<rule>.log`、`benchmark: benchmarks/<rule>.tsv`。
   - 执行指令按 `ExecSpec` 生成：`wrapper:`、`conda:`/`container:` + `shell:`，或 cwl_runner 的 `shell:`。没有可执行模板时报错。
5. 目标：所有输出节点的上游产物，写入 `rule all`；没有输出节点时取所有叶子工具节点的输出。没有任何目标时报错。

#### 5.3.2 命令构造 `build_command()`

```
python -m snakemake -s <runs/ID/Snakefile> -d <workdir> --cores N
    --printshellcmds --rerun-incomplete --nocolor
  [--conda-prefix P --use-conda | --sdm conda apptainer]   # 仅当 Snakefile 含 wrapper/conda/container
  [<rule> --until <rule>]                                  # 运行至此
  [<rule> --until <rule> --forcerun <rule>]                # 单步
  [--dry-run]
```

- 不含 wrapper/conda/container 的纯 shell 工作流不需要 Conda。
- 「运行至此」和「单步」都把目标 rule 显式作为 target，因此即使该分支不在 `rule all` 中也能运行。

#### 5.3.3 `RunManager(workdir, registry, config=None, on_update=None)`

- `start(session, mode, target_uid, cores, dry_run) -> run_id`：
  1. 编译，并按画布拓扑求出目标的全部上游工具节点（`planned_jobs`，即缓存判定前的静态上界；`planned_jobs_kind="graph_rules_before_cache"`）。
  2. 在 `runs.lock` 文件锁内检查是否已有未结束的运行（有则抛 `RunBusyError`），然后写入运行目录的全部快照文件。
  3. 以 `start_new_session=True` 启动脱离的监督进程 `python -m glue.run_worker <dir>`，写入 pid 后创建 `ready` 标记。
  4. 若传入 `on_update`，则起一个守护线程每 0.3 s 读取状态并回调副本。
- `status(run_id)`：读取 `status.json`；若状态未结束但 pid 已不存在或成为僵尸进程，则判为 `failed`。
- `cancel(run_id)`：创建 `cancel` 标记文件。
- `list_runs(limit)`：按 `status.json` 修改时间倒序排列。

#### 5.3.4 运行监督 `glue/run_worker.py`

- 等待 `ready` 后启动 Snakemake（新进程组），逐行写 `snakemake.log`，并经 `parse_log_line()` 更新 `status.json`（原子写）。
- 发现 `cancel` 标记后，对进程组依次发送 SIGINT（等 10 s）→ SIGTERM（等 5 s）→ SIGKILL。
- 结束时归一化节点状态：成功运行中实际执行且输出齐全的节点记为 `done`，其余（缓存命中或未执行）记为 `skipped`；失败时仍处于 running 的节点记为 `failed`。
- 监督进程独立于 UI/MCP，关闭界面后运行与状态记录继续。

#### 5.3.5 日志解析 `parse_log_line()`

纯函数，兼容 Snakemake 8/9 的文本输出：

| 模式 | 动作 |
| :--- | :--- |
| `(local)rule X:` + `jobid: N` | 记录 jobid → rule，节点置 `running` |
| `Finished job N` / `Finished jobid: N` | 节点置 `done` |
| `N of M steps` | 更新 `progress` |
| `Error in rule X:` | 节点置 `failed`，记录 `failed_rule` |
| `Nothing to be done` | 等待中的节点置 `skipped` |

### 5.4 `ui/workstation_window.py`（1,410 行）

#### 5.4.1 布局

菜单（文件 / 编辑 / 运行 / 工具库 / 视图）+ 工具栏（保存、全量运行、预演、取消、运行历史、适应画布，右侧为节点状态颜色图例）。停靠面板：左侧工具库，右侧属性（NodeGraphQt `PropertiesBinWidget`）与文件预览，底部运行日志。状态栏显示运行状态与进度条。

#### 5.4.2 节点类

- `BioNode` 基类记录各端口的格式标签。`BioInputNode` 有 4 个具体子类，`BioOutputNode` 1 个。
- `SnakemakeWrapperNode` 按 `tool_id` **懒生成子类**：首次拖入或加载时用 `type()` 生成，`register_node` 后缓存。
- 所有自定义属性的默认值都来自 `session_schema`，保证与 MCP 写出的节点逐字段一致。路径用 `FILE_OPEN` 控件，参数和线程数用 `QLINE_EDIT`，`bio_uid`/`tool_id` 隐藏。
- 加载会话前先调用 `sanitize_session()`（补全默认属性，移除不可用节点和损坏连线，修复重复 uid），再预注册所需的工具类，最后 `deserialize_session`。

#### 5.4.3 工具库

- 分类懒展开：展开时才创建子项。搜索框 200 ms 防抖，支持 `in:FORMAT`、`out:FORMAT` 过滤。
- 未封装或未审核的条目显示为灰色并加后缀。
- 拖拽载荷为 `text/plain` 的 `biows-tool:<tool_id>` / `biows-node:<type>`。NodeGraphQt 画布只接受 `nodegraphqt/nodes`、`text/plain`、`text/uri-list` 三种格式，非原生载荷会经 `data_dropped` 信号转交，由 UI 懒注册节点类后在落点创建节点。
- 双击条目在视图中心创建节点。

#### 5.4.4 端口格式拦截

`port_connected` 中调用 `formats_compatible()`。不兼容时提示原因，并延后到事件循环中撤销这次连接（若栈顶是 connect 宏则 `undo()`，可一并恢复被替换的旧连线；否则直接断开）。

#### 5.4.5 编辑与菜单

- 编辑菜单：撤销 / 重做（绑定 undo 栈）、复制、粘贴、删除、全选。后四项的快捷键只在画布获得焦点时生效。粘贴后立即重新分配重复的 `bio_uid`。
- 工具节点右键：运行此步、运行至此节点、预览输出文件、用默认程序打开输出、查看节点日志、打开输出目录、标记为已审核。
- 输出节点右键：预览输出文件、用默认程序打开输出。
- 输入节点右键：检查文件（完整统计）。
- 画布空白处右键：全量运行、预演、取消、自动布局、保存。

#### 5.4.6 状态着色

边框颜色：等待灰、运行中黄、完成绿、失败红、跳过/缓存淡绿；输入文件校验失败也显示红色。着色使用 `set_property(..., push_undo=False)`，不进入撤销栈。

#### 5.4.7 工作区同步

每 500 ms 轮询一次（取代 v0.1 的 `QFileSystemWatcher`，因为原子替换会使文件监视失效）：

- `session.meta.json` 的 revision 变化时：本地没有未保存修改则自动重载，否则询问；用户拒绝后该 revision 不再询问。轮询期间若有模态对话框打开则暂停。
- 最新运行未结束且不是当前跟随的运行时（例如 Agent 发起的），自动切换跟随。跟随中逐段读取 `snakemake.log` 并应用 `status.json`。
- 运行历史对话框（Ctrl+H）可选择任一历史运行，回放其节点状态与完整日志。

### 5.5 `mcp_server/bio_mcp.py`（268 行）

启动：`python -m mcp_server.bio_mcp --workspace DIR`（stdio）。耗时操作都通过 `asyncio.to_thread` 执行。

| 工具 | 签名 | 行为 |
| :--- | :--- | :--- |
| `search_bio_tools` | `(query="", input_format=None, output_format=None, limit=10, offset=0)` | 分页检索，每页至多 50 条 |
| `auto_wrap_bioconda_pkg` | `(pkg_name, cli_cmd, meta_yaml=None)` | 两段式：不带 `meta_yaml` 时返回帮助文本（≤6000 字符）、schema 与示例；带上时校验、落盘并刷新索引，返回 `reviewed=False` |
| `add_node` | `(tool_id_or_kind, properties=None, position=None)` | kind 可为 `fastq_input`/`fasta_reference`/`bam_input`/`vcf_input`/`output` 或工具 id；返回 `node_id`（即 `bio_uid`）；参数属性名为 `param_<name>` |
| `connect_nodes` | `(from_node, from_port, to_node, to_port)` | 端口存在性、格式兼容、单输入约束、环检测；不兼容时返回 `{ok: false, reason}` |
| `compile_and_run_async` | `(mode="all", target_node=None, cores=4, dry_run=False)` | 返回 `run_id, snakefile_path, planned_jobs, planned_jobs_kind, warnings` |
| `get_run_status` | `(run_id, log_tail=30)` | `RunStatus` 加日志末尾（≤100 行、≤8 KB） |
| `inspect_output_file` | `(node_id_or_path, full_stats=False)` | 节点 id 时解析其输出；路径必须位于工作区内（解析符号链接）；最多 10 个文件 |

所有会话写入走 `session_store.save_session(..., expected_revision, updated_by="mcp")`。**未实现**：v0.1 设想的 MCP sampling 路径（服务端直接请求客户端 LLM 生成工具定义），目前只有两段式调用。

---

## 6. 关键流程（时序）

### 6.1 用户在 UI 中搭建并运行

```
拖入 FASTQ 输入 → 设置路径 → 后台 inspect_bio_file（快速）→ 预览面板/边框
搜索 "bwa" → 拖入 → data_dropped → 懒注册节点类 → create_node
连线 → port_connected → formats_compatible（不兼容则撤销）
右键「运行至此」→ RunManager.start（编译、快照、启动监督进程）
轮询 status.json + 追加 snakemake.log → 节点着色 / 进度条
右键输出节点「预览输出文件」→ compile_session 解析路径 → inspect_bio_file
```

### 6.2 Agent 通过 MCP 搭建并运行

```
search_bio_tools(input_format="FASTQ", query="fastp")      → smk:bio/fastp / local:fastp
add_node("fastq_input", {path_r1, path_r2})                → node_id(bio_uid)
add_node("local:fastp") …                                  → node_id …
connect_nodes(n1,"reads",n2,"sample")                       → ok / 不兼容原因
compile_and_run_async(mode="all")                           → run_id, planned_jobs
get_run_status(run_id)（轮询）                              → running … success
inspect_output_file(n_out)                                  → 文件统计 + 前 5 条
（UI 侧在 500 ms 内重载画布并自动跟随该运行）
```

### 6.3 Bioconda 长尾工具自动封装

```
search_bio_tools("xxx") → conda:xxx（未封装）
auto_wrap_bioconda_pkg("xxx","cmd")            → 建环境 + 帮助文本 + schema
Agent 依据帮助文本编写 biows YAML
auto_wrap_bioconda_pkg("xxx","cmd", meta_yaml) → 校验、落盘为 auto:xxx/cmd（未审核）
UI 中右键「标记为已审核」后才能在默认配置下运行
```

---

## 7. 文件格式类型系统（`glue/formats.py`）

### 7.1 格式标签

`FASTQ, FASTA, SAM, BAM, CRAM, BAI, VCF, BCF, BED, GTF, GFF, BWA_INDEX, HTML, JSON, TSV, TEXT, ANY`。

| 标签 | 识别的扩展名（可叠加 `.gz/.bgz/.bgzf`） | 编译时输出扩展名 |
| :--- | :--- | :--- |
| FASTQ | `.fq .fastq` | `.fastq.gz` |
| FASTA | `.fa .fasta .fna .fas` | `.fa` |
| SAM/BAM/CRAM | 同名 | 同名 |
| BAI | `.bai .csi` | `.bai` |
| VCF / BCF | `.vcf` / `.bcf` | `.vcf.gz` / `.bcf` |
| BED/GTF/GFF | `.bed .gtf .gff .gff3` | 同名 |
| BWA_INDEX | `.amb .ann .bwt .pac .sa` | `multiext` |
| HTML/JSON/TSV/TEXT | `.html .json .tsv .csv .txt .log` | 同名 |
| ANY | 其他 | `.dat` |

目录输出不新增格式标签，由 `PortSpec.directory` 标记；预览返回 `DIRECTORY` 与条目列表。

### 7.2 兼容规则 `formats_compatible(out, in) -> (bool, reason)`

1. 任一方含 `ANY` → 兼容。
2. 集合有交集 → 兼容。
3. 下游显式声明组名 `ALIGNMENT`（SAM/BAM/CRAM）或 `VARIANT`（VCF/BCF）时，组内成员都可接入。
4. 其他情况不兼容，reason 形如「输出为 BAM，输入需要 FASTQ」。

UI 的端口拦截、MCP 的 `connect_nodes` 和编译器共用同一个函数。

---

## 8. 目录与工作区布局

### 8.1 代码仓库

```
openbioworkstation/
├── DESIGN.md  README.md  requirements.txt  requirements-dev.txt  pyproject.toml  run-demo.sh
├── glue/
│   ├── models.py  session_schema.py  errors.py        # 前后端契约（前端维护）
│   ├── bio_inspector.py  formats.py  config.py
│   ├── wrapper_registry.py  builtins.py  installed_tools.py  nf_converter.py  catalog_cache.py
│   ├── snakemake_bridge.py  run_worker.py  session_store.py
│   └── tool_runner.py  cwl_runner.py                  # 被生成的 shell 命令调用的 CLI
├── ui/  __init__.py（设定 QT_PREFERRED_BINDING=PySide6）  workstation_window.py
├── mcp_server/  bio_mcp.py
├── examples/    demo.py  demo_tools.py  README.md     # 离线演示
├── tests/       test_backend.py
├── validation/  验证脚本（历史本机报告不公开）
└── promo/       真实界面截图、结果成品及宣传物料

研究工作区 studies/ 整体保留在本地，不随公开仓库发布。
```

### 8.2 用户数据（XDG）

```
~/.config/biows/config.yaml           # 配置
~/.local/share/biows/upstream/        # 上游仓库（需手动放置）
~/.local/share/biows/auto_wrapped/    # 自动封装定义
~/.cache/biows/index.json  catalog-*.json
~/.cache/biows/conda-envs/            # Snakemake --conda-prefix 与 biows-<pkg> 环境
~/.cache/biows/common-tools/          # 本机工具环境（local: 节点）
```

### 8.3 项目工作区

```
<workspace>/
├── session.json  session.meta.json  session.lock  runs.lock
├── Snakefile                    # 最近一次运行的编译结果
├── results/<rule>/…  logs/<rule>.log  benchmarks/<rule>.tsv
├── runs/<run_id>/…              # 见 §4.3
└── .snakemake/
```

---

## 9. 并发、状态同步与一致性

| 场景 | 方案 |
| :--- | :--- |
| UI 与 MCP 同时编辑画布 | `save_session` 在 `session.lock`（flock）内比较 `expected_revision`，一致则原子写入并递增 revision，否则抛 `SessionConflictError`。UI 让用户选择覆盖、重载或取消；MCP 返回错误 |
| 同一工作区并发运行 | `runs.lock` 内检查未结束运行；Snakemake 自身的目录锁作为第二道防线 |
| UI/MCP 退出后运行继续 | 运行由脱离的 `run_worker` 进程托管 |
| 监督进程异常死亡 | `status()` 发现 pid 不存在或为僵尸进程时判为 `failed` |
| 不完整输出 | 始终带 `--rerun-incomplete` |

---

## 10. 安全设计

| 风险 | 对策 | 状态 |
| :--- | :--- | :--- |
| 命令注入 | 子进程一律 argv；包名、命令名、端口名、参数名用正则白名单，并排除 Python 关键字 | ✅ |
| Snakefile 代码注入 | 属性值、路径一律 `repr()`；`shell:` 中的端口引用使用 `{input.x:q}` 引号；不允许 `run:` 块 | ✅ |
| LLM 生成的定义 | `reviewed: false`；默认 `allow_unreviewed=false` 时拒绝编译；需在 UI 中审核 | ✅ |
| 任意文件读取 | 输入路径限制在工作区与 `allowed_input_roots` 内，MCP 输出预览限制在工作区内，均解析符号链接后判断 | ✅ |
| 环境膨胀 | `conda create` 超时 900 s | ⚠️ 未做磁盘配额检查 |
| 上游篡改 | wrapper 指令带固定版本前缀（`wrappers_version`） | ⚠️ 上游仓库未固定 commit |

---

## 11. 性能约束与预算

| 指标 | 目标 | 现状 |
| :--- | :--- | :--- |
| 冷启动 | < 2 s（索引已缓存） | 当前索引很小，未在大规模索引下测量 |
| 首次建索引（~14,000 项） | < 60 s，后台进行 | 未实测（上游未下载） |
| 工具搜索 | < 50 ms | 线性扫描；万级条目未实测 |
| 文件快速检查 | < 100 ms，与文件大小无关 | 演示数据上为毫秒级 |
| 节点状态刷新延迟 | < 500 ms | 轮询 500 ms + 监督进程逐行写入 |
| 默认安装 | 不预装工具环境 | ✅ |

---

## 12. 依赖与版本锁定

`requirements.txt`：

```text
NodeGraphQt>=0.6.40
PySide6>=6.6
snakemake>=8.20,<10
pyfastx>=2.1
pysam>=0.22
cyvcf2>=0.31
pyyaml>=6.0
mcp[cli]>=1.2,<2
setuptools>=70        # Python 3.12+ 下为 NodeGraphQt 提供 distutils 兼容
```

- 已验证的组合：Python 3.12.14，snakemake 9.27.1，mcp 1.30.0，PySide6 6.12.0，NodeGraphQt 0.6.44，pyfastx 2.3.1，pysam 0.24.1，cyvcf2 0.34.0。
- NodeGraphQt 通过 Qt.py 选择 Qt 绑定，环境变量是 `QT_PREFERRED_BINDING`（由 `ui/__init__.py` 设定），不是 qtpy 使用的 `QT_API`。
- 开发依赖：`requirements-dev.txt`（pytest、ruff）。代码风格以 `pyproject.toml` 中的 ruff 配置为准。
- 外部可执行程序：`conda`（使用 wrapper/conda 节点、自动封装时需要）、`cwltool`（CWL 节点）、`apptainer`（容器模式）。

---

## 13. 测试与验证

| 层级 | 现有内容 |
| :--- | :--- |
| 单元/集成（`tests/test_backend.py`，15 项） | 格式规则、会话冲突、符号链接路径、注册表、编译与环检测、目录输出编译、目录预览、文件检查、自动封装定义校验、Top-50 清单定义校验、审核覆盖、日志解析、真实 Snakemake 执行、planned_jobs 与单步状态 |
| 验证脚本（`validation/`） | `readers_check`（14 种格式）、`modes_check`（预演/全量/单步/运行至此）、`cancel_check`（互斥、取消、无孤儿进程）、`mcp_stdio_client`（7 个工具）、`ui_smoke`（offscreen UI 加载与保存）、`common_tools_check`/`common_tools_ui`（本机工具真实运行）、`demo_check`、`catalog_check`（真实上游索引 15,447 条与构建耗时）、`wrap_smoke`（auto 封装工具的合成数据冒烟，可只审核通过项） |
| 端到端 | auto `seqkit`（合成 FASTQ）、`smk:bio/fastp`（wrapper + Conda）、auto `fastqc`（目录输出）、`bcftools query`（课题真实 VCF）、`samtools flagstat`（课题真实 BAM）均经编译与 Snakemake 真实运行通过；Top-50 首批 46/46 合成数据冒烟通过 |
| 未覆盖 | Snakefile 编译快照测试、多版本 Snakemake 日志样本、注入用例的系统化测试、大规模索引性能 |

---

## 14. 交付里程碑与当前状态

| 里程碑 | 验收标准 | 状态 |
| :--- | :--- | :--- |
| M1 | 命令行下：检查文件、搜索工具、构造会话、编译、`snakemake -n` 通过；演示链路真实运行且状态解析正确 | ✅ 完成。`local:` 节点链路、离线演示链路与 `smk:` fastp + Conda 链路均已真实运行 |
| M2 | UI 完成 §6.1；MCP 在 Claude Code/Desktop 中完成 §6.2；UI 实时看到 MCP 的修改与运行 | ⚠️ UI 流程与 UI↔MCP 同步已实测；MCP 只用自写 stdio 客户端验证，未在真实 Agent 客户端中实测 |
| M3（可选） | nf-core 转换覆盖率、Snakemake logger 插件、多样本通配符、端口覆盖文件 | ❌ 未开始 |

---

## 15. 风险与待决问题

| 编号 | 风险 / 问题 | 当前决策 |
| :--- | :--- | :--- |
| R1 | snakemake-wrappers 的 `meta.yaml` 不给出结构化端口名 | 内置定义加启发式推断，推断出的定义默认未审核；待补端口覆盖文件 |
| R2 | CWL 支持依赖 `cwltool`，且 Snakemake 的 CWL 功能维护不活跃 | 自带 `cwl_runner` 只支持静态端口和输出；见 Q5 |
| R3 | nf-core 命令是 Groovy 模板 | 保守转换，不能证明正确时不生成命令；可运行比例待统计 |
| R4 | 日志文本格式随 Snakemake 版本变化 | 解析器为纯函数，并锁定 `snakemake<10`；长期迁移到 logger 插件 |
| R5 | LLM 生成定义的质量与安全 | schema 校验，未审核默认禁止运行 |
| R6 | 中文工具名清洗后 rule 名可读性差 | 不影响正确性（uid 保证唯一）；可改用 `tool_id` 生成 rule 名 |
| R7 | NodeGraphQt 与 PySide6 版本兼容 | 已锁定并验证 §12 的组合 |
| R8 | 后端代码风格与契约文件不一致（缺类型注解、使用缩写别名） | 待统一 |
| R9 | 上游包与 Python 版本不兼容（如 QUAST 5.3 需 Python 3.11） | 清单支持 `dependencies` 固定版本；封装后用冒烟发现并修正 |
| Q1 | 多样本通配符 | v2 |
| Q2 | 内存资源暴露 | M3 |
| Q3 | MCP 在 UI 未打开时运行 | 允许；状态持久化，UI 打开后可在运行历史中查看 |
| Q4 | Bioconda 索引改用 `channeldata.json` | ✅ 已实现；recipes 缺失时读取 channeldata（12,888 包），下载见 `glue.fetch_catalog` |
| Q5 | CWL 是否改用 Snakemake 原生 `cwl:` 指令 | 待评估 |
| Q6 | MCP sampling 自动封装路径 | 待实现 |

---

## 附录 A：v0.1 → v0.2 修订记录

| v0.1 写法 | 实际实现 / 更正 |
| :--- | :--- |
| 「Snakemake 8 起已移除 `cwl:` 指令」 | 错误。Snakemake 9.27 文档中该指令仍然存在；实现选择自带 `cwl_runner` |
| rule 名用「node_id 前 8 位」 | NodeGraphQt 加载时会重分配 id，且内存地址前缀几乎相同；改为 `bio_uid` |
| 预演使用 `-n --quiet rules` | 该参数会隐藏需要解析的行；实现只用 `--dry-run`，`planned_jobs` 由画布拓扑计算 |
| 输入节点「一个或两个输出端口」 | FASTQ 输入节点只有一个 `reads` 端口（列表）；输出节点只有一个可多连的 `files` 端口 |
| `QT_API=pyside6` | Qt.py 使用 `QT_PREFERRED_BINDING` |
| requirements 含 `snakemake-wrapper-utils` | 已删除（由各 wrapper 自己的环境安装）；新增 `setuptools`，`mcp` 限定 `<2` |
| `ToolSpec.exec` | 字段名为 `execution` |
| Bioconda 索引读 recipe `meta.yaml` | recipe 是 Jinja2 模板；实现只用目录名 |
| UI 用 `QFileSystemWatcher` 监听 | 改为 500 ms 轮询（原子替换会使文件监视失效） |
| 自定义 MIME 类型拖拽 | 画布只接受三种格式；改用 `text/plain` 加 `data_dropped` 信号 |
| `RunManager` 在 UI/MCP 进程内用读取线程托管 Snakemake | 改为脱离的 `run_worker` 监督进程，取消通过 `cancel` 标记文件实现 |
| 测试中使用 `snakemake --lint` | 生成的 Snakefile 必然触发 lint 警告（如绝对路径）；改为 `--dry-run` 校验 |
| 未提及本机工具 | 新增 `InstalledToolsAdapter`（`local:` 节点） |
