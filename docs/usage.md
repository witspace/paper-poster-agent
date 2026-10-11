# 使用 Paper Poster Agent

海报制作有两个入口：Codex 对话和终端 API。本文示例使用 `paper.pdf`、`figures/` 和 `projects/my-poster`，实际运行时换成对应材料即可。

## 两种入口

### 在 Codex 对话里制作

**推荐在 Codex 对话里制作。** 安装 skill 后，把论文、原图和会议信息交给 Codex，再发送这段话：

> 我想用 paper.pdf 和 figures/ 制作 Conference Name 2026 Main 的海报。请使用 $academic-poster-agent，保留论文原图，突出方法图和关键实验。你先给我看设计参考，我再告诉你哪里需要调整。

修改意见可以继续写在同一段对话里，比如放大方法图、保留实验条件，或把几个实验排在一起。Codex 会先生成设计参考，再制作 HTML 海报；作者确认内容和设计后，Agent 会继续导出打印包。

Codex 使用当前会话提供的检索、论文理解和 ImageGen 工具，沿用客户端的能力与额度，无需为本项目另配 API key。相关工具暂时不可用时，Codex 会保留已有成果，并说明接下来需要完成的步骤。

## 安装与体验

环境需要 Python 3.10+。在仓库目录建立虚拟环境：

```bash
python -m venv .venv
```

macOS / Linux 激活：

```bash
source .venv/bin/activate
```

Windows PowerShell 激活：

```powershell
.venv\Scripts\Activate.ps1
```

安装 CLI 和 Chromium，再检查本地环境：

```bash
python -m pip install -e .
python -m playwright install chromium
poster-agent doctor --workspace .
```

`doctor` 检查依赖、Chromium 实际启动、目录写入和模型配置。它只报告 key 是否配置。使用 `--skip-browser` 可跳过浏览器启动。

CLI 安装后，将 `skills/academic-poster-agent` 复制到 Codex 的 skills 目录。

macOS / Linux：

```bash
mkdir -p ~/.codex/skills
cp -R skills/academic-poster-agent ~/.codex/skills/
```

Windows PowerShell：

```powershell
$posterSkillsDir = Join-Path $env:USERPROFILE '.codex/skills'
New-Item -ItemType Directory -Path $posterSkillsDir -Force | Out-Null
Copy-Item -LiteralPath 'skills/academic-poster-agent' -Destination $posterSkillsDir -Recurse -Force
```

按客户端提供的方式刷新 skill，然后发送上面的提示。

项目也支持手动初始化：

```bash
poster-agent init projects/my-poster --paper paper.pdf --assets figures --conference "Conference Name" --year 2026 --track Main
```

可选的 `--assets` 用于导入作者原图。材料只有论文 PDF 时，Agent 会定位图的页码和区域并保留出处。机构标识使用作者提供的原件。

### 先试一次本地生成

仓库附带原创演示材料，适合先试用渲染和查看流程：

```bash
poster-agent demo projects/demo --png-width 6000
poster-agent review projects/demo
```

打开终端给出的本地地址，默认端口为 `8765`。端口被占用时可指定 `--port 8766`。演示使用原创合成论文与 SVG，依赖安装后可离线生成 HTML、6000 px 宽 PNG、单页 A0 PDF 和检查报告。

演示材料标注 **DEMO / SYNTHETIC DATA**，数值用于展示版面。它保持 `print_ready: false`；真实论文项目在完成核验和人工批准后进入打印交付。[查看演示材料](../examples/demo/README.md)。

### 公开样例的来源

首页对照图和 [HTML 样例](assets/showcase/poster.html)使用公开论文 [DINOv2: Learning Robust Visual Features without Supervision](https://arxiv.org/pdf/2304.07193v2)（Oquab 等，TMLR 2024）的三张原图：Figure 1 的 PCA 特征图（第 2 页）、Figure 3 的数据构建流程（第 4 页）和 Figure 2 的八项任务扩展实验（第 3 页）。排版对论文图文作了节选和重新安排，来源记录保存在 [source.json](assets/showcase/source.json)。

论文素材依据 [TMLR 的发表政策](https://jmlr.org/tmlr/author-guide.html)按 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) 复用；软件采用 [MIT 许可证](../LICENSE)。这份海报用于展示排版，内容与设计仍在审阅，打印交付按实际会议要求另行核验。

### 在终端调用 API

独立流程需要本机环境变量：

| 变量 | 用途 |
|---|---|
| `OPENAI_API_KEY` | 自己的 OpenAI API key |
| `POSTER_MODEL` | 账户可用、支持所需文本与视觉任务的模型 ID |
| `POSTER_IMAGE_MODEL` | 图像模型 ID，默认 `gpt-image-2` |

请在本机配置。模型访问权限和费用由 API 账户决定。模型任务会把所需论文文本与图像发送给对应 API；请根据材料的公开状态选择运行方式。分享前检查准备公开的文件。

从一篇新论文开始：

```bash
poster-agent run projects/my-poster --api --paper paper.pdf --assets figures --conference "Conference Name" --year 2026 --track Main --max-rounds 2
poster-agent review projects/my-poster
```

已有初始化项目可以运行：

```bash
poster-agent run projects/my-poster --api --max-rounds 2
```

`--api` 表示本次制作调用独立收费 API。流程依次完成官方规则研究、内容草稿、ImageGen 参考、实际渲染、独立审阅和 0–2 轮视觉调整，最后交给作者审阅。`--max-rounds` 接受 `0`、`1`、`2`。

科学内容问题进入 `needs_author`，由作者对照原文处理。原图缺失或需要人工判断时，报告会指出原因和下一步。

失败后查看 `run-report.json` 的 `failed_step`、`error` 和 `next_action`。解决对应问题后继续：

```bash
poster-agent run projects/my-poster --api --resume --max-rounds 2
```

恢复时会核对实际文件和当前摘要，复用有效阶段；已用的自动调整轮数继续累计。换论文、年份或 track 时建立新项目。原始 PDF 字节变化也会要求新建项目。

分步 API 命令包括 `research`、`draft`、`reference`、`critique`、`repair` 和 `apply`。这些命令会调用配置的 API。

```bash
poster-agent research projects/my-poster
poster-agent draft projects/my-poster
poster-agent reference projects/my-poster
poster-agent render projects/my-poster --png-width 6000
poster-agent critique projects/my-poster
poster-agent check projects/my-poster
```

已有参考图会继续使用。明确需要新的参考时运行：

```bash
poster-agent reference projects/my-poster --new-version
```

旧参考和版本历史保留。根据最新审阅做一轮视觉调整：

```bash
poster-agent repair projects/my-poster
```

该命令在应用调整后重新渲染、审阅和检查。

## 先核验会议要求

为确切会议、年份、track 和展示形式查正式通知。规则记录官方链接、逐字摘录、适用范围和核验时间。强制海报要求与可选打印服务分别保存。

方向和尺寸以本届通知为准。未公布的 PPI、色彩、出血等要求保持未知。自动研究会核对页面摘录；页面受阻、摘录不匹配或尺寸含义不清时，流程停在待核验处。

正式通知已经逐项核验后，可以准备 profile 并显式导入：

```bash
poster-agent rules projects/my-poster --file checked-profile.json
```

这一步记录“人工已核验导入”的来源状态。profile 的字段、来源分类和适用映射见 [数据约定](../CONTRACT.md#会议要求从哪里来)。提交渠道、paper ID、文件名、大小、截止日期与时区需要按实际通知确认。

## 原图、排版与检查

`--assets` 导入 PDF、SVG、PNG 和 JPEG 原件，并建立 `assets/catalog.json`。PDF 原图会转换为保留矢量内容的 SVG。预览图用于查看与设计参考，最终海报引用原件。

版面默认沿着问题、思路、方法、证据和研究范围展开。方法图和关键对比占据主要空间；实验条件、图注和必要表格靠近相关图。统一对齐和标题层级帮助观众连续阅读。信息密度同时看内容量、标签大小和阅读距离。

独立审阅对照：

| 对照对象 | 检查内容 |
|---|---|
| 论文、原图与海报 | 作者、数值、单位、图例、结论强度与研究范围 |
| ImageGen 参考与 HTML | 阅读顺序、层级、密度、空间比例、配色与美观 |
| HTML 与实际 PDF | 毫米尺寸、单页、字体嵌入、完整内容与视觉差异 |
| 高清局部与打印尺度 | 原图标签可读性、位图有效 PPI |

每条问题带位置、严重程度、实际依据和具体建议，并可查看高清 HTML 局部与独立渲染的 PDF 局部。参考图中的文字、图表和标识需要核验；科研内容使用原始来源。

默认 PNG 宽 6000 px，可用 `render --png-width` 调整。画布像素数、原图有效 PPI 和图内文字大小分别检查。SVG 中也可能包含低分辨率照片；放入最终版面后仍需查看实际位图清晰度。

## 审阅修改与打印

### 把哪里要改说清楚

```bash
poster-agent review projects/my-poster
```

工作台提供参考、HTML、前一版、PDF、圈选区域和版本记录。

- **保存反馈**：记录位置与意见，当前海报保留。
- **应用视觉调整（API）**：调用配置的 API 处理该条意见；也可以把意见交给当前 Codex 对话。
- **保留区域**：保护已经满意的版块。
- **批准当前版本**：作者确认内容、设计和可读性，程序同时要求当前技术与内容检查通过。

命令行反馈使用项目实际的版块 ID：

```bash
poster-agent feedback projects/my-poster --target method --message "放大方法图，保持标题和配色"
poster-agent apply projects/my-poster f0001
```

将 `method` 和 `f0001` 替换成实际版块与反馈 ID。`apply` 会调用 API。本地视觉修改可使用 `patch`：

```bash
poster-agent patch projects/my-poster visual-patch.json --reason "放大方法图"
poster-agent render projects/my-poster --png-width 6000
poster-agent check projects/my-poster
```

patch 的白名单包括有限的主题、版面、图高、显示标题和版块顺序；格式见 [数据约定](../CONTRACT.md#自动流程和审阅意见)。科研文字、数值、原图与来源保持。事实修改后需要重新核验科学内容。

需要继续修改已批准版本时，显式运行 `reopen`；`undo` 从历史恢复设计并创建新版本。

```bash
poster-agent reopen projects/my-poster
poster-agent undo projects/my-poster
```

### 满意后生成打印包

作者确认海报、当前检查通过后，运行：

```bash
poster-agent approve projects/my-poster
poster-agent package projects/my-poster
```

批准绑定当前版本与实际导出文件，随后固定设计。工作台也有批准后的打印包按钮。程序在打包前重新检查文件、科学审阅和当前批准。

ZIP 包含五个文件：

1. `poster-print.pdf`，或按已确认要求命名的 PDF。
2. `poster.html`，可编辑的独立 HTML。
3. `poster-4k.png`，高清 PNG。
4. `quality-report.json`，本次导出的检查报告。
5. `PRINT_README.txt`，尺寸、来源与打印说明。

论文全文、原始素材、项目历史与 API 配置保留在项目目录。选择文件名或会议打印服务时：

```bash
poster-agent package projects/my-poster --filename Poster_Submission.pdf
poster-agent package projects/my-poster --printing-service --paper-id ACTUAL_ID --track Main
```

`--printing-service` 应用已核验的服务尺寸、命名、文件大小和截止日期等条件。paper ID 与 track 填真实值。服务要求缺失、过期或条件不满足时，报告会说明需要处理的项。

`print_ready` 依赖当前文件摘要、实际技术结果、当前科研内容审阅和该版本的人工确认。报告包含毫米尺寸、页数、字体嵌入、文字完整性、布局边界、PNG 尺寸、有效 PPI 和 HTML/PDF 差异。

浏览器导出的 PDF 为 RGB。会议或印厂要求 PDF/X、指定 ICC、CMYK 或出血时，需要完成对应生产步骤并验证最终文件。结合报告查看原图标签与实际打印尺度，再交付印厂。

## 项目文件与验证

```text
project/
  conference.json   正式规则、来源与可选打印服务
  evidence.json     原文事实与科学内容审阅
  poster.json       内容、设计和当前批准
  run-report.json   API 阶段、失败位置与调整轮数
  source/           论文、页图和作者原件
  assets/           原图目录与来源
  reference/        设计参考与生成记录
  history/          版本历史
  exports/          HTML、PNG、PDF 与检查报告
```

本地已通过 84 项测试，包含真实 Chromium、PNG 和 PDF 验证。模型调用使用受控请求测试，覆盖格式、失败、密钥处理和恢复；线上收费 API 全流程仍需使用真实账户验证。

```bash
python -m unittest discover -s tests -v
```

用户论文、原图和项目记录保留在本地。公开仓库与宣传样例使用许可已核验的公开论文，并检查文件和截图中是否带有个人信息。会议提交和印厂交付由作者决定。

[返回 README](../README.md) · [数据与流程约定](../CONTRACT.md) · [MIT 许可证](../LICENSE)
