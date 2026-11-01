# Project communication copy

[Asset guide](README.md) · [Agent tutorial](../docs/agent-workflow.en.md)

## One-line description

A visual bioinformatics workstation for agent collaboration and on-demand tool adaptation.

## Short description

OpenBioWorkstation combines a node editor, Snakemake execution and MCP access in a shared local workspace. Researchers define questions and methods; agents assist with tool discovery, workflow construction, execution and output inspection. LLM-assisted adaptation generates additional tool definitions when required by an analysis.

## Social post

OpenBioWorkstation supports researcher-agent collaboration in local bioinformatics analysis. Construct workflows visually, execute them with Snakemake and use MCP to let an agent discover tools, build graphs and inspect outputs. LLM-assisted adaptation prepares tool definitions on demand. Linux desktop; GPL-3.0-only.

## Extended project introduction

Bioinformatics tools differ in implementation languages, dependency environments, command-line interfaces and input/output conventions. Writing, testing and maintaining a separate adapter for every tool and subcommand entails substantial, recurring engineering work as tools evolve.

OpenBioWorkstation addresses this integration burden through LLM-assisted, on-demand adaptation during analysis preparation. When a required tool lacks a suitable node definition, the workstation can prepare its dependency environment, retrieve command-line help and request an LLM-generated definition of inputs, outputs, parameters and execution commands. Structural checks and synthetic-input trials precede review. Adaptation is driven by the current task rather than requiring exhaustive advance integration of the entire ecosystem.

Through MCP, an agent can discover tools, construct workflows, start tasks and inspect outputs. The researcher retains responsibility for study design, method selection, parameter review and interpretation. Snakemake executes the workflow, while the workstation associates graph structure, execution logs and result files in a shared local workspace.

A local snapshot dated 1 November 2026 contained 69 software packages with 78 adapted nodes. Including five built-in wrapper definitions and ten local nodes, the installation contained 93 node definitions; 62 carried review flags. Review coverage is being expanded. The catalog contained 15,524 searchable entries from sources including Snakemake Wrappers, nf-core and Bioconda.

Packages, node definitions and catalog entries are distinct counts. These figures describe the recorded local installation, not the default contents of a fresh clone. An indexed tool is not necessarily executable or automatically adaptable. Generated definitions and successful synthetic trials do not establish correctness for real datasets.

The project targets Linux single-machine analysis and is distributed under GPL-3.0-only. An agent-collaboration tutorial and research examples accompany the software.

Project: https://github.com/ArchitektSpeer/openbioworkstation

## Demonstration sequence

1. Introduce the scientific question, sample design and researcher-agent responsibilities.
2. Discover SeqKit through MCP and create input, tool and output nodes.
3. Inspect ports, input previews and dry-run results.
4. Show actual run IDs, execution states, logs and the resulting TSV.
5. Explain extensions to real data and present the existing research examples.

## Frequently asked questions

**Does the agent perform the entire research process?**

The agent assists operational work. Researchers remain responsible for study design, justified parameters, assessment of evidence and interpretation.

**Are all indexed tools executable?**

No. Metadata entries, generated commands, executable definitions and validated workflows represent different levels of support. Check dependencies and definitions for the intended analysis.

**Does all data remain local?**

Workflow execution and storage are local. Dependency downloads and model requests may use the network. External-agent prompts and tool results follow the selected client's settings.

**Do the case studies establish general biological validity?**

They illustrate particular analyses and their existing reports. The WSMV negative result does not establish equivalence. Exploratory novelty claims were not rechecked for the communication materials. The reports are not presented as peer-reviewed publications.

**Where should a new user start?**

Run the offline demo, then follow the agent tutorial for the synthetic SeqKit exercise.

## Claim basis

- Architecture and behavior: [project overview](../README.md), [design document](../DESIGN.md).
- Current MCP tools and parameters: [server implementation](../mcp_server/bio_mcp.py).
- Synthetic exercise and scope: [tutorial](../docs/agent-workflow.en.md), [script](../examples/agent_seqkit.py).
- Tool counts: [local snapshot](qzone/tool-counts.json).
- Image provenance and historical review limits: [asset guide](README.md), [review record](review_log.md).
- Research status and limitations: [research examples](research/README.md).

No performance, adoption or institutional endorsement claim is made.
