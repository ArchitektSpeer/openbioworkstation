"""Rebuild the English A3 poster from actual, shipped screenshots."""

from common import ACCENT, BG, LINE, MUTED, ROOT, Image, ImageDraw, photo, rule, text


def main():
    im = Image.new("RGB", (3508, 4961), BG)
    d = ImageDraw.Draw(im)
    x = 200
    text(im, (x, 110), "OPEN SOURCE / LOCAL BIOINFORMATICS / AGENT ASSISTANCE", 42, ACCENT, True)
    text(im, (x, 210), "OpenBioWorkstation", 148, bold=True)
    text(im, (x, 420), "Local workflows and agent collaboration", 90, bold=True)
    text(im, (x, 555), "Visual bioinformatics with NodeGraphQt, Snakemake and MCP", 60, MUTED)
    text(im, (x, 665), "NodeGraphQt  /  Snakemake  /  MCP", 55, ACCENT)
    rule(im, 780, 3108, x)
    text(im, (x, 830), "01   INPUT → TOOLS → OUTPUT", 57, bold=True)
    photo(im, "branch", (x, 950, 3108, 790))
    text(im, (x, 1780), "Actual WSMV workflow; includes case-specific nodes.", 40, MUTED)
    text(im, (x, 1845), "The original interface is preserved in the screenshot.", 39, MUTED)
    text(im, (x, 1980), "02   INSPECTION AND EXECUTION", 57, bold=True)
    features = [
        (
            "ports",
            "Port format checks",
            "Reject incompatible formats",
            (0, 1560, 1600, 1620),
        ),
        (
            "running",
            "Execution states",
            "Follow node execution states",
            (550, 700, 1340, 1000),
        ),
        (
            "cache",
            "Reruns and cache",
            "Partial runs and cached skips",
            (2000, 1835, 3200, 1920),
        ),
        (
            "preview",
            "File previews",
            "Inspect bounded records",
            (1700, 0, 3200, 700),
        ),
    ]
    for i, (name, title, sub, crop) in enumerate(features):
        xx = x + (i % 2) * 1600
        yy = 2110 + (i // 2) * 520
        d.rounded_rectangle((xx, yy, xx + 1500, yy + 485), radius=18, outline=LINE, width=3)
        text(im, (xx + 35, yy + 22), title, 43, bold=True)
        photo(im, name, (xx + 35, yy + 105, 1430, 265), crop)
        text(im, (xx + 35, yy + 407), sub, 34, MUTED)
    text(im, (x, 3200), "03   RESEARCH CASE: WSMV × TriMV", 57, bold=True)
    photo(im, "wsmv_result", (x, 3320, 1680, 690))
    for y, cn, en in [
        (3330, "12 RNA-seq libraries", "Existing application case"),
        (3495, "0/73 sites at FDR < 0.10", "No site met the specified threshold"),
        (3660, "No significant association", "No significant association detected"),
        (3825, "No equivalence claim", "A negative result is not equivalence"),
    ]:
        text(im, (2020, y), cn, 43, bold=True)
        text(im, (2020, y + 72), en, 35, MUTED)
    rule(im, 4070, 3108, x)
    text(im, (x, 4120), "04   WORK WITH AN AGENT", 57, bold=True)
    text(im, (x, 4230), "Question → agent-built workflow → dry-run → execute → inspect", 48)
    text(im, (x, 4310), "Researcher oversight with agent-assisted workflow operations", 45, MUTED)
    text(im, (x, 4425), "Agent tutorial: docs/agent-workflow.en.md", 43, ACCENT, True)
    text(im, (x, 4510), "Research examples: promo/research/", 40, MUTED)
    text(im, (x, 4600), "Linux, single machine. MCP stdio has been exercised.", 37, MUTED)
    text(
        im,
        (x, 4665),
        "Single machine; stdio tested; validate each agent client separately.",
        37,
        MUTED,
    )
    rule(im, 4750, 3108, x)
    text(im, (x, 4800), "github.com/ArchitektSpeer/openbioworkstation", 45, ACCENT, True)
    text(im, (2880, 4800), "GPL-3.0", 55, bold=True)
    im.save(ROOT / "poster.png", dpi=(300, 300))
    im.save(ROOT / "poster.pdf", "PDF", resolution=300)


if __name__ == "__main__":
    main()
