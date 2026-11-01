"""Rebuild the bilingual A3 poster from actual, shipped screenshots."""

from common import ACCENT, BG, LINE, MUTED, ROOT, Image, ImageDraw, photo, rule, text


def main():
    im = Image.new("RGB", (3508, 4961), BG)
    d = ImageDraw.Draw(im)
    x = 200
    text(im, (x, 110), "OPEN SOURCE / LOCAL BIOINFORMATICS / AGENT ASSISTANCE", 42, ACCENT, True)
    text(im, (x, 210), "OpenBioWorkstation", 148, bold=True)
    text(im, (x, 420), "本地生信工作流与 Agent 协作", 90, bold=True)
    text(im, (x, 555), "Visual workflows and agent-assisted bioinformatics", 60, MUTED)
    text(im, (x, 665), "NodeGraphQt  /  Snakemake  /  MCP", 55, ACCENT)
    rule(im, 780, 3108, x)
    text(im, (x, 830), "01   输入 → 工具 → 输出 / INPUT → TOOLS → OUTPUT", 57, bold=True)
    photo(im, "branch", (x, 950, 3108, 790))
    text(im, (x, 1780), "真实 WSMV 案例截图；包含案例专用节点。", 40, MUTED)
    text(im, (x, 1845), "Actual WSMV case screenshot; includes case-specific nodes.", 39, MUTED)
    text(im, (x, 1980), "02   过程检查与执行 / INSPECTION AND EXECUTION", 57, bold=True)
    features = [
        (
            "ports",
            "端口格式检查 / Port checks",
            "拒绝不兼容格式 / Reject incompatible formats",
            (0, 1560, 1600, 1620),
        ),
        (
            "running",
            "运行状态 / Execution state",
            "显示节点状态 / Display node execution states",
            (550, 700, 1340, 1000),
        ),
        (
            "cache",
            "单步与缓存 / Reruns and cache",
            "局部重跑 / Partial runs and cached skips",
            (2000, 1835, 3200, 1920),
        ),
        (
            "preview",
            "文件预览 / File previews",
            "有限记录预览 / Bounded record inspection",
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
    text(im, (x, 3200), "03   研究案例 / RESEARCH CASE: WSMV × TriMV", 57, bold=True)
    photo(im, "wsmv_result", (x, 3320, 1680, 690))
    for y, cn, en in [
        (3330, "12 个 RNA-seq 文库", "12 RNA-seq libraries"),
        (3495, "0/73 位点达到 FDR < 0.10", "0/73 sites at FDR < 0.10"),
        (3660, "未检出显著关联", "No significant association detected"),
        (3825, "阴性结果不证明等效", "A negative result is not equivalence"),
    ]:
        text(im, (2020, y), cn, 43, bold=True)
        text(im, (2020, y + 72), en, 35, MUTED)
    rule(im, 4070, 3108, x)
    text(im, (x, 4120), "04   与 Agent 协作 / WORK WITH AN AGENT", 57, bold=True)
    text(im, (x, 4230), "研究者定义问题 → Agent 搭图 → dry-run → 执行与核对", 48)
    text(im, (x, 4310), "Define the question → build → dry-run → execute → inspect", 45, MUTED)
    text(im, (x, 4425), "中英教程 / Tutorial: docs/agent-workflow.en.md", 43, ACCENT, True)
    text(im, (x, 4510), "研究附件 / Research PDFs: promo/research/", 40, MUTED)
    text(im, (x, 4600), "Linux 单机；MCP stdio 已验证；具体 Agent 客户端需单独验证。", 37, MUTED)
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
