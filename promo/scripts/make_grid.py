"""Rebuild nine 1080px cards and the 3240px contact sheet from shipped assets.
Requires Pillow and Noto Sans CJK SC (font collection index 2).
"""

from common import ACCENT, BG, MUTED, ROOT, Image, photo, rule, text

EN_TITLES = {
    1: "Visual workflows for local bioinformatics",
    2: "Inspect the workflow graph",
    3: "Check file-format compatibility",
    4: "Follow execution state",
    5: "Rerun a step and reuse cached outputs",
    6: "Inspect input and output files",
    7: "Share a workspace with an agent via MCP",
    8: "Research case: WSMV coinfection",
    9: "Start with the demo and agent tutorial",
}
EN_NOTES = {
    2: "Case overview and branch detail; case-specific nodes are shown.",
    3: "An incompatible JSON-to-BAM connection is rejected.",
    4: "Actual BWA MEM execution; yellow indicates a running node.",
    5: "Actual single-step execution with other nodes skipped.",
    6: "Bounded previews do not establish whole-file integrity.",
    7: "Stdio tested; end-user agent clients require separate verification.",
}


def base(i, title, tag):
    im = Image.new("RGB", (1080, 1080), BG)
    text(im, (56, 40), "OPENBIOWORKSTATION  /  " + tag, 24, ACCENT, True)
    text(im, (56, 95), title, 48, bold=True)
    text(im, (56, 161), EN_TITLES[i], 23, MUTED)
    rule(im, 200)
    rule(im, 980)
    text(im, (56, 1004), "LOCAL WORKFLOWS  ·  OPEN SOURCE", 23, MUTED)
    text(im, (968, 998), f"{i:02}", 34, ACCENT, True)
    return im


def main():
    cards = []
    im = base(1, "Local bioinformatics workflows", "WORKSTATION")
    text(im, (56, 240), "OpenBio", 102, bold=True)
    text(im, (56, 370), "Workstation", 102, bold=True)
    text(im, (56, 540), "Visual nodes · Snakemake execution", 41)
    photo(im, "branch", (56, 640, 968, 270))
    cards.append(im)
    specs = [
        (2, "Workflow overview", "CANVAS", "canvas", "Actual case workflow and branch detail."),
        (3, "Port format checks", "PORTS", "ports", "JSON-to-BAM connection rejected and logged."),
        (4, "Execution states", "EXECUTION", "running", "Yellow indicates an executing node."),
        (
            5,
            "Single-step reruns",
            "CACHE",
            "cache",
            "Actual single-step run; other nodes are skipped.",
        ),
        (
            6,
            "Inspect before connecting",
            "FILES",
            "preview",
            "Bounded inspection does not validate the whole file.",
        ),
        (
            7,
            "Shared agent workspace",
            "MCP",
            "branch",
            "The first case-sample branch was built through MCP.",
        ),
    ]
    for i, title, tag, name, note in specs:
        im = base(i, title, tag)
        if i == 2:
            photo(im, name, (56, 215, 968, 460))
            photo(im, "branch", (56, 700, 968, 205))
        elif i == 3:
            photo(im, name, (56, 230, 968, 510), (750, 260, 3000, 1370))
            text(im, (56, 770), "Original rejection log (detail)", 30, MUTED)
            photo(im, name, (56, 825, 968, 65), (0, 1560, 1600, 1620))
        elif i == 4:
            photo(im, name, (56, 220, 968, 460))
            photo(im, name, (56, 700, 968, 170), (550, 700, 1340, 1000))
        elif i == 5:
            photo(im, name, (56, 215, 968, 540))
            photo(im, name, (56, 780, 968, 100), (2000, 1840, 3200, 1920))
        elif i == 6:
            photo(im, name, (56, 220, 490, 630), (0, 0, 1700, 1920))
            photo(im, name, (565, 220, 460, 630), (1700, 0, 3200, 1920))
        else:
            photo(im, name, (56, 230, 968, 450))
            text(im, (56, 715), "Stdio tested; verify each agent client.", 33)
            text(im, (56, 782), "add_node → connect_nodes → run", 32, ACCENT)
        text(im, (56, 912), note, 26, MUTED)
        text(im, (56, 950), EN_NOTES[i], 22, MUTED)
        cards.append(im)
    im = base(8, "WSMV coinfection analysis", "WSMV")
    photo(im, "wsmv_result", (56, 235, 968, 530))
    text(im, (56, 805), "No significant association detected", 43, bold=True)
    text(im, (56, 870), "Limited sample size; no equivalence claim.", 31, MUTED)
    text(im, (56, 930), "0/73 sites at FDR < 0.10; no equivalence claim.", 27, MUTED)
    cards.append(im)
    im = base(9, "Start with the local demo", "GET STARTED")
    text(im, (56, 270), "./run-demo.sh", 68, bold=True)
    text(im, (56, 395), "Synthetic inputs · Offline execution", 40)
    text(im, (56, 570), "github.com/ArchitektSpeer/", 40, ACCENT)
    text(im, (56, 630), "openbioworkstation", 49, ACCENT, True)
    text(im, (56, 715), "docs/agent-workflow.en.md", 33, ACCENT)
    text(im, (56, 800), "GNU GPL v3.0", 56, bold=True)
    text(im, (56, 885), "Single machine; review each tool definition.", 31, MUTED)
    text(im, (56, 937), "Single machine; validate each tool and client.", 27, MUTED)
    cards.append(im)
    out = ROOT / "grid"
    out.mkdir(exist_ok=True)
    sheet = Image.new("RGB", (3240, 3240), BG)
    for i, im in enumerate(cards):
        im.save(out / f"{i + 1:02}.png")
        sheet.paste(im, ((i % 3) * 1080, (i // 3) * 1080))
    sheet.save(out / "grid.png")


if __name__ == "__main__":
    main()
