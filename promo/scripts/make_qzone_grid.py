"""Compose nine independent QQ Zone images from factual copy and original assets."""

import json

from common import ASSETS, ROOT, Image, ImageDraw, font

OUT = ROOT / "qzone"
INK, MUTED, BLUE, LINE = "#20272e", "#63707a", "#355d78", "#d4dce1"


def main():
    counts = json.loads((OUT / "tool-counts.json").read_text())
    cards = []

    def base(i, title, english):
        im = Image.new("RGB", (1080, 1080), "white")
        d = ImageDraw.Draw(im)

        def text(x, y, s, size=32, color=INK, bold=False):
            f = font(size, bold)
            while d.textbbox((x, y), s, font=f)[2] > 1030 and size > 20:
                size -= 1
                f = font(size, bold)
            if d.textbbox((x, y), s, font=f)[2] > 1030:
                raise ValueError(f"Card {i}: text too wide: {s}")
            d.text((x, y), s, font=f, fill=color)

        text(55, 38, "OpenBioWorkstation", 27, BLUE, True)
        text(55, 100, title, 52, INK, True)
        text(57, 178, english, 25, MUTED)
        d.line((55, 235, 1025, 235), fill=LINE, width=2)
        d.line((55, 995, 1025, 995), fill=LINE, width=2)
        text(55, 1017, "Bioinformatics workflows · Linux · GPL-3.0", 23, MUTED)
        text(975, 1010, f"{i:02}", 34, BLUE, True)
        return im, d, text

    def photo(im, name, box, crop=None):
        x, y, w, h = box
        src = Image.open(ASSETS / f"{name}.png").convert("RGB")
        if crop:
            src = src.crop(crop)
        src.thumbnail((w, h), Image.Resampling.LANCZOS)
        im.paste(src, (x + (w - src.width) // 2, y + (h - src.height) // 2))

    im, d, t = base(1, "Visual bioinformatics workstation", "Visual bioinformatics workflows")
    t(55, 290, "OpenBio", 110, bold=True)
    t(55, 435, "Workstation", 110, bold=True)
    t(58, 610, "Node editor · Snakemake execution", 40)
    t(58, 675, "Agent collaboration through MCP", 40)
    t(58, 810, "Local computational analysis", 34, BLUE)
    t(58, 875, "Agent tutorial and research examples", 30, MUTED)
    cards.append(im)

    im, d, t = base(2, "Visual workflow construction", "Workflow construction")
    photo(im, "branch", (55, 285, 970, 495))
    t(55, 830, "Nodes represent analysis steps; edges represent data dependencies.", 35)
    t(55, 895, "WSMV workflow excerpt; includes case-specific nodes.", 30, MUTED)
    cards.append(im)

    im, d, t = base(3, "Tool integration and discovery", "Local snapshot · 2026-11-01")
    t(55, 265, str(counts["auto_wrapped_packages"]), 125, BLUE, True)
    t(270, 310, "software packages adapted locally", 39, bold=True)
    t(55, 450, f"{counts['indexed_entries']:,}", 105, BLUE, True)
    t(475, 495, "searchable catalog entries", 39, bold=True)
    t(55, 595, "Sources: Snakemake Wrappers, nf-core and Bioconda", 29, MUTED)
    d.line((55, 665, 1025, 665), fill=LINE, width=2)
    t(55, 700, "78 adapted nodes + 5 built-in definitions + 10 local nodes", 33)
    t(55, 770, "93 node definitions; 62 carry review flags", 38, bold=True)
    t(55, 855, "Tool review is progressing incrementally.", 29, MUTED)
    t(55, 905, "Indexed entries are not necessarily executable or installed by default.", 27, MUTED)
    t(
        55,
        950,
        "Definitions and review flags do not establish validity for all datasets.",
        27,
        MUTED,
    )
    cards.append(im)

    im, d, t = base(4, "LLM-assisted tool adaptation", "LLM-assisted tool adaptation")
    stages = [
        (280, "Extract command-line help", "Prepare an environment and retrieve help text."),
        (
            425,
            "Generate a definition with an LLM",
            "Describe inputs, outputs, parameters and commands.",
        ),
        (
            570,
            "Check the definition and run a trial",
            "Check structure, test synthetic inputs and record the outcome.",
        ),
        (
            715,
            "Review before use",
            "Inspect commands, ports and parameters before marking reviewed.",
        ),
    ]
    for y, title, sub in stages:
        d.rectangle((55, y, 1025, y + 115), fill="#f2f5f7", outline=LINE, width=2)
        t(80, y + 10, title, 35, BLUE, True)
        t(80, y + 65, sub, 29)
        if y < 715:
            d.line((540, y + 115, 540, y + 138), fill=BLUE, width=3)
            d.polygon([(531, y + 132), (549, y + 132), (540, y + 142)], fill=BLUE)
    t(55, 865, "Configure the model endpoint and tool dependencies.", 31)
    t(
        55,
        925,
        "Generated definitions require review; adaptation may fail for some tools.",
        28,
        MUTED,
    )
    cards.append(im)

    im, d, t = base(5, "Execution states and records", "Execution states and run records")
    photo(im, "running", (55, 270, 970, 490))
    t(55, 795, "Node states reflect workflow execution.", 37)
    t(55, 865, "Each run retains a snapshot, logs and output paths.", 32, MUTED)
    t(55, 925, "Snakemake schedules workflow tasks.", 31, MUTED)
    cards.append(im)

    im, d, t = base(
        6, "Partial runs and file inspection", "Partial execution and output inspection"
    )
    photo(im, "preview", (55, 275, 970, 510), (1700, 0, 3200, 900))
    t(55, 815, "Run up to a target node or repeat a single step.", 34)
    t(55, 880, "Check port formats and preview input and output files.", 31, MUTED)
    t(55, 940, "Quick previews cover a bounded set of records.", 29, MUTED)
    cards.append(im)

    im, d, t = base(7, "Researcher-agent collaboration", "Agent-assisted analysis through MCP")
    rows = [
        (280, "Researcher", "Study design, parameter review and interpretation"),
        (450, "Agent / MCP", "Discover tools, construct workflows and start runs"),
        (620, "Shared workspace", "The desktop and agent access the same session"),
    ]
    for y, title, sub in rows:
        d.rectangle((55, y, 1025, y + 135), fill="#f2f5f7", outline=LINE, width=2)
        t(85, y + 15, title, 37, BLUE, True)
        t(85, y + 75, sub, 31)
        if y < 620:
            d.line((540, y + 135, 540, y + 160), fill=BLUE, width=3)
            d.polygon([(531, y + 153), (549, y + 153), (540, y + 165)], fill=BLUE)
    t(55, 810, "Tutorial: synthetic FASTQ to SeqKit statistics.", 34)
    t(55, 880, "The tutorial uses actual stdio calls and workflow execution.", 31, MUTED)
    t(55, 940, "Check compatibility with each end-user agent client.", 28, MUTED)
    cards.append(im)

    im, d, t = base(8, "WSMV coinfection case study", "Application case: WSMV / TriMV")
    photo(im, "wsmv_result", (55, 275, 970, 545))
    t(55, 840, "12 RNA-seq libraries; 73 tested sites.", 34)
    t(55, 900, "No site reached FDR < 0.10; this does not establish equivalence.", 30, MUTED)
    t(55, 949, "Existing case results; not reanalyzed for this figure.", 27, MUTED)
    cards.append(im)

    im, d, t = base(
        9,
        "Bioinformatics with agent collaboration",
        "Bioinformatics analysis with agent collaboration",
    )
    t(55, 280, "Researcher × Agent × Workstation", 57, BLUE, True)
    t(55, 380, "Researcher: define the question and methods", 38, bold=True)
    t(55, 445, "Review methods, parameters and interpretation.", 31, MUTED)
    t(55, 535, "Agent: organize analysis through MCP", 38, bold=True)
    t(55, 600, "Find tools, build workflows, start runs and inspect outputs.", 31, MUTED)
    t(55, 690, "Workstation: execute and retain run records", 38, bold=True)
    t(55, 755, "Associate workflow graphs, execution logs and output files.", 31, MUTED)
    t(55, 845, "github.com/ArchitektSpeer/", 37, BLUE)
    t(55, 900, "openbioworkstation", 47, BLUE, True)
    cards.append(im)

    sheet = Image.new("RGB", (3240, 3240), "white")
    for i, card in enumerate(cards):
        card.save(OUT / f"{i + 1:02}.png")
        sheet.paste(card, ((i % 3) * 1080, (i // 3) * 1080))
    sheet.save(OUT / "grid.png")
    sheet.thumbnail((1620, 1620), Image.Resampling.LANCZOS)
    sheet.save(OUT / "preview.png")


if __name__ == "__main__":
    main()
