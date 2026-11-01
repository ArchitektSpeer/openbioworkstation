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
            if d.textbbox((x, y), s, font=f)[2] > 1030:
                raise ValueError(f"Card {i}: text too wide: {s}")
            d.text((x, y), s, font=f, fill=color)

        text(55, 38, "OpenBioWorkstation", 27, BLUE, True)
        text(55, 100, title, 52, INK, True)
        text(57, 178, english, 25, MUTED)
        d.line((55, 235, 1025, 235), fill=LINE, width=2)
        d.line((55, 995, 1025, 995), fill=LINE, width=2)
        text(55, 1017, "生物信息学工作流 · Linux · MIT", 23, MUTED)
        text(975, 1010, f"{i:02}", 34, BLUE, True)
        return im, d, text

    def photo(im, name, box, crop=None):
        x, y, w, h = box
        src = Image.open(ASSETS / f"{name}.png").convert("RGB")
        if crop:
            src = src.crop(crop)
        src.thumbnail((w, h), Image.Resampling.LANCZOS)
        im.paste(src, (x + (w - src.width) // 2, y + (h - src.height) // 2))

    im, d, t = base(1, "生物信息学可视化工作站", "Visual bioinformatics workflows")
    t(55, 290, "OpenBio", 110, bold=True)
    t(55, 435, "Workstation", 110, bold=True)
    t(58, 610, "节点图构建 · Snakemake 执行", 40)
    t(58, 675, "MCP 接口支持 Agent 协作", 40)
    t(58, 810, "面向本地计算分析", 34, BLUE)
    t(58, 875, "Agent 协作教程与研究案例", 30, MUTED)
    cards.append(im)

    im, d, t = base(2, "工作流的可视化组织", "Workflow construction")
    photo(im, "branch", (55, 285, 970, 495))
    t(55, 830, "节点表示分析步骤，连线表示数据依赖。", 35)
    t(55, 895, "WSMV 案例局部；包含案例专用节点。", 30, MUTED)
    cards.append(im)

    im, d, t = base(3, "工具接入与检索规模", "Local snapshot · 2026-11-01")
    t(55, 265, str(counts["auto_wrapped_packages"]), 125, BLUE, True)
    t(270, 310, "个软件包已在本机建立封装", 39, bold=True)
    t(55, 450, f"{counts['indexed_entries']:,}", 105, BLUE, True)
    t(475, 495, "条可检索工具索引", 39, bold=True)
    t(55, 595, "索引来源：Snakemake Wrappers、nf-core、Bioconda", 29, MUTED)
    d.line((55, 665, 1025, 665), fill=LINE, width=2)
    t(55, 700, "78 个封装节点 + 5 个内置定义 + 10 个本机节点", 33)
    t(55, 770, "合计 93 个节点定义，62 个带审核标记", 38, bold=True)
    t(55, 855, "工具审核工作正在逐步推进。", 29, MUTED)
    t(55, 905, "可检索不等于可直接执行；本机封装不代表默认随仓库安装。", 27, MUTED)
    t(55, 950, "定义存在或带审核标记不代表已通过所有真实数据验证。", 27, MUTED)
    cards.append(im)

    im, d, t = base(4, "LLM 辅助工具自动适配", "LLM-assisted tool adaptation")
    stages = [
        (280, "提取工具帮助", "创建依赖环境，获取命令行帮助文本"),
        (425, "LLM 生成节点定义", "描述输入、输出、参数及执行命令"),
        (570, "结构检查与合成输入试运行", "检查定义并尝试执行，记录适配状态"),
        (715, "审查定义后使用", "核对命令、端口和参数，再标记审核"),
    ]
    for y, title, sub in stages:
        d.rectangle((55, y, 1025, y + 115), fill="#f2f5f7", outline=LINE, width=2)
        t(80, y + 10, title, 35, BLUE, True)
        t(80, y + 65, sub, 29)
        if y < 715:
            d.line((540, y + 115, 540, y + 138), fill=BLUE, width=3)
            d.polygon([(531, y + 132), (549, y + 132), (540, y + 142)], fill=BLUE)
    t(55, 865, "需配置 LLM 接口及工具依赖环境。", 31)
    t(55, 925, "生成结果需检查；不保证所有索引工具均可自动适配。", 28, MUTED)
    cards.append(im)

    im, d, t = base(5, "执行状态与运行记录", "Execution states and run records")
    photo(im, "running", (55, 270, 970, 490))
    t(55, 795, "图中节点状态随任务执行更新。", 37)
    t(55, 865, "每次运行保留快照、日志与输出路径。", 32, MUTED)
    t(55, 925, "任务调度由 Snakemake 完成。", 31, MUTED)
    cards.append(im)

    im, d, t = base(6, "局部重跑与结果检查", "Partial execution and output inspection")
    photo(im, "preview", (55, 275, 970, 510), (1700, 0, 3200, 900))
    t(55, 815, "支持运行至指定节点与单步重新执行。", 34)
    t(55, 880, "连接端口时检查格式；输入及输出可预览。", 31, MUTED)
    t(55, 940, "快速预览仅覆盖有限记录。", 29, MUTED)
    cards.append(im)

    im, d, t = base(7, "Agent 与研究者协作", "Agent-assisted analysis through MCP")
    rows = [
        (280, "研究者", "研究设计、参数审查与结果解释"),
        (450, "Agent / MCP", "检索工具、构建流程、发起运行"),
        (620, "共享工作区", "图形界面与 Agent 访问同一会话"),
    ]
    for y, title, sub in rows:
        d.rectangle((55, y, 1025, y + 135), fill="#f2f5f7", outline=LINE, width=2)
        t(85, y + 15, title, 37, BLUE, True)
        t(85, y + 75, sub, 31)
        if y < 620:
            d.line((540, y + 135, 540, y + 160), fill=BLUE, width=3)
            d.polygon([(531, y + 153), (549, y + 153), (540, y + 165)], fill=BLUE)
    t(55, 810, "配套教程：合成 FASTQ → SeqKit 统计。", 34)
    t(55, 880, "已完成 stdio 调用与实际执行验证。", 31, MUTED)
    t(55, 940, "具体 Agent 客户端的兼容性需另行检验。", 28, MUTED)
    cards.append(im)

    im, d, t = base(8, "WSMV 共感染分析案例", "Application case: WSMV / TriMV")
    photo(im, "wsmv_result", (55, 275, 970, 545))
    t(55, 840, "12 个 RNA-seq 文库，73 个受检位点。", 34)
    t(55, 900, "均未达到 FDR < 0.10；阴性结果不证明等效。", 30, MUTED)
    t(55, 949, "既有案例结果；未在本次制图中重新分析。", 27, MUTED)
    cards.append(im)

    im, d, t = base(9, "面向 Agent 协作的生信分析", "Bioinformatics analysis with agent collaboration")
    t(55, 280, "研究者 × Agent × 工作站", 57, BLUE, True)
    t(55, 380, "研究者：确定研究问题与分析方案", 38, bold=True)
    t(55, 445, "审查方法、参数与结果解释。", 31, MUTED)
    t(55, 535, "Agent：通过 MCP 组织分析操作", 38, bold=True)
    t(55, 600, "检索工具、构建流程、发起运行、检查输出。", 31, MUTED)
    t(55, 690, "工作站：执行流程并保留运行证据", 38, bold=True)
    t(55, 755, "关联节点图、执行日志与结果文件。", 31, MUTED)
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
