# HackerShelf

> 这是 HackerShelf 自己用的 CLAUDE.md 去掉个人信息后的模板。Claude Code 打开这个仓库时会读它；拿去做自己的版本时，改掉网址、门槛和“我”的偏好即可。

把 Hacker News 二十年里被不同的人反复推荐的论文和开源书，做成一个公开的静态书架：每篇配中文导读、HN 原话（链回原评论）、逐年提及和学习路径。发现层借鉴 Karpathy 的 HackerTube：社区长期口碑 + LLM 立场标注。

- 方法、数字和局限：README.md
- 一个月 demo：demo/README.md（在 Claude Code 里说“跑 demo”）
- 月度更新：.claude/skills/monthly-update/SKILL.md（说“月度更新”）
- 提示词：prompts/（和代码里的常量一致）

## 当前策略
- 主入口是 GitHub Pages 上的公开静态站，只放发现层：书架、详情、浏览、搜索、学习路径、每日新鲜书架。读论文去 arXiv 或 alphaXiv，读书去官方免费版。
- 先把论文这条线跑通，再接图书。图书只做开源书：开放许可，或作者、出版社官方免费放出的完整版；只链接官方版，不托管全文。
- 所有 LLM 工作（立场标注、卡片、中文说明、学习路径、主题树命名）都在 Claude Code 里离线完成，用子 agent，走订阅额度。
- 网站不调用任何模型 API。详情页提供“复制提问提示词”（提示词 + 论文链接 + 中文导读），贴进任意模型。

## 不做
账号系统、多人功能、评论区；公开托管论文 PDF 或图书全文；网站调用任何模型 API；arXiv 以外的付费墙论文（只给链接）。

## 硬约束
- 版权：arXiv 内容只在本机缓存、只给自己看（arXiv 的使用条款允许个人使用，不允许在自己的服务器上公开再分发，除非论文的许可证允许）。由 PDF 派生的缩略图同样只私用。公开站只放：生成的封面、arXiv 元数据、我们写的中文导读和学习路径、HN 原话（写明作者、链回原评论）。
- 速率：arXiv 每 3 秒 1 个请求、单连接；OpenAlex 必须带 key（免费，每天 $1 额度）。所有外部请求经过同一个限速 + 磁盘缓存层（`pipeline/hs/http.py`），限速写在 `pipeline/config.toml`。
- 数据分离：`catalog.db` 可随时重建、只读；公开站的数据（从 catalog 导出的 JSON、Actions 生成的 `fresh.json`）都能重建。
- 密钥只在 `.env`，不进 git。浏览器不直接调任何模型 API。
- 大批量标注先试跑：超过约 1,000 条的 LLM 标注或抽取，先用 200 条样本跑通，报告质量、预计耗时和额度占用，等我确认。
- 署名：HN 数据来自 open-index/hacker-news（ODC-By 1.0），页面底部写明。
- 已知数据问题：HF 数据集 2026-08-23 之后停更（数据到 2026-08-21），之后的部分用 HN Algolia API 补。

## 借鉴 HackerTube 的规则（默认值，在 `pipeline/config.toml`，可调）
- 一条提及：评论里链到这篇论文、评论者自己的文字（去掉链接和 `>` 引用）≥100 字符；或者论文本身被发成帖子。
- 入选：≥3 个不同的人、≥3 个不同月份进主书架；2/2 作候选层，界面一律写“被提及”。
- LLM 结合帖子标题和上一条评论判断每条提及的立场：strong_rec / rec / reference / joke / critical。
- 每个条目最多保留 20 条提及，优先推荐和批评、优先不同评论者；统计数字用全部提及计算。
- `score = 有推荐的不同月份数 + 0.5 × 有强推荐的不同月份数`；同一个人最多算 2 个月。
- 没有正向立场的条目写“被提及”，不写“被推荐”。

## 技术栈
- 管线：Python 3.12 + uv + DuckDB + httpx。批量 LLM 任务在 Claude Code 里用子 agent 跑：脚本切分输入、合并结果，prompt、输入、输出都落盘（`data/llm/<任务>/`），能断点续跑和复跑（`pipeline/hs/llm_batch.py`）。立场标注用 Haiku，复核、卡片、中文说明、学习路径用 Sonnet。
- Web：Next.js（App Router，TypeScript）+ Tailwind，`output: 'export'` 静态导出，basePath `/shelf`；数据在构建期从 catalog 读，浏览和搜索的数据导出成 JSON，在浏览器里算。
- embedding 离线算（bge-small-en-v1.5，fastembed），主题树和相关论文都预先算好。

## 目录
```
pipeline/       Python 管线，每一步一个能单独运行的命令（uv run --project pipeline …）
prompts/        给子 agent 的提示词（从代码常量生成）
web/            Next.js 公开站
deploy/public/  构建、检查、预览公开站；每日新鲜书架的脚本和工作流
demo/           一个月 demo 的配置和脚本
data/           原始下载、缓存、管线产物、模型任务的输入输出（git 忽略，不附带）
reports/        月度小结、抽检表（git 忽略）
```

## 工作方式
- 先样本后全量：每个管线步骤先在 1 个月数据（demo/）或 200 条样本上跑通。
- 产品取舍拿不准就列选项和推荐来问我；纯技术细节自己决定，偏离上面的默认值时记一条决策（做了什么、为什么）。
- 提交可以自己做；推送和发布之前先问我。
