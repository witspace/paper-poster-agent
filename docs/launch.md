# 把 Paper Poster Agent 发布到 GitHub

首页先展示 **论文原图 → HTML 海报**，接着给出 Codex skill 的使用入口。重点讲清三件事：省下内容整理和排版的工作、能继续调整设计、用原图把研究讲明白。

`YOUR_HANDLE` 代表 GitHub 账号，实际发布时替换。下面的命令和发布文案已备好，创建仓库、推送和发布 Release 由维护者执行。

## 项目怎么介绍

仓库名建议用 `paper-poster-agent`，项目名保持 **Paper Poster Agent**。README、分享封面和小红书笔记都用这个名字。

**About，可直接粘贴：**

> A Codex skill for academic posters: original figures, editable HTML, visual feedback, high-resolution PNG and PDF exports.

**中文一句话：**

> 把论文和原图交给 Codex，整理成学术海报；看参考、说修改意见，再导出高清文件。

**Topics：**

`academic-poster` · `research-tools` · `codex-skill` · `html` · `pdf` · `ai-agent` · `openai` · `playwright`

Topics 描述项目，帮助读者找到相近工具。[GitHub 官方说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics)。

推荐顺序是 **原图与海报对比 → Codex skill → 一段可复制的提示 → 修改示例 → 导出文件**。安装步骤放在[使用指南](usage.md)，终端 API 作为另一个入口。

学术海报工具已有 [Paper2Poster](https://github.com/Paper2Poster/Paper2Poster) 和 [Any2Poster](https://github.com/Any2Poster/Any2Poster)。本项目用具体样例展示原图保留、会议要求核验、人工修改和导出检查，方便读者判断是否适合自己的论文。

## 公开素材已经准备好

首页样例使用公开论文 DINOv2（Oquab 等，TMLR 2024）的三张原图：PCA 特征图、数据构建流程和八项任务扩展实验。HTML 海报保留这些图和公开论文署名，展示图文如何安排。

- [论文原图与海报对比](assets/paper-to-poster.png)：首页和小红书首发配图。
- [HTML 海报文件](assets/showcase/poster.html)：下载后在浏览器打开，查看图文安排与原图复用。
- [样例来源记录](assets/showcase/source.json)：记录原图文件、渲染方式和当前状态。
- [GitHub 分享封面](assets/social-preview.png)：链接转发时显示的 1280 × 640 图片。

论文图文按 CC BY 4.0 复用，依据是 TMLR 的发表政策；仓库的 MIT 许可证适用于软件。[论文与许可来源见使用指南](usage.md#公开样例的来源)。公开样例展示版面，当前处于审阅状态；会议要求和最终打印文件仍按实际项目核验。

合成 demo 保留在 `examples/demo/`，用于离线体验和渲染测试，图中保留 **DEMO / SYNTHETIC DATA**。首页和推广配图使用上面的公开 DINOv2 论文对照。

第一次提交从公开源码 ZIP 解压出的干净目录开始。个人论文项目、密钥和运行记录另外保存。检查待提交文件列表与截图内容，避免带入个人路径、账号信息或私人材料。

## 六步完成首发

### 1. 解压公开源码包

将 `paper-poster-agent-source.zip` 解压到一个新的空目录，进入其中的 `paper-poster-agent/`。按[使用指南](usage.md#安装与体验)安装，确认 CLI 和 Codex skill 的入口能找到。

### 2. 登录 GitHub

安装 Git 和 GitHub CLI 后，在 PowerShell 执行：

```powershell
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git
gh auth status
```

### 3. 设置提交邮箱并检查文件

在 GitHub 的 **Settings → Emails** 复制账户提供的 `noreply` 邮箱。把下面的占位符替换为公开账号名和该邮箱；设置只作用于当前仓库。

```powershell
git init -b main
git config --local user.name "YOUR_HANDLE"
git config --local user.email "YOUR_GITHUB_NOREPLY_EMAIL"
git add -- README.md README.en.md CONTRACT.md CONTRIBUTING.md LICENSE AGENTS.md .gitignore .env.example pyproject.toml MANIFEST.in poster_agent skills tests docs .github examples/demo
git diff --cached --name-only
git diff --cached --stat
```

提交作者邮箱会进入 Git 历史，应在首次提交前设置。看完待提交列表后执行：

```powershell
git commit -m "Release Paper Poster Agent preview"
```

### 4. 创建仓库并推送

下面的命令创建公开仓库并上传首次提交：

```powershell
gh repo create YOUR_HANDLE/paper-poster-agent --public --source . --remote origin --push
gh repo view --web
```

这个流程由 CLI 创建仓库。仓库名已被使用时，先查看已有仓库，再决定发布位置。

### 5. 设置首页并查看测试结果

填写上面的 About 和 Topics，在 **Settings → Social preview** 上传 `docs/assets/social-preview.png`。仓库已经包含许可证、三种 Issue 模板和测试工作流。

打开 **Actions**，检查首次推送的结果。测试工作流覆盖 Python 3.10 和 3.13，安装 Chromium 后运行本地测试。发布前让两组检查通过；错误从日志中定位后修复。

GitHub 社交预览接受 PNG、JPG、GIF，文件小于 1 MB；官方建议尺寸为 1280 × 640。[设置预览图](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/customizing-your-repositorys-social-media-preview)。

### 6. 发布 v0.1.0 Preview

进入 **Releases → Draft a new release**，标签填 `v0.1.0`，标题填 `v0.1.0 Preview — Paper Poster Agent`，勾选 **Pre-release**，先保存草稿。[GitHub 官方操作说明](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)。

添加准备好的两个附件：

- `paper-poster-agent-source.zip`
- `paper_poster_agent-0.1.0-py3-none-any.whl`

这两个文件作为 Release 附件，源仓库保持精简。检查正文、附件和安装步骤后发布，再从实际下载链接试一次安装。

首版地址为 `https://github.com/YOUR_HANDLE/paper-poster-agent/releases/tag/v0.1.0`。替换账号后，可将该地址加入 README 的下载入口和公开介绍。

## Release 文案

> **论文原图，变成一张讲得清楚的海报。**
>
> Paper Poster Agent 帮忙整理内容、安排图文和导出高清文件。方法图与实验图继续使用论文原图，作者通过对话和圈选反馈调整重点、间距与配色。
>
> **推荐在 Codex 对话里制作。** 按使用指南安装 `academic-poster-agent` skill，准备论文 PDF、原图和会议信息，发送：
>
> “请使用 $academic-poster-agent，用 paper.pdf 和 figures/ 制作 Conference Name 2026 Main 的海报。保留论文原图，突出方法图和关键实验，先展示设计参考，再按反馈调整。”
>
> 首页展示公开论文 DINOv2（Oquab 等，TMLR 2024）的原图与 HTML 海报对比，便于先看效果。论文素材按 CC BY 4.0 复用，来源见使用指南。样例处于审阅阶段，最终内容和打印要求按实际项目核验。
>
> **也支持终端 API。** 完成依赖安装、`OPENAI_API_KEY` 和 `POSTER_MODEL` 配置后运行：
>
> ```bash
> poster-agent run projects/my-poster --api --paper paper.pdf --assets figures --conference "Conference Name" --year 2026 --track Main
> ```
>
> 独立收费 API 的完整线上流程仍需真实账户验证。仓库另附可离线运行的合成 demo，用于体验渲染和审阅。已有本地测试覆盖渲染、PDF 检查、反馈、版本冻结和交付打包。
>
> 输出包括可编辑 HTML、高清 PNG 和 PDF。作者确认内容与设计后，再完成打印检查和交付。当前 PDF 为 RGB；PDF/X、CMYK、指定 ICC 与出血要求按打印服务的实际要求处理并验证。
>
> 欢迎 Star 收藏，或通过 Issue 提出安装、版面和会议要求的问题。反馈附可公开的最小材料，并删掉个人路径与密钥。

## 一段 25 秒的演示脚本

静态对比图和 HTML 样例已经备好。下面是待录制的脚本；修改前后画面来自录制时实际完成的调整。

| 时间 | 画面 | 字幕 |
|---|---|---|
| 0–4 秒 | 展示公开 DINOv2 的数据构建流程与实验图，保留署名 | DINOv2 论文原图，排进海报 |
| 4–9 秒 | 打开公开 HTML 样例，展示方法与实验区域 | 排成一张讲得清楚的海报 |
| 9–14 秒 | 在 Codex 输入一次真实修改意见：“放大方法图，标题和配色保持现在这样” | 想改哪里，直接说 |
| 14–20 秒 | 展示此次修改的前后版，放大对应区域 | 原图保留，重点更清楚 |
| 20–25 秒 | 展示项目名、原图对比和 Codex skill 入口 | Paper Poster Agent · 在 Codex 里开始 |

录制时只截内容区域，隐藏账号、个人路径与其他窗口。等待过程经过剪辑时标注“已剪辑”。发布前查看实际画面和字幕；线上 API 演示应来自完成验证的真实运行。

## 一周后看哪些地方值得改

GitHub Traffic 可供有权限的维护者查看最近 14 天的访问者、完整克隆和来源网站，统计使用 UTC。[官方说明](https://docs.github.com/en/repositories/viewing-activity-and-data-for-your-repository/viewing-traffic-to-a-repository)。这些数据用于观察趋势，结合实际 Issue 和试用反馈判断效果。

| 收到的反馈 | 下一步 |
|---|---|
| skill 安装步骤找不到 | 缩短入口，补一张安装成功的画面 |
| 论文与原图导入卡住 | 补可公开的文件目录和导入示例 |
| 方法图太小、实验难以对比 | 调整版面，补对应区域的前后对照 |
| 能导出，但图内文字难读 | 展示打印尺度局部，说明放大和取舍 |
| 有同学分享完成的海报 | 先收集使用反馈；公开案例继续使用许可已核验的公开论文 |

“装好了”“重点讲清楚了”“按反馈改好了”是有用的使用结果。若以后介绍节省的时间，记录材料准备、制作和修改的实际用时，并注明样本与计时范围。
