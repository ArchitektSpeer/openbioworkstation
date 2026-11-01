"""Compose an English software overview using original screenshots and figure panels."""

from math import atan2, cos, sin

from common import ASSETS, ROOT, Image, ImageDraw, font

W, H = 3600, 2800
INK = "#20272e"
MUTED = "#57616b"
ACCENT = "#355d78"
LINE = "#c6cdd3"
PALE = "#f2f5f7"


def main():
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)

    def txt(x, y, value, size=38, color=INK, bold=False):
        f = font(size, bold)
        bounds = d.textbbox((x, y), value, font=f)
        if bounds[2] > W - 100:
            raise ValueError(f"Text exceeds page width: {value}")
        d.text((x, y), value, fill=color, font=f)

    def line(x1, y1, x2, y2, fill=LINE, width=2):
        d.line((x1, y1, x2, y2), fill=fill, width=width)

    def arrow(x1, y1, x2, y2):
        line(x1, y1, x2, y2, ACCENT, 4)
        a = atan2(y2 - y1, x2 - x1)
        d.polygon(
            [
                (x2, y2),
                (x2 - 17 * cos(a - 0.45), y2 - 17 * sin(a - 0.45)),
                (x2 - 17 * cos(a + 0.45), y2 - 17 * sin(a + 0.45)),
            ],
            fill=ACCENT,
        )

    def panel(x, y, label, cn, en):
        txt(x, y, label, 50, ACCENT, True)
        txt(x + 78, y, cn, 39, INK, True)
        txt(x + 78, y + 65, en, 32, MUTED)

    def image(name, box):
        x, y, w, h = box
        src = Image.open(ASSETS / f"{name}.png").convert("RGB")
        # Keep the complete original image; only resample it to the panel size.
        src.thumbnail((w, h), Image.Resampling.LANCZOS)
        im.paste(src, (x + (w - src.width) // 2, y + (h - src.height) // 2))

    def box(x, y, w, h, title, subtitle):
        d.rectangle((x, y, x + w, y + h), fill=PALE, outline=LINE, width=2)
        tw = d.textlength(title, font=font(35, True))
        txt(x + (w - tw) / 2, y + 24, title, 35, INK, True)
        tw = d.textlength(subtitle, font=font(28))
        txt(x + (w - tw) / 2, y + 80, subtitle, 28, MUTED)

    txt(130, 95, "OpenBioWorkstation", 118, INK, True)
    txt(135, 265, "Visual bioinformatics workflows", 64, INK)
    txt(137, 362, "Workflow construction, agent access and local execution", 43, MUTED)
    line(130, 470, 3470, 470, INK, 3)

    panel(130, 525, "a", "Workflow editor", "Visual workflow construction")
    image("canvas", (130, 680, 2380, 1428))
    txt(130, 2140, "WSMV workflow: sample chains share a reference and index.", 36)
    txt(
        130,
        2200,
        "The actual case workflow includes case-specific analysis nodes.",
        29,
        MUTED,
    )

    line(2580, 535, 2580, 2230)
    panel(2660, 525, "b", "Interfaces and execution", "MCP and desktop access")
    txt(2660, 675, "Researcher defines methods", 35)
    txt(2660, 730, "Review parameters and interpret results", 28, MUTED)
    box(2660, 840, 350, 145, "Desktop UI", "NodeGraphQt")
    box(3100, 840, 370, 145, "Agent", "MCP / stdio")
    arrow(2835, 985, 2835, 1080)
    arrow(3285, 985, 3285, 1080)
    line(2835, 1080, 3285, 1080, ACCENT, 4)
    arrow(3060, 1080, 3060, 1150)
    box(2660, 1150, 810, 165, "Shared workspace", "session.json · revision checks")
    arrow(3060, 1315, 3060, 1420)
    box(2660, 1420, 810, 165, "Workflow compilation", "Snakefile")
    arrow(3060, 1585, 3060, 1690)
    box(2660, 1690, 810, 165, "Workflow execution", "Snakemake")
    arrow(3060, 1855, 3060, 1960)
    box(2660, 1960, 810, 165, "Execution records", "run ID · logs · outputs")
    txt(2660, 2160, "Architecture schematic", 29, MUTED)

    line(130, 2290, 3470, 2290)
    # A compact case caption, rather than turning a limited negative result into a headline.
    txt(130, 2340, "c", 50, ACCENT, True)
    txt(208, 2340, "Application case", 43, INK, True)
    txt(
        208,
        2425,
        "WSMV / TriMV coinfection: 12 RNA-seq libraries; no tested site (0/73) reached FDR < 0.10.",
        39,
    )
    txt(
        208,
        2490,
        "The negative result does not establish absence of an effect or statistical equivalence.",
        32,
        MUTED,
    )
    txt(
        208,
        2560,
        "Case-specific nodes are included. The MCP stdio interface has been exercised.",
        32,
        MUTED,
    )
    txt(
        208,
        2612,
        "Check end-user agent compatibility separately. Case analyses were not rerun for this figure.",
        27,
        MUTED,
    )
    line(130, 2695, 3470, 2695, INK, 2)
    txt(130, 2725, "github.com/ArchitektSpeer/openbioworkstation", 31, ACCENT)
    txt(2510, 2725, "Linux · GPL-3.0 · docs/agent-workflow.en.md", 28, MUTED)

    im.save(ROOT / "academic-overview.png", dpi=(300, 300))
    small = im.copy()
    small.thumbnail((1800, 1400), Image.Resampling.LANCZOS)
    small.save(ROOT / "academic-overview.preview.png")


if __name__ == "__main__":
    main()
