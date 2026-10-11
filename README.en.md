# Paper Poster Agent

[中文](README.md) · [English](README.en.md)

**Paper Poster Agent turns a paper and its original figures into a conference poster.**

Codex handles content, layout and high-resolution exports. The author chooses what to emphasize, reviews a design reference and asks for changes.

![Original DINOv2 figures alongside an HTML poster made from the public paper](docs/assets/paper-to-poster.png)

The public example uses figures and charts from DINOv2 (Oquab et al., TMLR 2024), reused under CC BY 4.0. [Paper and license sources](docs/usage.md#公开样例的来源) · [View the full poster](docs/assets/showcase/poster-preview.png) · [Download the HTML example](docs/assets/showcase/poster.html) and open it in a browser.

## What the agent takes care of

- **Content and layout.** Codex reads the paper, checks the current conference requirements and arranges the text and figures.
- **A design to review first.** A reference image shows the colors and layout. Figure sizes, headings, spacing and colors remain adjustable.
- **Room for the research details.** The method figure can take more space, experiments can appear side by side, and conditions, captions and tables can stay next to the relevant figures. The final poster uses the original figures and paper data.

The project supports editable HTML, a PNG above 4K resolution and PDF. Once the author accepts the content and design, the agent prepares the print delivery files.

## Start in Codex (recommended)

Install the [academic-poster-agent skill](docs/usage.md#在-codex-对话里制作), then send this prompt to Codex:

> I want a poster from paper.pdf and figures/ for Conference Name 2026 Main. Please use $academic-poster-agent, keep the original figures, and emphasize the method and key experiments. Show me a design reference first so I can tell you what to adjust.

Codex uses the tools available in the current session. The [usage guide covers CLI and skill installation](docs/usage.md#安装与体验).

## Give feedback in plain language

The poster preview supports feedback on selected regions. Changes can also be requested in the conversation:

> "The method figure is too small. Please enlarge it and keep the current title and colors."
>
> "These experiments need to be compared. Please place them in the same section."
>
> "This section has room for more detail. Please add the experimental conditions and explanation."

Version history keeps the previous layouts for comparison. After the author accepts the final version, the agent packages the **print PDF, high-resolution PNG and editable HTML**. The [usage guide explains print delivery](docs/usage.md#审阅修改与打印).

## Run from the terminal

Complete the [terminal API setup](docs/usage.md#在终端调用-api), replace the paper and conference details, and run the commands below. This workflow uses the paid API configured for the account:

```bash
poster-agent run projects/my-poster --api --paper paper.pdf --assets figures --conference "Conference Name" --year 2026 --track Main
poster-agent review projects/my-poster
```

Star the repository to save it for the next conference, or share it with a labmate preparing a poster.

Preview · [Usage and version notes](docs/usage.md#项目文件与验证) · [Contributing](CONTRIBUTING.md) · [MIT License](LICENSE)
