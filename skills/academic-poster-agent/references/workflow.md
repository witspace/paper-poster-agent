# 执行与验收流程

以下 `PROJECT`、`PAPER.pdf`、会议与作者素材目录由实际任务替换。使用已安装仓库的 CLI 和共享模块，项目中保留可追溯成果。

## 1. 选择入口与建立项目

```bash
poster-agent doctor --workspace PROJECT_PARENT
poster-agent init PROJECT --paper PAPER.pdf --assets FIGURES_DIR --conference "NAME" --year 2026 --track "TRACK"
```

`PROJECT_PARENT` 是存在且可写的父目录。作者素材目录可省略。`init` 建立论文 PDF、文本、页图、原图目录和规则/证据骨架；已经初始化的项目继续使用，新的输入使用新的项目目录。

会话模式由当前 Codex 的检索、论文理解、内置 ImageGen 与视觉工具完成角色，CLI 负责本地处理。生成 JSON 时可调用 `poster_agent.project.write_json`，保留真实换行与 UTF-8。明确选择独立 API 的用户可用：

```bash
poster-agent run PROJECT --api --max-rounds 2
poster-agent run PROJECT --api --resume --max-rounds 2
```

API 配置由用户本地提供 `OPENAI_API_KEY`、可用的 `POSTER_MODEL` 和可选 `POSTER_IMAGE_MODEL`。这些命令会按账户计费。当前会话入口无需另配 key，工具不可用时保留失败阶段，用户明确选择后才能切换到 API。

离线安装体验可运行 `poster-agent demo NEW_PROJECT`。原创合成 demo 标注虚构作者、图和数据，展示实际渲染与审阅，保持 `print_ready: false`。

## 2. 查验正式会议规则

按确切会议名称、年份、track 与展示形式查本届官方 presenter/poster/printing 页面。打开页面核对原文，保留 URL、逐字摘录、查询时间和适用范围。逐项记录尺寸/最大展板尺寸、方向、文件格式、命名、分辨率、出血、色彩、文件大小、截止日期与时区、提交渠道和标识规定。

`conference.json` 的来源与要求至少包括：

```text
identity: {name, year, track}
official_domains: [official hostnames]
sources: [{url, title, quote, scope, category, year, track}]
requirements: {width_mm, height_mm, orientation, dimension_policy, format,
               file_name, min_ppi, bleed_mm, pdf_standard, color_profile, ...}
requirement_sources: {field: [zero-based source indices]}
printing_service: {requirements: {...}, requirement_sources: {...},
                   unresolved_rules: [], unresolved: [], ...}
unresolved: []
warnings: []
```

`category` 为 `mandatory_poster`、`optional_printing` 或 `official_identity`，`scope` 与 `track` 为本项目 track 或 `all_tracks`。来源年份匹配本届。每个规则映射到对应类别的正式来源；会议可选打印服务的截止与命名保存在 `printing_service`。

`dimension_policy` 为精确尺寸 `exact`，或官方上限 `maximum`。方向为 `portrait`、`landscape`、`either` 或未规定。未规定的 DPI、出血等保留 `null`。不同会议的要求从本次来源确定。

自动研究调用 `validate_research` 对官方页面、准确摘录、类别、尺寸和方向作检查；页面被拦截或数据解读不能确认时留下 `unresolved`。当前会话已经核验原文，或人提供正式通知且已确认内容时，可建立完整 profile 并显式导入：

```bash
poster-agent rules PROJECT --file checked-profile.json
```

profile 必须包含正式链接、摘录、适用年份/track、已确认数值和 `requirement_sources`。导入记录 `explicitly_imported_checked_profile` 与时间，区别于实时网页抓取。关键尺寸未知时继续内容与素材准备，尺寸明确后再进入打印验收。最终提交前复核命名、真实 paper ID、服务选择与具体截止时刻。

## 3. 建立事实与原图记录

阅读论文和页图，记录标题、作者、机构、问题、方法、实验条件、数据集、对比方法、指标、数字与边界。把海报所需事实写入 `evidence.json`：

```text
paper: {title, path: source/paper.pdf, sha256}
items: [{id, page, text, figure, source_asset}]
content_review: {status: pending, issues: []}
```

保留 `init` 记录的原 PDF SHA-256；每条事实定位到实际页码或源图路径。每个 section 的 `source_refs` 对应条目 ID。核对表格列、数值精度、单位、图内条件、结论强度及研究范围。

`--assets` 导入作者 PDF、SVG 和位图，`assets/catalog.json` 包含 `entries: [{id, path, preview, type, source_file, ...}]`。海报图片使用实际 `path`；`preview` 用于视觉检查与 ImageGen 输入。原始图 PDF 导入后提供保留矢量内容的 SVG。机构标识按用户提供的原件登记，保持比例与来源。

只有论文 PDF 时，依据真实页图选择区域：

```python
from poster_agent.ingest import extract_regions
extract_regions("PROJECT", [
    {"id": "method-original", "page": 3, "bbox": [0.08, 0.10, 0.92, 0.45]}
])
```

示例页码与范围须按本论文重新确定；页码从 1 起，边界为归一化 `x0,y0,x1,y1`。函数保存 SVG、PNG 预览，并向 catalog/provenance 追加来源。检查裁剪中的图例、坐标轴、单位和标签完整，排除无关正文。SVG 包裹的低分辨率照片仍需按实际打印 PPI 检查。

## 4. 设计参考与 HTML 规格

先组织连续展示逻辑，选择真正支持主张的原图、关键表格和解释。默认顺序为问题→核心思路→方法→证据→范围。共享对齐与标题层级连接内容，方法概览占主要视觉面积；密度保留研究条件、对照和必要说明，同时确保图内文字和正文能读。

调用内置 ImageGen 前先查看目标原图，按工具文档使用引用/编辑机制。提供毫米画布比例、作者原图、真实机构标识、内容层级与目标密度，生成平面海报参考。保存至 `reference/design-reference.png`，记录工具、提示词、输入图、时间与参考用途。

参考图用于空间比例、配色、文字层级和阅读顺序。生成的作者、日期、Logo、科研数字和图表逐项核验，错误保留在审阅记录中；HTML 使用已核验的原文与作者原图。已有有效参考保持；明确的新参考请求保存新文件并保留旧版本。独立 API 对应：

```bash
poster-agent reference PROJECT
poster-agent reference PROJECT --new-version
```

`poster.json` 的完整结构见 `CONTRACT.md`。版面示例：

```json
{"columns": 2, "style": "narrative", "gap_mm": 10, "margin_mm": 20, "title_pt": 74, "body_pt": 25}
```

这是 layout 的示例值，按真实尺寸调整。section 保持稳定 `id`，支持 `paragraphs`、`bullets`、`image`、`caption`、`rows`、`span`、`image_height_mm` 和 `hide_heading`。连续章节可含 `tables: [{title, rows, caption, highlight_rows}]`；表头索引 0。标识配置为 `branding: {logo, alt, logo_width_mm}`，SVG 标识供 ImageGen 引用时可提供实际栅格预览 `logo_preview`。

## 5. 独立对照、局部检查和修订

```bash
poster-agent render PROJECT --png-width 6000
poster-agent check PROJECT
```

检查 `exports/quality-report.json` 与实际文件。允许导出待审草稿，打印就绪需要后续批准。

| 对照 | 核对内容 | 调整方向 |
|---|---|---|
| 论文/原图 → 海报 | 作者、数字、单位、图例、方法与实验条件、结论范围 | 按证据纠正；需要作者判断时明确定位 |
| 参考 → HTML | 层级、图文面积、密度、留白、对齐、配色、美观 | 调整有限视觉参数，保持科研内容 |
| HTML → PDF | 实际尺寸、页数、字体、图像、完整文字与裁切 | 修复导出和资源，再独立重渲 PDF |
| 高清局部 → 打印尺度 | 图内标签、公式、图注、有效 PPI | 获取原件或调整放置尺寸，复查可读性 |

整张看阅读顺序与主次，局部看细节。使用原生 6000 px PNG 的裁图与 PDF 独立区域重渲；当前代码可生成同一套局部检查材料，无需 API：

```python
from pathlib import Path
from poster_agent.agent import _review_crops
from poster_agent.project import load_spec
from poster_agent.render import check_project
project = Path("PROJECT")
crops = _review_crops(project, load_spec(project), check_project(project))
```

查看返回路径中的 HTML/PDF 区域图，并按需继续放大图内标签。几何记录来自实际浏览器，当前文件摘要必须匹配。全局像素差只描述一种差异；视觉质量还需阅读性、风格与美观判断。

独立审阅写入 `visual-critique.json`，每条问题包含版块/位置、严重程度、实际证据和具体建议。API 入口由 `critique` 生成；会话入口用与作者角色分开的检查过程。区别客观错误、源图限制、主观偏好和不确定性，不复制生成参考的错误。

有据可修的视觉问题最多自动修两轮，每轮更新版本、渲染、再审阅与检查。科学内容问题记录 `needs_author` 并保留事实，交作者核对。原图清晰度、生产转换与无法确认的规则不能伪装成布局修复。无必要调整时停止自动修改；余下设计判断交人。

完成源内容核对后，才记录 `evidence.content_review.status: "accepted"` 与 `content_sha256 = content_digest(load_spec(PROJECT))`。同时保留 reviewer 与实际问题记录。排版变化保留这一审阅，标题、数字、图注、表格或图源变化须重审。

API 完整链的 `run-report.json` 记录阶段、结果、失败、安全错误、下一步与累计修订轮数。恢复用实际原 PDF、参考、manifest/文件摘要和最新审阅判断；有效阶段复用，失败阶段明确重做。自动修订上限随恢复保留。

## 6. 圈选意见、局部修改与满意冻结

```bash
poster-agent review PROJECT
poster-agent feedback PROJECT --target method --message "放大方法图，保持标题和配色"
```

工作台保留稳定 section ID 和归一化 `x,y,width,height` 选区，`feedback.json` 存为四项数组；模型 critique 的 `bbox` 使用 `x0,y0,x1,y1`，读取时区分这两种含义。`global` 为全局，`header` 为标题区。保存意见不改变当前海报。

会话模式读取 pending 反馈，定位需要变化与保留的部分，遵守锁区，修改必要目标与邻接空间，保存新版本并展示前后对照。视觉补丁：

```bash
poster-agent patch PROJECT visual-patch.json --reason "放大方法图并保持原有配色"
poster-agent render PROJECT --png-width 6000
poster-agent check PROJECT
```

白名单为有限 `theme`、`layout` 参数，section 的 `span/image_height_mm/hide_heading` 与 `section_order`。正文至少 18 pt。锁区会保护内容、位置及影响它的全局样式；必要时根据用户明确的新意见解锁，记录原因。

科研内容修改先核对源证据，再用 `save_revision` 保存，更新证据并重新审核，保持版本与审批规则。成功处理后更新反馈的 applied 状态和实际版本。API 入口可用 `apply PROJECT FEEDBACK_ID`，无需 key 的会话入口由当前 Codex 完成。

用户明确确认当前内容、设计和可读性，技术与科学审核也通过后：

```bash
poster-agent approve PROJECT
```

批准会重查当前导出并绑定确切版本/摘要。用户满意后保持当前设计；新的明确修改请求使用 `reopen PROJECT`，修改后重新审阅。`undo PROJECT` 恢复设计并产生新版本。模型和自动修订均不代替人批准。

## 7. 五文件打印包与最终交付

查看最终 PDF 与 `poster-pdf-preview.png`，逐区检查尺寸、方向、页数、字体、有效 PPI、文字与原图细节。二维码仅在真实目的地已确定时制作并核验链接。

```bash
poster-agent package PROJECT
# 有正式命名要求时使用已确认的真实值
poster-agent package PROJECT --filename Poster_Submission.pdf
# 用户明确使用会议打印服务时
poster-agent package PROJECT --printing-service --paper-id ACTUAL_ID --track TRACK
```

批准后工作台也提供打印包按钮。程序重查当前真实文件、批准、所选打印规则与已记录文件大小等条件，再输出 `exports/print-package-vNNNN.zip`，其中恰好五个文件：

1. 按正式要求命名的 PDF，或 `poster-print.pdf`。
2. `poster.html`，原图资源嵌入，可编辑。
3. `poster-4k.png`。
4. `quality-report.json`。
5. `PRINT_README.txt`，包含尺寸、100% 实际尺寸打印说明、来源与剩余备注。

`print_ready` 依赖当前实际文件摘要、技术结果、匹配科研内容审阅和确切版本的人工确认。论文全文、源图目录、历史与配置保留在本地项目；公开源码包只含代码、skill 和原创演示，不携带用户论文、临时文件或会话资料。

浏览器 PDF 为 RGB。PDF/X、ICC/CMYK 或出血要求需对应生产处理并验证最终转换文件。精确提交时刻、时区、渠道和会议条件再次对照正式通知。完成本地交付；发布 GitHub、上传海报、提交会议或印厂由用户明确决定。
