# 软件展示图 / Software overview figure

## 内容与版式 / Content and layout

- **a. 工作流编辑 / Workflow editor**：直接使用 `assets/canvas.png`，完整保留截图内容，仅缩放。
- **b. 接口与执行 / Interfaces and execution**：以当前软件结构绘制示意图，明确区别于界面截图。图形界面和 MCP Agent 均访问本地共享工作区，工作流编译后由 Snakemake 执行。
- **c. 应用案例 / Application case**：陈述既有 WSMV 案例的样本量和位点检验结果；保留阴性结果不等同于统计等效的解释边界。

The layout combines an unchanged workflow screenshot, an explicitly labeled architecture schematic and a concise case caption. The schematic summarizes the current implementation; it is not a screenshot. Research figures and analyses were not regenerated for this composition.

主标题描述软件用途；分面标题及图注采用事实陈述。使用白底、深灰文字与蓝灰辅助色；中英信息按相同层级排列。未使用 AI 生成界面，也未复用参考项目的图片、商标或文案。

The title describes the software's purpose. Panel titles and captions use factual wording, with a white background, dark text and a restrained blue-gray accent. Chinese and English follow the same hierarchy. No AI-generated interface or third-party image, logo or wording is used.

## 参考 / References

版式参考科研软件文献和官方文档中“界面、工作流及说明分面呈现”的方式，具体构图和文字为本项目重新编排。

The layout was informed by panel-based presentations of software interfaces and workflows in research articles and official documentation. Composition and wording were developed for this project.

- [Rose et al. (2019), Flexible design of multiple metagenomics classification pipelines with UGENE, Figure 1](https://academic.oup.com/bioinformatics/article/35/11/1963/5144668). DOI: 10.1093/bioinformatics/bty901.
- [UGENE: Workflow Designer - Pipelines and Repeatable Experiments](https://ugene.net/quick-start-guide/what-you-can-do-in-ugene/workflow-designer-pipelines-and-repeatable-experiments/).

## 重建与检查 / Rebuild and checks

```bash
python promo/scripts/make_academic_figure.py
```

依赖与字体要求同本目录既有脚本。输出为 3600×2800 PNG（300 dpi），并生成 1800×1400 预览图。2026-11-01 已查看合成预览，未见标题、图注或示意图文字重叠和截断；截图细字需查看完整分辨率或原素材。该检查不涉及重新运行研究案例。

Requirements match the existing composition scripts. Outputs are a 3600×2800 PNG at 300 dpi and an 1800×1400 preview. The composed preview was inspected on 2026-11-01; no visible overlap or clipping of titles, captions or schematic text was found. Fine screenshot text requires full resolution or the source asset. This review did not rerun the research case.
