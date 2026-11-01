# OpenBioWorkstation

**English** | [简体中文](README.zh-CN.md)

**A visual bioinformatics workstation for researcher–agent collaboration**

OpenBioWorkstation is a Linux desktop application for constructing, executing and inspecting bioinformatics workflows. It combines a visual node editor with Snakemake execution and a Model Context Protocol (MCP) interface. Researchers and agents work with the same local workflow, while analysis steps, execution logs and output files remain available for inspection.

The researcher defines the scientific question, selects methods and reviews results. An agent can assist with tool discovery, workflow construction, task execution and output inspection. This division of responsibilities supports agent-assisted computational analysis while retaining researcher oversight of methodological and biological interpretation.

![Example bioinformatics workflow in OpenBioWorkstation](promo/assets/branch.png)

*An excerpt from the WSMV application workflow. The example includes case-specific nodes.*

## Main capabilities

- Construct workflows by connecting input, tool and output nodes, with checks for file-format compatibility.
- Execute a complete workflow, run up to a selected node or repeat a single step; reuse existing outputs where applicable.
- Inspect input and output files, follow node execution states and review previous runs.
- Use MCP to let an agent operate on the same workspace as the desktop interface.
- Generate additional tool definitions from command-line help using an LLM, followed by checks, trial execution and review.

## Installation

OpenBioWorkstation requires Linux, Python 3.11 or later and a graphical desktop session. The example below uses `uv`. Bioinformatics executables are installed separately when required.

```bash
git clone https://github.com/ArchitektSpeer/openbioworkstation.git
cd openbioworkstation
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
./run-demo.sh
```

The demonstration inspects synthetic FASTQ and FASTA files and produces HTML and JSON reports. After Python dependencies have been installed, it runs without network access or Conda. It demonstrates file inspection and workflow execution rather than read filtering, alignment or variant analysis. See the [demo guide](examples/README.en.md) for instructions.

## Working with the desktop application

Open a separate workspace for your own analysis:

```bash
.venv/bin/python -m ui.workstation_window --workspace ~/biows/projects/my-analysis
```

1. Add input nodes and select the corresponding data files. Inspect the file previews before constructing the workflow.
2. Search the tool library, add the required nodes and connect compatible input and output ports.
3. Review tool parameters and run a dry run before starting the analysis.
4. Execute the workflow and inspect node states and logs. For subsequent changes, run up to a selected node or repeat a step whose upstream results are already available.
5. Inspect the output files and save the workspace. Results are stored in `results/`; run records are stored in `runs/`.

The current interface uses Chinese menu labels. Full execution is available as **全量运行**; output inspection is available as **预览输出文件**. Use **Ctrl+S** to save the session. Open demonstration workspaces through `./run-demo.sh`, which registers their additional example tools.

## Available tools

Tool availability depends on installed executables, downloaded metadata and locally prepared definitions. The application provides five built-in wrapper definitions for fastp, BWA index/mem and SAMtools sort/index. Local nodes additionally cover SAM/BAM conversion, filtering and deduplication, variant statistics and sequence statistics.

Install the commonly used executables with Conda:

```bash
conda create -y --solver libmamba --override-channels \
  -c conda-forge -c bioconda --strict-channel-priority \
  -p ~/.cache/biows/common-tools fastp bwa samtools bcftools seqkit
```

Set `BIOWS_COMMON_ENV` if these packages are installed in a different Conda environment. Local executable-based nodes require both package metadata and the corresponding binaries in that environment.

The repository also includes a [tool pack](tool_packs/top50.yaml) containing 50 node definitions for 42 software packages. These definitions do not install their dependencies automatically when the repository is cloned.

A local installation snapshot dated **1 November 2026** contained 69 software packages with 78 adapted nodes. Together with five built-in definitions and ten local nodes, this represented 93 node definitions, of which 62 carried a review flag. The catalog contained 15,524 searchable entries. These figures describe that installation, rather than the default contents of a new installation. Software packages, node definitions and catalog entries are distinct counts; review coverage is being expanded.

Download upstream catalog metadata when broader tool discovery is needed:

```bash
.venv/bin/python -m glue.fetch_catalog --all
```

Catalog entries describe tools from Snakemake Wrappers, nf-core and Bioconda. Searchability does not imply that a tool is directly executable or has been validated for a particular analysis.

## Agent-assisted analysis

Connect an MCP-capable agent client to the workspace used by the desktop application. The following is a generic stdio configuration; replace all paths with absolute paths and adapt the configuration to the chosen client.

```json
{
  "mcpServers": {
    "openbioworkstation": {
      "command": "/absolute/path/openbioworkstation/.venv/bin/python",
      "args": ["-m", "mcp_server.bio_mcp", "--workspace", "/absolute/path/biows/projects/my-analysis"],
      "env": {"PYTHONPATH": "/absolute/path/openbioworkstation"}
    }
  }
}
```

The MCP interface supports tool discovery, node creation, port connections, asynchronous execution, status queries, file inspection and tool-adaptation jobs. Save desktop changes before agent edits, and reload the workspace when prompted after external changes.

A suitable initial request is:

> Inspect the input files, identify the required tools and construct the workflow. Perform a dry run before execution. Report the run ID, output paths and any errors, and distinguish completed operations from proposed analysis steps.

The [agent tutorial](docs/agent-workflow.en.md) provides a complete synthetic FASTQ-to-SeqKit exercise, exact tool-call examples and guidance for real-data analysis. The MCP stdio interface has been exercised; compatibility with each end-user agent client should be checked separately.

## LLM-assisted tool adaptation

For an indexed tool without a suitable definition, select the on-demand wrapping action in the tool-library context menu, or run:

```bash
.venv/bin/python -m glue.wrap_service --tool conda:fastp --wait
```

The application prepares an environment, extracts command-line help and can ask an LLM to generate input, output, parameter and execution definitions. It then checks the definition and attempts execution with synthetic inputs. Configure `llm_base_url`, `llm_model` and `llm_api_key`, or use `BIOWS_LLM_BASE_URL`, `BIOWS_LLM_MODEL` and `BIOWS_LLM_API_KEY`. The model endpoint must support the chat-completions request format used by the application.

Generated definitions remain unreviewed by default. Inspect commands, ports, parameters and trial results before marking a definition reviewed. A successful synthetic trial does not establish correctness for real samples. Without an LLM configuration, environment preparation and help extraction remain available, but the definition must be supplied separately.

## Configuration and data access

The default configuration file is `~/.config/biows/config.yaml`. A minimal example is:

```yaml
workspace: ~/biows/projects/my-analysis
cores: 4
deploy: conda
conda_bin: conda
allow_unreviewed: false
allowed_input_roots:
  - ~/biows/input
```

The desktop application and MCP server accept `--config FILE` to select another configuration. Inputs must be within the workspace or an allowed input directory. MCP file inspection is restricted to the workspace.

Analysis execution and file storage are local. Dependency downloads and model requests can require network access. An external agent may transmit prompts and tool results according to its client's settings; select those settings to suit the data being analyzed.

## Application examples

The [research examples](promo/research/README.md) include a WSMV/TriMV coinfection analysis, a software walkthrough and an exploratory wheat chloroplast RNA-editing report.

The WSMV example used 12 RNA-seq libraries. None of 73 tested sites reached FDR < 0.10 in the reported analysis of coinfection and within-host WSMV diversity. This result does not establish absence of an effect or statistical equivalence. The examples include case-specific analysis steps, and the accompanying reports are not presented as peer-reviewed publications. Complete raw data and analysis workspaces are not included in this repository.

## Scope and limitations

OpenBioWorkstation currently supports Linux single-machine analysis. It does not provide a multi-user service, remote collaboration or a cluster configuration interface. Multiple samples are represented by separate node chains; sample wildcard expansion is not implemented.

File-format checks identify compatible data types, while bounded previews inspect only a subset of records. Neither substitutes for complete file validation or assessment of biological suitability. Upstream tool adapters support a subset of the indexed ecosystem; verify definitions, dependencies and parameters for the intended analysis.

## License

OpenBioWorkstation is distributed under the [MIT License](LICENSE). Dependencies and invoked bioinformatics tools retain their respective licenses.
