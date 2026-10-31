"""Rebuild A3 300dpi poster PNG and one-page PDF; requires Pillow."""

from common import ACCENT, BG, LINE, MUTED, ROOT, Image, ImageDraw, photo, rule, text


def main():
    im = Image.new("RGB", (3508, 4961), BG)
    d = ImageDraw.Draw(im)
    x = 200
    text(im, (x, 125), "OPEN SOURCE / LOCAL BIOINFORMATICS", 48, ACCENT, True)
    text(im, (x, 235), "OpenBioWorkstation", 148, bold=True)
    text(im, (x, 450), "把生信流程连起来，让每一步可见", 83, bold=True)
    text(im, (x, 595), "可视化节点画布  +  Snakemake 执行  +  MCP Agent 接入", 55, MUTED)
    rule(im, 740, 3108, x)
    text(im, (x, 810), "01   输入 → 工具 → 输出", 65, bold=True)
    photo(im, "branch", (x, 940, 3108, 850))
    text(im, (x, 1830), "真实 WSMV 案例画布局部；案例自定义节点不随软件内置发布。", 41, MUTED)
    text(im, (x, 1970), "02   从接线到重跑，保留过程", 65, bold=True)
    features = [
        ("ports", "类型检查", "不兼容连线被拒绝", (0, 1560, 1600, 1620)),
        ("running", "状态着色", "节点边框跟随运行状态", (550, 700, 1340, 1000)),
        ("cache", "单步与缓存", "运行至此、单步重跑与缓存跳过", (2000, 1835, 3200, 1920)),
        ("preview", "校验与预览", "快速预览有限记录，不代表全文件", (1700, 0, 3200, 700)),
    ]
    for i, (name, title, sub, crop) in enumerate(features):
        xx = x + (i % 2) * 1600
        yy = 2110 + (i // 2) * 555
        d.rounded_rectangle((xx, yy, xx + 1500, yy + 510), radius=18, outline=LINE, width=3)
        text(im, (xx + 35, yy + 20), title, 54, bold=True)
        photo(im, name, (xx + 35, yy + 105, 1430, 285), crop)
        text(im, (xx + 35, yy + 420), sub, 38, MUTED)
    text(im, (x, 3290), "03   真实案例 / WSMV × TriMV", 65, bold=True)
    photo(im, "wsmv_result", (x, 3410, 1680, 810))
    text(im, (2020, 3470), "完整流程已跑通", 64, bold=True)
    for y, s in [
        (3600, "12 个 RNA-seq 文库再分析"),
        (3690, "未检出共感染的显著影响"),
        (3780, "0 / 73 位点达到 FDR < 0.10"),
        (3890, "样本量有限，不证明等效"),
        (4000, "案例展示流程，不宣称重大发现"),
    ]:
        text(im, (2020, y), s, 40, MUTED)
    rule(im, 4290, 3108, x)
    text(im, (x, 4350), "NodeGraphQt · Snakemake · MCP · Bioconda", 61, bold=True)
    text(im, (x, 4450), "复用成熟开源组件，不重复造轮子", 48)
    text(im, (x, 4530), "5 个内置 wrapper 定义 + 8 个本机节点（需安装对应工具）", 38, MUTED)
    text(
        im, (x, 4590), "上游生态规模未实测；MCP 真实客户端、smk: + Conda 链路尚未验证。", 36, MUTED
    )
    rule(im, 4690, 3108, x)
    text(im, (x, 4750), "github.com/ArchitektSpeer/openbioworkstation", 48, ACCENT, True)
    text(im, (2880, 4750), "MIT", 60, bold=True)
    im.save(ROOT / "poster.png", dpi=(300, 300))
    im.save(ROOT / "poster.pdf", "PDF", resolution=300)


if __name__ == "__main__":
    main()
