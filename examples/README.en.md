# Offline demo

[简体中文](README.md) | **English**

From the project root, run `./run-demo.sh` or:

```bash
.venv/bin/python -m examples.demo
```

The default workspace is `demo_workspace/`. The demo launcher registers three demo-specific tools, so open this workspace with the demo entry point rather than the standard desktop entry point.

The six-node graph includes paired FASTQ inputs (12 reads of 80 bp per mate), a 1,000-bp FASTA reference, two inspection nodes, a report aggregation node and an output node. It inspects synthetic files and generates HTML/JSON reports; it does not perform read filtering, alignment or variant analysis.

1. Select input nodes to view previews and statistics.
2. Search for `demo` in the tool library; clear the search to restore categories.
3. Right-click the canvas and select the full-run action. Observe Snakemake logs and node states.
4. Run again to observe cached outputs being skipped.
5. Force a single-step rerun on the report aggregation node.
6. Preview the output node and open the generated HTML in a browser.
7. Save the graph and reopen through the demo launcher to retain its layout and connections.

Outputs are stored in `demo_workspace/results/`; run snapshots and logs are in `runs/`. Execution is offline and does not require Conda. Samples are created only when the workspace has no session. `./run-demo.sh --reset` resets the demo graph and samples.

Generated workspaces and historical local validation reports are not published in the repository. For standard MCP use, follow the [agent tutorial](../docs/agent-workflow.en.md); its exercise uses a standard local SeqKit node, not demo-only tools.
