# 宣传物料 / Communication materials

- `academic-overview.png`：新版学术风格横版展示图，3600×2800 px，300 dpi；`academic-overview.preview.png` 为预览版。
- [版式说明与参考 / Layout notes and references](academic-overview.notes.md)。

- `grid/grid.png`：3240×3240 总图；`grid/01.png` 至 `09.png`：1080×1080 单图。
- `poster.png` / `poster.pdf`：A3，3508×4961 px，300 dpi（像素取整带来不足 0.04 mm 的纸张误差）。PDF 为高分辨率单页图像，文字非可选文本。
- `copy.md`：中英双语定位、简介、社交文案、演示顺序、FAQ 与能力依据。
- `research/`：经授权发布的既有研究 PDF、双语发布说明及文件校验和。
- [中文 Agent 协作教程](../docs/agent-workflow.zh-CN.md) / [English agent tutorial](../docs/agent-workflow.en.md)。

The kit includes a bilingual A3 poster, nine presentation cards, bilingual communication copy, agent tutorials and authorized existing research PDFs. Screenshots preserve the actual Chinese UI. Research PDFs retain their original languages; see the [bilingual research release notes](research/README.md) for scope and limitations.
- `review_log.md`：Qwen 视觉复核及处理记录。

## 可复现

Python 3 + Pillow，系统安装 Noto Sans CJK SC。脚本使用 Noto CJK 字体集合第 2 个字型（SC）：

```bash
python promo/scripts/make_grid.py
python promo/scripts/make_poster.py
```

脚本仅依赖本目录素材；可从任意工作目录调用脚本的绝对路径。字体位置见 `scripts/common.py`，其他系统可调整字体路径。

## 素材真实性与来源

`assets/` 中的图片均为原阶段 B/D 留存的真实成品，未生成或替换界面内容。

| 公开素材 | 原截图标识 / 用途 |
|---|---|
| canvas.png | B_02_full_canvas：完整案例画布 |
| detail.png | B_02b_shared_nodes_detail：共享参考与索引 |
| branch.png | B_02c_canvas_zoom：原画布局部，展示输入→工具→输出 |
| ports.png | B_03_port_type_rejected：JSON→BAM 拒绝日志 |
| running.png | B_04_running：真实 BWA MEM 单步运行，黄色边框 |
| cache.png | B_07_step_rerun_cached：真实单步运行，其他节点 skipped |
| preview.png | B_06a_preview_fastq_input：FASTQ 预览 |
| history.png | B_08_run_history：真实运行历史 |
| wsmv_result.png | 定稿 graphical abstract：与论文结论一致的结果图 |

原件属于本地保留的 WSMV 案例，本仓库仅收录上述成品图片。原始运行记录和完整分析脚本不包含在公开仓库；经授权发布的案例稿件及报告位于 `research/`。案例首个样本分支使用 MCP add_node/connect_nodes 搭建，其余样本并非全部由 MCP 创建；第 7 格显示相应画布，不能作为真实 Agent 客户端验证的证据。截图的案例自定义节点、自动封装项及工具库计数不等于软件默认内置生态。

裁切和缩放均由脚本显式记录：端口错误日志、运行中 BWA 节点、单步成功状态、预览面板为原图局部。第 2 格完整画布为结构概览，细节点名可查看 assets 原图。宣传中文主标题每格不超过 20 字，额外小字用于验证边界与素材解释。

图示节点颜色与文字标签共同表达状态；正文采用深色文字和浅底，方便黑白打印。技术栈中的 Bioconda 表示工具环境来源，不表示已验证整个上游生态。
