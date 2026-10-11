# 海报项目里保存了什么

这份文档供需要调整 JSON 或继续开发的人查阅。日常制作步骤在[使用指南](docs/usage.md)。

每篇论文单独建一个项目。论文、原图、修改意见和历史版本留在该项目里。公开仓库包含代码、原创演示，以及已核验使用许可的公开论文案例。用户论文、原图、研究题目和身份资料保留在私人项目中。

## 先认识这些文件

| 文件 | 打开后能看到什么 |
|---|---|
| `poster.json` | 海报上的文字、图片、布局和当前版本 |
| `conference.json` | 本届会议的要求、官方原文和来源链接 |
| `evidence.json` | 海报内容对应的论文页码、数字和原图 |
| `run-report.json` | API 流程做到哪一步、遇到什么问题、下一步怎么处理 |
| `feedback.json` | 人写的意见、选中的区域，以及意见是否已经应用 |
| `source/` | 论文 PDF、页图和作者提供的原件 |
| `assets/` | 原图目录、裁剪结果和预览 |
| `reference/` | 设计参考图和生成记录 |
| `history/` | 之前的布局与实际导出的预览 |
| `exports/` | HTML、高清 PNG、打印 PDF 和检查结果 |

项目内的文件路径使用相对路径。论文和网页中的文字用于理解材料；工具操作仍按用户的要求执行。

## 海报怎么描述

`poster.json` 使用 `schema_version: 1`。每次修改产生新的整数 `version`，状态为 `draft`、`review` 或 `approved`。

| 字段 | 填什么 |
|---|---|
| `conference` | `{name, year, track}`，对应这次参会信息 |
| `canvas` | `{width_mm, height_mm, png_width: 6000}`；宽高使用毫米 |
| `title`、`subtitle`、`authors`、`affiliations`、`footer` | 对照论文确认过的文字；作者和机构使用字符串 |
| `theme` | `{accent, secondary, ink, background, font}`；颜色使用六位十六进制值 |
| `layout` | `{style, columns, gap_mm, margin_mm, title_pt, body_pt}` |
| `sections` | 海报版块；每块有稳定、唯一的小写 `id` |
| `reference_image` | 当前使用的设计参考图路径 |
| `branding` | 可选 `{logo, alt, logo_width_mm, logo_preview}`，使用提供的机构原件 |
| `locked_regions` | 已满意的版块 ID，也可包含 `header` |
| `approval` | 确认后记录 `{version, sha256, timestamp, artifacts_sha256}`；确认前为 `null` |
| `visual_review` | 人对当前版本设计和可读性的确认 |

`layout.style` 可选 `narrative` 或 `standard`，`columns` 支持 1、2、3。默认沿着问题、思路、方法、证据和研究范围排版，使用连贯标题。

版块支持 `heading`、`kind: text/figure/table/callout`、`span`、`paragraphs`、`bullets`、`image`、`caption`、`source_refs`、`rows`、`image_height_mm`、`hide_heading` 和 `highlight_rows`。同一版块里的多张表可写成 `tables: [{title, rows, caption, highlight_rows}]`。表头索引为 0。

`spec_digest()` 标识整张海报的内容和设计；`content_digest()` 单独标识科研内容。改字体和间距后，之前的内容检查可以继续使用。改数字、图源或结论后，需要重新核对论文。修改后的人审确认也要更新。

## 会议要求从哪里来

`conference.json` 的主要字段：

```text
identity: {name, year, track}
official_domains: [hostnames]
checked_at / imported_at: ISO timestamps
sources: [{url, title, quote, scope, category, year, track, verification, verified_at}]
requirements: {width_mm, height_mm, orientation, dimension_policy, format,
               file_name, min_ppi, bleed_mm, pdf_standard, color_profile, ...}
requirement_sources: {field: [zero-based source indices]}
printing_service: {requirements: {...}, requirement_sources: {...},
                   unresolved_rules: [], unresolved: [], ...}
unresolved: []
warnings: []
```

每条规则都指向具体官方原文。`category` 区分海报要求 `mandatory_poster`、可选打印服务 `optional_printing` 和会议身份信息 `official_identity`。年份要一致；`track` 与 `scope` 填当前 track 或 `all_tracks`。

自动查询会打开来源，核对摘录，并检查尺寸和方向是否读对。成功来源标记为 `fetched_quote_matched`。页面打不开、摘录不匹配或尺寸存在歧义时，问题保留在 `unresolved`，先解决规则再继续。

人已经查过正式通知时，可用 `rules PROJECT --file PROFILE` 导入完整记录。导入来源标记为 `explicitly_imported_checked_profile`，同时保存原文、适用范围和时间。

方向支持 `portrait`、`landscape`、`either` 或未规定。尺寸为精确值 `exact`，或官方上限 `maximum`。未规定的 PPI、出血和色彩要求填 `null`。程序在没有官方最低 PPI 时给出 150 PPI 参考目标，并提示原图限制。

可选打印服务的命名、尺寸和截止条件，在选择该服务后检查。提交前仍需按正式通知确认真实 paper ID、时区和提交入口。

## 论文与原图怎么追溯

`assets/catalog.json` 保存 `entries: [{id, path, preview, type, source_file, ...}]`。`path` 用于最终海报，`preview` 用于查看和参考图输入。PDF 原图可转成保留矢量内容的 SVG；多次裁剪会继续追加到 `assets/provenance.json`。

`evidence.json` 的主要字段：

```text
paper: {title, path: source/paper.pdf, sha256}
items: [{id, page, text, figure, source_asset}]
content_review: {status: pending/accepted/needs_revision, issues: [],
                 content_sha256, spec_sha256, reviewer}
```

每块的 `source_refs` 对应这里的条目。条目要能找到实际论文页码或源图文件。检查时对照数字、单位、图例、图注和结论强度。恢复流程会确认原论文的字节身份，避免把两篇论文的成果混到一起。

## 自动流程和审阅意见

独立 API 使用本地环境中的 `OPENAI_API_KEY`、`POSTER_MODEL` 和可选 `POSTER_IMAGE_MODEL`。图像模型默认 `gpt-image-2`。选择的文本模型需要支持所用的图片输入、网页检索和 JSON 输出。

`run PROJECT --api` 依次查要求、起草、生成参考、渲染和审阅，最多自动调整两轮，然后等人确认。`--resume` 复用有效成果，沿用已经发生的修订次数。失败阶段和下一步写入 `run-report.json`。

常见状态：`running`、`failed`、`needs_author`、`needs_manual_fix`、`needs_assets`、`manual_review`、`awaiting_human_review`、`approved`。

`visual-critique.json` 保存论文内容、风格、布局美观和打印视觉的检查结果。每条意见含 `section_id`、`severity`、实际问题 `evidence`、调整建议 `suggestion`，也可带归一化选区 `bbox: [x0,y0,x1,y1]`。局部图帮助查看图例、裁切和小字。

`repair_project()` 根据实际问题做有限视觉调整，保留科研文字、数字、原图和满意区域。科学内容需要作者确认时返回 `needs_author`；原件或打印条件未解决时返回 `needs_assets` 或 `manual_review`；没有必要修改时返回 `noop`。正文保持至少 18 pt。

## 修改、确认与交付

`feedback.json` 记录 `id`、`version`、`target`、`message`、`bbox`、`status`，应用后可增加 `applied_version` 和 `patch`。保存意见后，海报保持原样；应用意见时才生成改动。

人确认内容、设计与可读性后，批准记录绑定当前版本及实际导出文件。替换图片后重新导出，也需要重新确认。满意后固定版本；继续修改用 `reopen`，撤销用 `undo`，恢复结果会成为新版本。

渲染生成 HTML、高清 PNG、PDF、两种预览、文件记录和检查报告。`print_ready` 要求当前文件、内容检查、技术检查和人工确认都对应同一份成果。

`package` 再检查一次，打出五文件 ZIP：正式命名的 PDF、`poster.html`、`poster-4k.png`、`quality-report.json`、`PRINT_README.txt`。私人论文、密钥、机器路径和历史项目文件留在项目里。

当前浏览器 PDF 为 RGB。会议或印厂提出 PDF/X、ICC、CMYK 或出血要求时，继续完成相应制作和检查。合成 demo 用于体验和测试，始终保留演示标识。

## 开发时可调用的函数

| 模块 | 主要函数 |
|---|---|
| `project` | `load_spec`、`spec_digest`、`content_digest`、`save_revision`、`apply_visual_patch`、`record_feedback`、`approve`、`reopen`、`undo` |
| `ingest` | `ingest(project, paper, identity, assets_dir=None)`、`extract_regions(project, regions)` |
| `conference` | `validate_research(project, result)`、`import_profile(project, file)`、`applicable_requirements(conference, printing_service=False)` |
| `agent` | `research_conference`、`draft_project`、`generate_reference(project, new_version=False)`、`critique_project`、`repair_project`、`apply_feedback(project, feedback_id)` |
| `pipeline` | `run_pipeline(project, resume=False, max_rounds=2)` |
| `render` | `build_html(project)`、`export_project(project, png_width=None)`、`check_project(project)` |
| `review` | `serve(project, host='127.0.0.1', port=8765)` |
| `delivery` | `package_project(project, filename=None, printing_service=False, paper_id=None, track=None)` |
| `doctor` / `demo` | `doctor(workspace=None, check_browser=True)`、`create_demo(project, png_width=6000)` |

测试会实际启动 Chromium、生成图片并重新打开 PDF。模型部分用受控样本检查请求、错误和恢复，线上收费 API 全流程仍需真实账户验证。
