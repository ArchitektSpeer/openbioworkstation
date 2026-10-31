"""Rebuild nine 1080px cards and the 3240px contact sheet from shipped assets.
Requires Pillow and Noto Sans CJK SC (font collection index 2).
"""

from common import ACCENT, BG, MUTED, ROOT, Image, photo, rule, text


def base(i, title, tag):
    im = Image.new("RGB", (1080, 1080), BG)
    text(im, (56, 40), "OPENBIOWORKSTATION  /  " + tag, 24, ACCENT, True)
    text(im, (56, 105), title, 54, bold=True)
    rule(im, 190)
    rule(im, 980)
    text(im, (56, 1004), "LOCAL WORKFLOWS  ·  OPEN SOURCE", 23, MUTED)
    text(im, (968, 998), f"{i:02}", 34, ACCENT, True)
    return im


def main():
    cards = []
    im = base(1, "把生信流程连起来", "工作台")
    text(im, (56, 240), "OpenBio", 102, bold=True)
    text(im, (56, 370), "Workstation", 102, bold=True)
    text(im, (56, 540), "可视化节点 · Snakemake 执行", 41)
    photo(im, "branch", (56, 640, 968, 270))
    cards.append(im)
    specs = [
        (2, "从画布看见完整流程", "画布", "canvas", "真实案例全貌；下方为分支局部"),
        (3, "连线先检查文件类型", "端口", "ports", "JSON → BAM 被拒绝，错误写入日志"),
        (4, "运行状态实时可见", "执行", "running", "黄色边框表示运行中；保留原始状态"),
        (5, "只重跑需要更新的一步", "缓存", "cache", "真实单步运行；其余节点跳过或缓存"),
        (6, "先预览，再连接", "文件", "preview", "快速检查有限记录，不代表全文件"),
        (7, "Agent 与画布共享工作区", "MCP", "branch", "案例首个样本分支经 MCP 搭建"),
    ]
    for i, title, tag, name, note in specs:
        im = base(i, title, tag)
        if i == 2:
            photo(im, name, (56, 215, 968, 460))
            photo(im, "branch", (56, 700, 968, 205))
        elif i == 3:
            photo(im, name, (56, 230, 968, 510), (750, 260, 3000, 1370))
            text(im, (56, 770), "原始拒绝日志（局部放大）", 30, MUTED)
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
            text(im, (56, 715), "stdio 已验证 · 真实客户端尚未验证", 33)
            text(im, (56, 782), "add_node → connect_nodes → run", 32, ACCENT)
        text(im, (56, 934), note, 26, MUTED)
        cards.append(im)
    im = base(8, "真实案例，完整流程跑通", "WSMV")
    photo(im, "wsmv_result", (56, 235, 968, 530))
    text(im, (56, 805), "未检出共感染的显著影响", 43, bold=True)
    text(im, (56, 880), "样本量有限；阴性结果不证明等效", 31, MUTED)
    cards.append(im)
    im = base(9, "从本地演示开始", "参与")
    text(im, (56, 270), "./run-demo.sh", 68, bold=True)
    text(im, (56, 395), "合成样本 · 离线运行", 40)
    text(im, (56, 570), "github.com/ArchitektSpeer/", 40, ACCENT)
    text(im, (56, 630), "openbioworkstation", 49, ACCENT, True)
    text(im, (56, 800), "MIT License", 56, bold=True)
    text(im, (56, 890), "小规模工具库 · 单机 · 无多用户", 31, MUTED)
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
