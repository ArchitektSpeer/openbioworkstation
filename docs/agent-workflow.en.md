# Agent-assisted bioinformatics analysis

[简体中文](agent-workflow.zh-CN.md) | **English** · [Project overview](../README.md)

This tutorial uses MCP to connect an agent to a computational bioinformatics workflow. The researcher defines the question, study design and interpretation; the agent converts operational steps into inspectable tool calls and run records. “Experiment” here means computational analysis, not wet-lab equipment control.

## 1. Responsibilities

| Stage | Researcher | Agent and workstation |
|---|---|---|
| Question and design | Define controls, replicates, confounders and endpoints | Organize sample metadata and identify missing information |
| Data and methods | Confirm provenance, reference versions and parameter rationale | Inspect files, discover tools and construct the graph |
| Execution | Review generated commands and important intermediate outputs | Perform a dry run, execute and retrieve states and logs |
| Interpretation | Assess assumptions, effect sizes and limits | Summarize evidence, anomalies, parameters and result tables |

Generated prose is not evidence of execution. Reports should identify actual run IDs, logs, files and statistical outputs. A successful synthetic test does not establish biological validity.

## 2. Installation and a separate workspace

Install Python dependencies using the [project instructions](../README.md). The exercise requires only SeqKit. Skip this installation if your existing common-tools environment already contains it:

```bash
conda create -y --solver libmamba --override-channels \
  -c conda-forge -c bioconda --strict-channel-priority \
  -p ~/.cache/biows/common-tools seqkit
mkdir -p ~/biows/projects/agent-seqkit/inputs
```

`BIOWS_COMMON_ENV` selects an alternative environment containing both Conda package metadata and executables. A binary on the system PATH alone does not register a `local:` node. Create two synthetic 4-bp reads:

```bash
printf '@r1\nACGT\n+\nIIII\n@r2\nTGCA\n+\nIIII\n' \
  > ~/biows/projects/agent-seqkit/inputs/reads.fastq
```

Use a fresh exercise directory to preserve existing files. No sequencing download is needed. This exercise does not evaluate real-sample quality or variation.

## 3. Connect an agent through MCP

This is a generic stdio configuration; consult your client's documentation for configuration location and supported fields. Replace every path with an absolute path; do not use `~` in this JSON:

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

Pass `BIOWS_COMMON_ENV` in the server's `env` when using a custom prefix. Clients normally start stdio servers themselves. Confirm these nine tools are available:

| Tool | Purpose |
|---|---|
| `search_bio_tools` | Search by keyword and file format |
| `add_node` | Add an input, tool or output node |
| `connect_nodes` | Connect ports using stable node IDs |
| `compile_and_run_async` | Compile a run snapshot and start asynchronous execution |
| `get_run_status` | Retrieve saved state and bounded log output |
| `inspect_output_file` | Inspect node outputs or workspace-contained files |
| `auto_wrap_bioconda_pkg` | Extract CLI help and submit a tool definition |
| `wrap_tool` | Start an on-demand wrapping job |
| `get_wrap_job` | Query a wrapping job |

Stdio testing and end-user agent integration are separate verification levels. The supplied script uses the MCP Python client; it does not establish Claude Desktop compatibility. The standard MCP server does not register demo-only tools, so use a fresh standard workspace rather than `demo_workspace`.

Open the same standard workspace in the desktop application:

```bash
.venv/bin/python -m ui.workstation_window --workspace ~/biows/projects/agent-seqkit
```

Both interfaces share local session files. Save UI changes before agent edits; reload and reconcile after revision conflicts. The current high-level MCP interface does not read the complete canvas, modify existing node parameters or delete nodes. Use the UI or reviewed scripts for those operations rather than inventing tool names.

## 4. A prompt for the agent

```text
Use the openbioworkstation MCP tools in the configured fresh workspace to summarize a synthetic FASTQ.
Input: inputs/reads.fastq in the workspace, containing two 4-bp reads.
First confirm local:seqkit/stats is available. Do not download data or wrap a replacement tool.
Create FASTQ input -> SeqKit stats -> output, using returned node_id values and port names.
Run with dry_run=true and wait for that run to succeed; then execute with dry_run=false and cores=2.
Poll each run to a terminal state. Inspect the TSV and verify num_seqs=2 and sum_len=8.
Report actual run IDs, output paths, checks and failures. Do not report dry-run success as completed analysis.
This is a computational workflow exercise and produces no biological conclusion.
```

## 5. Tool-call sequence

These are tool names and JSON arguments, not shell commands. Replace `<INPUT_ID>` and other placeholders with the stable `node_id` returned by each `add_node` call, not internal session dictionary keys.

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

After the dry run reaches `state=success`:

```text
compile_and_run_async({"mode":"all","cores":2,"dry_run":false})
get_run_status({"run_id":"<RUN_ID>","log_tail":30})
inspect_output_file({"node_id_or_path":"<TOOL_ID>"})
```

Receiving a run ID does not mean completion. Wait for `success`; report diagnostics for `failed` or `cancelled`. The successful real run should produce one TSV row with `num_seqs=2` and `sum_len=8`. Locate files from inspection results rather than assuming output names. Previews are bounded; inspect full result tables when needed.

To reproduce the same calls without an interactive agent client, use the supplied script. It creates synthetic inputs and requires a workspace without an existing session or identically named input:

```bash
.venv/bin/python -m examples.agent_seqkit \
  --workspace ~/biows/projects/agent-seqkit-script
```

Local verification on 2026-11-01 completed discovery, three nodes/two connections, a Snakemake dry run, actual execution and TSV value checks through a real MCP stdio subprocess: two sequences and eight bases. This verifies the synthetic SeqKit path, not all tools or external agent clients.

## 6. Extend to real research

For short-read alignment, prepare a sample table containing sample IDs, treatment groups, independent biological replicates, batches, R1/R2 paths, provenance and checksums. Record the hypothesis, controls and exclusion criteria before asking the agent to organize execution.

```text
FASTQ -> fastp -> BWA MEM -> SAMtools view -> sort -> index -> output
                      ^
FASTA -> BWA index ----+
```

Search for `local:fastp`, `local:bwa/index`, `local:bwa/mem`, `local:samtools/view`, `local:samtools/sort` and `local:samtools/index` after installing their dependencies. Paired FASTQ inputs use `path_r1` and `path_r2`; a FASTA input uses kind `fasta_reference` with property `path`. Use ports from discovery and node-creation results. Verify one sample before extending to separate sample chains; multi-sample wildcard expansion is not supported.

Alignment alone does not establish differential expression, RNA editing or variation. Choose appropriate downstream counting, filtering, statistical modeling and multiple-testing procedures. Distinguish workstation nodes from external analysis scripts. Report sample size, effect estimates, uncertainty, thresholds and sensitivity analyses. Failure to detect a significant difference is not equivalence.

Research prompt template:

```text
Question: [hypothesis and prespecified endpoint]
Sample table: [path; groups, replicates, batches and files]
Reference: [organism, assembly, annotation and checksums]
Methods: [tools, versions, parameters, filters and statistical model]
Constraints: [cores, allowed input roots and output workspace]
First identify missing information and available tools, then build and dry-run one sample chain.
After execution, summarize inputs, parameters, logs, output checksums and anomalies by run ID.
Separate biological interpretation from execution evidence. Label unexecuted steps explicitly.
```

## 7. Failures and reviewable records

- Missing `local:` node: check Conda metadata, executables and the server's `BIOWS_COMMON_ENV`; restart MCP and search again.
- Connection returns `ok=false`: check direction, format, occupied single-input ports and cycles.
- `step` reruns a target and requires existing upstream outputs. Use `all` or `until` for initial analysis; pass the stable target ID as `target_node`.
- When wrapping is needed, use `wrap_tool` and poll `get_wrap_job`. Generated definitions remain unreviewed; inspect commands, ports and trial outputs before marking them reviewed.
- External agents may transmit prompts and tool results according to client policy. Local execution does not imply previews remain inaccessible to an external model; configure the client accordingly.

Retain `session.json`, the session snapshot, Snakefile, manifest, status and logs in `runs/<run_id>/`. Also export environment versions, input/reference checksums, the analysis plan and final results. Keep API keys out of reports.

## 8. Existing research and demonstration material

The [research showcase](../promo/research/README.md) contains the existing WSMV introduction, case manuscript, software walkthrough and an exploratory wheat chloroplast RNA-editing report. These preserved artifacts were not regenerated by this tutorial and should not be described as peer-reviewed publications. The independent synthetic exercise avoids requiring complete case-study data.
