# Software overview figure

## Content and layout

- **a. Workflow editor:** uses `assets/canvas.png`, preserving the complete original screenshot and resampling it to fit the panel.
- **b. Interfaces and execution:** a schematic of the software architecture, explicitly distinguished from an interface screenshot. The desktop and MCP agent share a local workspace; compiled workflows execute through Snakemake.
- **c. Application case:** reports the existing WSMV sample size and site-level result, retaining the distinction between a negative finding and statistical equivalence.

The layout combines an unchanged workflow screenshot, an architecture schematic and a concise case caption. Research figures and analyses were not regenerated for the composition. English annotations describe the software; original screenshots retain the actual interface language.

The title describes the software's purpose. Panel titles and captions use factual wording, with a white background, dark text and a restrained blue-gray accent. No AI-generated interface or third-party image, logo or wording is used.

## References

The layout was informed by panel-based presentations of software interfaces and workflows in research articles and official documentation. Composition and wording were developed for this project.

- [Rose et al. (2019), Flexible design of multiple metagenomics classification pipelines with UGENE, Figure 1](https://academic.oup.com/bioinformatics/article/35/11/1963/5144668). DOI: 10.1093/bioinformatics/bty901.
- [UGENE: Workflow Designer - Pipelines and Repeatable Experiments](https://ugene.net/quick-start-guide/what-you-can-do-in-ugene/workflow-designer-pipelines-and-repeatable-experiments/).

## Rebuild and checks

```bash
python promo/scripts/make_academic_figure.py
```

Requirements match the existing composition scripts. Outputs are a 3600×2800 PNG at 300 dpi and an 1800×1400 preview. Review the complete composition for clipping and overlap after rebuilding. Fine screenshot text requires full resolution or the original asset. Layout review does not establish scientific validity or rerun the research case.
