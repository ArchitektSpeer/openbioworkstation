"""Compose an A3 poster emphasizing researcher-agent collaboration."""

import json

from common import ROOT, Image, ImageDraw, font, photo

INK, MUTED, BLUE, LINE = "#20272e", "#63707a", "#355d78", "#d4dce1"


def main():
    counts = json.loads((ROOT / "qzone/tool-counts.json").read_text())
    im = Image.new("RGB", (3508, 4961), "white")
    d = ImageDraw.Draw(im)

    def text(x, y, s, size=42, color=INK, bold=False):
        f = font(size, bold)
        bounds = d.textbbox((x, y), s, font=f)
        if bounds[2] > 3335 or bounds[3] > 4850:
            raise ValueError(f"Text outside content bounds: {s}")
        d.text((x, y), s, font=f, fill=color)

    def line(y):
        d.line((180, y, 3328, y), fill=LINE, width=3)

    text(180, 135, "OpenBioWorkstation", 144, bold=True)
    text(185, 355, "A workstation for agent-assisted bioinformatics", 91, bold=True)
    text(185, 505, "On-demand tool adaptation and inspectable workflow execution", 51, MUTED)
    text(
        185,
        630,
        "Visual workflows  ·  Snakemake execution  ·  MCP access  ·  Local run records",
        46,
        BLUE,
    )
    line(775)

    text(180, 835, "Researcher, agent and workstation", 62, bold=True)
    roles = [
        (
            180,
            "Researcher",
            "Define the question and methods",
            "Review parameters and interpretation",
        ),
        (
            1260,
            "Agent / MCP",
            "Discover tools and build workflows",
            "Start runs and inspect outputs",
        ),
        (
            2340,
            "Workstation / Snakemake",
            "Execute the analysis workflow",
            "Retain graphs, logs and output files",
        ),
    ]
    for x, title, first, second in roles:
        text(x, 965, title, 52, BLUE, True)
        text(x, 1060, first, 43)
        text(x, 1130, second, 40, MUTED)

    photo(im, "branch", (180, 1270, 3148, 1392))
    text(
        180,
        2700,
        "WSMV workflow excerpt: sample chains share a reference and index. Case-specific nodes are included.",
        38,
        MUTED,
    )
    text(180, 2780, "Port format checks, execution states, partial reruns and file previews.", 42)
    line(2890)

    text(180, 2940, "Tool integration and discovery", 60, bold=True)
    text(2510, 2960, "Local snapshot / 2026-11-01", 37, MUTED)
    text(180, 3040, str(counts["auto_wrapped_packages"]), 177, BLUE, True)
    text(1770, 3040, f"{counts['indexed_entries']:,}", 177, BLUE, True)
    text(190, 3260, "software packages adapted locally", 46)
    text(1780, 3260, "searchable catalog entries", 46)
    text(
        180,
        3380,
        "78 adapted nodes + 5 built-in wrappers + 10 local nodes = 93 node definitions",
        42,
    )
    text(
        180,
        3470,
        "62 nodes carry review flags; tool review is progressing incrementally.",
        45,
        bold=True,
    )
    text(
        180,
        3560,
        "Packages, nodes and catalog entries are distinct counts. Indexed entries are not necessarily executable.",
        37,
        MUTED,
    )
    line(3670)

    text(180, 3725, "On-demand tool adaptation with an LLM", 60, bold=True)
    stages = [
        (180, "Extract CLI help", "Prepare the environment"),
        (1000, "Generate a definition", "Describe ports and commands"),
        (1820, "Check and trial", "Test with synthetic inputs"),
        (2640, "Review before use", "Inspect and mark reviewed"),
    ]
    for i, (x, title, sub) in enumerate(stages):
        d.rectangle((x, 3860, x + 688, 4070), fill="#f2f5f7")
        text(x + 35, 3890, title, 45, BLUE, True)
        text(x + 35, 3980, sub, 35, MUTED)
        if i < 3:
            text(x + 720, 3915, "→", 54, BLUE)
    text(
        180,
        4130,
        "Configure the model endpoint and dependencies. Generation and synthetic trials do not validate real-data analysis.",
        37,
        MUTED,
    )
    text(
        180,
        4200,
        "Local adaptations are not installed by default. Check compatibility with each end-user agent client.",
        37,
        MUTED,
    )
    line(4310)

    text(180, 4370, "Application case: WSMV / TriMV coinfection", 46, bold=True)
    text(
        180,
        4455,
        "12 RNA-seq libraries; no tested site (0/73) reached FDR < 0.10. The result does not establish equivalence.",
        36,
        MUTED,
    )
    text(180, 4540, "Source code, agent tutorial and research examples", 45, BLUE)
    line(4655)
    text(180, 4710, "github.com/ArchitektSpeer/openbioworkstation", 51, BLUE, True)
    text(180, 4800, "Linux  ·  GNU GPL v3.0", 34, MUTED)

    im.save(ROOT / "agent-poster.png", dpi=(300, 300))
    im.save(ROOT / "agent-poster.pdf", "PDF", resolution=300)
    preview = im.copy()
    preview.thumbnail((1100, 1600), Image.Resampling.LANCZOS)
    preview.save(ROOT / "agent-poster.preview.png")


if __name__ == "__main__":
    main()
