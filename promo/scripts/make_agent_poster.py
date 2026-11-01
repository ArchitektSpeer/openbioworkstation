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
    text(185, 355, "面向 Agent 协作的生物信息学工作站", 91, bold=True)
    text(185, 505, "A bioinformatics workstation for researcher-agent collaboration", 51, MUTED)
    text(185, 630, "节点图构建  ·  Snakemake 执行  ·  MCP 接口  ·  本地运行记录", 46, BLUE)
    line(775)

    text(180, 835, "研究者、Agent 与工作站的协作分工", 62, bold=True)
    roles = [
        (180, "研究者", "确定研究问题与分析方案", "审查方法、参数与结果解释"),
        (1260, "Agent / MCP", "检索工具、构建流程", "发起运行并检查输出"),
        (2340, "工作站 / Snakemake", "执行分析流程", "关联节点图、日志与结果文件"),
    ]
    for x, title, first, second in roles:
        text(x, 965, title, 52, BLUE, True)
        text(x, 1060, first, 43)
        text(x, 1130, second, 40, MUTED)

    photo(im, "branch", (180, 1270, 3148, 1392))
    text(
        180,
        2700,
        "WSMV 案例工作流局部：多条样本链共享参考序列与索引；包含案例专用节点。",
        38,
        MUTED,
    )
    text(180, 2780, "支持端口格式检查、执行状态显示、局部重新执行与文件预览。", 42)
    line(2890)

    text(180, 2940, "工具接入与检索规模", 60, bold=True)
    text(2510, 2960, "本机快照 / 2026-11-01", 37, MUTED)
    text(180, 3040, str(counts["auto_wrapped_packages"]), 177, BLUE, True)
    text(1770, 3040, f"{counts['indexed_entries']:,}", 177, BLUE, True)
    text(190, 3260, "个软件包已在本机建立封装", 46)
    text(1780, 3260, "条可检索工具索引", 46)
    text(180, 3380, "78 个封装节点 + 5 个内置 wrapper 定义 + 10 个本机节点 = 93 个节点定义", 42)
    text(180, 3470, "其中 62 个带审核标记；工具审核工作正在逐步推进。", 45, bold=True)
    text(180, 3560, "软件包、节点与索引采用不同统计口径；可检索不等于可直接执行。", 37, MUTED)
    line(3670)

    text(180, 3725, "LLM 辅助工具自动适配", 60, bold=True)
    stages = [
        (180, "提取工具帮助", "创建依赖环境"),
        (1000, "LLM 生成定义", "描述端口与命令"),
        (1820, "检查与试运行", "检查结构及合成输入"),
        (2640, "审查后使用", "核对定义并标记审核"),
    ]
    for i, (x, title, sub) in enumerate(stages):
        d.rectangle((x, 3860, x + 688, 4070), fill="#f2f5f7")
        text(x + 35, 3890, title, 45, BLUE, True)
        text(x + 35, 3980, sub, 35, MUTED)
        if i < 3:
            text(x + 720, 3915, "→", 54, BLUE)
    text(
        180, 4130, "需配置模型接口与工具依赖环境；生成定义及试运行不能替代真实数据验证。", 37, MUTED
    )
    text(
        180, 4200, "本机封装不代表随仓库默认安装；具体 Agent 客户端的兼容性需单独检验。", 37, MUTED
    )
    line(4310)

    text(180, 4370, "应用案例：WSMV / TriMV 共感染分析", 46, bold=True)
    text(
        180,
        4455,
        "12 个 RNA-seq 文库；73 个受检位点均未达到 FDR < 0.10。阴性结果不证明统计等效。",
        36,
        MUTED,
    )
    text(180, 4540, "开源代码、Agent 协作教程与研究案例", 45, BLUE)
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
