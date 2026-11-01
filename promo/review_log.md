# 宣传图视觉复核记录

日期：2026-10-31 UTC。视觉模型：Qwen3.8-Flash，经本机 qodercn CLI。

## 方法与实际限制

对九宫格总图、9 张单图和海报分别附图调用。首轮使用指定完整检查提示；第二轮使用短提示。因多次超时，查看 CLI 诊断后发现 `CALL_COUNT_LIMIT` 排队及 endpoint election / network timeout；停止本次并发工作，剩余调用改为串行。没有修改模型、账户或服务设置。

每张图最多两轮检查。失败、中断和超时不等于通过。原始输出和中断记录保留在本地审计日志，公开文档仅收录摘要。

```bash
qodercn -p -m Qwen3.8-Flash --permission-mode bypass_permissions \
  -w <仓库根目录> --attachment <图片路径> \
  "检查这张宣传图：文字是否清晰可读、有无重叠或截断、留白是否合理、整体是否美观专业。指出具体问题。"
```

## 逐图结果

| 成品 | 首轮 | 第二轮 | 处理 / 最终状态 |
|---|---|---|---|
| `grid/01.png` | 调用超时，无有效意见 | 调用超时，无有效意见 | 人工查看无可见重叠或截断；Qwen 结论未完成 |
| `grid/02.png` | 调用超时，无有效意见 | 调用超时，无有效意见 | 人工检查后缩小下方局部图，确保与说明留有间距；Qwen 结论未完成 |
| `grid/03.png` | 收到有效意见 | 因排队/网络问题中断，无有效意见 | 按意见放大节点/日志、分离截图标题栏并增加间距；第二轮未返回，不能标为模型通过 |
| `grid/04.png` | 调用超时，无有效意见 | 因排队/网络问题中断，无有效意见 | 人工查看无可见重叠或截断；Qwen 结论未完成 |
| `grid/05.png` | 调用超时，无有效意见 | 因排队/网络问题中断，无有效意见 | 人工查看无可见重叠或截断；Qwen 结论未完成 |
| `grid/06.png` | 调用超时，无有效意见 | 调用超时，无有效意见 | 人工查看无可见重叠或截断；Qwen 结论未完成 |
| `grid/07.png` | 调用超时，无有效意见 | 调用超时，无有效意见 | 人工查看无可见重叠或截断；Qwen 结论未完成 |
| `grid/08.png` | 因排队/网络问题中断，无有效意见 | 调用超时，无有效意见 | 人工查看无可见重叠或截断；Qwen 结论未完成 |
| `grid/09.png` | 因排队/网络问题中断，无有效意见 | 调用超时，无有效意见 | 人工查看无可见重叠或截断；Qwen 结论未完成 |
| `grid/grid.png` | 因排队/网络问题中断，无有效意见 | 调用超时，无有效意见 | 人工查看无可见重叠或截断；Qwen 结论未完成 |
| `poster.png` | 调用超时，无有效意见 | 调用超时，无有效意见 | 放大日志、状态条和预览上部；已渲染 PDF 查看，Qwen 结论未完成 |

## 有效意见与处理

第 3 格收到的意见：原图缩小后关键节点与日志字号小，日志局部的标题栏看似截断，截图与放大条重复，间距可改善。处理：裁出关键节点，单独裁取原始拒绝日志，移除日志标题栏碎片并增大间距。没有采纳“给被拒连线加高亮”的建议，因为拒绝后该连线并不存在，不能制造界面证据。

同步改善海报：缓存改用真实成功状态条局部，预览改用面板上部，端口检查使用独立日志。第 2 格下方局部图与说明增加间距。

## 人工与程序检查

- 已查看九宫格总图、关键单图与海报；截图内细字仍需放大查看原素材，主标题和解释文字不依赖细字。完整画布是结构概览，不承诺缩略图能读完所有节点名。
- 字体经运行时确认为 Noto Sans CJK SC；九格主标题均不超过 20 字。
- 9 张单图为 1080×1080，总图为 3240×3240；海报为 3508×4961、300 dpi。
- PDF 经 pdfinfo 确认为单页 A3，并使用 pdftoppm 渲染检查。PDF 为图像，文字不可选取。
- 公开素材与真实原件逐字节相同，成品只做脚本化裁切、缩放与排版。

## 未完成项

受 Qoder 服务排队及网络失败影响，本次没有取得全部成品的有效 Qwen 意见，也没有取得修改后第 3 格的有效复核结论。两轮尝试已结束，**本批物料不能声称“已全部通过视觉模型复核”**。这一限制不影响软件测试与仓库安全检查的独立结果。

## 2026-11-01 双语更新复核 / Bilingual update review

本轮保留 `assets/` 原始截图，更新九宫格中英文标题、说明及 A3 海报，并加入 Agent 教程入口。既有 Qwen 记录仅适用于历史版本，不作为本轮模型复核证明。本轮未调用外部视觉模型。

The original screenshot assets were preserved. Card annotations and the A3 poster were updated with bilingual text and the agent-tutorial entry point. Historical Qwen records do not constitute review of this revision; no external visual model was used for this update.

- 已查看重建后的九宫格总图；标题、说明与截图无可见重叠或截断。截图内细字仍需打开原图查看。 / Inspected the rebuilt contact sheet; no visible annotation clipping or overlap. Fine screenshot text still requires the original assets.
- 已将最新 `poster.pdf` 用 Poppler 渲染为 PNG 并查看；布局无可见重叠或截断。`pdfinfo` 确认为 A3 单页。 / Rendered and inspected the latest poster PDF with Poppler; no visible overlap or clipping. `pdfinfo` confirms one A3 page.
- 九格各 1080×1080，总图 3240×3240；海报 3508×4961，300 dpi。PDF 仍为不可选取文字的图像版。 / Cards are 1080×1080, the sheet 3240×3240, and the poster 3508×4961 at 300 dpi. The PDF remains an image-based version.
- 研究附件为原有 PDF 的逐字节副本，未重排或改写；`research/SHA256SUMS` 记录校验和。 / Research attachments are unchanged byte-for-byte copies, with checksums in `research/SHA256SUMS`.
- Agent 教程配套脚本已通过实际 stdio、dry-run、真实执行及 2 条序列/8 bp 输出检查；本轮 pytest 为 17 passed，Ruff 检查通过。 / The tutorial script completed actual stdio calls, dry-run, execution and checks for two sequences/eight bases; pytest reported 17 passed and Ruff passed.


## 2026-11-01 Agent 协作主题海报

新增 `agent-poster.png`、`agent-poster.pdf` 及预览图。内容合并新版九宫格，强调研究者、Agent 与工作站的职责；数量沿用 `qzone/tool-counts.json` 的本机快照。真实截图来自 `assets/branch.png`，未修改界面内容。已使用 Poppler 渲染 PDF 并查看，未见标题、说明或适配流程文字重叠与截断。`pdfinfo` 确认为单页 A3；PNG 为 3508×4961、300 dpi。Ruff 检查通过；本次仅制作材料，未重新运行研究分析或工具验证。


## 2026-11-01 许可证标注更新

项目许可证调整为 GPL-3.0-only。已重建各版海报、九宫格及软件概览图，使许可证标注一致；两份海报 PDF 经 Poppler 渲染查看，未见页脚文字重叠或截断。原有研究 PDF 保持不变。

## 2026-11-01 English project descriptions and communication materials

The repository description, project metadata and communication copy were changed to English. Both poster layouts, both nine-card sets and the software overview were rebuilt with English annotations. Original interface screenshots and research PDFs were preserved. All README files, software interface labels, CLI messages and business-code comments remain unchanged.

The two poster PDFs were rendered with Poppler and visually inspected. Both card sheets and the overview preview were also inspected; no annotation overlap or clipping was observed. Longer English card headings are fitted to the available width. Tool counts and GPL-3.0-only licensing remain unchanged. This update did not rerun research analyses or expand tool validation.
